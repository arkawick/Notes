# How this runs without the Sony dependencies

CMWEB is an internal application. It expects a Sony network, a Sony package
index, and a handful of files that are generated at deploy time and never
committed. None of that exists on a laptop.

This document explains, in detail, **what each of those dependencies is, what
was put in its place, and why that particular substitution was chosen** — then,
in §8, how to build a setup like this for another internal application.

[README.md](README.md) is the tour of the folder. [USING-TESTDATA.md](USING-TESTDATA.md)
is the runbook. This is the *why*.

---

## 1. What is actually missing

Four different kinds of dependency, which need four different kinds of answer.
Conflating them is the main way this sort of project goes wrong.

| Kind | Examples | Can it be faked? |
| --- | --- | --- |
| **Live network services** | Gerrit, C2D, JIRA, M+, Jenkins, DMS, LDAP, OpenSearch | No. There is no data to serve. |
| **Internal Python packages** | `c2dclient`, `jiraapi`, `mplusclient`, `jenkinsclient`, `somc-dmsclient`, `vendorrelease`, `somcutil`, `somc-decorators`, `somc-django-inlines`, `generic-pages`, `repo-manifest`, `commit-message-checker`, `envoy` | Yes — the *import* must succeed; whether the *call* can is a separate question. |
| **Internal apt packages** | `somc-c2d-repository`, `somc-virtualenv3`, plus dev headers for PostgreSQL/ODBC/graphviz/LDAP | Avoided entirely by not needing what they build. |
| **Generated, uncommitted files** | `cmweb/secure.py`, `cmweb/settings_deployed.py`, the bare git mirrors under `PATH_REPOSITORY` | Yes — write a local version. |

The insight that makes the whole thing tractable: **an internal package is not
the same thing as an internal service.** Roughly half of CMWEB's internal
dependencies are pure logic — string handling, XML parsing, subprocess
wrapping, Django template tags — with no server behind them at all. Those can be
reimplemented completely. Only the other half are clients for services, and
those are the ones that genuinely cannot work.

---

## 2. The five substitution techniques

Every missing piece is handled by exactly one of these. The choice is not a
matter of taste; it follows from what the thing does.

### A. Reimplement it

**When:** the package is pure logic with no service behind it.

`envoy` is a 60-line wrapper around `subprocess` whose result object exposes
`status_code` / `std_out` / `std_err`; `base/utils/git.py` depends on exactly
those three attributes. `repo_manifest` parses repo XML into project objects.
`somcutil.git` / `.matcher` are string and regex helpers. `somc_decorators.retry`
is a generic retry decorator. `inlines` is a Django template library.
`generic_pages` is a Django model.

These are reimplemented properly, and the local site is not degraded by them at
all. Two were *forced* to be real rather than stubs:

- **`inlines`** provides `{% show_object %}`, `{% show_object_list %}`,
  `{% inline_url %}` and the `render_inlines` filter. Almost every CMWEB
  template renders objects through `show_object`, so a stub would have produced
  a site of blank pages. The contract had to be inferred from the templates
  that ship with the app: `show_object` selects the first template that exists
  out of `inlines/<app_label>_<model_name>.html` then `inlines/default.html`,
  with `object`, `model`, `mode` and `cache_key` in context. Dozens of those
  per-model templates are in the repository, which is what made the contract
  recoverable.
- **`generic_pages.GenericPage`** is a *concrete model* with an `author`
  foreign key. `blog.Post` subclasses it, `blog/migrations/0001_initial.py`
  declares an FK onto it, `blog/views.py` filters on `author`, and the post
  templates render the author's profile. A stub class would have broken
  `migrate`, not just rendering.

### B. Raise on use, with a message that names the package

**When:** the package is a client for a service that is not reachable.

`c2dclient`, `jiraapi`, `mplusclient`, `jenkinsclient`, `dmsclient`,
`vendorrelease`. Importing succeeds, constructing succeeds, calling raises
`ShimNotAvailable`. Mechanism in §4.

The point is diagnostic honesty. A silent `None` or an empty list would let a
page render *wrongly*, and you would waste an afternoon deciding whether CMWEB
had a bug. An exception whose message says

