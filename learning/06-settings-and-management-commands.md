# 06 — Settings and management commands

> **Goal:** know exactly which settings module is in force in any given
> context, be able to write a management command with arguments, and know when
> configuration belongs in `settings.py` versus in the database.

---

# Part A — Settings

## 1. What a settings module is

`settings.py` is **an ordinary Python module**. Django imports it once at
startup and copies every module-level name that is `UPPER_CASE` into
`django.conf.settings`.

```python
from django.conf import settings
settings.DEBUG
settings.GLOBALS['PATH_REPOSITORY']
```

Three consequences of it being real code:

1. It can compute values (`join(...)`, `dirname(...)`, `subprocess`).
2. It can import other modules — and therefore fail at import time.
3. `from .settings import *` gives you inheritance between settings modules.

Never import `cmweb.settings` directly in application code. Always
`from django.conf import settings`, which gives the *configured* module,
whichever one that turned out to be.

## 2. How Django finds it

The `DJANGO_SETTINGS_MODULE` environment variable, a dotted path.

| Entry point | Sets it via |
| --- | --- |
| `manage.py` | `os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings")` |
| `wsgi.py` | `os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings_wsgi")` |
| Celery | `cmweb.settings_deployed` |
| Jenkins jobs | written by `cmweb-scripts/bin/run_commands.sh` |
| Anything else | you export it yourself |

`setdefault`, not `=` — an already-set environment variable always wins. That
is how you run one-off commands against production settings:

```bash
DJANGO_SETTINGS_MODULE=cmweb.settings_prod ../ENV/bin/python3 manage.py shell
```

## 3. CMWEB's settings layering

```
                       cmweb/settings.py            <- the base: 600 lines, everything
                              |
        +---------------------+---------------------+------------------+
        |                     |                     |                  |
  settings_prod.py     settings_stage.py     settings_test.py    dev_template.py
        |                                                          (copy this
        +----------- symlinked at deploy time as ---------+         for local dev)
                     settings_deployed.py
                              |
                       settings_wsgi.py              <- what Apache actually loads
```

Each child starts with a star-import:

```python
"""Support for Production environment settings."""
from __future__ import absolute_import

from .settings import *
```

and then overrides. From `settings_prod.py`:

```python
DEBUG = False
ALLOWED_HOSTS = ['*']
CACHE_MIDDLEWARE_SECONDS = 10 * 60

GLOBALS['CM_WEB_NAME'] = 'CMWEB'
GLOBALS['CM_WEB_ENVIRONMENT'] = 'production'
GLOBALS['GERRIT_SERVER'] = "review.ptc.sony.co.jp"

DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': DATABASES__DEFAULT__NAME,
    'USER': 'cmweb',
    'HOST': DATABASES__DEFAULT__HOST,
    'PORT': DATABASES__DEFAULT__PORT,
    'PASSWORD': DATABASES__DEFAULT__PASSWORD,
}

MIDDLEWARE = \
    ['django.middleware.cache.UpdateCacheMiddleware'] + \
    ['django.middleware.gzip.GZipMiddleware'] + \
    list(MIDDLEWARE) + \
    ['django.middleware.cache.FetchFromCacheMiddleware']

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
```

Note the middleware wrapping: production sandwiches the base list between the
two halves of Django's page cache. `UpdateCacheMiddleware` must be **first** and
`FetchFromCacheMiddleware` **last** — that is Django's documented requirement,
and the list arithmetic above is how CMWEB satisfies it without restating the
whole stack.

Two operational facts that follow from this file:

- The page cache is 10 minutes, so a data fix may take 10 minutes to be visible.
- Sessions live in memcached, so **flushing the cache logs every user out.**

### `settings_wsgi.py` — the outermost layer

```python
"""The outer-most wrapper settings module for running CM Web in WSGI."""

# This has to exist, no error handling
from .settings_deployed import *

IS_WSGI = True
LOGGING['root']['level'] = 'ERROR'

GRAPPELLI_ADMIN_TITLE = GLOBALS['CM_WEB_NAME'] + ' Admin'
```

`IS_WSGI` is then used by two logging filters in `settings.py`
(`RequireIsWsgiTrue` / `RequireIsWsgiFalse`) so that web requests and
command-line runs log to different places.

`settings_deployed.py` is **generated** — Ansible symlinks it to
`settings_<env>.py` (chapter 08). It is gitignored, and Celery expects it by
name.

## 4. `secure.py` — mandatory despite the `try`

At `cmweb-project/cmweb/settings.py:563`:

