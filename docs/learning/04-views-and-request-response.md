# 04 — Views and request/response handling

> **Goal:** be able to read any CMWEB view class, name every mixin in its MRO,
> say what each one contributes, and predict which template will render.

---

## 1. The contract

A Django view is **anything callable that takes an `HttpRequest` and returns an
`HttpResponse`.** That is the entire contract. Everything else — generic views,
mixins, decorators — is convenience built on top of it.

```python
from django.http import HttpResponse

def hello(request):
    return HttpResponse("hello")
```

If a view raises instead of returning, Django converts certain exceptions into
responses:

| Exception | Becomes |
| --- | --- |
| `Http404` | 404 page (`404.html`) |
| `PermissionDenied` | 403 |
| `SuspiciousOperation` | 400 |
| anything else | 500 (`500.html`), or a traceback if `DEBUG` |

---

## 2. `HttpRequest` — what you get

| Attribute | Contains |
| --- | --- |
| `request.method` | `'GET'`, `'POST'`, ... |
| `request.GET` | `QueryDict` of the query string |
| `request.POST` | `QueryDict` of form-encoded body |
| `request.body` | Raw bytes (for JSON payloads) |
| `request.FILES` | Uploaded files |
| `request.path` / `request.path_info` | URL path |
| `request.META` | The WSGI `environ` — headers as `HTTP_*` keys |
| `request.headers` | Case-insensitive header mapping (Django 2.2+) |
| `request.COOKIES` | dict |
| `request.session` | Set by `SessionMiddleware` |
| `request.user` | Set by `AuthenticationMiddleware` |
| `request.resolver_match` | The `ResolverMatch` — set *after* resolution |

`QueryDict` is immutable and multi-valued: `request.GET['x']` gives the **last**
value, `request.GET.getlist('x')` gives all of them.

CMWEB reads `request.META` directly in a couple of places, e.g.
`base/views/mixins.py`:

```python
if self.request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
```

That is the raw form of "is this an AJAX request".

---

## 3. `HttpResponse` and its subclasses

| Class | Use |
| --- | --- |
| `HttpResponse` | Content in hand |
| `JsonResponse` | dict -> JSON, sets content type |
| `HttpResponseRedirect` / `redirect()` | 302 |
| `HttpResponsePermanentRedirect` | 301 |
| `HttpResponseNotFound` / `Http404` | 404 |
| `StreamingHttpResponse` | Large or generated content, no `.content` |
| `FileResponse` | Files, with range support |
| `TemplateResponse` | **Lazy** — carries template + context, renders later |

CMWEB adds its own in `cmweb-app/base/utils/http.py`: `JsonResponse`,
`JsonTemplateResponse`, `FileResponse`. `JsonTemplateResponse` is the important
one — it is what makes `FormatMixin` work (section 7).

`StreamingHttpResponse` appears in `explorer/views/labels.py` for CSV exports of
large commit lists, so the whole file never has to exist in memory.

---

## 4. Function-based vs class-based views

### Function-based (FBV)

```python
def build_detail(request, pk):
    build = get_object_or_404(Build, pk=pk)
    return render(request, 'builds/build_detail.html', {'build': build})
```

Simple, explicit, easy to read. Branching on `request.method` by hand.

### Class-based (CBV)

```python
from django.views.generic import DetailView

class BuildDetail(DetailView):
    model = Build
```

`Build` -> table, template name `builds/build_detail.html`, context name
`build` plus `object`. All by convention.

### `as_view()` — the bridge

`urls.py` needs a *callable*, and a class is not one. `as_view()` is a
classmethod that returns a closure:

```python
path('builds/<int:pk>/', BuildDetail.as_view(), name='build_detail')
```

Roughly, `as_view()` returns a function that, per request:

1. instantiates the class (`self = cls(**initkwargs)`)
2. sets `self.request`, `self.args`, `self.kwargs`
3. calls `self.dispatch(request, *args, **kwargs)`

`dispatch()` then looks at `request.method` and calls `self.get()`,
`self.post()`, etc.

**The instance is created fresh per request** — so `self.foo = ...` is safe, but
anything set at class level is shared across all requests forever. That is why
`LabelList` sets its mutable state in `__init__`:

```python
def __init__(self, *args, **kwargs):
    """Initialization."""
    super(LabelList, self).__init__(*args, **kwargs)
    self.title_list = []
    self.system_branches = None
```

