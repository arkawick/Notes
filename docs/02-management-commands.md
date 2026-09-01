# 2. Management commands

*How `manage.py` subcommands work, and the 61 that CMWEB defines.*

---

## Part A — The Django concept

### What a management command is

`manage.py` is Django's command-line entry point. You have already used built-in
subcommands:

```bash
./manage.py migrate
./manage.py runserver
./manage.py createsuperuser
```

A **management command** is a custom subcommand you write yourself. It is the
standard way to run code that is not triggered by a web request: scheduled jobs,
data imports, batch maintenance, one-off scripts.

### Why not just write a script?

A plain Python script cannot use Django's ORM, because Django needs to be
configured first — settings loaded, app registry populated, database connections
set up. A management command gets all of that for free.

### How Django finds them

Purely by file location. Any Python file at:

```
<app>/management/commands/<name>.py
```

becomes `./manage.py <name>`. Both `management/` and `commands/` need an
`__init__.py`. There is no registration step.

### The anatomy

Every command file defines a class named exactly `Command`, subclassing
`BaseCommand`:

```python
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """One-line summary shown by manage.py help."""

    help = __doc__

    def add_arguments(self, parser):
        """Declare command-line options."""
        parser.add_argument('--days', type=int, default=7)

    def handle(self, *args, **options):
        """The actual work."""
        print(options['days'])
```

- `add_arguments` receives an `argparse` parser — standard Python argument
  parsing.
- `handle` is called with the parsed options as a dict.
- Django supplies `-v/--verbosity`, `--traceback`, `--settings` and others
  automatically.

---

## Part B — A real CMWEB command

The whole of `explorer/management/commands/find_incomplete_labels.py`:

```python
"""Management command to update ``ManifestBranch`` objects based on rules."""

import datetime
import logging

from django.core.management.base import BaseCommand
from django.apps import apps

from base.utils.log import configure_logging


Label = apps.get_model('explorer', 'label')


class Command(BaseCommand):
    """Command to check incomplete ``Label`` objects.

    Need to track any incomplete labels and report.

    """

    help = __doc__

    def add_arguments(self, parser):
        """Add the arguments."""
        super(Command, self).add_arguments(parser)
        parser.add_argument(
            '--days', type=int,
            dest='days', default=7,
            help='The number of days that we go back.'
        )

    def handle(self, *args, **options):
        """Do the stuff."""
        configure_logging(**options)
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=options['days'])
        incomplete_labels = Label.objects.versioned().filter(
            incomplete=True, date_created__gt=start_date)
        for label in incomplete_labels:
            logging.info(label)
```

Four CMWEB conventions are visible here:

1. **`apps.get_model()` instead of importing the model.** More on this below.
2. **`help = __doc__`** — the class docstring doubles as `--help` text.
3. **`configure_logging(**options)`** — a CMWEB helper (`base/utils/log.py`)
   that translates Django's `-v` level into Python logging levels, so output
   goes through `logging` rather than `print`.
4. **Docstrings on everything**, because pydocstyle is a CI gate.

---

## Part C — The inventory

61 commands across 12 apps.

| App | Count | Theme |
| --- | --- | --- |
| `explorer` | 18 | Indexing builds, commits, repositories |
| `base` | 6 | Version, cache, auth setup, git sync |
| `issues` | 5 | JIRA sync, tag maintenance |
| `users` | 5 | LDAP user lifecycle |
| `historian` | 5 | Trend and zeitgeist data |
| `packages` | 4 | Package indexing |
| `harvest` | 4 | Cherry-pick automation |
| `rebase` | 4 | Rebase tracking |
| `request` | 3 | Request workflow upkeep |
| `vendorsync` | 3 | Vendor release ingestion |
| `dashboards` | 2 | Activity archiving, SW projects |
| `aod`, `product_packages` | 1 each | |

### The ones you will meet first

| Command | Does |
| --- | --- |
| `index_labels` | Import builds from C2D (the build system) |
| `index_latest` | Index the newest build per branch |
| `sync_commits` | Backfill commit details and review notes |
| `sync_projects_from_gerrit` | Refresh the repository list |
| `find_incomplete_labels` | Report builds that indexed only partly |
| `cmweb_version` | Print the running version |
| `delete_cache_key` | Drop one cache entry without flushing everything |
| `setup_auth` | Create the groups and permissions the site expects |

> **Historic note.** Older documentation references `./manage.py index_all`.
> **That command no longer exists** — it was split into the per-area commands
> above.

---

## Part D — CMWEB conventions

### 1. Fetch models with `apps.get_model()`

```python
Label = apps.get_model('explorer', 'label')      # CMWEB style
from explorer.models import Label                # normal Django style
```

Both work. CMWEB prefers the first in commands and indexing code because the
app's models import each other heavily, and a direct import from a command can
trigger a circular import. `apps.get_model()` defers the lookup until the app
registry is fully loaded.

Follow it in new indexing code. For simple commands touching one app, a direct
import is fine and clearer.

### 2. Write through the write alias

```python
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS

using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE', DEFAULT_DB_ALIAS)
Label.objects.using(using).filter(...)
```

Django supports multiple databases; `.using(alias)` picks one. Production once
had a read replica behind `cmweb/routers.py::MasterSlaveRouter`, and although
that router is currently disabled, all write paths still honour the alias.
Match it — it costs nothing and keeps the option open.

### 3. Retry network and git operations

