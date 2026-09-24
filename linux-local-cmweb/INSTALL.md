# Installing CMWEB on Linux — full guide

Start to finish, on a machine with no Sony network access, **with or without
`sudo`**.

[README.md](README.md) explains how the harness is put together and how it maps
onto the upstream Quick Guide. This is the walkthrough: every command, what it
needs, and what to do when it is not available.

> **Not yet executed on Linux.** This folder was built on Windows by reading the
> source. Facts about the source are cited by file and line and were checked;
> the install itself has not been run. Section 8 is the honest list of where it
> is most likely to need a fix.

---

## 1. The short answer on `sudo`

**You almost certainly do not need it.**

`sudo` appears in exactly one place — `setup.sh` step 1, `apt-get install`. That
step exists to guarantee compilers and dev headers for building Python packages
from source. But nearly every dependency in `requirements-linux.txt` is either
pure Python or ships prebuilt manylinux wheels, so pip does not compile anything
on a normal x86-64 or arm64 Linux box.

```bash
./setup.sh --skip-apt       # the no-sudo path, and a fine default
```

There are exactly **two** things you cannot pip-install your way out of:

| Need | Why sudo helps | No-sudo alternative |
| --- | --- | --- |
| **Python ≥ 3.10** | `apt-get install python3.12` | §2 — pyenv, uv, or a standalone build |
| **The `venv` module** | Debian/Ubuntu split it into `python3-venv` | §4b — `virtualenv` from pip |

Everything else — `git`, `libxml2-dev`, `libssl-dev` — is either optional or
already covered by wheels. Details in §7.

---

## 2. Preflight

```bash
python3 --version          # must be 3.10, 3.11, 3.12 or 3.13
python3 -c 'import venv'   # must print nothing
df -h .                    # ~1.5 GB free
```

**Python version is the one hard requirement.** `requirements-linux.txt` pins
Django 5.2.8, which supports Python 3.10 through 3.13. Notably the *upstream*
`etc/requirements-20.txt` also pins Django 5.2.8 while Ubuntu 20.04 ships Python
3.8 — so a 20.04 box needs a newer interpreter regardless of which requirements
file you use.

`setup.sh` checks both of these before it does anything and stops with a
pointer here.

### Getting a newer Python without sudo

Any of these work; pick whichever your machine already leans toward.