A class-level `title_list = []` would accumulate across requests.

### Passing arguments through `as_view()`

Anything you pass to `as_view()` becomes an instance attribute. CMWEB uses this
to make one view class serve several URLs:

```python
re_path(LABEL_PREFIX + r'/\+commits' + COMMIT_FILTER + ...,
        LabelCommitList.as_view(section='commits',
                                url_name='explorer_label_commits'),
        name='explorer_label_commits'),

re_path(LABEL_PREFIX + r'/\+allcommits' + COMMIT_FILTER + ...,
        LabelCommitList.as_view(section='allcommits',
                                url_name='explorer_label_all_commits'),
        name='explorer_label_all_commits'),
```

Same class, four registrations (`commits`, `allcommits`, `subcommits`,
`appcommits`), differing only by the `section` attribute.

---

## 5. The generic view hierarchy

```
View                       dispatch(), http_method_names
 ├── TemplateView          + TemplateResponseMixin, ContextMixin
 ├── RedirectView
 ├── DetailView            SingleObjectMixin  -> get_object(), 'object' in context
 ├── ListView              MultipleObjectMixin -> get_queryset(), 'object_list', pagination
 ├── FormView              FormMixin -> get_form(), form_valid(), form_invalid()
 ├── CreateView            ModelFormMixin
 ├── UpdateView            ModelFormMixin
 └── DeleteView            DeletionMixin
```

### The hook methods you override

| View | Hook | Returns |
| --- | --- | --- |
| `ListView` | `get_queryset()` | The queryset to list |
| `ListView` | `get_context_data(**kwargs)` | dict for the template |
| `DetailView` | `get_object(queryset=None)` | One instance |
| any | `get_template_names()` | A list of candidate template names, tried in order |
| any | `dispatch()` | Runs before method dispatch — the place for per-request setup |
| any | `render_to_response(context, **kwargs)` | The response object |
| `FormView` | `form_valid(form)` / `form_invalid(form)` | Response after validation |

### Default template names

| View | Default |
| --- | --- |
| `ListView` | `<app>/<model>_list.html` |
| `DetailView` | `<app>/<model>_detail.html` |
| `CreateView`/`UpdateView` | `<app>/<model>_form.html` |
| `DeleteView` | `<app>/<model>_confirm_delete.html` |

`LabelList` needs no `template_name` because `explorer` + `label` + `_list`
already resolves to `explorer/label_list.html`.

---

## 6. Mixins and the MRO

A mixin is a small class that overrides one or two hook methods and calls
`super()`. Compose several and you get layered behaviour.

**The rule: mixins go to the LEFT of the base view class.** Python's method
resolution order runs left to right, so a mixin only gets to intercept a hook
if it appears before the class that defines the default.

```python
class LabelDetail(FormatMixin, ManifestMixin, DepthMixin, UrlKwargsMixin,
                  DetailView):
```

MRO for `get_context_data()`:

```
FormatMixin -> ManifestMixin -> DepthMixin -> UrlKwargsMixin -> DetailView -> ...
```

Each one does its bit and calls `super()`, so the context accumulates as the
call unwinds. Verify it yourself:

```python
[c.__name__ for c in LabelDetail.__mro__]
```

### Ordering constraints are real

`BranchNameDecoderMixin`'s docstring says it outright:

> *If used in conjunction with `base.views.mixins.UrlKwargsMixin`, make sure to
> place this above `UrlKwargsMixin` in the inheritance hierarchy.*

Because it rewrites `kwargs` during `dispatch()`, and `UrlKwargsMixin` copies
`kwargs` into the context. Decode first, then copy — get the order wrong and
the template shows an encoded branch name.

---

## 7. CMWEB's mixin catalogue

### `base/views/mixins.py`

#### `FormatMixin` — one view, many content types

This is the most important mixin in the codebase. It lets a single view serve
HTML, JSON, XML, CSV and plain text.

