# How this runs without the Sony dependencies (Linux)

CMWEB expects a Sony network, a Sony package index, and files that are generated
at deploy time and never committed. This folder runs it without any of them —
and, unlike the Windows harness, **without replacing CMWEB's own settings
module.**

That single difference drives everything below. Where
[`../local-cmweb/HOW-IT-WORKS.md`](../local-cmweb/HOW-IT-WORKS.md) substitutes
for the configuration, this one *satisfies* it.

> **Not executed on Linux.** This folder was built on Windows by reading the
> source; source facts are cited by file and line and were checked, but the
> install has not been run. The dependency list *has* been corrected against a
> real from-scratch run of the Windows harness. See [README.md](README.md) §9 and
> [INSTALL.md](INSTALL.md) §8.

---

## 1. Two ways to solve the same problem

| | `local-cmweb/` (Windows) | `linux-local-cmweb/` (here) |
| --- | --- | --- |
| Settings | `config/settings_local.py` — a full replacement, ~370 lines | **the real `cmweb.settings`, unmodified** |
| `DJANGO_SETTINGS_MODULE` | `config.settings_local` | `cmweb.settings` |
| `cmweb/__init__.py` | bypassed via a `sys.modules` binding | **runs normally** |
| Layout | three siblings wired onto `sys.path` | a `site/` symlink tree reproducing the manifest |
| `secure.py` | not needed — settings never import it | **generated** from `etc/secure.py.in` |
| URLconf | `config/urls_local.py`, a parallel copy | `cmweb/urls.py`, copied and one line patched |
| Apps dropped | `search`, `django_opensearch_dsl`, `rpc4django`, `rest_framework_swagger` | **only** `python-ldap` shimmed by choice; the rest install for real |
| LDAP | backends removed from settings | backends present, decline, fall through |

Neither is better in the abstract. The Windows approach exists because Windows
cannot build `python-ldap` and the real settings die on `git describe` and
`NameError`. The Linux approach is preferable **when you can make it work**,
because the site then behaves the way production does rather than the way a
substitute settings module makes it behave — which is the whole point of testing
locally.

---

## 2. What is missing, and what answers it

Four kinds of dependency, four kinds of answer.

| Kind | Examples | Answer here |
| --- | --- | --- |
| **Live services** | Gerrit, C2D, JIRA, M+, Jenkins, DMS, LDAP, OpenSearch | shims that raise, naming the package (§4) |
| **Internal Python packages** | `c2dclient`, `jiraapi`, `somcutil`, `repo-manifest`, `somc-django-inlines`, `generic-pages`, … | `stubs/`, **shared** with the Windows harness (§4) |
| **Internal apt packages** | `somc-c2d-repository`, `somc-virtualenv3`, dev headers | sidestepped — §6 and `etc/apt-packages.list` |
| **Generated files** | `cmweb/secure.py`, `cmweb/settings_deployed.py`, the git mirrors | `secure.py` generated; the rest not needed (§3) |

The key insight, same as on Windows: **an internal package is not the same thing
as an internal service.** About half of CMWEB's internal dependencies are pure
logic — subprocess wrapping, XML parsing, regex helpers, Django template tags —
with no server behind them, and those are reimplemented completely rather than
stubbed. Only service clients genuinely cannot work.

---

## 3. Satisfying the real settings instead of replacing them

Four things stand between `cmweb.settings` and a working import. Each is
*satisfied* here rather than avoided.

### `secure.py` — the mandatory "optional" file

`settings.py:562-565` does:

```python
try:
    from .secure import *
except Exception as e:
    sys.stderr.write("%r.\n" % e)
```

which looks optional — but twenty lines later it references `OPENSEARCH_HOST`
and `OPENSEARCH_AUTH_*` **unguarded** when building `OPENSEARCH_DSL`. So a
missing `secure.py` produces `NameError: OPENSEARCH_HOST`, not a readable
message. In production Ansible renders this file from the vault; on a Jenkins
slave the job builders write it from bound credentials. Here `setup.sh` copies
`etc/secure.py.in` into `site/cmweb/secure.py`.

Because it is imported *last*, anything in it wins over `settings.py`. It carries
four things: the OpenSearch names (pointed at `localhost`, never contacted —
`OPENSEARCH_DSL_AUTOSYNC` is already `False`), empty service credentials,
`DEBUG = True`, and `ALLOWED_HOSTS = ['*']` — the last because `settings.py`
defines no `ALLOWED_HOSTS` at all, and Django's `DEBUG` fallback covers only
localhost.

### The defaults that already suit a laptop

Two pleasant surprises, both verified:

- `DATABASES` defaults to **SQLite** at `join(PATH_ROOT, 'cm_web_db')`
  (`settings.py:193-201`). No substitution needed.