**uv** (fastest, one static binary, no compiler needed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv python find 3.12          # note the path
```

**pyenv** (compiles CPython, so it *does* want build deps — use only if you
already have them, or on a distro where they ship by default):

```bash
curl -fsSL https://pyenv.run | bash
export PATH="$HOME/.pyenv/bin:$PATH"; eval "$(pyenv init -)"
pyenv install 3.12
pyenv local 3.12
```

**python-build-standalone** (prebuilt, no compiler, no installer):

```bash
mkdir -p ~/opt && cd ~/opt
# pick the cpython-3.12.* x86_64-unknown-linux-gnu-install_only asset from
# https://github.com/astral-sh/python-build-standalone/releases
tar xf cpython-3.12.*-install_only.tar.gz      # unpacks into ./python
export PATH="$HOME/opt/python/bin:$PATH"
```

Then point `setup.sh` at it by putting that `python3` first on `PATH`.

---

## 3. Get the files in place

The three source directories must sit side by side with this folder:

```
web/
├── cmweb-project/        the Django project
├── cmweb-app/            all the Django apps
├── cmweb-scripts/        infrastructure (not needed to run locally)
├── local-cmweb/          the Windows harness — stubs/ is shared from here
└── linux-local-cmweb/    ← you are here
```

`setup.sh` checks for `cmweb-project/cmweb`, `cmweb-app/explorer`,
`local-cmweb/stubs` and the fixture, and names whichever is missing.

**`local-cmweb/stubs/` is required** even though you are not on Windows — it
holds the shims for the ~17 Sony-internal packages, and this folder symlinks to
it rather than duplicating them.

If you copied the tree off a Windows machine, fix the line endings and exec bits
once:

```bash
cd linux-local-cmweb
sed -i 's/\r$//' setup.sh run.sh clean.sh scripts/*.py
chmod +x setup.sh run.sh clean.sh
```

---

## 4. Path A — with `sudo`

```bash
cd linux-local-cmweb
./setup.sh
```

Step 1 installs `etc/apt-packages.list`:

```
python3-pip  python3-venv  python3-dev  pkg-config
libxml2-dev  libxslt1-dev  libcurl4-openssl-dev  libssl-dev  git
```

That is a trimmed version of `cmweb-project/etc/apt-get-22.list`. Dropped, with
reasons, at the top of `etc/apt-packages.list` — the two that matter are
`somc-c2d-repository` and `somc-virtualenv3`, which live on Sony's internal apt
repository and are not reachable.

On a non-Debian distro, translate:

| Debian/Ubuntu | Fedora/RHEL | Arch | openSUSE |
| --- | --- | --- | --- |
| `python3-venv` | *(in `python3`)* | *(in `python`)* | *(in `python3`)* |
| `python3-dev` | `python3-devel` | *(in `python`)* | `python3-devel` |
| `libxml2-dev` | `libxml2-devel` | `libxml2` | `libxml2-devel` |
| `libxslt1-dev` | `libxslt-devel` | `libxslt` | `libxslt-devel` |
| `libssl-dev` | `openssl-devel` | `openssl` | `libopenssl-devel` |
| `libcurl4-openssl-dev` | `libcurl-devel` | `curl` | `libcurl-devel` |

then run `./setup.sh --skip-apt`.

## 4b. Path B — without `sudo`

```bash
cd linux-local-cmweb
./setup.sh --skip-apt
```

If that fails at the virtualenv step because `venv` is missing — the usual case
on a stock Debian or Ubuntu where you cannot install `python3-venv` — use
`virtualenv` from PyPI instead, which is pure Python and needs no privileges:

```bash
python3 -m pip install --user virtualenv     # or: pip install --user virtualenv
python3 -m virtualenv ENV
touch ENV/.virtualenv-installed              # so `make install` skips somc-virtualenv3
./setup.sh --skip-apt                        # now reuses the ENV/ you just made
```

`setup.sh` only creates `ENV/` when `ENV/bin/python3` is missing, so it will
pick up the one you built and carry on from step 4.

If even `pip` is unavailable:

```bash
curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user
export PATH="$HOME/.local/bin:$PATH"
```

### Behind a proxy

```bash
export https_proxy=http://proxy-sen.noc.sony.co.jp:10080
export http_proxy=$https_proxy
export no_proxy=localhost,127.0.0.1
```

Note that the upstream Makefile deliberately *unsets* the proxy before pip
(`cmweb-project/Makefile:63-64` and `:72`) because internal PyPI is inside the
network. Here the opposite is true — the packages are on public PyPI — so leave
the proxy set.

---

## 5. What `setup.sh` does, step by step

Run it once and it does all of this; the manual equivalents matter when a step
fails.

| Step | Command | Notes |
| --- | --- | --- |
| 0 | preflight | Python ≥ 3.10, `venv` present, source dirs found |
| 1 | `apt-get install` | skipped by `--skip-apt`; also skipped automatically if `apt-get` or `sudo` is missing |
| 2 | assemble `site/` | a tree of symlinks — see below |
| 3 | `python3 -m venv ENV` | then `touch ENV/.virtualenv-installed` |
| 4 | `pip install -r requirements-linux.txt` | ~40 packages |
| 5 | `manage.py migrate --noinput --skip-checks` | `--skip-checks` is mandatory |
| 6 | `scripts/load_testdata.py` | ~90 s, signals muted |
| 7 | `scripts/post_setup.py` | Site row, home page, logins |

### Step 2 in detail

`site/` is built as a directory of symlinks into `cmweb-project`, with `apps`
pointing at `cmweb-app` — exactly the layout the `cmweb-manifest` produces —
plus two real files:

- **`site/cmweb/secure.py`**, copied from `etc/secure.py.in`. Mandatory:
  `settings.py` imports it in a `try/except`, but references `OPENSEARCH_HOST`
  and `OPENSEARCH_AUTH_*` unguarded afterwards, so without it you get
  `NameError: OPENSEARCH_HOST`.
- **`site/cmweb/urls.py`**, copied and patched. This is the upstream
  instruction "open `/site/cmweb/urls.py` and update this line" — line 44,
  `RedirectToUrl.as_view()` → `auth_views.LoginView.as_view()`, so that
  `/accounts/login/` serves Django's own login form instead of redirecting to
  the LDAP flow.

Nothing is written into `cmweb-project`, `cmweb-app` or `cmweb-scripts`. They
have no `.git` in this working copy, so a mistake there would be unrecoverable.

### Step 5: why `--skip-checks`

Django runs system checks before `migrate`. The checks import the URLconf, which
reaches view classes that evaluate `paginate_by = Parameter.get_int(...)` at
class-body scope — a database query issued before any table exists. Without the
flag: `no such table: django_site`.

### Step 6: why not `make install-testdata`

The upstream target is a plain `loaddata`, which works. But the fixture is an
*already-indexed* snapshot; replaying it through the normal save path re-fires
CMWEB's indexing signals, which try to reach JIRA and M+ once per issue and
write a django-reversion revision per row — minutes instead of ~90 seconds, and
none of the work is wanted. `scripts/load_testdata.py` mutes model signals for
the duration. Full detail in
[`../local-cmweb/USING-TESTDATA.md`](../local-cmweb/USING-TESTDATA.md).

---

## 6. Run and verify

```bash
./run.sh                    # http://127.0.0.1:8000/
./run.sh --port 8080
./run.sh --public           # 0.0.0.0, reachable from other machines
```

Log in:

| User | Password | Where from |
| --- | --- | --- |
| `admin` | `s3cr17` | in the fixture — the upstream dev credential, verified against its PBKDF2 hash |
| `local` | `local` | created by `scripts/post_setup.py` |

Pages with real data behind them: `/builds/` (18 builds), `/commits/` (1,272),
`/repositories/` (1,087), `/branches/` (3), `/issues/` (405), `/packages/`
(771), `/admin/`, `/api/`.

```bash
ENV/bin/python3 scripts/smoke_test.py
```

requests ~21 pages through the test client. The Windows equivalent reports
`20 ok, 0 redirect/not-found, 0 failing`; this one adds `/accounts/login/`.

> The test client bypasses `WSGI_APPLICATION`, so a green smoke run does not
> prove `./run.sh` works. Check both.

**If you change the port, re-run post-setup.** `settings.py` defines no
`SITE_ID` — only `FEED_SITE_ID = 1` (`settings.py:219`) — so Django resolves
the current site by matching the request's `Host` header against `Site.domain`:

```bash
ENV/bin/python3 scripts/post_setup.py localhost:8080
```

---

## 7. Which dependencies actually need a compiler

The reason Path B works. From `requirements-linux.txt`:

| Group | Compiler needed? |
| --- | --- |
| Django and all `django-*`, DRF and its renderers | No — pure Python |
| `celery`, `kombu`, `django-celery-results` | No |
| `beautifulsoup4`, `isoweek`, `Markdown`, `markdown2`, `python-dateutil`, `python-debian`, `python-json-logger`, `pytz`, `six`, `simplejson`, `xlrd`, `Paste`, `pygerrit2` | No |
| `django-opensearch-dsl` → `opensearch-py` | No |
| `lxml` | Ships manylinux wheels — no. Only builds from source if pip falls back to the sdist, which is when `libxml2-dev`/`libxslt1-dev` matter. |
| `dulwich` | Ships wheels; has a pure-Python fallback |
| `rcssmin`, `rjsmin` | Build an optional C speedup and **fall back to pure Python** if no compiler is present |
| `pycodestyle`, `pydocstyle`, `pyflakes`, `unittest-xml-reporting` | No |

Deliberately absent, which is what removes the rest of the system dependencies:
`psycopg2-binary` (SQLite locally), `pymemcache` (the default `CACHES` is
LocMemCache, `settings.py:484-488`), `pyodbc`, `pygraphviz`, `boto3`,
`python-ldap` (see below).

**If a build does fail** and you cannot install dev headers, force wheels only
and see exactly which package is the problem:

```bash
ENV/bin/pip install --only-binary=:all: -r requirements-linux.txt
```

### LDAP is off by default

`requirements-linux.txt` leaves `python-ldap` and `django-auth-ldap` commented
out, and `stubs/` provides no-op shims. This is a choice, not a limitation:
`AUTHENTICATION_BACKENDS` (`settings.py:465-469`) ends in `ModelBackend`, so the
LDAP backends are tried and fall through to Django's own login — which is
exactly what the upstream guide means by "on local environment, the default
django login is used instead of LDAP".

To use the real ones you need `libldap2-dev` and `libsasl2-dev` (so, sudo) and a
reachable LDAP server. Uncomment both lines, then `./setup.sh --relink` so the
shims stop shadowing them.

---

## 8. Troubleshooting

Ordered by how likely I think each is on a first run.

| Symptom | Fix |
| --- | --- |
| `Python 3.x is too old` | §2 — you need ≥ 3.10 |
| `the venv module is missing` | §4b — `pip install --user virtualenv` |
| pip fails building `lxml` | `--only-binary=:all:`, or install `libxml2-dev`/`libxslt1-dev` |
| `ModuleNotFoundError: c2dclient` (or another internal name) | `PYTHONPATH` is not picking up `stubs/`. `run.sh` and the scripts set it; a bare `./manage.py` from `site/` does not — use `PYTHONPATH=../stubs ./manage.py …` |
| `ImportError` from `cmweb/__init__.py` | It imports `cmweb.celery` and `six.moves`, so `celery` and `six` must be installed. Unlike the Windows harness, nothing here bypasses `__init__.py`. |
| `NameError: OPENSEARCH_HOST` | `site/cmweb/secure.py` missing — `./setup.sh --relink` |
| `no such table: django_site` during migrate | `--skip-checks` was dropped |
| `near "ALTER": syntax error` | `GLOBALS['CM_WEB_ENVIRONMENT']` is not `'dev'`. It is `'dev'` by default (`settings.py:44`), so something overrode it. |
| Loading the fixture takes 10+ minutes | You ran `loaddata` directly instead of `scripts/load_testdata.py` |
| `/` returns 404 | `post_setup.py` has not run — no `home` page |
| Every page redirects to `/request/branches/` | The user lacks `users.view_all_pages` — re-run `post_setup.py` |
| Feeds or absolute URLs say `example.com` | The `Site` row does not match your host:port — §6 |
| `make install` tries to run `somc-virtualenv3` | `ENV/.virtualenv-installed` missing — `touch` it |
| `make static` / `make test` fails in compression | django-compressor offline mode; use `run.sh` (DEBUG serves static directly) or `manage.py test … --skip-checks` |
| A page 500s with `ShimNotAvailable` | That view needs a Sony-internal service. The message names it. Not a bug in the data. |
| `$'\r': command not found` | Windows line endings — §3 |

Start over at any point:

```bash
./clean.sh          # site/, stubs, var/, repository/, cache/, static/
./clean.sh --all    # also ENV/ and the database
./setup.sh --fresh
```

---

## 9. Afterwards

```bash
cd site
make install NO_APT_INSTALL=1        # now works — see README §3
make test TESTED_APPS="explorer"
make kwalitee                        # pyflakes + pycodestyle + pydocstyle
ENV/bin/python3 manage.py shell
```

What this instance cannot do — no indexing, no search, no git-backed pages, no
Gerrit workflow completion — and why, is in [README.md §8](README.md#8-limits).

---

## Related

- [README.md](README.md) — how the harness is built and how it maps to the upstream Quick Guide
- [`../local-cmweb/USING-TESTDATA.md`](../local-cmweb/USING-TESTDATA.md) — the fixture in detail
- [`../docs/development.md`](../docs/development.md) — the real upstream development guide
