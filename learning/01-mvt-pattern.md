# 01 — The MVT design pattern

> **Goal:** understand what MVT is, why Django calls it that instead of MVC,
> and be able to name the exact Django class responsible for each step of a
> request — then find all of them in CMWEB.

---

## 1. The problem the pattern solves

A web application has to do three unrelated things every time a request
arrives:

1. **Know things.** What a "build" is, which commits belong to it, what makes
   a branch active. This is *domain knowledge* and it outlives any particular
   screen.
2. **Decide things.** Which build did the user ask for? Are they allowed to see
   it? Should this be HTML or JSON?
3. **Show things.** Turn the answer into bytes a browser can render.

If those three are written as one blob, changing the page layout risks breaking
the database queries, and adding a JSON endpoint means copying the domain
knowledge. Every server-side web framework since the 1990s answers this the
same way: **separate the three, and make the dependencies point one direction
only.**

```
  presentation  --depends on-->  logic  --depends on-->  data
   (templates)                  (views)                 (models)
```

Data must never import presentation. That single rule is what the pattern buys
you.

---

## 2. MVC, as normally taught

Classic Model–View–Controller, from Smalltalk-80:

| Letter | Responsibility |
| --- | --- |
| **Model** | Domain data and the rules that govern it. Knows nothing about screens. |
| **View** | The visual presentation of a model. |
| **Controller** | Accepts user input, decides what to do, updates model and view. |

The confusion begins immediately, because "View" in MVC means *the thing the
user looks at* — what a web framework calls a template.

---

## 3. Django's renaming: MVT

Django uses different words for almost the same shape:

| Django name | MVC equivalent | What it is in Django |
| --- | --- | --- |
| **Model** | Model | A `django.db.models.Model` subclass — one class per table |
| **View** | *Controller* | A callable that takes `HttpRequest` and returns `HttpResponse` |
| **Template** | *View* | A text file with placeholders, rendered against a context dict |

So a Django **view is a controller**, and a Django **template is an MVC view**.
The letters shift by one. This is the single most common source of confusion
when someone comes to Django from Rails, Spring MVC or ASP.NET MVC.

### Where did the controller go?

The framework itself is the controller. Django's own FAQ puts it as: *"the
controller is the framework itself: the machinery that sends a request to the
appropriate view, according to the Django URL configuration."*

That machinery is real code you can point at:

| Job | Django class |
| --- | --- |
| Turn a WSGI call into an `HttpRequest` | `django.core.handlers.wsgi.WSGIHandler` |
| Run middleware, call the view, run response middleware | `django.core.handlers.base.BaseHandler.get_response()` |
| Match the path to a view | `django.urls.resolvers.URLResolver.resolve()` |
| Render a template with a context | `django.template.backends.django.Template.render()` |

So MVT is really **M-V-T plus a framework-provided C**. Some people write it as
`MTV` (Model–Template–View); it is the same three letters in a different order
and means exactly the same thing.

---

## 4. The full request lifecycle

This is the sequence you should be able to recite. Django-specific names are in
`code font`; everything else is prose.

```
 1. Web server (Apache + mod_wsgi, or runserver) receives bytes on a socket
 2. It builds a WSGI `environ` dict and calls the WSGI application
 3. WSGIHandler.__call__(environ, start_response)
 4.   - builds an HttpRequest (subclass WSGIRequest) from environ
 5.   - calls BaseHandler.get_response(request)
 6.       - REQUEST MIDDLEWARE: each entry in MIDDLEWARE, top to bottom.
 7.         Any of them may short-circuit by returning an HttpResponse.
 8.       - URL RESOLUTION: the ROOT_URLCONF module is imported, its
 9.         urlpatterns list is walked, first match wins. Produces a
10.         ResolverMatch = (view callable, args, kwargs, url_name, ...)
11.       - VIEW MIDDLEWARE: every middleware with process_view(), in
12.         MIDDLEWARE order. May also short-circuit.
13.       - THE VIEW is called: view(request, *args, **kwargs)
14.             - reads/writes MODELS via the ORM
15.             - builds a context dict
16.             - returns an HttpResponse or a TemplateResponse
17.       - TEMPLATE-RESPONSE MIDDLEWARE (process_template_response())
18.       - If the response is lazy (TemplateResponse), .render() is
19.         called now: the TEMPLATE is loaded, parsed, and rendered
20.         against the context, and the response content is set
21.       - RESPONSE MIDDLEWARE: same list, bottom to top
22. start_response(status, headers) is called; the body is yielded
23. Web server writes bytes back to the client
```