> `'c2dclient'` is a Sony-internal package with no public release, so
> local-cmweb ships a shim instead. The code path you just hit needs the real
> implementation.

tells you immediately that you have hit the boundary of the local setup, not a
defect.

### C. Decline politely

**When:** the application has a working fallback, and raising would block it.

`ldap` / `django_auth_ldap`. `users/auth.py` imports `django_auth_ldap.backend`
at module level, so the module must exist — but `LDAPBackend.authenticate()`
returns `None` rather than raising, because that is exactly the protocol Django
uses to mean "this backend does not know this user, try the next one".
`AUTHENTICATION_BACKENDS` then falls through to `ModelBackend` and the local
user table. The right stub here is a polite refusal, not an error.

`jiraapi.JiraClient` is a nuanced case of the same idea. Its docstring records
the reasoning: callers in `issues/indexing.py` build the client *outside* their
`try/except` and guard only the request:

```python
client = get_jira_client()      # must not raise
try:
    return client.get(...)      # may raise; None means "not in JIRA"
except Exception:
    pass
```

So the constructor must succeed and `get()` must raise — and the application
then reads the failure as "this issue does not exist in JIRA", which is the
*correct* answer when there is no JIRA to ask.

### D. Serve a notice page

**When:** the missing thing is a web UI that is dead or pointless locally.

- **`rpc4django`** — CMWEB exposes XML-RPC at `/rpc/` for the git-mirroring
  scripts to fetch the mirror manifest. Nothing local calls it, so
  `serve_rpc_request` returns an HTTP 501 with a paragraph explaining what
  production uses it for. The shim also supplies a pass-through `@rpcmethod`
  decorator, since application code decorates functions with it at import time.
- **`rest_framework_swagger`** — `django-rest-swagger` 2.1.1 is unmaintained
  and incompatible with DRF 3.15, so this one is not even installable. It is
  shimmed rather than substituted, and `/api/` uses DRF's own browsable
  renderer, which is better anyway.

### E. Remove the app from settings

**When:** an app exists *only* to talk to a service, and has no models anything
else references.

`search` and `django_opensearch_dsl` are dropped from `INSTALLED_APPS`, and
`search/` is dropped from the URLconf. `search` has no models — it is
`documents.py` definitions plus a signal processor — so nothing else breaks. No
shim needed at all.

Contrast with **`django_celery_results`, which is deliberately kept**. It looks
like broker infrastructure, but the `backend` app imports
`django_celery_results.models.TaskResult` at module level, and the models need
no broker — results just go to the database. Removing it breaks the import;
keeping it costs nothing.

And `celery` itself is a hard requirement, which is worth knowing because a
from-scratch install proved it the hard way:

```
cmweb-app/base/__init__.py  →  from .tasks import run_command
cmweb-app/base/tasks.py     →  from celery import shared_task
```

`base` is in `INSTALLED_APPS`, so **celery must import before the app registry
finishes populating.** Without it, `manage.py migrate` dies inside
`django.setup()`. It was missing from `requirements.txt` for months and nobody
noticed, because every existing venv happened to have it.

---

## 3. The inventory

Everything in `stubs/`, by technique.

| Shim | Stands in for | Technique | Fidelity |
| --- | --- | --- | --- |
| `envoy` | `envoy` | A — reimplemented over `subprocess` | **Full** |
| `somc_decorators.retry` | `somc-decorators` | A | **Full** |
| `somcutil.git` / `.matcher` / `.cron` | `somcutil` | A | **Full** — pure string/regex |
| `repo_manifest` | `repo-manifest` | A | Parses real manifest XML |
| `inlines` | `somc-django-inlines` | A | Reimplemented; contract inferred from shipped templates |
| `generic_pages` | `generic-pages` | A | **Real concrete model** — `blog.Post` subclasses it |
| `commit_message_checker` | `commit-message-checker` | A | Shim Django app; URLs answer |
| `c2dclient` | `c2dclient` | B — raises | No build system to query |
| `jiraapi` | `jiraapi` | B/C — constructs, `get()` raises | Read as "not in JIRA" |
| `mplusclient` | `mplusclient` | B — raises | See §4, the class-body trap |
| `jenkinsclient` | `jenkinsclient` | B — raises | |
| `dmsclient.dmsodbc` | `somc-dmsclient` | B — raises | Legacy ODBC issue DB |
| `vendorrelease` | `vendorrelease` | B — raises | |
| `ldap` | `python-ldap` | C — `initialize()` raises, `set_option()` ignores | Needs a C toolchain on Windows |
| `django_auth_ldap` | `django-auth-ldap` | C — `authenticate()` returns `None` | Falls through to `ModelBackend` |
| `rpc4django` | `rpc4django` | D — 501 notice + pass-through decorator | |
| `rest_framework_swagger` | `django-rest-swagger` | D — notice page | 2.1.1 is dead on DRF 3.15 |
| *(none)* | `search`, `django_opensearch_dsl` | E — removed from settings | No models |

