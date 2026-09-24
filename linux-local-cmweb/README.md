# linux-local-cmweb

Running CMWEB on a Linux machine, following the upstream Quick Guide as closely
as the missing Sony infrastructure allows.

> **Status: written but not executed.** This folder was built on Windows by
> reading the source. Every claim about *the source* below was verified against
> the actual files (they are cited by path and line). Nothing here has been run
> on Linux — `apt-get`, `python3 -m venv`, `pip install`, `migrate`,
> `loaddata` and `runserver` are all untested in this layout. Expect to fix
> something on the first run; §9 lists where I would look first.

**Linux is the platform CMWEB is written for**, which is why this exists
separately from [`../local-cmweb/`](../local-cmweb/README.md). That one runs on
Windows and has to replace `cmweb.settings` wholesale. Here the real
`cmweb.settings` is used unmodified, which means the site behaves the way it
does in production rather than the way a substitute settings module makes it
behave.

---

## 1. What upstream says, and what changes

The Quick Guide assumes a Sony network. Mapping it to this working copy:

| Upstream step | Here | Why |
| --- | --- | --- |
| `repo init -u …/cmweb-manifest -b cloudj2` <br> `repo sync` | `setup.sh` builds `site/` out of symlinks | No Gerrit access, and the three repos are already extracted. The manifest only ever placed two projects — `cmweb-project` at `site` and `cmweb-app` at `site/apps` — so a symlink tree reproduces it exactly. |
| `cd site && make install` | `setup.sh` creates the virtualenv, then `make install` works | `make install` needs `somc-virtualenv3` (internal) and `etc/requirements-22.txt` (half internal packages). Both are substituted — see §3. |
| `./manage.py migrate` | same, plus `--skip-checks` | System checks import the URLconf, which reaches view classes evaluating `Parameter.get_int(...)` at class-body scope — a query before any table exists. |
| `Site.objects.create(domain='localhost:8000', …)` | `scripts/post_setup.py` | Same thing, plus the home page and a usable login. See §5. |
| edit `site/cmweb/urls.py` login line | `setup.sh` copies and patches it | Keeps `cmweb-project` untouched. Same one-line change. |
| `make install-testdata` | `scripts/load_testdata.py` | Same fixture, loaded with model signals muted — minutes faster and semantically correct. See [`../local-cmweb/USING-TESTDATA.md`](../local-cmweb/USING-TESTDATA.md). |
| `make index-testdata` | **not available** | Needs C2D and Gerrit. |
| `./manage.py runserver` | `run.sh` | Same command, with the environment set up. |
| `make test`, `make kwalitee` | work, from `site/` | See §7. |

Everything else in the upstream guide — the fixture in `TestCase.fixtures`,
`makemigrations`/`migrate`, PEP-8 — applies unchanged.

---

## 2. Quick start

Full walkthrough, including the no-`sudo` path, in
**[INSTALL.md](INSTALL.md)**. The short version:

```bash
cd linux-local-cmweb
./setup.sh              # or: ./setup.sh --skip-apt   (no sudo needed)
./run.sh
```

Then <http://127.0.0.1:8000/>, and log in at `/accounts/login/` or `/admin/`:

| User | Password | Where from |
| --- | --- | --- |
| `admin` | `s3cr17` | in the fixture — the upstream dev credential |
| `local` | `local` | created by `scripts/post_setup.py` |

`admin`/`s3cr17` was verified by checking the password against the PBKDF2 hash
carried in `testdata.json` (user `pk=1`), so the upstream guide is accurate on
that point.

Options:

```bash
./setup.sh --fresh                 # drop the database and rebuild
./setup.sh --relink                # rebuild only site/, then stop
./setup.sh --skip-apt              # no sudo apt-get
./setup.sh --host localhost:8080   # Site row for a different port
./clean.sh [--all]                 # remove what setup.sh generated
```

---

## 3. What `setup.sh` builds

```
linux-local-cmweb/
├── ENV/                     virtualenv (the Makefile's default ../ENV, seen from site/)
├── site/                    ← PATH_SITE — a tree of symlinks, built, never committed
│   ├── cmweb/                 every module symlinked from cmweb-project/cmweb/, except:
│   │   ├── secure.py            generated from etc/secure.py.in
│   │   └── urls.py              copy of upstream with the login line patched
│   ├── apps -> ../../cmweb-app       ← APPS_DIR
│   ├── etc/                   apt lists symlinked; requirements-2*.txt → ours
│   ├── manage.py, Makefile, static/, templates/, bin/, .pycodestylerc → symlinks
├── stubs -> ../local-cmweb/stubs     shims for the Sony-internal packages
├── cm_web_db                sqlite database (PATH_ROOT/cm_web_db)
├── repository/              PATH_REPOSITORY — empty; see §8
├── cache/                   PATH_LABEL_CACHE
└── var/log/
```