- `CACHES` defaults to **`LocMemCache`** (`settings.py:484-488`). No memcached.
- `GLOBALS['CM_WEB_ENVIRONMENT']` is already `'dev'` (`settings.py:44`) — which
  matters more than it looks; see §7.

### `PATH_ROOT`, and why `site/` is a symlink tree

`settings.py:53-68` derives every path relatively:

```python
PATH_PROJECT    = dirname(abspath(__file__))   # site/cmweb
PATH_SITE       = dirname(PATH_PROJECT)        # site
PATH_ROOT       = dirname(PATH_SITE)           # linux-local-cmweb/
PATH_REPOSITORY = join(PATH_ROOT, 'repository')
```

On a web server `PATH_ROOT` is `/srv/www/<host>/`. Here it is
`linux-local-cmweb/`. So reproducing the manifest layout — `cmweb-project` at
`site`, `cmweb-app` at `site/apps` — is enough to make every derived path land
correctly, with the database, `static/`, `cache/` and `repository/` inside this
folder instead of beside the source.

`setup.sh` builds `site/` as a directory of symlinks, with two real files:
`cmweb/secure.py` (generated) and `cmweb/urls.py` (patched). It does **not**
create `cmweb-project/apps` and `cmweb-project/cmweb/secure.py` directly, even
though both are gitignored upstream and doing so would be legitimate — because
these three directories are extracted copies with no `.git`, so a mistake there
is unrecoverable.

### `git describe` fails harmlessly

`settings.py:32-34` runs `git --git-dir=<site>/apps/.git describe` to build
`__version__`. `cmweb-app` has no `.git` here, so the subprocess fails, stdout is
empty, and `__version__` ends up `''`. It feeds the PJAX version header and the
footer, neither of which breaks. Worth knowing so you do not chase it.

### `cmweb/__init__.py` runs — so celery is mandatory

The Windows harness binds `cmweb` into `sys.modules` with an explicit `__path__`
so `__init__.py` never executes. Here it runs, and it does:

```python
from six.moves import reload_module
from cmweb.celery import app as celery_app
from cmweb.settings import __version__, ...
```

so `six` and `celery` must be installed. `cmweb/celery.py` also does
`os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cmweb.settings_deployed')` —
a file that does not exist here. Harmless in practice, because
`cmweb-project/manage.py` sets `DJANGO_SETTINGS_MODULE` to `cmweb.settings`
*before* importing Django, and `run.sh` and all three scripts export it. It
would only bite a bare `python -c 'import cmweb'`.

---

## 4. The shims

`stubs` is a **symlink to `../local-cmweb/stubs`**, not a copy. One source of
truth, no drift — and it is why `setup.sh` checks for `local-cmweb/stubs` up
front and why a Linux-only checkout still needs that folder (its `.venv` and
database are irrelevant and can be deleted).

The full per-package inventory, the fidelity table and the `_shim.py` internals
are in [`../local-cmweb/HOW-IT-WORKS.md`](../local-cmweb/HOW-IT-WORKS.md) §2–§4.
The two things worth repeating here, because they are the load-bearing ideas:

**Construction succeeds; calls raise.** Application code routinely builds a
service client *outside* the `try/except` that guards the request, so
`ShimObject.__init__` must not raise. Calling any method raises
`ShimNotAvailable`, whose message names the real package — so a failure is never
mistaken for a CMWEB bug.

**A catch-all `__getattr__` must refuse protocol names.** `_shim.py` keeps a
`_PROTOCOL_NAMES` set (`contribute_to_class`, `deconstruct`, `__iter__`, …) and
raises `AttributeError` for those. The reason is concrete:
`request/models.py` builds an `MPlusAPI()` **inside the body of the
`RepositoryRequest` model class**, so the instance becomes a class attribute and
Django's `ModelBase.add_to_class` probes
`hasattr(value, 'contribute_to_class')`. A naive shim answers yes, Django calls
it, and model construction explodes at import time. If `hasattr()` lies,
frameworks make decisions on the lie.

### Which shims Linux still needs, and which it doesn't

This is the real delta from the Windows setup.

**Installed for real from PyPI** (the Windows harness deletes these apps from
settings; here they are in `INSTALLED_APPS` because the real settings put them
there, so they have to be genuine):

| Package | Why it can be real here |
| --- | --- |
| `django-opensearch-dsl` | the `search` app and every `documents.py` import it; `OPENSEARCH_DSL_AUTOSYNC` is `False`, so nothing connects on save |
| `django-celery-results` | `backend` imports `TaskResult` at module level; the models need no broker |
| `celery` | `base/__init__.py` → `base/tasks.py` → `shared_task`; needed before the app registry finishes |
| `rpc4django` | on public PyPI and importable, so `/rpc/` can be the real handler |

