# 09 — Comparing MVT with the CMWEB applications

> **Goal:** hold the textbook pattern and the real application side by side,
> trace one request all the way through, and be able to say — for each place
> CMWEB departs from the pattern — what was traded for what.

Read this last. It assumes chapters 01–08.

---

## 1. The mapping, concretely

| MVT concept | Textbook Django | CMWEB |
| --- | --- | --- |
| Project package | `mysite/` beside `manage.py` | `cmweb-project/cmweb/` — a **separate git repository** |
| Apps | `mysite/blog/` | `cmweb-app/*` — **another repository**, mounted at `cmweb-project/apps/` |
| Model | `blog/models.py`, ~100 lines | `explorer/models.py`, 2,700 lines, 23 model classes |
| Manager | `objects = models.Manager()` | `explorer/managers.py` — 8 custom managers with named querysets |
| View | `blog/views.py` | `explorer/views/` — a **package** of six modules |
| Mixins | rarely | `base/views/mixins.py` + `explorer/views/mixins.py`, 6–7 deep per view |
| URLconf | `blog/urls.py` | `explorer/urls/` — a package with shared regex fragments |
| Template | `blog/templates/blog/post_list.html` | same convention, plus `.json` / `.xml` / `.csv` siblings |
| Template tags | occasionally | `explorerutils.py` renders the entire JSON API |
| Settings | one `settings.py` | five modules + a generated `secure.py` + a `Parameter` DB table |
| Migrations | `makemigrations` output | 39 in `explorer` alone (102 across all apps), one of them environment-conditional |
| Server | `runserver` | Apache + mod_wsgi, 16 x 15, baked into an AMI |
| Background work | Celery + broker + worker | Celery configured, **no broker, no worker** — everything eager |
| Scheduled work | cron or Celery beat | ~50 Jenkins jobs in `cmweb-scripts/jobs_on_cloud/` |

The letters are all present and in the right places. What changed is **scale**,
and scale is what produced every deviation below.

---

## 2. One request, all the way down

Take a real URL:

```
GET https://cmweb.ptc.sony.co.jp/builds/platform/manifest/1.2.3/+commits/cherry/json
```

### Step 1 — Apache (chapter 08)

- TLS terminated by `SSLEngine On`.
- `Alias /static/` does not match, so the request falls through.
- `RewriteRule`s do not match (the URL already uses the `+` form).
- `<Location "/">` requires LDAP basic auth. The user's credentials are bound
  against `ldaps://LDAP.jp.sony.com:3269`. On failure: 401, rewritten by
  `ErrorDocument` into a redirect to `/register`.
- `WSGIScriptAlias /` hands the request to
  `/srv/www/cmweb.ptc.sony.co.jp/site/cmweb/wsgi.py`, in one of 240
  process/thread slots.
- `REMOTE_USER` is set to the authenticated username.

### Step 2 — WSGI and settings (chapter 06)

- `wsgi.py` sets `DJANGO_SETTINGS_MODULE=cmweb.settings_wsgi`.
- `settings_wsgi` -> `settings_deployed` (a symlink) -> `settings_prod` ->
  `settings` -> `secure.py`.
- The Django application is wrapped in Paste's `ErrorMiddleware`.

### Step 3 — Middleware, request phase (chapter 04)

Top to bottom through `MIDDLEWARE`, which in production is sandwiched:

```
UpdateCacheMiddleware          <- prod only; may serve nothing yet
GZipMiddleware                 <- prod only
CommonMiddleware
SessionMiddleware              <- session from memcached
SessionTimeoutMiddleware
CsrfViewMiddleware
AuthenticationMiddleware       <- request.user
RemoteUserMiddleware           <- REMOTE_USER -> Django user via RemoteLDAPBackend
MessageMiddleware
PaginationMiddleware
PjaxVersionMiddleware
PermissionCheckMiddleware      <- gate 2: users.view_all_pages
FetchFromCacheMiddleware       <- prod only; may return a cached page HERE
```

If `FetchFromCacheMiddleware` has a fresh copy, **the request ends here** — no
view, no model, no template. Up to 10 minutes stale.

### Step 4 — URL resolution (chapter 04)

`ROOT_URLCONF = 'cmweb.urls'`:

```python
re_path(r'^(explorer/)?', include('explorer.urls')),
```

then `explorer/urls/__init__.py`:

```python
path(r'builds', include('explorer.urls.labels'),),
```

then `explorer/urls/labels.py`:

```python
re_path(LABEL_PREFIX + r'/\+commits' + COMMIT_FILTER +
        '(?:/(?P<format>html|json))?'
        '(?:/(?P<project>.+))?'
        '/?$',
        LabelCommitList.as_view(section='commits',
                                url_name='explorer_label_commits'),
        name='explorer_label_commits'),
```