**Why a symlink tree rather than two symlinks into `cmweb-project`.** Upstream
needs `cmweb-app` at `cmweb-project/apps/` and a `cmweb/secure.py`; both paths
are in `cmweb-project/.gitignore`, so creating them would be perfectly
legitimate. But the three directories in this working copy are **extracted
copies with no `.git`**, so anything written there is unrecoverable. Building
`site/` here instead keeps them read-only inputs.

It also puts `PATH_ROOT` in a useful place. `settings.py:53-68` derives
everything relatively:

```python
PATH_PROJECT    = dirname(abspath(__file__))   # site/cmweb
PATH_SITE       = dirname(PATH_PROJECT)        # site
PATH_ROOT       = dirname(PATH_SITE)           # linux-local-cmweb/
PATH_REPOSITORY = join(PATH_ROOT, 'repository')
```

so the database, `static/`, `cache/` and `test-results/` all land inside this
folder rather than beside the source directories.

### The two substitutions that make `make install` work

`make install` is `$(cmweb_apt_get)` + `$(cmweb_pip_freeze)`
(`cmweb-project/Makefile:167`). Both would fail here:

- **`somc-virtualenv3`** builds the virtualenv (`Makefile:155`) and is
  Sony-internal. `setup.sh` creates `ENV/` with `python3 -m venv` and then
  `touch`es `ENV/.virtualenv-installed`, the stamp file that target produces —
  so make considers it done and skips straight to pip.
- **`etc/requirements-$(OS_VERSION).txt`** contains ~17 internal packages.
  `site/etc/requirements-20.txt` and `requirements-22.txt` are both symlinks to
  `requirements-linux.txt` here. (`OS_VERSION` comes from `lsb_release
  --release`, hence both names.)

So after `setup.sh` has run once, the upstream command works verbatim:

```bash
cd site && make install NO_APT_INSTALL=1
```

---

## 4. What the shims cover

`stubs/` is shared with the Windows harness rather than duplicated; the
inventory and fidelity table is in
[`../local-cmweb/README.md`](../local-cmweb/README.md). In short: `envoy`,
`somc_decorators`, `somcutil`, `repo_manifest`, `inlines` and `generic_pages`
are real reimplementations; `c2dclient`, `jiraapi`, `mplusclient`,
`jenkinsclient`, `dmsclient` and `vendorrelease` raise `ShimNotAvailable` naming
the package they stand in for.

**Linux needs fewer substitutions than Windows did.** The real `cmweb.settings`
lists `search`, `django_opensearch_dsl`, `django_celery_results` and
`rpc4django` in `INSTALLED_APPS` (`settings.py:312-370`); the Windows harness
deletes those apps, while here they are installed for real from PyPI. Still
shimmed:

- **`rest_framework_swagger`** — `django-rest-swagger` 2.1.1 is unmaintained and
  incompatible with DRF 3.15.
- **`ldap` / `django_auth_ldap`** — by choice, not necessity. Local development
  uses Django's own login, and `AUTHENTICATION_BACKENDS`
  (`settings.py:465-469`) already ends in `ModelBackend`, so the LDAP backends
  are tried and fall through. Uncomment `python-ldap` and `django-auth-ldap` in
  `requirements-linux.txt` and add `libldap2-dev`/`libsasl2-dev` if you want the
  real ones.

---

## 5. The Site row, and why the domain matters

`settings.py` defines **no `SITE_ID`** — only `FEED_SITE_ID = 1`
(`settings.py:219`). Without `SITE_ID`, Django's sites framework resolves the
current site by matching the request's `Host` header against `Site.domain`.
That is exactly why the upstream guide says to create a Site with domain
`localhost:8000`: browse on a different host or port and the lookup finds
nothing.

`scripts/post_setup.py` sets **`pk=1`** to that domain rather than creating a
second row, so both the host lookup and `FEED_SITE_ID = 1` resolve to it. If
you change the port, re-run:

```bash
./setup.sh --host localhost:8080 --relink   # or just re-run post_setup.py
ENV/bin/python3 scripts/post_setup.py localhost:8080
```

`post_setup.py` also creates the `home` generic page (`/` is the catch-all
generic_pages view, so without it the front page 404s) and grants
`users.view_all_pages` — the permission `PermissionCheckMiddleware` gates the
whole site on — to both `local` and the fixture's `admin`. The fixture was
dumped with `--exclude auth.permission` (`Makefile:229`), so `admin`'s own
permission rows are not guaranteed to survive a fresh `migrate`.

---

## 6. Verify

```bash
ENV/bin/python3 scripts/smoke_test.py
```

