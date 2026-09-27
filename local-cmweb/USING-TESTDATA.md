# Running local CMWEB on `testdata.json`

A step-by-step runbook for turning `cmweb-app/explorer/fixtures/testdata.json`
into a browsable CMWEB instance on this machine.

[README.md](README.md) explains *how the harness works* — the shims, the
settings, the deliberate differences from production. This document is the
*do this* version, centred on the fixture.

Everything below was run and verified on 2026-09-22: 20 of 20 smoke-test pages
returned 200.

---

## 1. What the fixture is

```
cmweb-app/explorer/fixtures/testdata.json      5.6 MB, 21,929 objects, 42 models
```

It is a `manage.py dumpdata` snapshot of a **real, already-indexed CMWEB
database**, trimmed to a few branches. Upstream it is produced by
`make testdata` (`cmweb-project/Makefile:211-231`), which runs `index_testdata`
against C2D and Gerrit and then dumps the result. That half needs Sony
infrastructure; loading the dump does not, which is what makes local browsing
possible at all.

What is in it:

| Rows | Model | |
| ---: | --- | --- |
| 5,276 | `packages.packagerevisiondelivery` | |
| 4,765 | `explorer.labelcomponentmembership` | which repo revision is in which build |
| 4,080 | `base.property` | the generic key/value store |
| 2,213 | `explorer.manifestcomponent` | |
| 1,272 | `explorer.commit` | |
| 1,087 | `explorer.project` | Gerrit repositories |
| 771 | `packages.packagerevision` | |
| 492 | `auth.user` + 491 `users.profile` | |
| 405 | `issues.issue` | |
| **18** | **`explorer.label`** | **the builds — the centre of the app** |
| 17 | `base.parameter` | runtime configuration |
| 3 | `explorer.manifestbranch` | |

The three manifest branches, and therefore the whole shape of the sample:

```
platform/amssmanifest    kumano-sm8150-la1.0
platform/manifest        p-kumano
platform/systemmanifest  p-kumano
```

The 18 builds are a mix of `C2D` releases (`55.0.A.0.470` … `55.0.A.0.477`),
`ANDROID` and `AMSS` nightly builds (`P-KUMANO-181212-1947`,
`KUMANO-SM8150-LA1.0-181212-1957`), and three `LATEST` virtual labels. The
underlying data is from December 2018 — dates on the site will look old, and
that is correct.

> **What it does not contain:** the `home` generic page, the `Site` row, and any
> user who can actually see the site. Those are environment-specific and get
> created separately (step 3 below). A fixture-only database renders `/` as a
> 404 and everything else as a redirect.

---

## 2. Prerequisites

- **Python 3.12** on `PATH` (`python --version`)
- **PowerShell**, from the `local-cmweb` directory
- ~700 MB free: 500 MB virtualenv, ~90 MB SQLite database
- No network access to anything Sony-internal is needed

You do **not** need PostgreSQL, memcached, OpenSearch, Gerrit, a JRE, or a C
toolchain. Nothing in `cmweb-project/`, `cmweb-app/` or `cmweb-scripts/` is
written to.

---

## 3. Load it — the short version

```powershell
cd C:\Users\Arkajyoti\Downloads\web\local-cmweb
.\setup.ps1
.\run.ps1
```

Then open <http://127.0.0.1:8000/>. That is the whole procedure; the rest of
this document explains what those two scripts did and what to do when you want
something other than the default.

Expect `setup.ps1` to take **3–5 minutes on a cold run**, most of it pip
installing and then ~90 seconds loading the fixture.

---

## 4. Load it — what actually happens

`setup.ps1` is five steps. Each has a manual equivalent, useful when one of them
fails or when you want to redo just that part.