```python
try:
    from .secure import *
except Exception as e:
    sys.stderr.write("%r.\n" % e)
```

That looks optional. It is not. Thirty lines later:

```python
OPENSEARCH_DSL = {
    'default': {
         'hosts': OPENSEARCH_HOST,
         'port': 443,
         'http_auth': (OPENSEARCH_AUTH_USERNAME, OPENSEARCH_AUTH_PASSWORD),
    }
}
```

`OPENSEARCH_HOST` is referenced **unguarded**. Without `secure.py`, settings
fails with a bare `NameError: name 'OPENSEARCH_HOST' is not defined` rather
than a readable message about a missing file. The `try/except` swallows the
useful error and leaves the useless one.

`secure.py` supplies:

| Name | Used for |
| --- | --- |
| `DATABASES__DEFAULT__HOST/PORT/NAME/PASSWORD` | RDS connection |
| `CACHES__DEFAULT__HOST/PORT` | ElastiCache |
| `AUTH_DEFAULT_SERVICE_USERNAME/PASSWORD` | LDAP service account |
| `LDAP_SERVER` | LDAP host |
| `OPENSEARCH_HOST`, `OPENSEARCH_AUTH_USERNAME/PASSWORD` | OpenSearch |

It is never committed. In production Ansible renders it from a Jinja2 template
fed by an encrypted vault (chapter 08). For local development, copy
`cmweb/dev_template.py`.

**This is the settings anti-pattern to learn from:** secrets correctly kept out
of git, but the fallback path produces an unreadable error. If you were fixing
it, the honest form would be an explicit check with a message naming the file.

## 5. Settings you should be able to explain

| Setting | Value in CMWEB | Why it matters |
| --- | --- | --- |
| `INSTALLED_APPS` | 21 CMWEB apps + Django + third party | Registers models, migrations, templates, static, admin |
| `MIDDLEWARE` | 10 entries, ending with the two CMWEB ones | Order is the onion order |
| `ROOT_URLCONF` | `'cmweb.urls'` | Where resolution starts |
| `WSGI_APPLICATION` | `'cmweb.wsgi.application'` | Must name the **object** |
| `DATABASES` | sqlite by default, PostgreSQL per env | |
| `DATABASE_ALIAS_FOR_WRITE` | `'default'` | Indexing writes through this |
| `DATABASE_ROUTERS` | `()` | The replica router is disabled |
| `TEMPLATES` | one DTL backend | Chapter 05 |
| `CELERY_TASK_ALWAYS_EAGER` | `True` | See below |
| `OPENSEARCH_DSL_AUTOSYNC` | `False` | Index refreshed by a Jenkins job, not on save |
| `DEFAULT_AUTO_FIELD` | `'django.db.models.BigAutoField'` | New models get bigint PKs |
| `SECRET_KEY` | hardcoded in `settings.py` | Overridden in deployed envs; never rely on the base value |
| `TEST_RUNNER` | `xmlrunner...XMLTestRunner` | XML output for Jenkins |

### The `MIDDLEWARE` list, annotated

```python
MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django_session_timeout.middleware.SessionTimeoutMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.RemoteUserMiddleware',   # Apache's REMOTE_USER -> Django user
    'django.contrib.messages.middleware.MessageMiddleware',
    'django_pagination_bootstrap.middleware.PaginationMiddleware',
    'cmweb.middleware.PjaxVersionMiddleware',                # stamps X-PJAX-Version
    'cmweb.middleware.PermissionCheckMiddleware',            # the view_all_pages gate
]
```

`SessionMiddleware` must precede `AuthenticationMiddleware` (which needs
`request.session`), which must precede `RemoteUserMiddleware`. The order is not
cosmetic.

### `CELERY_TASK_ALWAYS_EAGER = True` — read this carefully

Celery is wired up (`cmweb/celery.py`, `@shared_task` modules, and
`django_celery_results` in `INSTALLED_APPS`), but there is **no broker and no
worker in any deployed environment**:

- `CELERY_TASK_ALWAYS_EAGER = True` is set in the base `settings.py` and is
  never overridden by `settings_prod/stage/test.py`.
- No broker URL is configured anywhere, including the Ansible-rendered
  `secure.py`.
- No Ansible role installs or starts a worker.
- `cmweb-scripts/bin/run_commands.sh` re-asserts eager mode for Jenkins runs.

So **every `.delay()` runs inline and synchronously in the calling thread.** A
slow task is a slow page, and there is no queue to inspect. Do not reach for
`.delay()` expecting it to make anything asynchronous.

