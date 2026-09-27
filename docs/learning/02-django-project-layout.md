# 02 — Django project layout, and CMWEB's version of it

> **Goal:** be able to create a Django project from nothing, explain what every
> generated file is for, and then explain exactly how and why CMWEB's layout
> differs from the generated one.

---

## 1. Project vs application

Django draws a line that is easy to miss because both words are overloaded.

| | **Project** | **Application (app)** |
| --- | --- | --- |
| What it is | The deployable unit — configuration and entry points | A reusable bundle of models, views, templates |
| How many | Exactly one per site | Many per project |
| Created by | `django-admin startproject` | `django-admin startapp` / `manage.py startapp` |
| Contains | `settings.py`, root `urls.py`, `wsgi.py`, `asgi.py` | `models.py`, `views.py`, `admin.py`, `migrations/` |
| Registered by | — | being listed in `INSTALLED_APPS` |

The rule of thumb from Django's own docs: *an app does one thing well; a
project is a collection of apps plus configuration.*

An app becomes "real" to Django only when it is in `INSTALLED_APPS`. That
listing is what makes Django look for its `models.py` (to register models), its
`migrations/` directory, its `templates/` and `static/` subdirectories, and its
`admin.py`.

---

## 2. The standard generated layout

```bash
django-admin startproject mysite
cd mysite
python manage.py startapp blog
```

produces:

```
mysite/                     <- the "outer" project directory (any name)
├── manage.py               <- CLI entry point
├── mysite/                 <- the "inner" package: the project itself
│   ├── __init__.py
│   ├── settings.py         <- all configuration
│   ├── urls.py             <- the ROOT_URLCONF
│   ├── asgi.py             <- ASGI entry point
│   └── wsgi.py             <- WSGI entry point (this is what Apache calls)
└── blog/                   <- an app
    ├── __init__.py
    ├── admin.py            <- admin site registrations
    ├── apps.py             <- the AppConfig for this app
    ├── migrations/
    │   └── __init__.py
    ├── models.py           <- M
    ├── tests.py
    └── views.py            <- V
```

Two directories are conventionally added by hand, because `startapp` does not
create them:

```
    blog/
    ├── templates/blog/     <- T   (note the repeated app name!)
    └── static/blog/        <- CSS/JS/images
```

### The repeated-directory-name trick

`templates/blog/index.html`, not `templates/index.html`. This looks redundant
but is essential. Django's `APP_DIRS` template loader searches *every* installed
app's `templates/` directory as one merged namespace. Without the app-name
subdirectory, two apps that both ship `index.html` would collide, and which one
won would depend on `INSTALLED_APPS` order. The same applies to `static/`.

CMWEB follows this convention exactly:

```
cmweb-app/explorer/templates/explorer/label_list.html
cmweb-app/explorer/static/explorer/...
```

### What each generated file actually does

| File | Purpose | Gotcha |
| --- | --- | --- |
| `manage.py` | Thin wrapper that sets `DJANGO_SETTINGS_MODULE` and calls `execute_from_command_line` | It is the *only* file that hardcodes a default settings module |
| `settings.py` | A plain Python module. Every uppercase module-level name becomes a setting | It is code, so it can compute values — which is both its power and its trap |
| `urls.py` | Module with a module-level `urlpatterns` list | Pointed at by the `ROOT_URLCONF` setting, not by filename magic |
| `wsgi.py` | Exposes a module-level `application` object | Named by `WSGI_APPLICATION`; must be the *object*, not a factory function |
| `asgi.py` | Same, for async servers | Unused by CMWEB (Apache + mod_wsgi is WSGI-only) |
| `apps.py` | An `AppConfig` subclass — app metadata and the `ready()` hook | `ready()` is the correct place to connect signals |
| `admin.py` | Where you call `admin.site.register(...)` | Loaded by `admin.autodiscover()` |
| `migrations/` | Ordered schema-change scripts | Chapter 07 |

---

## 3. Building a project from scratch, step by step

This is the exercise the topic list calls "setting up a Django project using
the standard project layout". Do it once in a scratch directory; it takes ten
minutes and makes the CMWEB layout legible.

```bash
# 1. Isolated environment
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Linux
pip install django

# 2. Project skeleton
django-admin startproject mysite .
#   the trailing "." puts manage.py in the current dir instead of nesting

# 3. First app
python manage.py startapp builds
```

**4. Register the app.** In `mysite/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'builds',                       # <- added
]
```

**5. Write a model** in `builds/models.py`:

```python
from django.db import models


class Build(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created',)

    def __str__(self):
        return self.name
```

**6. Create and apply the migration:**

```bash
python manage.py makemigrations builds
python manage.py migrate
```

**7. Write a view** in `builds/views.py`:

