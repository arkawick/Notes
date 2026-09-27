# 3. Views, URLs and templates

*How a request becomes a page, and the mixin system CMWEB builds on top.*

---

## Part A — The Django concept

### The request cycle

```
browser → URLconf → middleware → view → template → response
```

A **view** is a callable that takes an `HttpRequest` and returns an
`HttpResponse`. That is the entire contract.

### Function views vs. class-based views

The simplest view is a function:

```python
def my_view(request):
    return HttpResponse("hello")
```

But most pages repeat the same shapes: *list the objects*, *show one object*,
*edit one object*. Django ships **class-based generic views** for these:

| Class | Gives you |
| --- | --- |
| `ListView` | A page listing a queryset, with pagination |
| `DetailView` | A page for one object, looked up by pk or slug |
| `CreateView` / `UpdateView` / `DeleteView` | Form handling for one object |
| `TemplateView` | Renders a template with no model |
| `RedirectView` | Issues a redirect |
| `View` | The bare base — you implement `get()`, `post()` yourself |

A complete `ListView` (`aod/views.py`, real CMWEB code):

```python
from django.views.generic import ListView

from aod.models import SystemFamily


class SystemFamilyView(ListView):
    """View class for SystemFamily."""

    model = SystemFamily
    paginate_by = 20
```

That is a full paginated list page. Django infers:

- the queryset → `SystemFamily.objects.all()`
- the template → `aod/systemfamily_list.html` (`<app>/<model>_list.html`)
- the context variable → `object_list`

### The methods you override

Class-based views are customised by overriding methods, not by passing
arguments:

| Method | Override to |
| --- | --- |
| `get_queryset()` | Change which objects are listed |
| `get_context_data()` | Add extra variables to the template |
| `get_template_names()` | Choose the template dynamically |
| `dispatch()` | Run code before anything else |
| `get_object()` | Change how the single object is found |

**Always call `super()`** when overriding, or you lose the base behaviour:

```python
def get_context_data(self, **kwargs):
    """Return context data."""
    context = super().get_context_data(**kwargs)
    context['extra'] = 'thing'
    return context
```

### Mixins and MRO

A **mixin** is a small class providing one piece of behaviour, combined into a
view through multiple inheritance:

```python
class MyView(MixinA, MixinB, ListView):
```

Python resolves attributes left-to-right — the **MRO** (method resolution
order). `MixinA` wins over `MixinB`, which wins over `ListView`. When each
mixin calls `super()`, they chain. **Order is therefore behaviour, not style.**

### URLconfs

A URLconf maps patterns to views:

```python
from django.urls import path, re_path

urlpatterns = [
    path('things/', ThingList.as_view(), name='thing_list'),
    re_path(r'^things/(?P<pk>\d+)/$', ThingDetail.as_view(), name='thing_detail'),
]
```

- `path()` — simple string patterns.
- `re_path()` — regular expressions. `(?P<name>...)` captures a **named group**,
  which arrives in the view as `self.kwargs['name']`.
- `name=` lets you generate the URL later with `reverse('thing_detail', kwargs={'pk': 1})`
  or `{% url 'thing_detail' pk=1 %}` in a template. Always use names; never
  hardcode URLs.
- `.as_view()` converts the class into a callable.

Patterns are tried **top to bottom, first match wins**.

---

## Part B — CMWEB's view layer

### What is actually used

| Base class | Uses | | Mixin | Uses |
| --- | --- | --- | --- | --- |
| `ListView` | 58 | | `UrlKwargsMixin` | 58 |
| `DetailView` | 36 | | `AjaxableResponseMixin` | 55 |
| `UpdateView` | 34 | | `FormatMixin` | 35 |
| `CreateView` | 28 | | `ManifestsMixin` | 31 |
| `View` | 23 | | `ManifestMixin` | 29 |
| `DeleteView` | 15 | | `DepthMixin` | 17 |
| `TemplateView` | 12 | | `BranchNameDecoderMixin` | 12 |
| `RedirectView` | 11 | | `PaginateMixin` | 7 |

Almost no function views. A representative declaration
(`explorer/views/labels.py:51`):

```python
class LabelList(FormatMixin, ManifestMixin, ManifestsMixin, DepthMixin,
                BranchNameDecoderMixin, UrlKwargsMixin, ListView):
```

Six mixins. Reading such a declaration means knowing what each contributes.

---

## Part C — The mixins

Defined in `base/views/mixins.py` (generic) and `explorer/views/mixins.py`
(domain-specific).

### `FormatMixin` — one view, many formats

The most important one to understand. A trailing URL segment — `/json`, `/xml`,
`/csv`, `/txt` — or `?format=json` selects **both** the response content type
and a template suffix:

```
/builds/            → explorer/label_list.html   → text/html
/builds/json        → explorer/label_list.json   → application/json
/builds/csv         → explorer/label_list.csv    → text/csv + attachment header
```