Two details that catch people out:

- **Middleware is an onion, not a queue.** The request phase runs top-to-bottom,
  the response phase runs bottom-to-top. The last middleware in `MIDDLEWARE` is
  closest to the view.
- **`TemplateResponse` is lazy on purpose.** The view returns before rendering
  happens, which is exactly what lets response middleware alter the context or
  swap the template. Django's class-based generic views return
  `TemplateResponse`; a bare `render()` call returns an already-rendered
  `HttpResponse`.

---

## 5. The four letters in minimal code

```python
# models.py — M
from django.db import models


class Build(models.Model):
    name = models.CharField(max_length=200)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created',)

    def __str__(self):
        return self.name

    def is_recent(self):                 # domain rule lives WITH the data
        from datetime import timedelta
        from django.utils import timezone
        return self.created > timezone.now() - timedelta(days=7)
```

```python
# views.py — V (the controller)
from django.shortcuts import render, get_object_or_404
from .models import Build


def build_detail(request, pk):
    build = get_object_or_404(Build, pk=pk)
    return render(request, 'builds/build_detail.html', {'build': build})
```

```
{# templates/builds/build_detail.html — T #}
{% extends "base.html" %}
{% block content %}
  <h1>{{ build.name }}</h1>
  {% if build.is_recent %}<span class="badge">new</span>{% endif %}
{% endblock %}
```

```python
# urls.py — the routing half of the framework's controller
from django.urls import path
from . import views

urlpatterns = [
    path('builds/<int:pk>/', views.build_detail, name='build_detail'),
]
```

Notice `is_recent()` lives on the model, and the template calls it with no
parentheses. That is the pattern working: the *rule* is stated once, next to
the data it is a rule about, and both HTML and JSON renderings get it for free.

---

## 6. The same four letters in CMWEB

CMWEB is a large, old, real application, so each letter is spread over more
files — but they are the same letters.

### M — `cmweb-app/explorer/models.py`

2,700 lines, 23 model classes. The core chain:

```
Project  -->  Branch  -->  ManifestBranch  -->  Label  -->  Commit
(a Gerrit     (a git        (a manifest        (a build)    (a sha1)
 repo)         branch)       branch)
```

Real code, `cmweb-app/explorer/models.py:97`:

```python
class Project(models.Model):
    """Represents a Gerrit project, with underlying git repository."""

    name = models.CharField(max_length=200, unique=True)
    is_manifest = models.BooleanField(default=False, db_index=True)
    ...
    objects = ProjectManager()

    class Meta(object):
        verbose_name = 'Repository'
        verbose_name_plural = 'Repositories'
        ordering = ('-is_manifest', '-importance', 'name',)

    def git_path(self):
        """Return path to the underlying git repository."""
        return os.path.join(settings.GLOBALS['PATH_REPOSITORY'],
                            self.name + '.git')
```

`git_path()` is a domain rule — "where on disk does this repository live" —
stated once on the model. Views, templates, management commands and the JSON
API all use the same answer.

### V — `cmweb-app/explorer/views/`

Six modules: `labels.py`, `commits.py`, `branches.py`, `projects.py`,
`features.py`, `mixins.py`. Almost every view is class-based. Real code,
`cmweb-app/explorer/views/labels.py:240`:

```python
class LabelDetail(FormatMixin, ManifestMixin, DepthMixin, UrlKwargsMixin,
                  DetailView):
    model = Label
    default_depth = 1
    default_manifest = None

    def get_object(self, queryset=None):
        """Return label object."""
        label = get_label_or_404(self.kwargs.get('name'), self.manifest)
        self.manifest = label.manifest_branch.project.name
        return label
```

That is the controller: it interprets the URL, fetches the model object, and
lets `DetailView` do the rest.

### T — `cmweb-app/explorer/templates/explorer/`

Around 40 templates. Note that they come in **matched sets by extension**:

```
label_list.html           label_list.json
commit_list.html          commit_list.json
label_commit_list.html    label_commit_list.json    label_commit_list.csv
manifestbranch_list.html  manifestbranch_list.json  manifestbranch_list.xml
```

One view, several presentations. That is `FormatMixin` (chapter 04) picking a
template suffix from the URL. The MVT separation is what makes it possible: the
view has no idea which of those files will be used.

### C — spread across `cmweb-project/cmweb/`

| Piece | File |
| --- | --- |
| WSGI entry point | `cmweb-project/cmweb/wsgi.py` |
| Root URLconf | `cmweb-project/cmweb/urls.py` |
| Custom middleware | `cmweb-project/cmweb/middleware.py` |
| Per-app URLconfs | `cmweb-app/<app>/urls.py` or `<app>/urls/` |