Note the shape of it: **the raise-on-use shims are all tiny** (a dozen lines,
an exception class and a `ShimObject` subclass), and **the reimplementations are
where the work went.** That is the expected distribution, and a useful sanity
check — if you find yourself writing hundreds of lines of a *service client*
stub, you are faking data, which is a different and much worse project.

---

## 4. The `_shim` machinery, and the bug that shaped it

`stubs/_shim.py` provides two things.

**`ShimNotAvailable(NotImplementedError)`** — the exception, whose message always
names the real package.

**`ShimObject`** — a base class for service clients. Construction always
succeeds and records its arguments; any method call raises. That split matters
because application code routinely builds a client outside the `try/except` that
guards the request.

The interesting part is this, verbatim from `_shim.py`:

```python
_PROTOCOL_NAMES = frozenset((
    'contribute_to_class', 'deconstruct', 'get_absolute_url',
    'resolve_expression', 'as_sql', 'prepare_database_save',
    '__iter__', '__len__', '__getitem__', '__call__', '__deepcopy__', ...
))
```

`ShimObject.__getattr__` raises `AttributeError` for those names instead of
returning a callable. The comment explains why, and it is the best lesson in the
whole folder:

> Django and the standard library probe objects with `hasattr()` for protocol
> hooks. A `__getattr__` that returns a callable for *any* name makes every such
> probe succeed, and the caller then invokes something that raises.

The concrete failure: `request/models.py` constructs an `MPlusAPI()` **inside the
body of the `RepositoryRequest` model class**, to populate `FUNCTIONAL_AREAS`. So
the instance ends up as a class attribute, and Django's
`ModelBase.add_to_class` checks `hasattr(value, 'contribute_to_class')`. A naive
catch-all `__getattr__` answers *yes*, Django calls it, and model construction
explodes at import time — before any of your own code runs.

**The general rule: a catch-all `__getattr__` must refuse protocol names.**
Otherwise `hasattr()` lies, and frameworks make decisions on that lie.

---

## 5. Settings: a replacement, not an override

`config/settings_local.py` deliberately does **not** do
`from cmweb.settings import *`. That import alone would:

- shell out to `git describe` against `apps/.git`, which does not exist here;
- create directories next to the source repositories;
- die with `NameError: OPENSEARCH_HOST`, because `cmweb/secure.py` is
  (correctly) not committed, and settings references that name unguarded a few
  lines after importing `secure` inside a `try/except`.

So everything CMWEB reads is redefined from scratch, with each deviation marked
`LOCAL:`. The substitutions:

| Real | Local | Why |
| --- | --- | --- |
| PostgreSQL / RDS | SQLite at `var/cmweb_local.sqlite3` | no server needed |
| memcached / ElastiCache | `LocMemCache` | ditto |
| OpenSearch | *app removed* | §2E |
| Celery + SQS | `CELERY_TASK_ALWAYS_EAGER` | already true in production |
| LDAP via Apache + `RemoteUserMiddleware` | `LocalPermissionMiddleware` | §6 |
| offline compression via a YUI jar | `COMPRESS_ENABLED = False` | needs a JRE |
| SMTP | console email backend | see mail in the terminal |
| `/srv/www/<host>/` layout | three sibling directories on `sys.path` | nothing is moved |

### The `cmweb` package trick

CMWEB's middleware, context processors and JSON serializer live in
`cmweb-project/cmweb/` and are referenced by dotted path
(`cmweb.middleware.PjaxVersionMiddleware`, `cmweb.urljsonserializer`). Importing
that package normally runs `cmweb/__init__.py`, which imports `cmweb.celery`
**and `cmweb.settings`** — the very module being avoided.