It works by overriding two methods:

```python
def get_template_names(self):
    names = super().get_template_names()
    prefix, _ext = splitext(names[0])
    fmt = self.get_format()
    if fmt in ['xml', 'json', 'csv']:
        return ['{}.{}'.format(prefix, fmt)] + names
    return names
```

So **exposing a data feed is just adding a template file** — no new view, no
serializer. This is why most explorer URLs end with an optional
`(?P<format>json|html)` group.

Extra query parameters it understands: `?pretty` (indented JSON), `?jsonp`,
`?noparse`.

### `ManifestMixin` — the implicit manifest

CMWEB tracks several repo manifests (`platform/manifest`,
`platform/systemmanifest`, `platform/amssmanifest`…). Most URLs work with or
without naming one:

```
/builds/1.2.A.3.4                              → uses the default
/builds/manifest/platform/amssmanifest/1.2.A.3.4 → explicit
```

The mixin reads the `manifest` URL kwarg during `dispatch()`, falling back to
`settings.GLOBALS['PLATFORM_MANIFEST']`, and exposes it as `self.manifest`.

Note that `LabelList` overrides `default_manifest = SYSTEM_MANIFEST` — the build
list defaults to *system* builds while other views default to platform.

### `BranchNameDecoderMixin` — the slash problem

Git branch names contain slashes (`oss/android-11`), which collide with URL
path separators. CMWEB encodes them as backslash
(`base.constants.URL_SLASH_ENCODE_CHAR = '\\'`):

```
branch  oss/android-11
URL     /branches/oss\android-11
```

The mixin decodes during `dispatch()`, mutating `self.kwargs`.

> **This is the MRO rule you must remember.** `BranchNameDecoderMixin` has to
> sit **above** `UrlKwargsMixin`, because `UrlKwargsMixin` copies `self.kwargs`
> into the template context. Reverse them and templates receive the still-encoded
> name. The docstring in the source says so explicitly.

### `UrlKwargsMixin`

Three lines: copies every URL kwarg into the template context, so
`{{ branch }}`, `{{ manifest }}`, `{{ section }}` work without plumbing.

### `AjaxableResponseMixin`

For forms submitted by JavaScript. If the request has
`X-Requested-With: XMLHttpRequest`, it returns JSON instead of re-rendering:

- valid → `JsonResponse([form.instance])`
- invalid → `JsonResponse(form.errors, status=400)`
- exception → `JsonResponse(['Unexpected error: …'], status=500)`

It also appends `base/default_form.html` to the template candidates, so a form
view needs no template of its own.

### `PaginateMixin`

`ListView` paginates automatically; this adds pagination to views that are not
`ListView`s — a `DetailView` showing a paginated list of related objects. Page
size comes from a `Parameter`, not a constant.

### `DepthMixin`

Reads `?depth=N` and puts it in the context, controlling how deeply nested
structures are rendered.

### `GenericObjectMixin`

Resolves `<app>/<model>/<pk>` URL kwargs into a model and object via
`apps.get_model()`. Powers the generic inline and in-place-edit endpoints in
`base/urls.py` — one view serving every model.

### `ManifestsMixin`

Adds `manifests` (all manifest `Project`s) to the context, for the manifest
switcher in the UI. Note the plural — distinct from `ManifestMixin`.

---

## Part D — URL structure

### Shared regex fragments

`explorer/urls/__init__.py` defines building blocks reused across every explorer
URLconf:

```python
REMOTES_PATTERN = r'|'.join([r + '/' for r in REMOTES])   # oss/|semc/|aosp/…
BRANCH = r'(' + REMOTES_PATTERN + r')*[^/]+'
MANIFEST = r'[^\+]+manifest(-indus)?'
LABEL_PREFIX = r'^(?:/(?P<manifest>%s))?/(?P<name>%s)' % (MANIFEST, LABEL_NAME)
LABEL_SECTION = r'(?:/\+(?P<section>summary|issues|(modem-|sub|all|app)?commits|'
                r'components|repositories|decoupled|nv|changes|products|apps))?'
COMMIT_FILTER = '(?:/(?P<filter>all|internal|plain|cherry|revert|…))?'
```

Composed into patterns like:

```python
re_path(LABEL_PREFIX + r'/\+commits' + COMMIT_FILTER +
        '(?:/(?P<format>html|json))?'
        '(?:/(?P<project>.+))?'
        '/?$',
        LabelCommitList.as_view(section='commits',
                                url_name='explorer_label_commits'),
        name='explorer_label_commits'),
```

Note `.as_view(section=..., url_name=...)` — extra kwargs become instance
attributes, so one view class serves several URLs with different behaviour.

### The `+` convention

Build sub-pages are prefixed with `+`:

```
/builds/<manifest>/<label>/+summary
                          /+commits/<filter>
                          /+allcommits
                          /+subcommits/<sublabel>
                          /+issues
                          /+repositories/<filter>
                          /+changes
                          /+browse/<path>
```