## 6. The other configuration system: `base.models.Parameter`

Not everything is in `settings.py`. CMWEB has a second, **runtime-editable**
configuration store — a key/value table in the database, editable from the
admin, cached.

```python
class Parameter(models.Model):
    """Model for site-wide run-time parameters."""

    key = models.SlugField('key', unique=True)
    value = models.TextField('value', blank=True, default="")

    objects = ParameterManager()

    @staticmethod
    def get(key, default=""):
        """Return `value` specified by `key`.

        If a parameter with ``key`` does not exist, it will be created
        using ``default`` as the value, and the default value will be returned.
        """
        cache_key = 'parameter-{}'.format(key)
        if cache_key in cache:
            return cache.get(cache_key)
        try:
            (param, _created) = \
                Parameter.objects.get_or_create(key=key,
                                                defaults={'value': default})
            ...
```

Note `get_or_create` — **reading an unknown key creates it** with the default.
So the admin's parameter list is self-populating: run the site once and every
tunable appears, ready to be changed.

Typed accessors: `get()`, `get_int()`, `get_list()`, `set_list()`, `get_ids()`.

Used for:

- Pagination sizes (`base-default-paginate-by`, `LABEL_PAGINATE_BY_KEY`)
- Sync intervals
- Gerrit service credentials (`gerrit-serviceusername`,
  `gerrit-servicepassword`)
- The LDAP service account

### When to use which

| Put it in | If |
| --- | --- |
| `settings.py` / `GLOBALS` | It differs per *environment* and changing it needs a deploy anyway |
| `secure.py` | It is a secret |
| `Parameter` | An operator should be able to change it at runtime without a deploy |
| `Property` | It belongs to one object, not the whole site |

`base.models.Property` is the third one: a generic key/value attached to *any*
object via a content type, used by `PropertyCacheMixin` to memoise id lists.

### The trap

`Parameter.get_int(...)` queries the database. Several CMWEB classes call it at
**class-body scope**, which means a database query at import time. That is why
the local setup must run `manage.py migrate --skip-checks`: system checks
import the URLconf, which imports those classes, which query tables that do not
exist yet.

**Do not add new class-body `Parameter` calls.** Put them inside a method, as
`PaginateMixin` does:

```python
def paginate_queryset(self, queryset, context, key=..., default=...):
    paginate_by = Parameter.get_int(key, default)
```

---

# Part B — Management commands

## 7. What they are

A management command is a subcommand of `manage.py`. Django finds them by
convention:

```
<app>/management/__init__.py
<app>/management/commands/__init__.py
<app>/management/commands/mycommand.py     ->  manage.py mycommand
```

The filename **is** the command name. The module must define a class called
exactly `Command`, subclassing `BaseCommand`.

## 8. Anatomy

```python
"""Management command to do a thing."""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """One-line summary shown by `manage.py help mycommand`."""

    help = __doc__

    def add_arguments(self, parser):
        """Add the arguments."""
        parser.add_argument('name')                       # positional
        parser.add_argument('--days', type=float, dest='days', default=1.0,
                            help='Number of days to index.')
        parser.add_argument('--all', action='store_true', dest='all_labels',
                            default=False, help='Do everything.')

    def handle(self, *args, **options):
        """Do the stuff."""
        if options['days'] < 0:
            raise CommandError('days must be positive')
        self.stdout.write(self.style.SUCCESS('done'))
```

| Piece | Purpose |
| --- | --- |
| `help` | Shown by `manage.py help <cmd>`. CMWEB sets `help = __doc__` throughout |
| `add_arguments(parser)` | Standard `argparse`; every option lands in `options` |
| `handle(*args, **options)` | The body |
| `self.stdout.write(...)` | Use this, not `print` — it is redirectable and testable |
| `self.style.SUCCESS/WARNING/ERROR` | Coloured output |
| `raise CommandError(...)` | Clean failure with a non-zero exit code, no traceback |

Options every command gets for free: `--verbosity`, `--settings`,
`--pythonpath`, `--traceback`, `--no-color`, `--skip-checks`.

### Calling one command from another

```python
from django.core.management import call_command

call_command('index_label',
             label_name=entry['name'],
             branch=entry['branch'],
             manifest=entry['manifest'],
             created=entry['created'],
             components=deeper,
             commits=deeper,
             add_branch=options['add_branch'])
```

That is real code from `index_labels.py`. Keyword arguments map onto the
`dest=` names from `add_arguments`.

## 9. CMWEB's commands