Captured kwargs:

```
manifest = 'platform/manifest'
name     = '1.2.3'
filter   = 'cherry'
format   = 'json'
```

plus the `as_view()` initkwargs `section='commits'` and
`url_name='explorer_label_commits'`.

### Step 5 — The view (chapter 04)

`LabelCommitList` is instantiated, `self.kwargs` is set, `dispatch()` runs down
the MRO:

| Mixin | During dispatch / context |
| --- | --- |
| `BranchNameDecoderMixin` | decodes `\` back to `/` in any branch kwarg |
| `ManifestMixin` | `self.manifest = 'platform/manifest'` |
| `FormatMixin` | `get_format()` -> `'json'` |
| `DepthMixin` | reads `?depth=` |
| `UrlKwargsMixin` | copies all kwargs into the context |
| `ListView` | calls `get_queryset()`, paginates |

### Step 6 — The models (chapter 03)

```python
Label.objects.versioned().filter(manifest_branch__project__name=...)
```

Two joins to reach `Project.name`. The commit list is filtered by `cherry`.
Denormalised counters (`commits_count`) are read straight off the row rather
than counted.

SQL goes to the `default` alias (the replica router is disabled).

### Step 7 — The template (chapter 05)

`FormatMixin.get_template_names()` turns
`explorer/label_commit_list.html` into
`['explorer/label_commit_list.json', 'explorer/label_commit_list.html']`.

The `.json` template loops and calls `{% show_commit_json commit %}`, an
inclusion tag rendering `explorer/tags/commit.json`, itself wrapped in
`{% cache CACHE_TIMEOUT ... %}`.

Context processors have already added every key of `settings.GLOBALS`, plus the
user's preferences.

### Step 8 — Response phase

- `render_to_response()` sets `Content-Type: application/json`.
- `PjaxVersionMiddleware` adds `X-PJAX-Version: <version>-<static md5>`.
- `GZipMiddleware` compresses.
- `UpdateCacheMiddleware` stores the page for 10 minutes.
- Apache logs the line, including `%D` — the microseconds it took.

**Eight layers, four of which are outside Django.** That is the honest shape of
"one request" in this application, and it is why `docs/how-the-site-works.md`
exists as a separate document.

---

## 3. Where CMWEB follows the pattern well

Worth stating, because the next section is all deviations.

### Named querysets on managers

```python
Label.objects.versioned()
Project.objects.system_manifests()
ManifestBranch.objects.active_for_week()
LabelComponentMembership.objects.changed()
```

Every one of those is a domain concept with a name, defined once. This is the
textbook "fat model" advice actually followed, and it is why `LabelList` is
readable despite doing six kinds of filtering.

### `get_absolute_url()` by route name

```python
def get_absolute_url(self):
    return reverse('explorer_project_detail', kwargs={'name': self.name})
```

The model names a route rather than importing a view. Admin, templates and
serialisers all get the canonical URL for free.

### One view, many representations

`FormatMixin` is genuinely elegant. A single `LabelCommitList` serves HTML,
JSON and CSV, and the view contains nothing about which. The separation is what
makes it possible — a view that built HTML strings could not do this.

### Composition over repetition in URLs

`LABEL_PREFIX`, `COMMIT_FILTER`, `LABEL_SECTION` are assembled rather than
retyped. Nine patterns in `urls/labels.py` share four fragments. Change the
grammar in one place.

### Configuration separated by lifetime

```
settings.py     changes with a deploy
secure.py       changes with a vault edit
Parameter       changes with an admin click
Property        changes per object
```

Four tiers, each matched to how often the value actually changes. Most
applications have one.

---

## 4. Where CMWEB departs — and the trade in each case

### 4.1 Models import from the presentation layer

```python
class Label(models.Model):
    def get_absolute_url(self):
        from explorer.templatetags.explorerutils import label_url
        return label_url(self, 'detail')

    @classmethod
    def icon_class(cls):
        from explorer.templatetags.explorerutils import label_icon
        return 'octicon octicon-{}'.format(label_icon(cls))