```python
from django.views.generic import ListView
from .models import Build


class BuildList(ListView):
    model = Build
    # default template name: builds/build_list.html
    # default context name:  object_list
```

**8. Route to it.** Create `builds/urls.py`:

```python
from django.urls import path
from .views import BuildList

urlpatterns = [
    path('', BuildList.as_view(), name='build_list'),
]
```

and include it from `mysite/urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('builds/', include('builds.urls')),
]
```

**9. Add the template** at `builds/templates/builds/build_list.html`:

```
{% for build in object_list %}
  <li>{{ build.name }} — {{ build.created|date:"Y-m-d" }}</li>
{% endfor %}
```

**10. Run it:**

```bash
python manage.py runserver
```

You have now touched every letter of MVT and both halves of the controller.
Everything CMWEB does is an elaboration of these ten steps.

---

## 4. How CMWEB's layout differs

CMWEB is *not* one directory produced by `startproject`. It is **three separate
git repositories** stitched together by Google's `repo` tool, from a manifest
project called `cmweb-manifest`.

```
                  +------------ the Django application -------------+

  cmweb-project/                    cmweb-app/                cmweb-scripts/
  the Django PROJECT                every Django APP          infrastructure
  ├── cmweb/                        ├── base/                 ├── ansible/
  │   ├── settings.py               ├── explorer/             ├── jobs_on_cloud/
  │   ├── settings_prod.py          ├── issues/               ├── cloudformation/
  │   ├── settings_stage.py         ├── request/              ├── agent/
  │   ├── settings_test.py          ├── harvest/              ├── bin/
  │   ├── urls.py                   ├── rebase/               └── etc/
  │   ├── wsgi.py                   ├── users/
  │   ├── middleware.py             └── ... 20+ apps
  │   ├── celery.py
  │   └── routers.py
  ├── templates/   site-wide
  ├── static/      CSS/JS/vendor
  ├── manage.py
  └── Makefile
```

### The critical constraint

**`cmweb-app` must be checked out or symlinked at `cmweb-project/apps/`.**

Nothing imports without this. `cmweb-project/cmweb/settings.py` does:

```python
APPS_DIR = join(GLOBALS['PATH_SITE'], 'apps')
sys.path.append(APPS_DIR)

FIXTURE_DIRS = (APPS_DIR,)
```

and separately reads `apps/.git` to compute the version string:

```python
curr_dir = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'apps', '.git')

__version__ = subprocess_output('git --git-dir=%s describe' % curr_dir)
```

`apps/` is listed in `cmweb-project/.gitignore` precisely so that the second
repository can be dropped in there without the first one noticing.

On a deployed host the result looks like this:

```
/srv/www/cmweb.ptc.sony.co.jp/
├── site/            <- cmweb-project        (PATH_SITE)
│   ├── cmweb/         settings, secure.py, settings_deployed.py -> settings_prod.py
│   └── apps/        <- cmweb-app            (on sys.path)
├── ENV/               virtualenv
├── static/            collectstatic + compressed output
├── repository/      -> /mnt/nfs/cmweb/repo-mirror   bare git mirrors
├── cache/             label metadata cache
└── var/log/           application logs
```

Every path in `settings.py` is derived from that shape:

```python
GLOBALS['PATH_PROJECT'] = dirname(abspath(__file__))       # site/cmweb
GLOBALS['PATH_SITE']    = dirname(GLOBALS['PATH_PROJECT']) # site
GLOBALS['PATH_ROOT']    = dirname(GLOBALS['PATH_SITE'])    # the deployment root
GLOBALS['PATH_REPOSITORY'] = join(GLOBALS['PATH_ROOT'], 'repository')
GLOBALS['PATH_LABEL_CACHE'] = join(GLOBALS['PATH_ROOT'], 'cache')
GLOBALS['PATH_VAR']     = join(GLOBALS['PATH_ROOT'], 'var')
GLOBALS['PATH_LOG']     = join(GLOBALS['PATH_VAR'], 'log')
```

This is why the local development copy needs `repository/`, `cache/` and
`var/log/` next to `cmweb-project/` — the settings module computes them
whether or not you intend to use them.

### Why split project from apps at all?

Not because they are independent components — neither runs without the other.
The split exists so the two can be **reviewed and released independently** in
Gerrit: application changes and configuration/deployment changes go through
separate review branches with separate cadences. `cmweb-scripts` is a third
repository for the same reason, and it contains no Python application code at
all.

### The `GLOBALS` dictionary

Standard Django puts everything at module level in `settings.py`. CMWEB adds a
project-specific dict:

```python
GLOBALS = {}
GLOBALS['CM_WEB_ENVIRONMENT'] = 'dev'
GLOBALS['CM_WEB_NAME'] = 'CMWEB Dev'
GLOBALS['PLATFORM_MANIFEST'] = 'platform/manifest'
GLOBALS['QSSI_MANIFEST'] = 'platform/qssimanifest'
...
```

