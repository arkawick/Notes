# 1. Django apps, and adding one to CMWEB

*Assumes no prior Django knowledge. Read this before the other seven.*

---

## Part A — The Django concept

### A project vs. an app

Django splits code into two levels:

- A **project** is the whole site. It holds settings, the root URL map, and the
  WSGI entry point. There is exactly one.
- An **app** is a self-contained feature area: its own models, views, templates
  and URLs. A project contains many.

The distinction is not enforced by the language — an app is just a Python
package that Django knows about. What makes it an app is being listed in the
`INSTALLED_APPS` setting.

In CMWEB this maps onto the repository split you already know:

| | Django role | Repository |
| --- | --- | --- |
| The project | settings, root URLconf, WSGI | `cmweb-project` |
| The apps (24 of them) | all features | `cmweb-app` |

### What an app is made of

Django looks for specific filenames inside an app package. None are mandatory —
Django simply uses them if present:

| File | Purpose |
| --- | --- |
| `models.py` | Database tables, defined as Python classes |
| `views.py` | Functions/classes that turn a request into a response |
| `urls.py` | Maps URL patterns to views |
| `admin.py` | Registers models with Django's built-in admin site |
| `apps.py` | App configuration object (optional) |
| `migrations/` | Versioned database schema changes |
| `templates/` | HTML templates |
| `templatetags/` | Custom template functions |
| `tests.py` or `tests/` | Tests |
| `management/commands/` | Custom `manage.py` subcommands |

### Why `INSTALLED_APPS` matters

Adding an app to `INSTALLED_APPS` is what makes Django:

- create database tables for its models
- discover its migrations
- find its templates and static files
- load its template tags
- register its admin classes

An app not in that list is invisible — its models will not get tables, even
though the Python imports fine. This is the most common beginner confusion.

---

## Part B — How CMWEB does it

### Where apps physically live

Because `cmweb-app` is a separate repository, CMWEB does something unusual.
`cmweb-project/cmweb/settings.py` contains:

```python
APPS_DIR = join(GLOBALS['PATH_SITE'], 'apps')   # <cmweb-project>/apps
sys.path.append(APPS_DIR)
```

`sys.path` is Python's list of directories to search for imports. Appending
`apps/` means every app inside it is importable **by its bare name**:

```python
from explorer.models import Label     # correct
from apps.explorer.models import Label  # wrong — this is not how it works
```

So `cmweb-app` must be checked out (or symlinked) at `cmweb-project/apps/`.
`local-cmweb` achieves the same thing differently, by putting the `cmweb-app`
directory directly on `sys.path` without moving it.

### The 24 apps, grouped

**Core domain**

| App | What it owns |
| --- | --- |
| `base` | Shared infrastructure: `Parameter`, `Property`, cache wrapper, view mixins, git/Gerrit/JIRA utilities |
| `explorer` | The heart — `Project`, `Branch`, `ManifestBranch`, `Label`, `Commit` |
| `issues` | Issues, delivery tags |
| `users` | LDAP-backed profiles, organisations, disciplines |
| `aod` | `SystemFamily` / `System` — the product taxonomy |

**Workflow**

| App | What it owns |
| --- | --- |
| `request` | Branch and repository request approval |
| `harvest` | Cherry-pick policies |
| `rebase` | Rebase policies |
| `schedule` | `BranchPeriod`, the shared "applies to a branch for a time window" base |
| `type_approval` | Type-approval windows |

**Presentation**

`dashboards`, `historian`, `packages`, `product_packages`, `vendorsync`, `blog`,
`search`

**Integration**

`api` (REST), `gerritproxy` (Gerrit REST wrapper), `backend` (async job
tracking), `cmjenkins` (Jenkins server registry)

---

## Part C — Adding a new app

### Step 1: create it in the right place

```bash
cd cmweb-project          # the PROJECT directory
./manage.py startapp myapp apps/myapp
```

Note the second argument. Without it, `startapp` creates the app in the current
directory, which is the wrong repository.

### Step 2: register it

In `cmweb-project/cmweb/settings.py`, add to the **CMWEB apps** block at the top
of `INSTALLED_APPS` — not the "Prerequisites" or "Django apps" blocks below it:

```python
INSTALLED_APPS = [
    # CMWEB apps
    'base',
    'inlines',
    'aod',
    'explorer',
    'myapp',            # <-- here
    ...
```

Order within `INSTALLED_APPS` matters for template resolution: the first app
with a matching template path wins. CMWEB relies on this deliberately —
the comments in `settings.py` note that `django_comments` must come after `blog`,
and `django.contrib.admin` after `grappelli`, so the earlier app's templates
override the later one's.