```

**The rule broken:** `models -> templatetags` is presentation flowing backwards
into data.

**Why it happened:** label URLs are genuinely complicated (manifest prefix
optional, delta labels have a different shape, branch names need encoding).
That logic was written once, for templates. The model needed the same answer.

**How it is contained:** the imports are *function-local*, so no import cycle
exists at module load.

**What it costs:** `explorer.models` cannot be imported in a context where
`explorer.templatetags` is unavailable, and the dependency is invisible until
the method is called. Compare `Project.get_absolute_url()`, three lines away,
which uses plain `reverse()` and has no such problem.

**If you were fixing it:** move URL construction into a plain module
(`explorer/urls_utils.py`), import it from both the model and the template tag.

### 4.2 Presentation concerns in the schema

```python
# COUNT(*) caching for templates
components_count = models.IntegerField(null=True, editable=False)
commits_count = models.IntegerField(null=True, editable=False)
all_commits_count = models.IntegerField(null=True, editable=False)
...
```

**The rule broken:** the schema now encodes a rendering optimisation. The
comment says so.

**Why it happened:** a build list page shows dozens of labels, each with
several counts. Live `COUNT(*)` across `explorer_label_commits` and
`CommitDelivery` per row is not viable.

**What it costs:** these fields can drift. They are maintained by
`Label.update_counts()` called from indexing — **not** by signals, and **not**
by `save()`. Change membership by hand and the counters lie until something
recomputes them.

**How to live with it:** in templates, read the field. In commands, call
`.count()` if correctness matters, and call `update_counts()` after any
membership change.

### 4.3 Database access at import time

Several classes call `Parameter.get_int(...)` in the **class body**, which
issues a query when the module is imported.

**What it costs:** you cannot import the URLconf before the database exists.
Hence:

```powershell
manage.py migrate --skip-checks
```

in `local-cmweb`, because system checks import the URLconf.

**The correct shape** is `PaginateMixin`'s — read the parameter inside the
method:

```python
def paginate_queryset(self, queryset, context, key=..., default=...):
    paginate_by = Parameter.get_int(key, default)
```

Same behaviour, no import-time query, and it picks up admin changes without a
restart.

### 4.4 A JSON API rendered by the template engine

`label_list.json` -> `{% show_label_json %}` -> `explorer/tags/label.json`,
which is hand-written JSON with `|escapejs` and `{% if not forloop.last %},{% endif %}`.

**Why it happened:** it predates Django REST Framework in this codebase, and it
buys per-fragment `{% cache %}` keyed on exactly the fields that change the
output.

**What it costs:** a stray comma is a client-side parse error the engine cannot
detect; escaping is manual and easy to forget; there is no schema.

**The coexisting alternative:** the `api` app uses DRF properly. New endpoints
belong there. Read the template approach so you can maintain it, do not extend
it.

### 4.5 Celery without Celery

`CELERY_TASK_ALWAYS_EAGER = True` in the base settings, never overridden. No
broker URL anywhere, including the Ansible-rendered `secure.py`. No Ansible
role installs a worker. `run_commands.sh` re-asserts eager mode.

**What it means:** every `.delay()` is a synchronous function call in the
request thread. There is no queue to inspect, no retry, no isolation.

**Combined with Apache's `processes=16 threads=15`:** a slow "task" holds one
of 240 slots for its full duration.

**Why it is survivable:** the genuinely long work — indexing — was moved out to
Jenkins jobs entirely. Celery is vestigial rather than load-bearing.

**What to watch for:** code that *reads* as asynchronous and is not. Do not add
a `.delay()` expecting a background job.

### 4.6 Two gates in two repositories

Exposing an endpoint needs a URLconf entry (`cmweb-app`), a `NO_AUTH_URLS`
entry (`cmweb-project`), and an Apache `LocationMatch` (`cmweb-scripts`) —
three repositories, three review cycles.

**Why:** defence in depth, and Apache was doing LDAP before Django's auth was
wired up.

**What it costs:** the failure modes are silent and confusing until you know
the table:

| Symptom | Missing |
| --- | --- |
| 401 | Apache block |
| `/access-denied` | `NO_AUTH_URLS` |
| 404 | URLconf |

### 4.7 Trusting a header

```python
auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
```

`PermissionCheckMiddleware` decodes the username and **does not verify the
password**.

**Why it is safe today:** Apache has already bound that exact username against
LDAP. Django is trusting an upstream that did the work.

**Why it is fragile:** the safety lives entirely in `cmweb.conf.j2`, in another
repository. Any deployment that puts this app behind something non-authenticating
makes it trivially impersonable.

**The lesson:** when trust is delegated to a component outside the codebase, the
codebase should say so loudly. This is the pattern to recognise, never to copy.

### 4.8 A migration whose content depends on settings

```python
env = settings.GLOBALS.get('CM_WEB_ENVIRONMENT')
...
if env != 'dev':
    operations.append(migrations.RunSQL('ALTER TABLE ... TYPE bigint;'))