`+` cannot appear in a build name, so this cleanly separates "a build" from "a
section of a build" without ambiguity.

### Root URLconf ordering

`cmweb-project/cmweb/urls.py`, simplified:

```python
urlpatterns = [
    path(r'grappelli/', include('grappelli.urls')),
    path(r'admin/', admin.site.urls),
    ...
    re_path(r'^(explorer/)?', include('explorer.urls')),   # greedy
    path(r'schedule/', include('schedule.urls')),
    ...
    path(r'', include('issues.urls')),
    path(r'', include('users.urls')),
    path(r'', include('dashboards.urls')),
    path(r'', include('base.urls')),
    path(r'', include('generic_pages.urls')),   # CATCH-ALL — must be last
]
```

Several apps mount at the root (`path(r'', ...)`), and `generic_pages` serves
any unmatched slug. **Anything added below it is unreachable.**

---

## Part E — Templates

### Inheritance chain

```
skeleton.html
   └─ bootstrap.html
        └─ base.html                ← the site chrome: topbar, sidebar, footer
             └─ <app>/<model>_list.html
```

Templates live in `cmweb-project/templates/` (site-wide) and
`<app>/templates/<app>/` (per app).

### The inlines system

CMWEB renders an object consistently wherever it appears, via
`somc-django-inlines`:

```django
{% load inlines_tags %}
{% show_object label %}
{% show_object commit mode='oneline' %}
```

`show_object` looks for `inlines/<app_label>_<model_name>.html`, falling back to
`inlines/default.html`. So `explorer.Label` renders through
`inlines/explorer_label.html` everywhere — one template governs its appearance
across the whole site.

Per-model inline templates extend one of:

| Base | Use |
| --- | --- |
| `inlines/default.html` | Full behaviour with caching and edit actions |
| `inlines/standard.html` | Icon + titlebar + meta layout |
| `inlines/nocache.html` | Volatile objects |
| `inlines/standard_nocache.html` | Both |

There is also a `render_inlines` filter that expands
`<inline type="app.model" ids="1,2" />` markup embedded in free-text bodies.

**If you add a model that appears in lists, add its inline template** — or it
renders as a bare link through the default.

### PJAX

The front end uses PJAX: links load only the content region and swap it in,
avoiding a full page reload. `PjaxVersionMiddleware` stamps a version header so
clients running stale JavaScript force a full reload. See
[04-middleware.md](04-middleware.md).

### Static assets

`django-compressor` with `COMPRESS_OFFLINE = True` — compression happens at
build time, not on request. **A template referencing a new CSS/JS file will not
work until `make static` runs.**

---

## Part F — Gotchas

### Database queries at import time

Some views do this at class-body scope:

```python
class ReleaseList(...):
    paginate_by = Parameter.get_int(RELEASES_PAGINATE_BY_KEY, 25)
```

Class bodies execute at **import** time, so this queries the database when the
module loads. Two consequences:

1. Changing that `Parameter` requires a process restart.
2. `manage.py` system checks import the URLconf → import views → hit the
   database. On an empty database that fails, which is why `migrate` needs
   `--skip-checks`. See [06-migrations.md](06-migrations.md).

Avoid the pattern in new code — override `get_paginate_by()` instead.

### Models at module scope

View modules start with:

```python
Parameter = apps.get_model('base', 'parameter')
Label = apps.get_model('explorer', 'label')
```

Same circular-import avoidance as in commands. Harmless; match it in explorer
code.

### Docstrings everywhere

pydocstyle runs over every non-migration file, so every view class and every
overridden method needs one. That is why you see:

```python
def get_queryset(self):
    """Return label object as per queryset."""
```

---

## Writing a view

```python
"""Views for the myapp app."""

from django.views.generic import ListView

from base.views.mixins import FormatMixin, UrlKwargsMixin
from myapp.models import Thing


class ThingList(FormatMixin, UrlKwargsMixin, ListView):
    """List `Thing` objects.

    Template: ``myapp/thing_list.html``

    Context:
        object_list
            The things.

    """

    model = Thing
    paginate_by = 25

    def get_queryset(self):
        """Return things, newest first."""
        qs = super(ThingList, self).get_queryset()
        return qs.order_by('-date_created')
```

Note the docstring style — CMWEB view docstrings document the template and the
context variables, which is genuinely useful when reading unfamiliar views.

```
[ ] mixins ordered correctly (BranchNameDecoderMixin above UrlKwargsMixin)
[ ] super() called in every override
[ ] template at <app>/templates/<app>/<model>_<suffix>.html
[ ] inlines/<app>_<model>.html if it appears in lists
[ ] URL registered with name=, above the catch-alls
[ ] no Parameter lookups at class-body scope
[ ] docstrings on class and every method
```

**Next:** [04-middleware.md](04-middleware.md)