The fix is to register the package without ever executing its `__init__.py`:

```python
_cmweb_pkg = types.ModuleType('cmweb')
_cmweb_pkg.__path__ = [join(PROJECT_REPO, 'cmweb')]
sys.modules['cmweb'] = _cmweb_pkg
```

Python then finds `cmweb.middleware` and friends through `__path__` and skips
`__init__.py` entirely. This is safe *only because* none of the three modules
used imports anything from the package itself — which was checked, not assumed.

### Hosts point at `.invalid`

```python
GLOBALS['GERRIT_SERVER'] = 'gerrit.local.invalid'
GLOBALS['JIRA_SERVER']   = 'jira.local.invalid'
```

`.invalid` is reserved by RFC 2606 and can never resolve. Anything that slips
past a shim and tries a real connection fails immediately and unmistakably,
rather than hanging on a DNS timeout or — worse — reaching something real.

---

## 6. Five traps that are not obvious

Each of these cost a debugging session, and none of them is discoverable by
reading the code top to bottom.

**1. `CM_WEB_ENVIRONMENT` must be exactly `'dev'`.** `explorer` migration `0037`
guards a PostgreSQL-only `ALTER COLUMN ... TYPE bigint` behind that precise
string, because SQLite cannot alter column types. Any other value and `migrate`
fails with `near "ALTER": syntax error`.

**2. `migrate` needs `--skip-checks`.** Django runs system checks first; the
checks import the URLconf; the URLconf reaches view classes that evaluate
`paginate_by = Parameter.get_int(...)` **at class-body scope** — a database query
issued before any table exists. Symptom: `no such table: django_site`.

**3. The fixture must load with model signals muted.** `testdata.json` is an
*already-indexed* snapshot. Replaying it through the normal save path re-fires
CMWEB's indexing signals, which try to reach JIRA and M+ once per issue,
recompute label completion, and write a `django-reversion` revision per row.
Measured: **47 seconds muted, over ten minutes not.** And the work is not merely
slow, it is wrong — the results are already in the file.

**4. The site is unbrowsable without an authenticated superuser.**
`PermissionCheckMiddleware` gates everything on `users.view_all_pages`. In
production Apache has already done LDAP basic auth and `RemoteUserMiddleware`
has turned it into a user. `LocalPermissionMiddleware` reproduces that
*assumption* by signing every request in as a local superuser — and
`RemoteUserMiddleware` is dropped, because with no Apache in front it logs
everyone out on every request. `CMWEB_LOCAL_AUTOLOGIN=0` restores production's
behaviour for an unprivileged user: a redirect to the branch-request list.

**5. The fixture contains no `Site` row and no home page.** `/` is the catch-all
generic_pages view, so without a page at slug `home` the front page 404s; feeds
and absolute URLs need the `Site`. Both are created by `scripts/post_setup.py`,
because they are environment-specific and correctly absent from a data dump.

> Worth noting: the local settings set `SITE_ID = 1`, which the *real*
> `settings.py` does not — it defines only `FEED_SITE_ID = 1` and lets Django
> resolve the site by matching the request `Host` against `Site.domain`. Pinning
> `SITE_ID` locally removes a whole class of "why does this say example.com"
> confusion at the cost of one behavioural difference from production.

---

## 7. What genuinely cannot work

The boundary is sharp and it is **always the same boundary**: anything that needs
a live service or a git mirror.

| Broken | Because |
| --- | --- |
| All indexing (`index_labels`, `index_latest`, `sync_commits`, …) | needs C2D, Gerrit and bare git mirrors |
| `/search/` | no OpenSearch cluster; the app is removed |
| Commit diffs, file browsing, manifest rendering | read bare repos under `var/repository/`, which is empty |
| Completing a branch or repository request | calls the Gerrit REST API |
| JIRA issue enrichment | no JIRA |
| `/rpc/` | notice page |

**How to tell a boundary from a bug:** a boundary raises `ShimNotAvailable` and
the message names the package. Anything else is a real defect — in CMWEB or in
this harness — and worth chasing.

---

## 8. Building a setup like this yourself