`explorer/management/commands/` holds 20 of them:

| Command | Does |
| --- | --- |
| `index_labels` | Fetch official labels from C2D, call `index_label` on each |
| `index_label` | Index one label's metadata, components, commits, sublabels |
| `index_label_commits` | Just the commits of one label |
| `index_latest` | The `LATEST` pseudo-label per branch |
| `index_delta_labels` | Deltas between labels |
| `index_sublabels` | Sub-builds |
| `index_repository` | One Gerrit repo |
| `index_static_manifest` | A pinned manifest |
| `index_jenkins_job` | Jenkins build metadata |
| `sync_commits` | Commit metadata from git + Gerrit review notes |
| `sync_labels`, `sync_labels_jira` | Label status, JIRA issue links |
| `sync_projects`, `sync_projects_from_gerrit` | The repo list |
| `update_manifestbranches` | Branch pointers |
| `update_include_exclude_rules` | The branch filter rules |
| `detect_branchpoints` | Where branches diverged |
| `find_incomplete_labels` | Audit for the `*_incomplete` flags |
| `fixup_manifestcomponents` | Data repair |
| `index_testdata` | Regenerate the test fixture |

Plus equivalents in `historian/` and `packages/`.

### The shared engine

The commands are **thin wrappers**. The real work is in
`explorer/management/indexing.py` (and the `historian/` and `packages/`
equivalents). Two house rules from that module:

1. **`apps.get_model()` for every model**, never a direct import — avoids
   circular imports across 21 apps.
2. **Writes go through `DATABASE_ALIAS_FOR_WRITE`**:

```python
using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE', DEFAULT_DB_ALIAS)
```

Follow both in new indexing code.

### A real command, read end to end

`index_labels.py`, trimmed:

```python
class Command(BaseCommand):
    """Command to index label.

    Fetch official labels from C2D and call the `index_label` command on each.
    """

    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--all-labels', action='store_true',
                            dest='all_labels', default=False, help='...')
        parser.add_argument('--days', type=float, dest='days', default=1.0,
                            help='Number of days to index. ...')
        parser.add_argument('--branch', type=str, dest='branch', default='',
                            help='Specify a branch to fetch labels for. ...')
        parser.add_argument('--add-branch', action='store_true',
                            dest='add_branch', default=False, help='...')

    def handle(self, *args, **options):
        """Do the stuff."""
        configure_logging(**options)

        query = Project.objects.system_manifests()
        if query.exists():
            manifests = query.values_list('name', flat=True)
        else:
            logging.warning("System manifest not found.")
            return

        threshold_time = timezone.now() - timedelta(days=options['days'])

        # Fetch labels from each C2D site in separate threads
        fetchers = []
        for site in C2D_SITES:
            fetcher = LabelFetcher(C2D_SITES[site], threshold, branch=...)
            fetchers.append(fetcher)
            fetcher.start()

        for fetcher in fetchers:
            fetcher.join()
            ...

        for entry in labels:
            deeper = entry['created'] > threshold_time
            call_command('index_label', label_name=entry['name'], ...)
```

Things to notice:

- `configure_logging(**options)` — CMWEB commands log rather than print,
  because they run unattended under Jenkins. `base/utils/log.py` wires
  `--verbosity` into the logging level.
- `Project.objects.system_manifests()` — a manager method, not an inline
  filter (chapter 03).
- `values_list('name', flat=True)` — do not materialise model objects you will
  not use.
- Threads for the network fetches, then a serial `call_command` loop for the
  writes.
- The `deeper` flag: labels newer than the threshold get a full index, older
  ones only get primed. Cheap-by-default, expensive-on-demand.

## 10. How commands actually run in production

**They are not cron jobs.** They are **Jenkins jobs**, defined as Jenkins Job
Builder YAML in `cmweb-scripts/jobs_on_cloud/*.yaml`. For example `index_labels`
runs hourly between 08:00 and 20:00.

Adding a scheduled indexing command therefore means **two** changes:

1. the command in `cmweb-app/<app>/management/commands/`
2. a job definition in `cmweb-scripts/jobs_on_cloud/*.yaml`

and `make update` on the `deploy_jenkins_jobs` job pushes the YAML to Jenkins.

### A Jenkins job is not a service call

`cmweb-scripts/bin/run_commands.sh` does a fresh `repo sync`, writes its own
`secure.py` and `settings_management.py`, and runs `manage.py <cmd>` against
**the same RDS instance the web servers read**.

