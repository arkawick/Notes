# local-cmweb

A self-contained way to run CMWEB on this machine, against the sample dataset
that ships in `cmweb-app/explorer/fixtures/testdata.json`.

**Nothing in `cmweb-project`, `cmweb-app` or `cmweb-scripts` is modified.** Those
three directories are read-only inputs; every local-only change lives here.

## Quick start

```powershell
cd local-cmweb
.\setup.ps1          # virtualenv, dependencies, migrate, load sample data
.\run.ps1            # http://127.0.0.1:8000/
```

`.\setup.ps1 -Fresh` rebuilds the database from scratch.

The site auto-logs-in as a local superuser (`local` / `local`). See
[Authentication](#authentication) for why, and how to turn it off.

**Step-by-step runbook:** [USING-TESTDATA.md](USING-TESTDATA.md) — what the
fixture contains, what each setup step does and its manual equivalent, how to
reload or substitute the data, and fixture-specific troubleshooting. This
document covers how the harness is *built*; that one covers how to *use* it.

## What you get

The fixture is a `dumpdata` snapshot of a real indexed database — 21,929 rows:

| Data | Rows |
| --- | --- |
| Builds (`explorer.Label`) | 18 |
| Commits | 1,272 |
| Repositories (`explorer.Project`) | 1,087 |
| Manifest branches | 3 |
| Repository memberships per build | 4,765 |
| Issues | 405 |
| Package revisions | 771 |
| Users / profiles | 492 |

Pages worth visiting:

| URL | Shows |
| --- | --- |
| `/builds/` | The build list — the centre of the application |
| `/builds/<manifest>/<label>/+commits` | Commits in a build |
| `/builds/<manifest>/<label>/+repositories` | Repository revisions in a build |
| `/commits/` | Commit list |
| `/repositories/` | Gerrit repositories |
| `/branches/` | Manifest branches |
| `/issues/` | Issues parsed from commit messages |
| `/packages/` | Debian package revisions |
| `/admin/` | Django admin, including the `Parameter` runtime settings |
| `/api/` | Browsable REST API |

## How it works

```
local-cmweb/
├── config/
│   ├── settings_local.py     standalone settings (does NOT import cmweb.settings)
│   ├── urls_local.py         root URLconf, mirrors cmweb/urls.py
│   ├── middleware_local.py   replaces PermissionCheckMiddleware
│   └── wsgi_local.py         WSGI application object
├── stubs/                    shims for Sony-internal packages
├── scripts/
│   ├── load_sample_data.py   fixture loader with model signals muted
│   └── post_setup.py         home page, Site row, local superuser
├── manage.py                 use this, not cmweb-project/manage.py
├── setup.ps1 / run.ps1
└── var/                      sqlite db, logs, cache  (gitignored)
```

`config/settings_local.py` puts `cmweb-app`, `cmweb-project` and `stubs/` on
`sys.path`, which is what normally requires `cmweb-app` to be checked out at
`cmweb-project/apps/`. The repositories stay where they are.

### The internal-package problem

`cmweb-project/etc/requirements-22.txt` lists packages published only on Sony's
internal index. They are not obtainable here, so `stubs/` provides stand-ins:

| Shim | Real package | Fidelity |
| --- | --- | --- |
| `envoy` | `envoy` | **Full** — reimplemented over `subprocess` |
| `somc_decorators.retry` | `somc-decorators` | **Full** — generic retry decorator |
| `somcutil.git` / `.matcher` | `somcutil` | **Full** — pure string/regex logic |
| `repo_manifest` | `repo-manifest` | **Parses manifests** — real XML parsing |
| `inlines` | `somc-django-inlines` | **Reimplemented** — `{% show_object %}`, `render_inlines` |
| `generic_pages` | `generic-pages` | **Real model** — `blog.Post` subclasses it |
| `c2dclient` | `c2dclient` | Raises on use — no build system to query |
| `jiraapi` | `jiraapi` | Constructs; requests raise (read as "not in JIRA") |
| `mplusclient` | `mplusclient` | Raises on use |
| `jenkinsclient` | `jenkinsclient` | Raises on use |
| `dmsclient` | `somc-dmsclient` | Raises on use |
| `vendorrelease` | `vendorrelease` | Raises on use |
| `ldap`, `django_auth_ldap` | `python-ldap` | No-op — needs a C toolchain on Windows |
| `rest_framework_swagger` | `django-rest-swagger` | Notice page — 2.1.1 is dead on DRF 3.15 |
| `rpc4django` | `rpc4django` | Notice page |

Anything that hits a raise-on-use shim throws `ShimNotAvailable`, whose message
names the missing package — so a shim boundary is never mistaken for a CMWEB bug.

### Deliberate differences from production

All marked `LOCAL:` in `config/settings_local.py`:

- **SQLite** instead of PostgreSQL, **local-memory cache** instead of memcached.
- **`CM_WEB_ENVIRONMENT = 'dev'`** — not cosmetic. `explorer` migration `0037`
  guards a PostgreSQL-only `ALTER COLUMN ... TYPE bigint` behind exactly this
  value, because SQLite cannot alter column types. Any other value breaks
  `migrate`.
- **Apps omitted**: `search` and `django_opensearch_dsl` (no OpenSearch),
  `django_celery_results` (no broker), `rest_framework_swagger`, `rpc4django`.
- **`RemoteUserMiddleware` dropped** — with no Apache doing LDAP auth in front,
  it logs every request out.
- **Compression off** — the real settings compress offline through a YUI jar
  that needs a JRE.
- **`cmweb` bound as a bare package.** `cmweb/__init__.py` imports
  `cmweb.celery` and `cmweb.settings`, and the latter shells out to
  `git describe` and dies on `OPENSEARCH_HOST` (it expects the uncommitted
  `cmweb/secure.py`). The settings module registers `cmweb` in `sys.modules`
  with an explicit `__path__` so its submodules — `middleware`,
  `context_processors`, `urljsonserializer` — import without running
  `__init__.py`. None of them needs anything from the package itself.

### Authentication

In production, requests reach Django already authenticated: Apache performs
LDAP basic auth, `RemoteUserMiddleware` turns that into a Django user, and
`PermissionCheckMiddleware` then requires the `users.view_all_pages` permission.

`config/middleware_local.py` reproduces that assumption by signing every request
in as a local superuser. Without it the site is unbrowsable, since nearly every
view sits behind that permission.

```powershell
.\run.ps1 -Anonymous        # or set CMWEB_LOCAL_AUTOLOGIN=0
```

turns it off, and you get production's behaviour for an unprivileged user:
redirected to the branch-request list. The `local` / `local` account also works
for a normal login at `/admin/`.

### Why the fixture loads with signals muted

`scripts/load_sample_data.py` detaches all model signals during the load. The
fixture is *already-indexed* data; replaying it through the normal save path
re-fires the indexing signals, which try to reach JIRA and M+ per issue,
recompute label completion, and write a django-reversion revision per row. That
is both very slow on SQLite and semantically wrong — the results are already in
the fixture. Signals are restored afterwards.

### Two shims that had to be more than stubs

Both were forced by how the application uses them, and both are worth knowing
about if a page misbehaves:

- **`inlines`** provides `{% show_object %}`, `{% inline_url %}` and the
  `render_inlines` filter. `show_object` picks
  `inlines/<app>_<model>.html` (dozens ship with the apps) falling back to
  `inlines/default.html`. `render_inlines` expands
  `<inline type="app.model" ids="1,2" />` markup embedded in page, post and
  comment bodies — the format comes from
  `blog/templates/admin/blog/post/change_form.html`, which generates it.
- **`generic_pages.GenericPage`** is a concrete model with an `author` foreign
  key. `blog.Post` subclasses it, `blog/migrations/0001_initial.py` declares a
  FK onto it, `blog/views.py` filters posts on `author`, and the post templates
  render the author's profile and gravatar.

## Verifying it works

```powershell
.venv\Scripts\python.exe scripts\smoke_test.py
```

Requests every significant page through Django's test client against the real
local database, and prints a status line per URL. Set `SMOKE_TRACEBACK=1` for
full tracebacks.

## Limits

This runs the **browse and admin surface** of CMWEB. It cannot do the things
that need infrastructure that is not here:

- **No indexing.** `index_labels`, `index_latest`, `sync_commits` and friends
  need C2D, Gerrit, and bare git mirrors. They will raise `ShimNotAvailable`.
- **No search.** `/search/` is removed; there is no OpenSearch cluster.
- **No Gerrit-backed workflow.** Branch and repository requests can be created
  and voted on, but completing one calls the Gerrit REST API and will fail.
- **No git-backed pages.** Commit diffs, file browsing and manifest rendering
  read bare repositories under `var/repository/`, which is empty. Point
  `GLOBALS['PATH_REPOSITORY']` at real mirrors if you have them.
- **No Celery worker.** Tasks run inline (`CELERY_TASK_ALWAYS_EAGER`).

## Troubleshooting

**`NameError: OPENSEARCH_HOST`** — something imported the real `cmweb.settings`.
Check that the `sys.modules['cmweb']` binding at the top of
`config/settings_local.py` still runs before Django loads.

**`no such table: django_site` during `migrate`** — you dropped `--skip-checks`.
System checks import the URLconf, which reaches modules that query the database
at import time.

**`near "ALTER": syntax error`** — `CM_WEB_ENVIRONMENT` is not `'dev'`.

**A page 500s with `ShimNotAvailable`** — that view needs a Sony-internal
service. The exception message names which one.

**`get_wsgi_application() takes 0 positional arguments`** — `WSGI_APPLICATION`
must name the application object in `config/wsgi_local.py`, not the factory
function. Note that `scripts/smoke_test.py` uses Django's test client, which
bypasses `WSGI_APPLICATION` entirely, so it will not catch this — check with a
real `.\run.ps1` before trusting a green smoke run.

## Keeping the source repositories clean

`manage.py` and the scripts set `sys.dont_write_bytecode = True`, so importing
`cmweb-app` and `cmweb-project` leaves no `__pycache__` directories behind. If
you run Django some other way and they appear, remove them with:

```powershell
Get-ChildItem -Path ..\cmweb-project,..\cmweb-app -Filter __pycache__ -Recurse -Directory |
    Remove-Item -Recurse -Force
```