### Step 1 — virtualenv

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
```

### Step 2 — dependencies

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`local-cmweb/requirements.txt`, **not** `cmweb-project/etc/requirements-22.txt`:
the Sony-internal packages are absent (the `stubs/` shims stand in), `python-ldap`
is absent, and versions are floated forward to ones that build on Python 3.12.

### Step 3 — database

Nothing to do on a first run. `-Fresh` deletes `var\cmweb_local.sqlite3` first.

### Step 4 — migrate

```powershell
.venv\Scripts\python.exe manage.py migrate --noinput --skip-checks
```

Two things about this command are not optional:

- **`--skip-checks`.** Django runs system checks before `migrate`, the checks
  import the URLconf, and the URLconf reaches view classes that evaluate
  `paginate_by = Parameter.get_int(...)` at class-body scope. That queries the
  database before any table exists. Without the flag you get
  `no such table: django_site`.
- **`CM_WEB_ENVIRONMENT = 'dev'`**, set in `config/settings_local.py`.
  `explorer` migration `0037` guards a PostgreSQL-only
  `ALTER COLUMN ... TYPE bigint` behind exactly that string. Any other value
  and SQLite fails with `near "ALTER": syntax error`.

Use `local-cmweb\manage.py`, never `cmweb-project\manage.py` — the latter loads
the real `cmweb.settings` and dies on the missing `secure.py`.

### Step 5 — load the fixture

```powershell
.venv\Scripts\python.exe scripts\load_sample_data.py
```

**Use this, not `manage.py loaddata`.** The script mutes every model signal
(`pre_save`, `post_save`, `m2m_changed`, …) for the duration of the load and
restores them afterwards. The fixture holds *already-indexed* data; replaying it
through the normal save path re-fires CMWEB's indexing signals, which try to
reach JIRA and M+ once per issue, recompute label completion, and write a
`django-reversion` revision per row. That takes **10+ minutes instead of ~90
seconds**, and every bit of the work is wrong — the results are already in the
file.

It prints:

```
Loading testdata.json (5.6 MB) with model signals muted...
Installed 21929 object(s) from 1 fixture(s)
Done in 92s.
```

### Step 5b — make the site navigable

```powershell
.venv\Scripts\python.exe scripts\post_setup.py
```

Creates the three things the fixture deliberately omits:

| | Why |
| --- | --- |
| `home` generic page | `/` is the catch-all `generic_pages` view; without it the front page 404s |
| `Site` row → `localhost:8000` | feeds and absolute URLs are built from it |
| superuser `local` / `local` | granted `users.view_all_pages`, the permission the whole site is gated on |

It finishes by printing the row counts, which is the quickest confirmation the
load worked:

```
Sample data loaded:
  builds             18
  commits            1272
  repositories       1087
  manifest branches  3
  issues             405
  package revisions  771
  user profiles      491
```

---

## 5. Run it

```powershell
.\run.ps1                  # http://127.0.0.1:8000/
.\run.ps1 -Port 8080
.\run.ps1 -Anonymous       # do not auto-login
```

You are signed in automatically as the `local` superuser. That is
`config/middleware_local.py` standing in for production's Apache-plus-LDAP
front end — without it nearly every view redirects you away, because
`PermissionCheckMiddleware` gates the site on `users.view_all_pages`.
`-Anonymous` gives you the unprivileged behaviour instead: a redirect to the
branch-request list.

### Pages that have real data behind them

| URL | What you get |
| --- | --- |
| `/builds/` | the 18 builds — the centre of the application |
| `/branches/platform/amssmanifest/kumano-sm8150-la1.0` | a build detail page |
| `…/kumano-sm8150-la1.0/+commits` | its commits |
| `…/kumano-sm8150-la1.0/+repositories` | repository revisions in that build |
| `…/kumano-sm8150-la1.0/+issues` | issues parsed out of its commit messages |
| `/commits/` | 1,272 commits |
| `/repositories/` | 1,087 Gerrit repositories |
| `/branches/` | the 3 manifest branches |
| `/issues/` | 405 issues |
| `/packages/` | 771 package revisions |
| `/admin/` | Django admin — including `base.Parameter`, the runtime config table |
| `/api/` | the browsable REST API |

Note the URL shape: branch names contain slashes, and CMWEB encodes them in
URLs. Builds are addressable both with and without the manifest prefix
(`ManifestMixin` defaults it to `GLOBALS['PLATFORM_MANIFEST']`), and label
sub-pages are the `+`-prefixed segments above.

---

## 6. Verify

```powershell
.venv\Scripts\python.exe scripts\smoke_test.py
```

Requests every significant page through Django's test client against the real
local database and prints a status line each. A good run ends:

```
20 ok, 0 redirect/not-found, 0 failing
```

Set `SMOKE_TRACEBACK=1` for full tracebacks on failures.

> The smoke test uses the test client, which **bypasses `WSGI_APPLICATION`
> entirely**. It will not catch a broken `config/wsgi_local.py`. Confirm with a
> real `.\run.ps1` before trusting a green run.

---

## 7. Reloading, resetting, substituting

**Re-load the fixture onto an existing database.** Safe — `loaddata` writes each
object at its explicit primary key, so rows are overwritten rather than
duplicated. Rows you added yourself that are not in the fixture survive.

```powershell
.venv\Scripts\python.exe scripts\load_sample_data.py
```

**Start completely over.** Deletes the SQLite file, migrates, reloads,
re-runs post-setup:

```powershell
.\setup.ps1 -Fresh
```

**Load a different dump.** The loader takes an optional path, so any
`dumpdata` snapshot with a compatible schema works — a trimmed fixture, or a
dump taken from stage:

```powershell
.venv\Scripts\python.exe scripts\load_sample_data.py C:\path\to\other.json
```

**Change the superuser.** `post_setup.py` reads two environment variables:

```powershell
$env:CMWEB_LOCAL_USER = 'arka'; $env:CMWEB_LOCAL_PASSWORD = 's3cret'
.venv\Scripts\python.exe scripts\post_setup.py
```

**Inspect the data without a browser:**

```powershell
.venv\Scripts\python.exe manage.py shell
.venv\Scripts\python.exe manage.py dbshell
```

---

## 8. Using the fixture outside this harness

On a Linux machine with a proper checkout (`cmweb-app` at `cmweb-project/apps/`)
and a working `cmweb/secure.py`, the upstream path is:

```bash
cd cmweb-project
make install-testdata        # = make db, then loaddata apps/explorer/fixtures/testdata.json
```

`make install-testdata` runs a plain `loaddata` with signals **live**, so expect
it to be slow for the reasons in step 5. It also does not create the home page,
the `Site` row or a privileged user — that part is specific to this harness.
The Makefile comment is accurate that it "works best on a fresh DB".

The fixture is also what `make test` builds on: `TESTED_APPS` test cases load it
as a Django fixture.

---

## 9. Regenerating it

You cannot do this here. `make testdata` is:

```make
index-testdata: install
	$(MANAGE_PY) index_testdata --system-branch … --amss-branch … --days …