Requests ~21 pages through Django's test client and prints a status line each.
The equivalent script on Windows reports `20 ok, 0 redirect/not-found,
0 failing`; this one adds `/accounts/login/`, which only exists after the
urls.py patch.

> The test client bypasses `WSGI_APPLICATION` entirely, so a green run does not
> prove `./run.sh` works. Check both.

---

## 7. Tests and lint

Both run from `site/`, using the upstream targets:

```bash
cd site
make test                                   # TESTED_APPS, --keepdb, XML to ../test-results
make test TESTED_APPS="explorer historian"
make kwalitee                               # pyflakes + pycodestyle + pydocstyle
```

`make test` depends on `static`, which runs `collectstatic` and
django-compressor with `COMPRESS_OFFLINE=True`. Offline compression is the one
step likely to need attention — production compresses through a YUI jar that
wants a JRE. If it blocks you, run the tests directly:

```bash
ENV/bin/python3 manage.py test explorer --keepdb -v2 --skip-checks
```

`make kwalitee` enforces 80-column pycodestyle and pydocstyle over every
non-migration file — every module, class and method needs a docstring. The
scripts in this folder follow that rule so they do not break the target if
anyone points it here.

---

## 8. Limits

The same ceiling as the Windows harness, for the same reasons:

- **No indexing.** `index_labels`, `index_latest`, `sync_commits` need C2D,
  Gerrit and bare git mirrors. They raise `ShimNotAvailable`.
- **No search.** `django_opensearch_dsl` is installed and the `search` app
  loads, but `secure.py` points `OPENSEARCH_HOST` at `localhost` and there is no
  cluster. `OPENSEARCH_DSL_AUTOSYNC` is already `False` in `settings.py`, so
  nothing tries to index on save; querying `/search/` will fail.
- **No git-backed pages.** Commit diffs, file browsing and manifest rendering
  read bare repositories under `repository/`, which is empty. Point
  `GLOBALS['PATH_REPOSITORY']` at real mirrors if you have them.
- **No Gerrit workflow completion.** Requests can be created and voted on;
  completing one calls the Gerrit REST API and fails.
- **No Celery worker** — `CELERY_TASK_ALWAYS_EAGER` is set in `settings.py` and
  never overridden, so tasks run inline. That is also true in production.
- **`__version__` will be empty.** `settings.py:32-34` runs `git
  --git-dir=<site>/apps/.git describe`, and `cmweb-app` has no `.git` here. The
  subprocess fails, stdout is empty, and the version string ends up `''`. It is
  used for the PJAX version header and the footer, neither of which breaks.

---

## 9. If the first run fails

In rough order of likelihood, given none of this has been executed:

| Symptom | Where to look |
| --- | --- |
| `NameError: OPENSEARCH_HOST` | `site/cmweb/secure.py` was not created — re-run `./setup.sh --relink` |
| `ModuleNotFoundError: c2dclient` (or another internal name) | `PYTHONPATH` is not picking up `stubs/`. `run.sh` and the scripts set it; a bare `./manage.py` from `site/` does not. |
| `ImportError` from `cmweb/__init__.py` | It imports `cmweb.celery` and `six.moves`, so `celery` and `six` must be installed. Unlike the Windows harness, nothing here bypasses `__init__.py`. |
| pip fails building `lxml` | `libxml2-dev` / `libxslt1-dev` missing — see `etc/apt-packages.list` |
| `near "ALTER": syntax error` during migrate | `GLOBALS['CM_WEB_ENVIRONMENT']` is not `'dev'`. It is `'dev'` by default in `settings.py:44`, so this only bites if something overrode it. |
| `no such table: django_site` during migrate | `--skip-checks` was dropped |
| `/` returns 404 | `post_setup.py` has not run |
| Every page redirects to `/request/branches/` | The logged-in user lacks `users.view_all_pages` — re-run `post_setup.py` |
| Feeds or absolute URLs point at `example.com` | The `Site` row does not match the host you are browsing — §5 |
| `make install` tries to run `somc-virtualenv3` | `ENV/.virtualenv-installed` is missing — `touch` it, or re-run `./setup.sh` |
| django-compressor fails during `make static` | Offline compression; use `manage.py runserver` with `DEBUG = True` instead, which serves static directly |

---

## Related

- [`../local-cmweb/README.md`](../local-cmweb/README.md) — the Windows harness, and the shim inventory this folder reuses
- [`../local-cmweb/USING-TESTDATA.md`](../local-cmweb/USING-TESTDATA.md) — the fixture in detail: contents, loading, reloading, regenerating
- [`../docs/development.md`](../docs/development.md) — the real upstream development guide
- [`../docs/how-the-site-works.md`](../docs/how-the-site-works.md) — one request end to end
- [`../CLAUDE.md`](../CLAUDE.md) — the short-form architecture notes