```

**Why:** SQLite cannot alter column types; the target table is an implicit M2M
join table with no model for the autodetector to work from.

**What it costs:** two databases can record the same migration as applied and
have different schemas; `makemigrations --check` cannot see the difference; and
`CM_WEB_ENVIRONMENT` must be the exact string `'dev'` or local migration fails
with `near "ALTER": syntax error`.

**The portable form** branches on `schema_editor.connection.vendor` instead.

### 4.9 A `try/except` that hides the error it should explain

```python
try:
    from .secure import *
except Exception as e:
    sys.stderr.write("%r.\n" % e)
```

followed thirty lines later by an unguarded `OPENSEARCH_HOST`.

**Result:** a missing `secure.py` produces `NameError: OPENSEARCH_HOST` instead
of "cmweb/secure.py is missing". The `except` makes the diagnosis *worse*, not
better.

**The lesson:** an `except` that only logs, in front of code that requires the
thing that failed, is worse than no `except` at all.

---

## 5. Scoreboard

| MVT rule | CMWEB | Note |
| --- | --- | --- |
| Fat models | **Followed** | Managers and model methods carry the domain |
| Thin views | **Followed** | `LabelList` is ~60 lines of its own code |
| Dumb templates | **Mostly** | HTML yes; the JSON templates carry real logic |
| Templates -> views -> models only | **Bent** | Function-local `templatetags` imports in models |
| Schema serves the domain, not the UI | **Bent deliberately** | Denormalised counters, documented as such |
| No side effects at import | **Broken** | Class-body `Parameter` queries |
| One source of truth for config | **Deliberately not** | Four tiers by change frequency — a feature |
| Serialisation in the view/serializer layer | **Bent** | JSON built in templates |

Roughly: the **core pattern is respected**, and every deviation is a
performance or history artefact rather than carelessness. Knowing which is
which is the point of this chapter.

---

## 6. Capstone exercise

Do this once, with the local instance running. It exercises all nine chapters.

**Task: add a "recent builds" JSON endpoint at `/builds/recent/json`.**

1. **Model (ch. 03).** Add a manager method:

```python
class LabelManager(Manager):
    def recent(self, days=7):
        """Return labels created in the last `days` days."""
        cutoff = timezone.now() - timedelta(days=days)
        return self.versioned().filter(date_created__gte=cutoff)
```

Not a filter in the view. A named domain concept.

2. **View (ch. 04).** Subclass `LabelList` and override `get_queryset()` only.
   Keep the mixin stack so you inherit `FormatMixin`.

3. **URL (ch. 04).** Add a `re_path` in `explorer/urls/labels.py`. Think about
   **where** in the list — it must come before the catch-all `LabelDetail`
   pattern, or `recent` will be read as a label name.

4. **Template (ch. 05).** You need `explorer/label_list.json` — which already
   exists, so if you named your view's template correctly you get JSON for
   free. Confirm that, and understand why.

5. **Settings (ch. 06).** Make the default window an admin-editable
   `Parameter`, read **inside** a method, not in a class body.

6. **Migration (ch. 07).** None needed — a manager method changes no schema.
   Prove it: `makemigrations --check --dry-run` should stay clean.

7. **Deployment (ch. 08).** If this endpoint were public, list the three edits
   and the repository each lives in.

8. **Reflection (ch. 09).** Which layer did each piece go in, and why not the
   next one up?

Then verify:

```powershell
curl.exe -s http://127.0.0.1:8000/builds/recent/json
```

> The working copy has **no git repositories** — changes to `cmweb-app/` are
> unrecoverable. Note what you edit, and revert it when you are done.

---

## 7. Check yourself

1. Name the eight steps a request passes through, and which four are outside
   Django.
2. At which step can a request be answered without any model or template being
   touched?
3. `LabelCommitList` is registered at four URLs with different `section=`
   values. Which MVT letter does that belong to, and why is it not a model
   concern?
4. Give two places where CMWEB follows fat-model/thin-view well, with file
   names.
5. `Label.get_absolute_url()` imports from `templatetags` inside the method.
   State the rule broken, why it happened, how it is contained, and what it
   costs.
6. Denormalised counters put a rendering concern in the schema. What maintains
   them, and what does *not*?
7. Why does the local `migrate` need `--skip-checks`, and what is the correct
   shape that would avoid it?
8. Why is `.delay()` misleading in this codebase, and how does Apache's process
   configuration make it worse?
9. `PermissionCheckMiddleware` trusts a username without a password. What makes
   that safe, where does that safety live, and what would break it?
10. Migration `0037` is conditional on a settings value. Name three
    consequences and the portable alternative.
11. The `try/except` around `secure.py` makes debugging harder. Explain
    precisely how.
12. Pick one deviation from section 4 and argue the opposite case — that it was
    the right call. Which ones is that easy for, and which ones is it hard for?