testdata: index-testdata
	$(MANAGE_PY) dumpdata --indent=2 --exclude auth.permission $(TESTDATA_APPS) \
	  > apps/explorer/fixtures/testdata.json
```

`index_testdata` indexes live branches out of C2D and Gerrit, so it needs Sony
network access, the bare git mirrors, and Linux. In production there is a
`create_cmweb_testdata` Jenkins job for exactly this. Locally, treat
`testdata.json` as a read-only input.

---

## 10. Troubleshooting

| Symptom | Cause |
| --- | --- |
| `NameError: OPENSEARCH_HOST` | The real `cmweb.settings` got imported. The `sys.modules['cmweb']` binding at the top of `config/settings_local.py` must run before Django loads. Usually means `cmweb-project\manage.py` was used instead of `local-cmweb\manage.py`. |
| `no such table: django_site` during migrate | `--skip-checks` was dropped. |
| `near "ALTER": syntax error` | `CM_WEB_ENVIRONMENT` is not exactly `'dev'`. |
| `Fixture not found: …` | Run the loader from `local-cmweb\`; it resolves the fixture relative to its own location, two directories up. |
| Load takes 10+ minutes | You ran `manage.py loaddata` directly instead of `scripts\load_sample_data.py`. Signals are firing. |
| `/` returns 404 | `post_setup.py` has not run — no `home` page. |
| Every page redirects to `/request/branches/` | Auto-login is off, or the user lacks `users.view_all_pages`. Re-run `post_setup.py`. |
| A page 500s with `ShimNotAvailable` | That view needs a Sony-internal service. The exception message names which one. Not a bug in the data. |
| `get_wsgi_application() takes 0 positional arguments` | `WSGI_APPLICATION` must name the application object in `config/wsgi_local.py`, not the factory. |
| `__pycache__` appearing in `cmweb-app/` | Something ran without `sys.dont_write_bytecode`. Clean-up command in [README.md](README.md#keeping-the-source-repositories-clean). |

---

## 11. What the fixture cannot give you

The data is a snapshot, so anything that reaches past the database fails — by
design, and loudly:

- **No indexing.** `index_labels`, `index_latest`, `sync_commits` need C2D,
  Gerrit and bare git mirrors. They raise `ShimNotAvailable`.
- **No search.** `/search/` is removed; `search` and `django_opensearch_dsl`
  are not installed.
- **No git-backed pages.** Commit diffs, file browsing and manifest rendering
  read bare repositories under `var/repository/`, which is empty. Point
  `GLOBALS['PATH_REPOSITORY']` at real mirrors if you have them.
- **No Gerrit workflow completion.** Branch and repository requests can be
  created and voted on; completing one calls the Gerrit REST API and fails.
- **No Celery worker** — tasks run inline, as they do in production.

---

## Related

- [README.md](README.md) — how the harness is built: the shim inventory, the settings differences, the authentication story
- [docs/development.md](../docs/development.md) — the real Linux setup
- [docs/operations/01-management-commands.md](../docs/operations/01-management-commands.md) — `index_testdata` in context
- [docs/architecture.md](../docs/architecture.md) — what `Label`, `Commit` and `ManifestBranch` mean