```python
class FormatMixin(object):
    response_class = JsonTemplateResponse

    def get_format(self):
        fmt = self.kwargs.get('format', None)      # from the URL
        if not fmt:
            fmt = self.request.GET.get('format', None)   # or ?format=
        if not fmt:
            return 'html'
        return fmt

    def get_template_names(self):
        names = super(FormatMixin, self).get_template_names()
        if not names:
            return names
        prefix, _ext = splitext(names[0])
        fmt = self.get_format()
        if fmt in ['xml', 'json', 'csv']:
            return ['{}.{}'.format(prefix, fmt)] + names
        return names

    def render_to_response(self, context, **response_kwargs):
        fmt = self.get_format()
        if fmt == "html":
            pass
        elif fmt == "txt":
            response_kwargs['content_type'] = 'text/plain'
        elif fmt == "xml":
            response_kwargs['content_type'] = 'application/xml'
        elif fmt == "csv":
            response_kwargs['content_type'] = 'text/csv'
        elif fmt == "json":
            ...
```

Two hooks, two effects:

1. `get_template_names()` swaps the extension -> `label_list.html` becomes
   `label_list.json`.
2. `render_to_response()` sets the `Content-Type`.

Plus a nice touch for CSV — a download filename derived from the template name:

```python
name = self.get_template_names()[0].replace('/', '-')
if fmt == 'csv':
    res['Content-Disposition'] = 'attachment; filename=%s' % name
```

This is why `explorer/templates/explorer/` contains matched sets like
`label_list.html` / `label_list.json`. **If you add a format to a URL pattern,
you must add the matching template file** — otherwise `TemplateDoesNotExist`.

It also supports `?pretty`, `?noparse` and `?jsonp` for JSON responses.

#### `UrlKwargsMixin` — URL kwargs into the context

```python
def get_context_data(self, **kwargs):
    context = super(UrlKwargsMixin, self).get_context_data(**kwargs)
    context.update(self.kwargs)
    return context
```

Four lines that mean a template can write `{{ branch }}` or `{{ manifest }}`
without the view explicitly forwarding them.

#### `DepthMixin` — a safely-parsed GET integer

```python
default_depth = 1

def get_context_data(self, **kwargs):
    context = super(DepthMixin, self).get_context_data(**kwargs)
    depth = self.default_depth
    if 'depth' in self.request.GET:
        try:
            depth = int(self.request.GET['depth'])
        except ValueError:
            pass
    context['depth'] = depth
    return context
```

Note the `try/except ValueError` — user input is never trusted into `int()`.
`depth` controls how far the JSON serialisers expand nested objects.

#### `PaginateMixin` — pagination for non-`ListView` views

`ListView` paginates its own `object_list`. When a `DetailView` needs to
paginate a *related* queryset (all commits in this build), this mixin provides
it:

```python
def paginate_queryset(self, queryset, context, key=DEFAULT_PAGINATE_BY_KEY,
                      default=DEFAULT_PAGINATE_BY_DEFAULT):
    paginate_by = Parameter.get_int(key, default)
    paginator = Paginator(queryset.all(), paginate_by)
    try:
        page = paginator.page(self.request.GET.get('page', 1))
    except Exception:
        raise Http404()
    context.update({
        'page_obj': page,
        'paginator': paginator,
        'is_paginated': True,
    })
    return context
```

Note the page size comes from `Parameter` — a runtime database value, not a
setting. Chapter 06.

#### `AjaxableResponseMixin` — dual-mode forms

Same form class serves a normal POST and an AJAX POST:

```python
def form_invalid(self, form):
    if self.request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        super(AjaxableResponseMixin, self).form_invalid(form)
        return JsonResponse(form.errors, status=400)
    else:
        return super(AjaxableResponseMixin, self).form_invalid(form)
```

Browser gets a re-rendered form with errors; JavaScript gets a 400 with a JSON
error dict.

#### `GenericObjectMixin` — `<app>/<model>/<pk>` editing

```python
def get_object(self):
    model = apps.get_model(self.kwargs.get('app'),
                           self.kwargs.get('model'))
    try:
        return model._default_manager.get(pk=self.kwargs.get('pk'))
    except ObjectDoesNotExist as e:
        raise Http404(e)
```

One view for editing *any* model, addressed by app label and model name in the
URL. Powerful — and exactly the kind of endpoint that must stay behind the
permission gates described in section 10.

### `explorer/views/mixins.py`

#### `ManifestMixin` — an implicit default

```python
class ManifestMixin(object):
    default_manifest = settings.GLOBALS['PLATFORM_MANIFEST']

    def __init__(self, *args, **kwargs):
        self.manifest = self.default_manifest
        super(ManifestMixin, self).__init__(*args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if 'manifest' in kwargs and kwargs['manifest']:
            self.manifest = kwargs['manifest']
        return super(ManifestMixin, self).dispatch(request, *args, **kwargs)
```