### Step 3: wire up URLs

Create `myapp/urls.py`:

```python
"""URLconf for myapp."""

from django.urls import re_path

from myapp.views import ThingListView

urlpatterns = [
    re_path(r'^things/?$', ThingListView.as_view(), name='myapp_thing_list'),
]
```

Then include it in `cmweb-project/cmweb/urls.py`:

```python
path(r'myapp/', include('myapp.urls')),
```

**Placement matters.** Add it *above* these two lines, which are catch-alls:

```python
re_path(r'^(explorer/)?', include('explorer.urls')),   # very greedy
...
path(r'', include('generic_pages.urls')),              # site-wide catch-all
```

The `generic_pages` include serves `/` and every flat page by slug, so anything
after it is unreachable.

### Step 4: add it to the test list

In `cmweb-project/Makefile`:

```makefile
TESTED_APPS ?= $(CORE_APPS) \
    aod \
    myapp \
    ...
```

This is easy to miss and fails silently — `make test` simply never runs your
app's tests. There is no automatic discovery.

### Step 5: migrations

```bash
./manage.py makemigrations myapp
./manage.py migrate --skip-checks
```

See [06-migrations.md](06-migrations.md) for why `--skip-checks` is needed.

### Step 6 (optional): navigation and inline templates

The sidebar is a `sitetree` dynamic tree defined at the bottom of
`cmweb/urls.py`. Add an `item(...)` entry to make your app appear.

If your models will be shown in lists, add
`myapp/templates/inlines/myapp_thing.html` — otherwise they render through the
generic fallback as a plain link. See [03-views.md](03-views.md#the-inlines-system).

---

## Part D — The `__init__.py` trap

Normally `__init__.py` is empty and just marks a directory as a Python package.
**In CMWEB, several apps put substantial logic there, and it executes at import
time.**

| File | Contents |
| --- | --- |
| `explorer/__init__.py` | ~180 lines: the XML-RPC manifest server (`GetApprovedManifest`, `GetManifest`). This is what the git-mirroring script calls to build the mirror. |
| `vendorsync/__init__.py` | ~400 lines: `label_complete` signal handlers doing AMSS / AU / Android / Mediatek release detection. |
| `base/__init__.py` | Re-exports the `run_command` Celery task |
| `historian/__init__.py` | Re-exports `analyze_zeitgeist_entry` |
| `request/__init__.py` | Re-exports `create_repositories` |

Three practical consequences:

**1. Importing an app can be expensive.** Importing `explorer` opens the cache
and reads `Parameter` rows from the database.

**2. Never import models at the top of `__init__.py`.** It runs before Django's
app registry is ready, and you get `AppRegistryNotReady`. Look at how
`vendorsync/__init__.py` does it — every handler imports its models *inside* the
function body:

```python
def handle_amss_release(instance):
    """Update AMSS release info."""
    # Avoid circular imports
    from base.models import Property
    from explorer.models import Label
    from .models import SourceBranch, ReleaseSource, Release
```

**3. The re-exports are not decoration.** They exist so Celery's
`autodiscover_tasks()` registers the task under the expected name. If your new
app has tasks, follow the pattern:

```python
"""My app."""

from __future__ import absolute_import

from .tasks import my_task

__all__ = ['my_task']
```

See [05-celery-tasks.md](05-celery-tasks.md).

### `apps.py` — mostly absent

Only four apps define one (`aod`, `explorer`, `product_packages`, `vendorsync`),
and they are minimal:

```python
class VendorSyncConfig(AppConfig):
    """Config class for the 'VendorSync' model."""

    name = 'vendorsync'
    verbose_name = _("Vendor Sync")
```

Modern Django auto-generates an `AppConfig` when you omit it, so add one only if
you need a custom `verbose_name` or a `ready()` hook. There is no house
convention to match.

---

## Checklist

```
[ ] created under cmweb-project/apps/
[ ] added to INSTALLED_APPS (CMWEB block)
[ ] urls.py written, included in cmweb/urls.py ABOVE the catch-alls
[ ] added to TESTED_APPS in the Makefile
[ ] makemigrations + migrate
[ ] every module/class/method has a docstring (pydocstyle gate — see 02)
[ ] no model imports at module level in __init__.py
[ ] inlines/<app>_<model>.html for models shown in lists
[ ] sitetree entry if it needs a sidebar link
```

**Next:** [02-management-commands.md](02-management-commands.md)