```python
from somc_decorators.retry import retry
from base.constants import GIT_UPDATE_MAX_TRIES

@retry(C2DError, tries=3, delay=5, backoff=2)
def fetch_something():
    ...
```

The shared git mirror can be mid-sync and Gerrit returns transient 401/502s, so
external calls are wrapped in retries throughout.

### 4. Long options

`--days`, `--branch`, `--manifest`, `--add-branch`. Short flags are rare,
because Jenkins passes commands as one long string.

### The only shared mixin

`base/management/mixins.py` defines `GerritRESTClientMixin` — the sole
command mixin in the codebase:

```python
class Command(GerritRESTClientMixin, BaseCommand):
    ...
```

It adds `--review-server`, `--username`, `--password`, and builds `self.gerrit`
in a `setup()` method, falling back to the `gerrit-serviceusername` /
`gerrit-servicepassword` `Parameter` rows when no credentials are given.

Two details:

- It calls `super().setup()` inside `try/except AttributeError`, so it composes
  with commands that have no `setup()` of their own.
- It hardcodes `verify='/etc/ssl/certs/ca-certificates.crt'` for TLS
  verification. That is the *system* CA bundle — separate from the virtualenv's
  `certifi` bundle that the Ansible `cmweb-node` role patches. Both must be
  correct; they are used by different libraries.

---

## Part E — Runtime configuration via `Parameter`

Commands rarely read constants from `settings.py`. Instead they read
`base.models.Parameter`, a cached key/value table editable in the Django admin:

```python
from base.models import Parameter

interval = Parameter.get_int('explorer-cachedbranch-updateinterval', 86400)
name     = Parameter.get('gerrit-serviceusername', '')
items    = Parameter.get_list('some-key', [])
```

`Parameter.get()` **creates the row with your default if it does not exist**, so
the admin page becomes self-documenting after one run.

Values are cached (`base.cache.cache`). Common keys:

| Key | Controls |
| --- | --- |
| `base-default-paginate-by` | Default page size |
| `explorer-cachedbranch-updateinterval` | Repository re-sync interval |
| `gerrit-serviceusername` / `-servicepassword` | Gerrit credentials |
| `jira-serviceusername` / `-servicepassword` | JIRA credentials |
| `users-serviceusername` / `-servicepassword` | LDAP bind account |

**Precedence gotcha**: for the LDAP account, `users/auth.py` reads
`Parameter.get(SERVICE_USERNAME_KEY, settings.AUTH_DEFAULT_SERVICE_USERNAME)` —
so the admin `Parameter` **overrides** the settings value. A stale row silently
beats a correct `secure.py`.

---

## Part F — How commands run in production

They are **not cron jobs**. Each is a Jenkins job whose `COMMANDS` parameter is
a `;`-separated string, executed by the shared `cmweb-run-commands` macro:

```bash
export DJANGO_SETTINGS_MODULE=cmweb.settings_management
make install VIRTUALENV_DIR=../.virtualenv NO_APT_INSTALL=1
. ../.virtualenv/bin/activate

rm -f failed_commands ; touch failed_commands
echo $COMMANDS | tr ";" "\n" | while read line; do
  ./manage.py $line -v3 --traceback || { echo "$line" >> failed_commands ; }
done
exit `wc -l < failed_commands`
```

Consequences:

- The **job's exit code is the number of failed commands**.
- All commands run even if an earlier one fails.
- Everything runs at `-v3 --traceback`.
- The settings module is `cmweb.settings_management`, generated by the job.

A new scheduled command therefore means a new YAML in
`cmweb-scripts/jobs_on_cloud/`, not a crontab edit. See
[08-ansible.md](08-ansible.md) and
[infrastructure.md](infrastructure.md#jenkins-jobs).

### Running one by hand

```bash
cd cmweb-project
../ENV/bin/python3 manage.py find_incomplete_labels --days 3 -v3 --traceback
```

In `local-cmweb`, most indexing commands will raise `ShimNotAvailable` — they
need C2D, Gerrit and git mirrors that are not present. `cmweb_version` and the
read-only commands work.

---

## Part G — Writing one

```python
"""Report builds with no products assigned."""

import logging

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS

from base.utils.log import configure_logging

Label = apps.get_model('explorer', 'label')


class Command(BaseCommand):
    """Report `Label` objects that have no `Product` rows."""

    help = __doc__

    def add_arguments(self, parser):
        """Add the arguments."""
        super(Command, self).add_arguments(parser)
        parser.add_argument('--fix', action='store_true',
                            help='Mark the labels incomplete as well.')

    def handle(self, *args, **options):
        """Do the stuff."""
        configure_logging(**options)
        using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE',
                        DEFAULT_DB_ALIAS)
        qs = Label.objects.using(using).filter(products__isnull=True)
        for label in qs:
            logging.info('No products: %s', label)
            if options['fix']:
                label.incomplete = True
                label.save(using=using)
```

Checklist:

```
[ ] file at <app>/management/commands/<name>.py
[ ] __init__.py in management/ and commands/
[ ] class named exactly Command
[ ] docstrings on module, class and every method (pydocstyle gate)
[ ] under 80 columns (pycodestyle gate)
[ ] configure_logging(**options), logging not print
[ ] writes use .using(DATABASE_ALIAS_FOR_WRITE)
[ ] a jobs_on_cloud/*.yaml if it needs a schedule
```

**Next:** [03-views.md](03-views.md)