This is why most explorer URLs work **both with and without** a manifest
prefix: `/builds/` and `/builds/platform/manifest/...` reach the same view, and
the first one gets the default filled in. Subclasses override
`default_manifest` — `LabelList` uses `SYSTEM_MANIFEST`, `LabelDetail` uses
`None`.

#### `BranchNameDecoderMixin` — slashes in URLs

Git branch names contain slashes (`release/1.2`). Slashes are path separators.
CMWEB's answer is to encode them as `\` — `base.constants.URL_SLASH_ENCODE_CHAR`
— and decode during `dispatch`:

```python
def dispatch(self, request, *args, **kwargs):
    branch = kwargs.get(self.branch_kwarg_name, '')
    if branch:
        kwargs[self.branch_kwarg_name] = str(branch).replace(
            URL_SLASH_ENCODE_CHAR, '/')
        # self.kwargs is set in the wrapper view function. Reset its value.
        self.kwargs[self.branch_kwarg_name] = kwargs[self.branch_kwarg_name]
    return super(BranchNameDecoderMixin, self).dispatch(
        request, *args, **kwargs)
```

Note it must fix **both** `kwargs` (passed down the chain) and `self.kwargs`
(read by everything else). The encoding side lives in the `url_with_branch`
template tag.

#### `ManifestsMixin` — the manifest dropdown

```python
context['manifests'] = Project.objects.manifests()
```

Injects the list of all manifest projects so the navigation dropdown can render.

---

## 8. URL routing

### `path()` vs `re_path()`

```python
path('builds/<int:pk>/', BuildDetail.as_view(), name='build_detail')
re_path(r'^builds/(?P<pk>\d+)/$', BuildDetail.as_view(), name='build_detail')
```

`path()` uses converters (`str`, `int`, `slug`, `uuid`, `path`) and is
preferred. `re_path()` gives full regex. CMWEB is overwhelmingly `re_path()`
because its URLs are genuinely irregular — branch names with slashes, optional
manifest prefixes, `+`-prefixed sections.

### Named groups become view kwargs

```python
re_path(r'^(?P<manifest>...)/(?P<name>...)$', LabelDetail.as_view())
```

-> `self.kwargs['manifest']`, `self.kwargs['name']`.

### `include()` and namespaces

```python
urlpatterns = [
    path(r'branches', include('explorer.urls.branches'),),
    path(r'repositories/', include('explorer.urls.projects'),),
    path(r'builds', include('explorer.urls.labels'),),
    path(r'labels', include(('explorer.urls.labels', 'explorer'), 'labels')),
    path(r'commits', include('explorer.urls.commits'),),
]
```

Look at lines 3 and 4: the **same** URLconf mounted at two prefixes,
`/builds` and `/labels`, the second under a namespace. That is a legacy-URL
alias kept alive without duplicating a single pattern.

### Composed regex fragments

`explorer/urls/__init__.py` defines shared building blocks:

```python
REMOTES_PATTERN = r'|'.join([r + '/' for r in REMOTES])

BRANCH = r'(' + REMOTES_PATTERN + r')*[^/]+'
MANIFEST = r'[^\+]+manifest(-indus)?'

BRANCH_PREFIX = r'^(?:/(?P<manifest>%s)/(?P<name>%s))?' % (MANIFEST, BRANCH)
COMMIT_FILTER = '(?:/(?P<filter>all|internal|plain|cherry|revert|' \
    'all-including-merges))?'
COMPONENT_FILTER = '(?:/(?P<filter>all|changed|added|removed))?'
LABEL_NAME = '[^+]+'
LABEL_PREFIX = r'^(?:/(?P<manifest>%s))?/(?P<name>%s)' % (MANIFEST, LABEL_NAME)
LABEL_SECTION = \
    r'(?:/\+(?P<section>summary|issues|(modem-|sub|all|app)?commits|' + \
    r'components|repositories|decoupled|nv|changes|products|apps))?'
```

and `explorer/urls/labels.py` assembles them:

```python
re_path(LABEL_PREFIX + r'/\+issues' + ISSUE_FILTER +
        '(?:/(?P<format>json|html|csv))?'
        '/?$',
        LabelIssueList.as_view(),
        name='explorer_label_issues'),
```

Read the resulting URL grammar as:

```
/builds  [/<manifest>]  /<label-name>  [/+<section>]  [/<filter>]  [/<format>]
```

Real examples:

```
/builds/
/builds/branch/l-mr1-kitakami2/json
/builds/platform/manifest/1.2.3
/builds/platform/manifest/1.2.3/+commits
/builds/platform/manifest/1.2.3/+allcommits/cherry/csv
/builds/platform/manifest/1.2.3/+repositories/changed
```

The `+` prefix on sections exists so section names can never collide with a
label name — `LABEL_NAME` is `[^+]+`, i.e. "anything without a plus".

**Order matters.** The first matching pattern wins, and Django never
backtracks into later patterns. In `explorer/urls/labels.py` the catch-all
`LabelDetail` pattern is deliberately **last**, because its `name` group would
otherwise swallow `+commits` and friends.

### `reverse()` and `{% url %}`

Never hardcode a URL. Name every pattern and look it up:

```python
from django.urls import reverse
reverse('explorer_project_detail', kwargs={'name': project.name})
```

```
{% url 'explorer_label_list' %}
```

CMWEB adds `base/templatetags/linkutils.py` with `smart_url` and
`url_with_branch` — wrappers that drop empty kwargs and apply slash-encoding,
so templates can pass optional arguments freely:

```
{% url_with_branch "explorer_label_list" manifest=manifest branch=b.name series=series product=product %}
```

---

## 9. Reading a real view end to end

`explorer/views/labels.py:53`:

```python
class LabelList(FormatMixin, ManifestMixin, ManifestsMixin, DepthMixin,
                BranchNameDecoderMixin, UrlKwargsMixin, ListView):
    default_manifest = SYSTEM_MANIFEST

    def __init__(self, *args, **kwargs):
        super(LabelList, self).__init__(*args, **kwargs)
        self.title_list = []
        self.system_branches = None
        self.series_set = None
        self.product_set = None

    def get_queryset(self):
        self.system_branches = ManifestBranch.objects.filter(
            project__name=self.manifest).order_by('name')
        queryset_name = self.request.GET.get('queryset', None)
        if queryset_name:
            labels = getattr(Label.objects, queryset_name)()
        else:
            labels = Label.objects.versioned().filter(
                manifest_branch__project__name=self.manifest)
        query = get_object_query_from_request(self.request, 'name__istartswith')
        labels = labels.filter(query)

        if self.kwargs.get('series'):
            labels = labels.filter(series__name=self.kwargs.get('series'))
        ...
```

Decoded, layer by layer:

| Layer | Contribution |
| --- | --- |
| `ListView` | Provides `get()`, pagination, `object_list` in context |
| `UrlKwargsMixin` | Puts `series`, `branch`, `status`, `product` into context |
| `BranchNameDecoderMixin` | Turns `release\1.2` back into `release/1.2` before anything reads it |
| `DepthMixin` | Adds `depth` for the JSON serialiser |
| `ManifestsMixin` | Adds `manifests` for the dropdown |
| `ManifestMixin` | Sets `self.manifest`, defaulting to `SYSTEM_MANIFEST` |
| `FormatMixin` | Picks `label_list.html` or `label_list.json` and the content type |
| `LabelList` itself | Only `get_queryset()` and context assembly |

The view's *own* code is about 60 lines. Everything else is composed. That is
the payoff of the mixin approach — and the cost is that you must read the MRO
to know what a view actually does.

> **One thing to be careful about.** `getattr(Label.objects, queryset_name)()`
> calls an arbitrary attribute of the manager named by a GET parameter. It
> works because managers only expose queryset methods, but it is the kind of
> reflection that deserves a second look before being copied into new code.

---

## 10. Middleware, and CMWEB's two security gates

Middleware wraps every request. The modern form is a callable class:

```python
class PjaxVersionMiddleware(object):
    """Set the X-PJAX-Version header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        version = settings.GLOBALS.get('CM_WEB_VERSION', 'unknown')
        md5 = settings.GLOBALS.get('STATIC_MD5', 'unknown')
        response = self.get_response(request)
        response['X-PJAX-Version'] = '{}-{}'.format(version, md5)
        return response
```

`__init__` runs **once at startup**; `__call__` runs per request. Work done
before `self.get_response(request)` is request-phase; after it is
response-phase.

Optional hooks: `process_view`, `process_exception`,
`process_template_response`.