The consequence is worth internalising: **indexing bugs surface as production
data problems, not as failed HTTP requests.** A broken command does not return
a 500 to anybody; it quietly writes wrong rows that the web tier then serves.
That is why the `*_incomplete` flags and `find_incomplete_labels` exist.

## 11. Writing a new command — checklist

1. Create `<app>/management/commands/<name>.py` (both `__init__.py` files must
   exist).
2. `class Command(BaseCommand)` with `help = __doc__`.
3. Every module, class and method needs a docstring — `make kwalitee` runs
   pydocstyle over every non-migration file, and CI enforces it.
4. Keep to 80 columns (pycodestyle).
5. Use `apps.get_model()`, not direct model imports.
6. Write via `DATABASE_ALIAS_FOR_WRITE`.
7. `configure_logging(**options)` and use `logging`, not `print`.
8. Make it **idempotent and resumable** — Jenkins will retry it.
9. If it needs a schedule, add the YAML in `cmweb-scripts/jobs_on_cloud/`.

## 12. Try it

```powershell
cd local-cmweb
```

**A. What settings are actually in force?**

```powershell
.venv\Scripts\python.exe manage.py shell
```

```python
import os
os.environ['DJANGO_SETTINGS_MODULE']
from django.conf import settings
settings.GLOBALS['CM_WEB_ENVIRONMENT']
settings.DEBUG, settings.DATABASES['default']['ENGINE']
settings.CELERY_TASK_ALWAYS_EAGER
```

**B. List every command Django can see:**

```powershell
.venv\Scripts\python.exe manage.py help
```

Note which explorer commands are present and remember they will raise
`ShimNotAvailable` locally — the C2D/Gerrit clients are stubs.

**C. Read a command's own help:**

```powershell
.venv\Scripts\python.exe manage.py help index_labels
```

**D. Inspect the runtime parameter store:**

```python
from base.models import Parameter
Parameter.objects.all().values_list('key', 'value')[:20]
Parameter.get_int('base-default-paginate-by', 25)
```

Then change one at `http://127.0.0.1:8000/admin/base/parameter/` and reload a
list page. No restart, no deploy.

**E. Diff two settings modules:**

```powershell
Select-String -Path ..\cmweb-project\cmweb\settings_prod.py -Pattern "^[A-Z_]+ *="
Select-String -Path ..\cmweb-project\cmweb\settings_test.py -Pattern "^[A-Z_]+ *="
```

**F. Write a trivial command.** Create
`cmweb-app/explorer/management/commands/count_labels.py`:

```python
"""Management command to count labels per manifest branch."""

from django.apps import apps
from django.core.management.base import BaseCommand

Label = apps.get_model('explorer', 'label')


class Command(BaseCommand):
    """Print the number of labels per manifest branch."""

    help = __doc__

    def add_arguments(self, parser):
        """Add the arguments."""
        parser.add_argument('--branch', dest='branch', default=None,
                            help='Restrict to one manifest branch.')

    def handle(self, *args, **options):
        """Do the stuff."""
        qs = Label.objects.all()
        if options['branch']:
            qs = qs.filter(manifest_branch__name=options['branch'])
        self.stdout.write(str(qs.count()))
```

then `manage.py count_labels` and `manage.py count_labels --branch=<name>`.

> Remember the local copy has **no git repositories** — deletions in
> `cmweb-app/` are unrecoverable. Write scratch commands there deliberately, and
> remove them when you are done.

## 13. Check yourself

1. Which environment variable selects the settings module, and why does
   `manage.py` use `setdefault` rather than assignment?
2. Name the five settings modules in `cmweb-project/cmweb/` and say which one
   Apache loads.
3. `settings_deployed.py` is not in git. What creates it, and how?
4. The import of `secure.py` is inside a `try`. Explain why the file is still
   mandatory, and what error you get without it.
5. Why does `settings_prod.py` build `MIDDLEWARE` by concatenation instead of
   restating the list?
6. What happens to every logged-in user if you flush the production cache?
7. `.delay()` is called in several places. What actually happens, and why?
8. What does `Parameter.get('some-new-key', 'x')` do the first time it is
   called with an unknown key?
9. Give the decision rule for `settings.py` vs `Parameter` vs `Property`.
10. Why does the local `migrate` need `--skip-checks`?
11. What three files must exist for `manage.py mycommand` to be discoverable?
12. Why do CMWEB commands log instead of printing?
13. In production, what runs `index_labels`, and against which database?
14. A nightly indexing command silently writes wrong data. Why does nobody get
    a 500, and what mechanism in the schema is meant to catch it?