---

## 7. Rules of thumb

The pattern only pays off if you put code in the right layer. The usual
formulation:

### Fat models

Domain logic belongs on the model or its manager. If you find yourself writing
the same `.filter()` chain in two views, it should be a manager method.

CMWEB does this well — `cmweb-app/explorer/managers.py` holds named querysets:

```python
class LabelManager(Manager):
    def versioned(self): ...
    def latest(self): ...
    def recommended(self, series=None): ...
    def in_last_week(self): ...
```

so a view says `Label.objects.versioned()` instead of restating the definition
of "versioned" every time.

### Thin views

A view should: read the request, call into models, build a context, return a
response. If a view is doing arithmetic on domain objects, that arithmetic
probably belongs on the model.

### Dumb templates

Templates should choose *what* to show, not *compute* it. Django's template
language deliberately cannot call a function with arguments — a design choice
to stop logic leaking into presentation. When a template genuinely needs
computation, the answer is a **custom template tag or filter**
(`cmweb-app/explorer/templatetags/explorerutils.py`), not more logic in the
template.

### The dependency rule

```
templates  ->  views  ->  models        (allowed)
models     ->  views                    (NEVER)
```

If a model needs a URL, it uses `reverse()` and a URL *name*, not an import of
the view. CMWEB does exactly that, `cmweb-app/explorer/models.py:124`:

```python
def get_absolute_url(self):
    """Return absolute URL for git repository."""
    return reverse('explorer_project_detail', kwargs={'name': self.name})
```

The model names the route; it does not import the view.

---

## 8. Where CMWEB bends the pattern (and why)

Real applications do not obey the diagram perfectly. Three honest examples you
will meet immediately — all covered in detail in chapter 09:

1. **Models import from templatetags.** `Label.get_absolute_url()` does
   `from explorer.templatetags.explorerutils import label_url` *inside the
   method*. That is a presentation module being called from the model layer.
   The function-local import is there to avoid a circular import at module
   load. It works, but it bends the dependency rule.

2. **Denormalised counters on models.** `Label` carries `commits_count`,
   `components_count`, `all_commits_count` and friends — columns that exist
   only so templates do not trigger `COUNT(*)` per row. The comment in the
   source is literally `# COUNT(*) caching for templates`. A presentation
   concern has been pushed into the schema, deliberately, for speed.

3. **Class-body database access.** Several classes call `Parameter.get_int(...)`
   at class-body scope, which queries the database at import time. This is why
   `manage.py migrate` needs `--skip-checks` in the local setup.

None of these are things to copy. They are things to *recognise*, so that when
a page is slow or an import blows up you know which rule was bent.

---

## 9. Try it

With the local instance running:

```powershell
cd local-cmweb
.\run.ps1
```

1. Open `http://127.0.0.1:8000/builds/` — the **T** you are looking at is
   `cmweb-app/explorer/templates/explorer/label_list.html`.
2. Open `http://127.0.0.1:8000/builds/json` — same **V**, different **T**
   (`label_list.json`), same **M**.
3. Now find the view. In `cmweb-app/explorer/urls/labels.py` the first
   `re_path` names `LabelList`. Open `cmweb-app/explorer/views/labels.py` and
   read `LabelList.get_queryset()`.
4. Confirm the model chain in the shell:

```powershell
.venv\Scripts\python.exe manage.py shell
```

```python
from explorer.models import Label
b = Label.objects.first()
b.name, b.manifest_branch.name, b.manifest_branch.project.name
b.get_absolute_url()                  # the model naming a route, not importing a view
b.commits.count(), b.commits_count    # live COUNT vs the denormalised column
```

---

## 10. Check yourself

1. In Django, which letter of MVT corresponds to MVC's "Controller"?
2. Name the Django class that walks the `MIDDLEWARE` list.
3. Why does response middleware run in reverse order?
4. What is the difference between returning `render(...)` and returning a
   `TemplateResponse`? Which one do generic class-based views return?
5. `Label` has both `commits` (a M2M) and `commits_count` (an integer column).
   Which layer does each belong to, and what is the cost of the second one?
6. A template needs to show "days since this build was created". Where should
   that calculation live, and why not in the template?
7. Which direction may imports point between models and views? Find one place
   in CMWEB where that rule is bent and explain how the breakage is contained.

Answers are in the text above — if any question sends you hunting, reread that
section before moving on to chapter 02.