**Still shimmed:**

| Shim | Why, on Linux specifically |
| --- | --- |
| all the service clients (`c2dclient`, `jiraapi`, `mplusclient`, `jenkinsclient`, `dmsclient`, `vendorrelease`) | the services are unreachable — nothing about the OS changes that |
| all the pure-logic internals (`envoy`, `somcutil`, `somc_decorators`, `repo_manifest`, `inlines`, `generic_pages`, `commit_message_checker`) | still not on public PyPI; the reimplementations lose nothing |
| `rest_framework_swagger` | `django-rest-swagger` 2.1.1 is unmaintained and incompatible with DRF 3.15 — not installable at any price |
| `ldap`, `django_auth_ldap` | **by choice, not necessity** — see below |

### LDAP is the one deliberate choice

Linux *can* build `python-ldap`, given `libldap2-dev` and `libsasl2-dev`. It is
still shimmed by default, because:

`AUTHENTICATION_BACKENDS` (`settings.py:465-469`) is

```python
['users.auth.AuthLDAPBackend', 'users.auth.RemoteLDAPBackend',
 'django.contrib.auth.backends.ModelBackend']
```

The LDAP backends are tried first, decline (the shim's `authenticate()` returns
`None`, which is Django's protocol for "not my user, try the next backend"), and
`ModelBackend` answers from the local user table. That is exactly what the
upstream Quick Guide means by *"on local environment, the default django login
is used instead of LDAP"* — the fallback is already in the real settings, so no
settings change is needed at all.

To use the real packages: uncomment them in `requirements-linux.txt`, add the two
apt packages, and `./setup.sh --relink` so the shims stop shadowing them. You
will also need a reachable directory server for it to be worth anything.

---

## 5. The one source edit upstream asks for

The upstream Quick Guide says:

> open `/site/cmweb/urls.py` and update this line
> `re_path(r'^accounts/login/?$', RedirectToUrl.as_view()),`
> with this line
> `re_path(r'^accounts/login/?$', auth_views.LoginView.as_view()),`

Because in production `/accounts/login/` redirects into the LDAP flow, and
locally there is nothing there. `setup.sh` applies exactly that change by
copying `cmweb/urls.py` and `sed`-ing line 44, rather than editing the source —
so `site/cmweb/urls.py` is a real file while every other module in
`site/cmweb/` is a symlink. If upstream ever renames that view, the script warns
that the patch did not apply and tells you to use `/admin/` instead.

This is a genuine divergence from the Windows harness, which keeps
`RedirectToUrl` and relies on auto-login instead — so here you get a real login
form at `/accounts/login/`.

---

## 6. Avoiding the apt dependencies

`cmweb-project/etc/apt-get-22.list` wants `somc-c2d-repository` and
`somc-virtualenv3` from Sony's apt repository, plus dev headers for PostgreSQL,
ODBC, graphviz and LDAP. None is reachable, and none is needed:

| Dropped | Because |
| --- | --- |
| `somc-virtualenv3` | `setup.sh` uses `python3 -m venv`, then `touch`es `ENV/.virtualenv-installed` — the stamp file that Makefile target produces, so `make install` skips it |
| `somc-c2d-repository` | the C2D client is shimmed |
| `libpq5`, `libpq-dev` | SQLite |
| `unixodbc*` | only the DMS client, which is shimmed |
| `graphviz`, `libgraphviz-dev` | only `django-extensions`' `graph_models` |
| `memcached` | `LocMemCache` |
| `python3-ldap`, `libldap2-dev`, `libsasl2-dev` | shimmed by choice (§4) |

And `make install` itself is made to work by a second substitution:
`site/etc/requirements-20.txt` and `requirements-22.txt` are both symlinks to
`requirements-linux.txt`, since the Makefile picks the file by
`lsb_release --release`. After `setup.sh` has run once,
`cd site && make install NO_APT_INSTALL=1` works verbatim.

The upshot, covered in [INSTALL.md](INSTALL.md) §1 and §7: **`sudo` is not
actually required.** Nearly every dependency is pure Python or ships manylinux
wheels, so `./setup.sh --skip-apt` is a fine default. Only two things resist a
no-sudo install, and both are about the interpreter rather than the packages —
Python ≥ 3.10 (Django 5.2's floor) and the `venv` module, which Debian and Ubuntu
split into `python3-venv`.

---

## 7. Traps that survive the switch to real settings

Most of the Windows gotchas are configuration, and disappear here. Three are
properties of the *application* and remain.

**1. `CM_WEB_ENVIRONMENT` must be exactly `'dev'`.** `explorer` migration `0037`
guards a PostgreSQL-only `ALTER COLUMN ... TYPE bigint` behind that precise
string, because SQLite cannot alter column types. `settings.py:44` already sets
`'dev'`, so this works out of the box — but it is why you must not casually
override it, and why the symptom `near "ALTER": syntax error` means "something
changed that value".

**2. `migrate` needs `--skip-checks`.** System checks import the URLconf, which
reaches view classes that evaluate `paginate_by = Parameter.get_int(...)` at
class-body scope — a query issued before any table exists. Symptom:
`no such table: django_site`.

**3. The fixture must load with model signals muted.** `testdata.json` is an
*already-indexed* snapshot; replaying it through the normal save path re-fires
the indexing signals, which try to reach JIRA and M+ per issue and write a
django-reversion revision per row. Measured on the Windows harness: **47 seconds
muted, over ten minutes not** — and the work is wrong either way, since the
results are already in the file. Hence `scripts/load_testdata.py` rather than
`make install-testdata`.

Two more are environment setup rather than traps, handled by
`scripts/post_setup.py`:

**The `Site` row must match the host you browse.** `settings.py` defines no
`SITE_ID` — only `FEED_SITE_ID = 1` (`settings.py:219`) — so Django resolves the
current site by matching the request's `Host` header against `Site.domain`. That
is why the upstream guide insists on `localhost:8000` exactly, and why changing
the port needs `post_setup.py localhost:8080`. (The Windows harness pins
`SITE_ID = 1` instead, removing the issue at the cost of one difference from
production.)

**`users.view_all_pages` must be granted explicitly.** `PermissionCheckMiddleware`
gates the whole site on it. The fixture's `admin` user (password `s3cr17`,
verified against its PBKDF2 hash) is a superuser, but the fixture was dumped with
`--exclude auth.permission` (`Makefile:229`), so its permission rows are not
guaranteed to survive a fresh `migrate`. `post_setup.py` grants it to both
`admin` and `local`.

---

## 8. What still cannot work

The boundary is the same on any OS: anything needing a live service or a git
mirror.

| Broken | Because |
| --- | --- |
| All indexing | needs C2D, Gerrit, bare git mirrors |
| `/search/` | `django_opensearch_dsl` is installed and `search` loads, but `OPENSEARCH_HOST` is `localhost` and there is no cluster |
| Commit diffs, file browsing, manifest rendering | read bare repos under `repository/`, which is empty |
| Completing a branch/repository request | calls the Gerrit REST API |
| `make static` / offline compression | production compresses through a YUI jar that wants a JRE; use `run.sh` with `DEBUG`, which serves static directly |

**Boundary or bug?** A boundary raises `ShimNotAvailable` and the message names
the package. Anything else is a real defect worth chasing.

Note the difference from Windows on search: there the app is *removed*, so
`/search/` 404s; here it is *present but unbacked*, so it loads and then fails on
query. Present-but-unbacked is closer to production and a better test of
everything around it.

---

## 9. Building a setup like this yourself

The methodology is in [`../local-cmweb/HOW-IT-WORKS.md`](../local-cmweb/HOW-IT-WORKS.md)
§8 as ten ordered steps and a debugging loop. Three points are specific to the
"satisfy the real settings" strategy used here, and they are the ones that decide
whether it is viable at all:

**Try satisfying before replacing.** Replacing a settings module is a standing
maintenance cost — every upstream change to `settings.py` has to be mirrored by
hand, and your local site quietly diverges from production. Spend the effort on
the generated files first (`secure.py` here). Only replace when the real module
has side effects you cannot suppress — which is exactly why Windows had to:
`git describe`, directory creation, and an unguarded `NameError`.

**Read the paths before moving anything.** `PATH_ROOT = dirname(PATH_SITE)` is
the single fact that made the symlink tree work and put every generated artefact
inside this folder. Applications that derive paths relatively will cooperate with
a layout you construct; applications with absolute paths will not, and you find
out which in five minutes of reading.

**Check the defaults before substituting them.** `settings.py` already defaults
to SQLite, `LocMemCache`, `CELERY_TASK_ALWAYS_EAGER`, and
`CM_WEB_ENVIRONMENT = 'dev'`. Four substitutions that turned out to be
unnecessary, because the application already had a development path. Read the
defaults first; you may be planning work that is already done.

---

## Related

- [README.md](README.md) — the folder tour and the upstream-step mapping
- [INSTALL.md](INSTALL.md) — the walkthrough, with and without `sudo`
- [`../local-cmweb/HOW-IT-WORKS.md`](../local-cmweb/HOW-IT-WORKS.md) — the canonical treatment: full shim inventory, `_shim.py` internals, the ten-step method
- [`../local-cmweb/USING-TESTDATA.md`](../local-cmweb/USING-TESTDATA.md) — the fixture in detail
- [`../docs/how-the-site-works.md`](../docs/how-the-site-works.md) — what the real deployment does