### The site is gated twice

**Gate 1 — Apache.** Every request is authenticated against LDAP before Django
sees it (HTTP Basic against `ldaps://LDAP.jp.sony.com:3269`, `Require
valid-user`). Only four paths are anonymous: `/rpc/`, `/register`,
`/access-denied` and favicons. Django's `RemoteUserMiddleware` then turns
Apache's `REMOTE_USER` into a logged-in user.

**Gate 2 — `PermissionCheckMiddleware`** (`cmweb-project/cmweb/middleware.py`),
on the `users.view_all_pages` permission:

```python
if user.has_perm('users.view_all_pages'):
    return None
else:
    return HttpResponseRedirect(reverse('request_branch_list'))
```

Anonymous access is only possible for paths matching `NO_AUTH_URLS` or under
`EXEMPT_URLS`:

```python
EXEMPT_URLS = ['accounts/', 'request/']

NO_AUTH_URLS = ['.+/trigger-config/?$', '.+/xml(/all)?/?$',
                'builds/(.+/)?rss/?$', 'projects/.+/rss/?$',
                'activity/rss/?$', 'rpc/?$', 'api/(?!a/).*$',
                'register$', 'access-denied$']
```

### Adding a public endpoint takes THREE edits

1. The URLconf.
2. `NO_AUTH_URLS` in `cmweb-project/cmweb/middleware.py`.
3. A `Require all granted` block in
   `cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2`.

Diagnosing which one you forgot:

| Symptom | Missing |
| --- | --- |
| HTTP 401 basic-auth prompt | The Apache `LocationMatch` block |
| Redirect to `/access-denied` | The `NO_AUTH_URLS` entry |
| 404 | The URLconf entry |

### A security note worth internalising

`PermissionCheckMiddleware` base64-decodes the `Authorization` header and
trusts the username **without checking the password**:

```python
auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
```

This is safe **only because Apache has already bound that username against
LDAP**. Put this app behind anything that does not authenticate and it is wide
open. Do not replicate the pattern.

---

## 11. Try it

```powershell
cd local-cmweb
.venv\Scripts\python.exe manage.py shell
```

**A. Read an MRO:**

```python
from explorer.views.labels import LabelList, LabelDetail
[c.__name__ for c in LabelList.__mro__]
[c.__name__ for c in LabelDetail.__mro__]
```

**B. See `FormatMixin` choose a template:**

```python
from django.test import RequestFactory
rf = RequestFactory()
v = LabelList()
v.request = rf.get('/builds/')
v.kwargs = {'format': 'json'}
v.object_list = None
v.get_format()               # 'json'
v.get_template_names()       # ['explorer/label_list.json', 'explorer/label_list.html']
```

**C. Resolve and reverse URLs:**

```python
from django.urls import resolve, reverse
m = resolve('/builds/')
m.func.__name__, m.url_name, m.kwargs

resolve('/builds/json').kwargs
reverse('explorer_label_list')
```

**D. Watch the two response formats:**

```python
from django.test import Client
c = Client()
c.get('/builds/')['Content-Type']
c.get('/builds/json')['Content-Type']
```

**E. Find every view that uses `FormatMixin`:**

```powershell
Select-String -Path ..\cmweb-app\*\views\*.py,..\cmweb-app\*\views.py -Pattern "FormatMixin"
```

---

## 12. Check yourself

1. What is the minimum contract a Django view must satisfy?
2. What does `as_view()` return, and when is the view instance created?
3. Why does `LabelList` set `self.title_list = []` in `__init__` rather than as
   a class attribute?
4. `LabelCommitList` is registered at four URLs. What differs between them?
5. Which two methods does `FormatMixin` override, and what does each achieve?
6. You add `(?P<format>json|html|csv)` to a URL and get `TemplateDoesNotExist`.
   What did you forget?
7. Why must `BranchNameDecoderMixin` appear above `UrlKwargsMixin` in the MRO?
8. Why must `BranchNameDecoderMixin` write to *both* `kwargs` and `self.kwargs`?
9. Why is the `LabelDetail` pattern last in `explorer/urls/labels.py`?
10. Why are label sections prefixed with `+`?
11. Name the three files you must edit to expose a new public endpoint, and the
    symptom of forgetting each one.
12. `PermissionCheckMiddleware` trusts a username without a password. Why is
    that not currently a vulnerability, and what would make it one?