The order matters. Each step is chosen to fail fast and to keep the diagnosis
local.

**1. Never modify the source.** Put every local-only file in one new directory.
Here `cmweb-project/`, `cmweb-app/` and `cmweb-scripts/` are read-only inputs,
wired together on `sys.path` rather than moved. This is what lets you `git pull`
the real repositories without a merge, and it keeps "is this us or them?"
answerable. `sys.dont_write_bytecode = True` in every entry point, so you do not
even leave `__pycache__` behind.

**2. Get `import settings` to work before anything else.** Not `migrate`, not a
page — just settings. This is where you discover the generated files
(`secure.py`), the subprocess calls (`git describe`), and the import-time side
effects. Decide here whether to *override* the real settings or *replace* them:
replace, if the real one has side effects you cannot suppress.

**3. Let the import errors drive the shim list.** Do not inventory the
requirements file and write stubs speculatively. Run it, read the
`ModuleNotFoundError`, write the smallest module that satisfies *that* import,
run again. The list you end up with is exactly the list you need, and each shim
is shaped by a real call site instead of a guess.

**4. Classify each one before writing it.** Ask a single question: *is there a
service behind this?* No → reimplement it (§2A) and the local site loses nothing.
Yes → raise on use (§2B) and make the message name the package. This one
question determines almost everything.

**5. Make construction succeed and calls fail.** Application code builds clients
outside the `try/except` that guards the request. And **refuse protocol names in
any catch-all `__getattr__`** (§4) — otherwise `hasattr()` lies to the framework.

**6. Expect the database layer to fight you.** Dumping PostgreSQL for SQLite
surfaces raw SQL in migrations, PostgreSQL-only column types, and `ALTER COLUMN`
statements. Grep the migrations for `RunSQL` and for your engine name early —
that is how migration `0037`'s `'dev'` guard turned up.

**7. Reproduce the authentication *assumption*, not the mechanism.** Do not try
to run LDAP. Work out what the auth stack leaves behind — here, "a logged-in
user with `view_all_pages`" — and provide that directly. Then give yourself a
switch to turn it off, so you can still see production's unprivileged
behaviour.

**8. Load real data, with signals off.** A production dump is worth more than
any amount of factory code, and it is usually already in the repository for the
test suite. Mute model signals: a snapshot is *already indexed*, and re-firing
the indexing pipeline over it is both slow and semantically wrong.

**9. Write the smoke test on day one.** `scripts/smoke_test.py` requests every
significant page through Django's test client and prints a status line each. It
is the only way to know that a shim you wrote for one page did not break
another. Know its blind spot: the test client bypasses `WSGI_APPLICATION`
entirely, so a green run does not prove the real server starts.

**10. Make failures name themselves.** `ShimNotAvailable('c2dclient', ...)`,
hosts at `.invalid`, `LOCAL:` comments on every deviation. The goal is that six
months later, someone hitting a 500 can tell in one line whether they found a
CMWEB bug or the edge of the sandbox.

### The debugging loop, concretely

```
run it  →  read the error  →  which of §1's four kinds is this?
                             ├─ import error      → new shim (§2A or §2B)
                             ├─ NameError/config  → settings (§5)
                             ├─ SQL error         → migrations / engine (§6)
                             └─ redirect/403      → auth assumption (§6.4)
        →  smoke test  →  repeat
```

---

## Verifying

```powershell
.venv\Scripts\python.exe scripts\smoke_test.py
```

A good run: `20 ok, 0 redirect/not-found, 0 failing`, covering the home page,
build/commit/repository/branch/issue/package lists, the blog, requests, harvest,
historian, vendors, the admin, the browsable API and four build sub-pages.

---

## Related

- [README.md](README.md) — the folder tour, shim table, deliberate differences
- [USING-TESTDATA.md](USING-TESTDATA.md) — the fixture: contents, loading, reloading
- [`../linux-local-cmweb/HOW-IT-WORKS.md`](../linux-local-cmweb/HOW-IT-WORKS.md) — the same problem solved differently, using the *real* settings
- [`../docs/how-the-site-works.md`](../docs/how-the-site-works.md) — what the real deployment does, end to end
- [`../CLAUDE.md`](../CLAUDE.md) — short-form architecture