Everything CMWEB-specific lives in `settings.GLOBALS[...]`, so it is visually
separated from Django's own settings. It is also passed wholesale to templates
by `cmweb.context_processors.settings`. Chapter 06 covers the layering.

### `apps/` vs `apps.py` — do not confuse them

- `cmweb-project/apps/` is a *directory* holding the whole second repository.
- `cmweb-app/explorer/apps.py` is a *module* holding an `AppConfig`:

```python
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VendorSyncConfig(AppConfig):
    """Configures vendor sync."""

    name = 'explorer'
    verbose_name = _("Explorer")
```

(The class name is a leftover from a copy-paste; the `name = 'explorer'`
attribute is what matters.)

### One more structural difference: `urls/` and `views/` as packages

Small apps have `views.py` and `urls.py`. `explorer` is not small, so both are
**packages**:

```
cmweb-app/explorer/views/          cmweb-app/explorer/urls/
├── __init__.py                    ├── __init__.py     <- shared regex fragments
├── branches.py                    ├── branches.py
├── commits.py                     ├── commits.py
├── features.py                    ├── features.py
├── labels.py                      ├── labels.py
├── mixins.py                      └── projects.py
└── projects.py
```

This is plain Python, not a Django feature — `include('explorer.urls.labels')`
works because `explorer/urls/labels.py` is an importable module with a
`urlpatterns` list. Chapter 04 covers how `explorer/urls/__init__.py` shares
regex fragments across the sub-modules.

---

## 5. The app catalogue

CMWEB has 21 apps in `cmweb-app/`. Grouped by what they do:

| Group | Apps | Role |
| --- | --- | --- |
| Foundation | `base` | Shared mixins, `Parameter`, `Property`, cache wrapper, template tags |
| Core domain | `explorer` | Projects, branches, labels, commits — the heart |
| Domain satellites | `issues`, `packages`, `product_packages`, `aod`, `historian` | JIRA issues, Debian packages, product mapping, AOD systems, history |
| Workflow | `request`, `harvest`, `rebase`, `vendorsync`, `type_approval`, `schedule` | FSM-driven processes |
| Integration | `gerritproxy`, `cmjenkins` | Talking to external services |
| Presentation | `dashboards`, `blog`, `users`, `search`, `api` | UI surfaces and access |
| Plumbing | `backend` | Task tracking |

`INSTALLED_APPS` lists more than these 21, because some apps are installed from
Sony-internal packages rather than living in `cmweb-app/` — `inlines`,
`generic_pages` and `commit_message_checker` among them. That is why
`local-cmweb/stubs/` has to provide stand-ins for them; see
[local-cmweb/README.md](../../local-cmweb/README.md).

Read [docs/01-django-apps.md](../01-django-apps.md) for the full catalogue with
per-app detail.

---

## 6. Try it

**A. Prove the `sys.path` trick.** In `local-cmweb/config/settings_local.py`,
find the lines that put `cmweb-app` on `sys.path`. That file does the same job
as the production `apps/` symlink, without moving any files. Then:

```powershell
cd local-cmweb
.venv\Scripts\python.exe manage.py shell
```

```python
import explorer, sys, os
os.path.dirname(explorer.__file__)   # points into cmweb-app, not cmweb-project
[p for p in sys.path if 'cmweb' in p]
```

**B. List the installed apps and where Django thinks they live:**

```python
from django.apps import apps
for cfg in apps.get_app_configs():
    print(f"{cfg.label:28} {cfg.path}")
```

**C. Find every template directory Django will search:**

```python
from django.template import engines
e = engines['django']
e.engine.dirs                      # the DIRS setting
[l for l in e.engine.template_loaders]
```

**D. Do the ten-step build** from section 3 in a throwaway directory. Then open
`cmweb-project/manage.py` and `cmweb-project/cmweb/wsgi.py` side by side with
your generated ones and list every difference.

---

## 7. Check yourself

1. What makes a directory a Django *app* as far as Django is concerned?
2. Why is a template stored at `explorer/templates/explorer/label_list.html`
   rather than `explorer/templates/label_list.html`?
3. Which setting names the root URLconf? Which names the WSGI callable?
4. `cmweb-app` is not inside `cmweb-project`. Name the two mechanisms in
   `settings.py` that depend on it being at `cmweb-project/apps/` anyway.
5. Why is `apps/` in `cmweb-project/.gitignore`?
6. `settings.GLOBALS['PATH_REPOSITORY']` resolves to a directory two levels
   above `settings.py`. Trace the three assignments that produce it.
7. What is the difference between `cmweb-project/apps/` and
   `cmweb-app/explorer/apps.py`?
8. `explorer` has `views/` as a package rather than `views.py`. Is that a
   Django feature or plain Python?
