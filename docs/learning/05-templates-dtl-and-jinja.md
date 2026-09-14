# 05 — Templates, frontend rendering, DTL and Jinja2

> **Goal:** be able to trace which template file renders a given page, follow
> the `{% extends %}` chain to the top, write a custom tag or filter, and
> explain precisely how the Django Template Language differs from Jinja2 — and
> where each one is actually used in this repository.

---

## 1. What a template engine does

A template is a text file with holes in it. The engine takes the file plus a
**context** (a dict) and produces a string.

```
template file  +  context dict  ->  rendered string
```

Three things make this a language rather than string formatting:

1. **Interpolation** — `{{ build.name }}`
2. **Control flow** — `{% if %}`, `{% for %}`
3. **Composition** — `{% extends %}`, `{% include %}`, `{% block %}`

Django ships two engines out of the box and can run both at once:

| Engine | Backend string |
| --- | --- |
| Django Template Language (DTL) | `django.template.backends.django.DjangoTemplates` |
| Jinja2 | `django.template.backends.jinja2.Jinja2` |

---

## 2. Configuring templates

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            join(GLOBALS['PATH_SITE'], 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'cmweb.context_processors.settings',
                'cmweb.context_processors.preferences',
                'cmweb.context_processors.sql_queries',
                'cmweb.context_processors.debug',
            ],
        },
    },
]
```

That is CMWEB's real config, `cmweb-project/cmweb/settings.py:287`.

| Key | Meaning |
| --- | --- |
| `BACKEND` | Which engine |
| `DIRS` | Project-wide template directories, searched **first** |
| `APP_DIRS` | Also search `<app>/templates/` for every installed app |
| `OPTIONS.context_processors` | Functions that add variables to every context |

### Resolution order

For `{% extends "base.html" %}` Django tries, in order:

1. each directory in `DIRS` -> `cmweb-project/templates/base.html` **found**
2. each installed app's `templates/` in `INSTALLED_APPS` order

This is why an app can override a third-party template just by shipping a file
at the same path — and why the app-name subdirectory convention
(`explorer/templates/explorer/...`) matters so much.

---

## 3. DTL syntax

### Three delimiters

```
{{ variable }}          interpolation
{% tag %}               logic
{# comment #}           comment (not emitted)
```

### Variable lookup — the four-step rule

For `{{ a.b }}` Django tries, in this order:

1. dictionary lookup — `a['b']`
2. attribute lookup — `a.b`
3. **calls it if callable** — `a.b()`
4. numeric index — `a[b]`

Step 3 is the surprising one. `{{ build.is_recent }}` calls the method. This is
also why `{{ label.commits.count }}` works — `count` is a method, called with
no arguments.

Silent failure is deliberate: a missing variable renders as the empty string
(`TEMPLATE_STRING_IF_INVALID`), it does not raise. Good for robustness, bad for
debugging — a typo in a variable name is invisible.

**Arguments are impossible.** `{{ a.b(1) }}` is a syntax error, always. If you
need to pass an argument, you need a filter or a tag. This is a design
constraint, not an oversight (see section 8).

### Filters

```
{{ value|lower }}
{{ value|default:"none" }}
{{ value|date:"Y-m-d" }}
{{ value|truncatewords:30 }}
{{ value|yesno:"btn-primary," }}
{{ value|default_if_none:'null' }}
{{ value|escapejs }}
{{ value|length }}
{{ value|join:", " }}
```

Chained left to right, at most one argument each, after a colon.

Real uses from `label_list.html` and `label.json`:

```
class="target branches form-control {{ branch|yesno:"btn-primary," }}"
"allCommitsCount": {{ object.all_commits_count|default_if_none:'null' }},
"name": "{{ object.name|escapejs }}",
"dateCreated": {{ object.date_created|date:"U" }}000,
```

Look at that last one — `date:"U"` formats as a Unix timestamp in seconds, and
the template appends three literal zeros to make it milliseconds for
JavaScript. Presentation logic, correctly kept in the presentation layer.

### Tags

```
{% if x %} ... {% elif y %} ... {% else %} ... {% endif %}
{% for item in list %} ... {% empty %} ... {% endfor %}
{% url 'name' arg=value %}
{% include "other.html" %}
{% extends "base.html" %}
{% block name %} ... {% endblock %}
{% load mytags %}
{% csrf_token %}
{% with total=x.y.z %} ... {% endwith %}
{% cache 600 "key" pk %} ... {% endcache %}
```

Inside a `{% for %}` you get a `forloop` object:

| Variable | Meaning |
| --- | --- |
| `forloop.counter` | 1-based index |
| `forloop.counter0` | 0-based index |
| `forloop.first` / `forloop.last` | booleans |
| `forloop.parentloop` | The enclosing loop |

`forloop.last` is what makes hand-written JSON templates possible:

```
{% for label in object_list %}
  {% show_label_json label depth %}{% if not forloop.last %},{% endif %}
{% endfor %}
```

### Autoescaping

DTL escapes HTML in `{{ }}` by default. To opt out:

```
{{ html|safe }}
{% autoescape off %} ... {% endautoescape %}
```

Only do this for content you generated. `mark_safe()` / `SafeText` in Python is
the same promise made from the other side.

---

## 4. Template inheritance

The single most important idea in DTL.

- `{% extends %}` **must be the first tag** in a file.
- A child template's content outside `{% block %}` tags is discarded.
- `{{ block.super }}` renders the parent's version of the block, so you can
  append rather than replace.
- Blocks can be nested; the same block name cannot appear twice at one level.

### CMWEB's chain

```
skeleton.html                cmweb-project/templates/
   ^  doctype, <head>, <title>, top-level blocks, PJAX version meta
   |
bootstrap.html               cmweb-project/templates/
   ^  Bootstrap 3 shell, sidebar, top bar. "Do not load any template tags here"
   |
base.html                    cmweb-project/templates/
   ^  the real site chrome: compressed CSS/JS, gravatar, sitetree, preferences
   |
base/base.html               cmweb-app/base/templates/base/     ({% extends "base.html" %})
   ^  a one-line indirection so apps never name the project template directly
   |
explorer/base.html           cmweb-app/explorer/templates/explorer/
   ^  {% block body_controller %}explorer{% endblock %}
   |
explorer/label_list.html     the actual page
```

Six levels. Worth walking once with the files open.

`skeleton.html` is where the interesting structural decisions live:

```
{% if not request.is_ajax %}<!DOCTYPE html>
<html lang="en">
  <head>
    ...{% endif %}
    <meta http-equiv="x-pjax-version" content="{{ CM_WEB_VERSION }}-{{ STATIC_MD5 | default:'unknown' }}">
    <title>{% block title %}{% endblock %} - {% firstof CM_WEB_NAME 'CM Web' %}</title>
```

That `{% if not request.is_ajax %}` wrapping the doctype and `<head>` is the
PJAX mechanism: for an AJAX navigation the same template renders **only the
fragment**, with no document wrapper. One template, two output shapes.

`bootstrap.html` carries a comment worth respecting:

```
{# Bootstrap layout that does not reply on any app. Do not load any template tags here #}
```

The layer is deliberately app-independent so it can be reused by pages that
render before the app stack is available.

### `{{ block.super }}` in practice

`explorer/label_list.html`:

```
{% block content_title %}Builds <small>{{ title }}</small>{{ block.super }}{% endblock %}
{% block body_action %}{{ block.super }} label_list{% endblock %}
```

The second one accumulates CSS class names down the inheritance chain — each
level appends its own, so the `<body>` ends up with a full trail of
controller/action classes that the JavaScript DOM router reads.

---

## 5. Context processors

A context processor is a function `(request) -> dict` whose result is merged
into **every** template context rendered with a `RequestContext`.

`cmweb-project/cmweb/context_processors.py`:

```python
def settings(request):
    """Put all values in settings.GLOBALS into the default template context."""
    return django.conf.settings.GLOBALS


def preferences(request):
    """Put all user preferences into the current context."""
    if request.user and hasattr(request.user, 'profile'):
        preferences = request.user.profile.preferences()
    else:
        preferences = Profile.registered_preferences
    return {
        'preferences': preferences,
        'preferences_json': json.dumps(preferences),
    }


def sql_queries(request):
    """Return a dictionary for sql queries during the request."""
    return {'sql': connection.queries}


def debug(request):
    """Return debug information for request."""
    return {'DEBUG': django.conf.settings.DEBUG}
```

The first one is why templates can write `{{ CM_WEB_NAME }}`,
`{{ PLATFORM_MANIFEST }}`, `{{ STATIC_MD5 }}` with nothing in the view — every
key of `GLOBALS` is a top-level template variable everywhere.

```
{% if manifest == PLATFORM_MANIFEST or manifest == SYSTEM_MANIFEST %}
```

That line in `label_list.html` reads two `GLOBALS` entries that no view ever
put in the context.

> **Cost.** A context processor runs on every single render. `sql_queries`
> returns `connection.queries`, which is only populated when `DEBUG` is on —
> cheap in production, but a reminder that anything expensive here is paid for
> by every page.

---

## 6. Custom template tags and filters

When a template needs computation, this is the sanctioned escape hatch.

### Where they live

```
<app>/templatetags/
├── __init__.py          <- required, or the module is invisible
└── mytags.py
```

Then `{% load mytags %}` at the top of the template.

CMWEB's:

| Module | Provides |
| --- | --- |
| `base/templatetags/linkutils.py` | `smart_url`, `url_with_branch` |
| `base/templatetags/stringutils.py` | string helpers |
| `base/templatetags/listutils.py` | list helpers |
| `base/templatetags/parameters.py` | reading `Parameter` from a template |
| `base/templatetags/properties.py` | reading `Property` from a template |
| `explorer/templatetags/explorerutils.py` | everything label/commit/manifest-shaped |

### The three kinds

```python
from django import template

register = template.Library()


@register.filter                       # 1. filter: {{ x|label_icon }}
def label_icon(label):
    ...


@register.simple_tag                   # 2. simple tag: {% label_url label 'detail' %}
def label_url(label, name, **kwargs):
    ...


@register.inclusion_tag('explorer/tags/label.json')   # 3. inclusion tag
def show_label_json(label, depth=0):
    """Return the JSON representation of the `Label` object."""
    if isinstance(depth, str):
        try:
            depth = int(depth)
        except ValueError:
            depth = 0
    return {
        'object': label,
        'depth': depth,
        'CACHE_TIMEOUT': settings.GLOBALS['CACHE_TIMEOUT'],
    }
```

An **inclusion tag** returns a context dict, and Django renders the named
template with it. It is a function *and* a template — a reusable component.

### The killer example: JSON built from templates

`explorer/templates/explorer/label_list.json`:

```
{% load explorerutils %}
[
  {% for label in object_list %}
    {% show_label_json label depth %}{% if not forloop.last %},{% endif %}
  {% endfor %}
]
```

and `explorer/templates/explorer/tags/label.json`:

```
{% load explorerutils properties cache %}
{% if not object %}
  null
{% else %}
  {% cache CACHE_TIMEOUT "label-json" object.pk depth object.status object.commits_incomplete object.sublabels_incomplete object.all_commits_count %}
    {
      "name": "{{ object.name|escapejs }}",
      "manifestGit": "{{ object.manifest_branch.project.name }}",
      "branch": "{{ object.manifest_branch.name }}",
      "dateCreated": {{ object.date_created|date:"U" }}000,
      "incomplete": {{ object.incomplete|lower }},
      ...
      {% if depth > 0 %}
        "products": [
          {% for p in object.products.all %}
            "{{ p.name }}"{% if not forloop.last %},{% endif %}
          {% endfor %}
        ],
```

Four things to take from this:

1. **CMWEB's JSON API is rendered by the template engine**, not by a
   serializer. That is why every `.html` view has a matching `.json` template.
2. **`depth` controls recursion.** `show_label_json` calls itself for
   `object.previous`, and `{% if depth > 0 %}` stops the descent. Chapter 04's
   `DepthMixin` is what puts `depth` in the context.
3. **`{% cache %}` is used per-fragment**, keyed on the values that would change
   the output — pk, depth, status, and the incomplete flags. Fragment caching
   at exactly the granularity that changes.
4. **`|escapejs` is mandatory** here. Autoescaping protects HTML, not JSON
   string literals; a label name with a quote in it would produce invalid JSON
   without it.

> **Honest assessment:** hand-writing JSON in a template is fragile — one
> misplaced comma is a parse error at the client, and the engine cannot help
> you. Django REST Framework serializers (used by the `api` app) are the modern
> answer. This pattern is here because it predates that and because it gives
> per-fragment caching for free. Read it, understand it, but reach for DRF in
> new code.

---

## 7. Static files and compression

```
{{ STATIC_URL }}css/screen.css
```

`STATIC_URL` comes from `django.template.context_processors.static`.

`django-compressor` bundles and minifies:

```
{% compress css %}
  <link rel="stylesheet" href="{{ STATIC_URL }}external/bootstrap-3.3.5-dist/css/bootstrap.css"/>
  <link rel="stylesheet" href="{{ STATIC_URL }}css/screen.css"/>
{% endcompress %}
```

In production `COMPRESS_OFFLINE = True`, so this is resolved at build time by
`make static`, not per request. Two consequences:

- **A template change that touches a `{% compress %}` block needs `make static`
  re-run**, or you get an offline-compression error at render time.
- The compressed manifest hash feeds `STATIC_MD5`, which feeds the
  `X-PJAX-Version` header, which is how stale clients are forced to reload.

### PJAX

`PjaxVersionMiddleware` stamps every response:

```python
version = settings.GLOBALS.get('CM_WEB_VERSION', 'unknown')
md5 = settings.GLOBALS.get('STATIC_MD5', 'unknown')
response['X-PJAX-Version'] = '{}-{}'.format(version, md5)
```

The browser compares it with the value it loaded with; a mismatch turns the
next PJAX navigation into a full page load. Combined with the
`{% if not request.is_ajax %}` guard in `skeleton.html`, this is the whole PJAX
mechanism: **same URL, same view, same template — fragment or full document
depending on the request.**

---

## 8. DTL vs Jinja2

Jinja2 was directly inspired by DTL and then deliberately went the other way on
the key trade-off.

| | **DTL** | **Jinja2** |
| --- | --- | --- |
| Ships with Django | Yes, and is the default | Yes, as a second backend |
| Call with arguments | **Impossible** — `{{ f(x) }}` is a syntax error | `{{ f(x) }}` works |
| Method calls | Automatic, zero-arg only | Explicit: `{{ obj.method() }}` |
| Filters | `{{ x\|f:"a" }}`, one argument | `{{ x\|f("a", "b") }}`, any number |
| Extra logic | Custom tags/filters in Python | Arbitrary Python-ish expressions inline |
| `{% for %}` else clause | `{% empty %}` | `{% else %}` |
| Loop variable | `forloop.counter` | `loop.index` |
| Macros | No | `{% macro %}` — reusable parameterised blocks |
| Tests | No | `{% if x is defined %}` |
| Speed | Slower | Notably faster (compiles to Python bytecode) |
| Autoescape | On by default | **Off** by default; Django's backend turns it on |
| Undefined variable | Silently empty | Configurable; can raise |
| Philosophy | Restrict the language to keep logic out | Trust the author, give them power |
| Context processors | Yes | **No** — use the `environment` callable instead |
| `{% csrf_token %}`, `{% url %}` | Built in | Must be injected into the environment |

### The same fragment in both

DTL:

```
{% extends "base.html" %}
{% block content %}
  <ul>
  {% for build in object_list %}
    <li class="{% cycle 'odd' 'even' %}">
      {{ build.name|upper }} — {{ build.created|date:"Y-m-d" }}
      {% if build.is_recent %}<span>new</span>{% endif %}
    </li>
  {% empty %}
    <li>No builds.</li>
  {% endfor %}
  </ul>
{% endblock %}
```

Jinja2:

```
{% extends "base.html" %}
{% block content %}
  <ul>
  {% for build in object_list %}
    <li class="{{ loop.cycle('odd', 'even') }}">
      {{ build.name|upper }} — {{ build.created.strftime('%Y-%m-%d') }}
      {% if build.is_recent() %}<span>new</span>{% endif %}
    </li>
  {% else %}
    <li>No builds.</li>
  {% endfor %}
  </ul>
{% endblock %}
```

Note `build.is_recent()` — explicit parentheses — and
`build.created.strftime(...)` — a Python call inline, which DTL cannot express
and would require a filter for.

### Running both at once

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.jinja2.Jinja2',
        'DIRS': [BASE_DIR / 'jinja2'],
        'APP_DIRS': True,
        'OPTIONS': {'environment': 'myproject.jinja2.environment'},
    },
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {'context_processors': [...]},
    },
]
```

with:

```python
# myproject/jinja2.py
from django.templatetags.static import static
from django.urls import reverse
from jinja2 import Environment


def environment(**options):
    env = Environment(**options)
    env.globals.update({'static': static, 'url': reverse})
    return env
```

Backends are tried in order. `APP_DIRS` for Jinja2 looks in `<app>/jinja2/`,
not `<app>/templates/`, so the two never collide.

### Which does CMWEB use?

**DTL only, for the web application.** There is no Jinja2 backend in
`TEMPLATES`, and no Jinja2 dependency in the Django requirements.

**Jinja2 is used heavily — but by Ansible, not by Django.** Every file under
`cmweb-scripts/ansible/roles/*/templates/` ending in `.j2` is a Jinja2 template
rendered by Ansible at deploy time to produce server configuration:

```
cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2
cmweb-scripts/ansible/roles/cmweb-node/templates/django/secure.py.j2
cmweb-scripts/ansible/roles/cmweb-node/templates/logrotate/cmweb.j2
```

This is the honest answer to "Jinja templates and DTL" in this codebase: they
are both here, they use nearly the same syntax, and they operate at completely
different times on completely different things.

| | DTL in CMWEB | Jinja2 in CMWEB |
| --- | --- | --- |
| Rendered by | Django, per HTTP request | Ansible, once per deploy |
| Input context | The view's context dict + context processors | Ansible vars: `group_vars/`, `hosts/`, vault |
| Output | HTML / JSON / XML / CSV sent to a browser | `/etc/apache2/sites-available/...`, `cmweb/secure.py` |
| Files | `cmweb-app/*/templates/`, `cmweb-project/templates/` | `cmweb-scripts/ansible/roles/*/templates/*.j2` |
| Failure shows up as | A 500 or a broken page | A failed playbook run, or a server that will not start |

One trap this creates, straight from `cmweb.conf.j2`:

```
LogFormat {% raw %}"%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D"{% endraw %} {{ hostname_short }}_access
```

Apache's own log format uses `%{...}i`, and Jinja2 would try to interpret the
braces. `{% raw %}` tells Jinja2 to emit the block literally. Chapter 08 goes
into this.

Chapter 08 covers the Ansible side in full.

---

## 9. Try it

```powershell
cd local-cmweb
.venv\Scripts\python.exe manage.py shell
```

**A. Render a template by hand:**

```python
from django.template.loader import render_to_string, get_template
t = get_template('explorer/label_list.json')
t.origin.name                       # the actual file on disk
```

**B. Walk the inheritance chain.** Open these six files in order and find each
`{% extends %}`:

```
cmweb-app/explorer/templates/explorer/label_list.html
cmweb-app/explorer/templates/explorer/base.html
cmweb-app/base/templates/base/base.html
cmweb-project/templates/base.html
cmweb-project/templates/bootstrap.html
cmweb-project/templates/skeleton.html
```

**C. See a context processor at work.** Load `http://127.0.0.1:8000/builds/`
and view source: the `<title>` ends with the value of
`settings.GLOBALS['CM_WEB_NAME']`, which no view ever set.

**D. Compare the two renderings of one view:**

```powershell
curl.exe -s http://127.0.0.1:8000/builds/json | Select-Object -First 20
curl.exe -s http://127.0.0.1:8000/builds/ | Select-String "<title>"
```

**E. Prove the PJAX split.** Request the same URL with and without the AJAX
header and compare whether a `<!DOCTYPE>` appears:

```python
from django.test import Client
c = Client()
b1 = c.get('/builds/').content[:60]
b2 = c.get('/builds/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').content[:60]
b1, b2
```

**F. Write a filter.** Add to `explorer/templatetags/explorerutils.py`:

```python
@register.filter
def shorten_sha(value, length=8):
    """Return the first `length` characters of a sha1."""
    return str(value)[:length]
```

then use `{{ commit.sha1|shorten_sha }}` in a template. Note you get exactly
one argument — that constraint is the whole point of section 8.

**G. Find the Jinja2 side:**

```powershell
Get-ChildItem -Path ..\cmweb-scripts\ansible -Filter *.j2 -Recurse | Select-Object FullName
```

---

## 10. Check yourself

1. In what order does Django search for `base.html`?
2. What are the four steps of DTL variable lookup, and which one surprises
   people?
3. Why can `{{ label.commits.count }}` work but `{{ label.members_for('x') }}`
   cannot?
4. What does `{{ block.super }}` do, and what is
   `{% block body_action %}{{ block.super }} label_list{% endblock %}`
   accumulating?
5. Which template in the chain decides whether a `<!DOCTYPE>` is emitted, and
   on what condition?
6. Name the four context processors CMWEB adds, and say which one makes
   `{{ PLATFORM_MANIFEST }}` resolve.
7. What is the difference between `@register.simple_tag` and
   `@register.inclusion_tag`?
8. In `label.json`, why is `|escapejs` required and autoescaping insufficient?
9. What is the `{% cache %}` fragment in `label.json` keyed on, and why those
   particular values?
10. You edit a template inside a `{% compress %}` block and production breaks.
    What step was missed?
11. Give three concrete syntax differences between DTL and Jinja2.
12. Jinja2 is used in this repository. Where, by what tool, and rendering into
    what output files?
13. Why does `cmweb.conf.j2` need `{% raw %}` around its `LogFormat` line?
