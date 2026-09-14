# 07 — Migrations and database integration

> **Goal:** understand migrations as a dependency graph rather than a list of
> files, be able to write a data migration safely, and know exactly how a
> schema change reaches production in CMWEB (it is not part of the deploy).

---

## 1. The problem

Models change. Databases hold data. You cannot just drop and recreate the
table.

A migration is a **versioned, ordered, reversible description of a schema
change**, expressed in Python so it works across database backends. Django
generates most of them for you by diffing your models against the migration
history.

```
models.py  --makemigrations-->  migrations/0042_....py  --migrate-->  the database
```

Django records what it has applied in a table called `django_migrations`
(columns: `app`, `name`, `applied`). That table is the source of truth about the
state of a given database.

---

## 2. Anatomy of a migration

```python
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('explorer', '0036_alter_projecttreenode_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='labelmembership',
            name='commits',
            field=models.ManyToManyField(blank=True,
                                         related_name='label_memberships',
                                         to='explorer.Commit'),
        ),
    ]
```

| Attribute | Meaning |
| --- | --- |
| `dependencies` | Migrations that must run **before** this one |
| `operations` | The ordered list of changes |
| `initial = True` | This is the app's first migration |
| `atomic = False` | Do not wrap in a transaction (needed for some PostgreSQL DDL) |
| `run_before` | The inverse of `dependencies` |
| `replaces` | This migration squashes the listed ones |

### It is a graph, not a list

`dependencies` may name migrations in **other apps**, and that is how Django
orders cross-app changes. Real example, `explorer/migrations/0002`:

```python
dependencies = [
    ('packages', '0001_initial'),
    ('explorer', '0001_initial'),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ('issues', '0001_initial'),
    ('aod', '0001_initial'),
]
```

Five dependencies across four apps, because that migration adds foreign keys
pointing at all of them. `swappable_dependency(settings.AUTH_USER_MODEL)` is
the correct way to depend on the user model — it resolves to whichever app
provides it, so a project with a custom user model still works.

Django topologically sorts the whole graph across all apps before running
anything.

---

## 3. The operations

| Category | Operations |
| --- | --- |
| Models | `CreateModel`, `DeleteModel`, `RenameModel` |
| Fields | `AddField`, `RemoveField`, `AlterField`, `RenameField` |
| Meta | `AlterModelOptions`, `AlterUniqueTogether`, `AlterIndexTogether`, `AlterModelTable`, `AlterOrderWithRespectTo` |
| Constraints/indexes | `AddIndex`, `RemoveIndex`, `AddConstraint`, `RemoveConstraint` |
| Escape hatches | `RunPython`, `RunSQL`, `SeparateDatabaseAndState` |

### `RunPython` — data migrations

```python
def init_explorer_data(apps, schema_editor):
    Project = apps.get_model("explorer", "Project")
    manifest_proj = Project.objects.filter(name="platform/manifest")
    if not manifest_proj:
        Project.objects.get_or_create(
            name="platform/manifest",
            description="Android manifest",
            date_modified="2015-11-02T05:20:08.460Z",
            defaults={
                'is_valid': True,
                'is_manifest': True,
                'has_children': True,
                'kind': 'CODE',
                'importance': 1000,
            })


class Migration(migrations.Migration):
    dependencies = [
        ('explorer', '0002_auto_20160728_0203'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('sites', '0002_alter_domain_unique')
    ]

    operations = [
        migrations.RunPython(init_explorer_data)
    ]
```

That is `explorer/migrations/0003_auto_20160824_0356.py`, and it seeds the
platform manifest project. Three rules it demonstrates:

1. **Use `apps.get_model()`, never `from explorer.models import Project`.**
   The `apps` argument is a *historical* model registry — it gives you the
   model as it was defined **at this point in the migration history**. A direct
   import gives you today's model, which may have fields this migration's
   database does not have yet. This is the single most common data-migration
   bug.

2. **Make it idempotent.** Note the `filter(...)` guard and `get_or_create`.
   Migrations get re-run against fresh databases constantly (every test run,
   every new environment).

3. **Custom `save()` and signals do not fire** on historical models. Historical
   models have fields and managers but **not** your custom methods. If your
   data migration needs domain logic, copy it into the migration.

For reversibility, supply a backward function:

```python
migrations.RunPython(forwards, backwards)
migrations.RunPython(forwards, migrations.RunPython.noop)   # explicitly a no-op
```

Without one, the migration is irreversible and `migrate <app> <earlier>` will
refuse.

### `RunSQL` — raw SQL

```python
migrations.RunSQL(
    'ALTER TABLE ... ;',                # forwards
    'ALTER TABLE ... ;',                # backwards (optional)
)
```

Use only when the ORM cannot express it. And beware: raw SQL is
backend-specific, which brings us to the most instructive migration in this
codebase.

---

## 4. The `0037` case study

`cmweb-app/explorer/migrations/0037_alter_labelcomponentmembership_groups_id.py`,
in full:

```python
# Generated by Django 3.2.5 on 2023-11-19 05:39

from django.db import migrations
from django.conf import settings

env = settings.GLOBALS.get('CM_WEB_ENVIRONMENT')


class Migration(migrations.Migration):

    dependencies = [
        ('explorer', '0036_alter_projecttreenode_id'),
    ]

    operations = []

    # 'dev' env uses SQLite database engine. But column type cannot be altered
    # in SQLite database. Other env's use PostgreSQL database engine. The
    # migration shall only apply to all env's except 'dev'.
    if env != 'dev':
        operations.append(migrations.RunSQL(
            'ALTER TABLE explorer_labelcomponentmembership_groups '
            'ALTER COLUMN id TYPE bigint;'))
```

Read this carefully, because it is doing several unusual things at once.

**What it fixes.** Django 3.2 introduced `DEFAULT_AUTO_FIELD`; CMWEB set it to
`BigAutoField`. Migrations `0018`–`0037` are the resulting `alter_..._id` sweep.
But the *implicit* M2M join table `explorer_labelcomponentmembership_groups`
has no model, so the autodetector could not generate an `AlterField` for it —
hence hand-written SQL.

**Why it is conditional.** SQLite cannot `ALTER COLUMN ... TYPE`. So the
operation is only appended when the environment is not `dev`.

**The three consequences you must know:**

1. **`GLOBALS['CM_WEB_ENVIRONMENT']` must be exactly the string `'dev'`** for a
   SQLite migrate to succeed. `'development'`, `'local'`, `'DEV'` all break with
   `near "ALTER": syntax error`. This is why `local-cmweb/config/settings_local.py`
   sets it to `'dev'` and carries a `LOCAL:` comment saying the value is not
   cosmetic.

2. **The migration reads settings at import time.** `env` is evaluated when the
   module is imported, and `operations` is built in the class body. So the
   *content of a migration* depends on the environment it is loaded in — which
   means two databases can have the same `django_migrations` row for `0037`
   and different schemas.

3. **`makemigrations --check` can disagree between environments.** A migration
   whose operations vary by settings is invisible to the autodetector's
   consistency checks.

**Would you write this today?** No. The portable form is to branch on
`schema_editor.connection.vendor` inside a `RunPython`, so the decision follows
the actual database rather than a settings string:

```python
def widen_id(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        'ALTER TABLE explorer_labelcomponentmembership_groups '
        'ALTER COLUMN id TYPE bigint;')
```

Learn the existing one because you will hit it; do not copy its shape.

---

## 5. The commands

```bash
manage.py makemigrations                    # detect changes in all apps
manage.py makemigrations explorer           # one app
manage.py makemigrations --name add_foo explorer   # name it yourself
manage.py makemigrations --empty explorer   # a blank one, for data migrations
manage.py makemigrations --check --dry-run  # CI: fail if models drifted

manage.py migrate                           # apply everything outstanding
manage.py migrate explorer                  # one app, up to its latest
manage.py migrate explorer 0035             # migrate BACKWARD to 0035
manage.py migrate explorer zero             # unapply everything in the app
manage.py migrate --fake explorer 0037      # mark applied without running
manage.py migrate --fake-initial            # for tables that already exist

manage.py showmigrations                    # what is applied, per app
manage.py sqlmigrate explorer 0037          # print the SQL, run nothing
manage.py squashmigrations explorer 0001 0037
```

`sqlmigrate` is the one to reach for first when reviewing a migration: it shows
you the actual DDL without touching anything.

`--fake` is a loaded weapon. It changes `django_migrations` without changing the
schema, so use it only when you are certain the schema already matches.

---

## 6. Autodetector limits — what it cannot see

`makemigrations` diffs your models against the recorded state. Things it gets
wrong or cannot do:

| Situation | What happens | What to do |
| --- | --- | --- |
| Renaming a field | Detected as remove + add -> **data loss** | Answer the interactive prompt `y`, or hand-edit to `RenameField` |
| Renaming a model | Same | `RenameModel` |
| Adding a non-nullable field to a populated table | Prompts for a one-off default | Better: add nullable, data-migrate, then alter to non-null (three migrations) |
| Implicit M2M join tables | Not represented as models | Hand-written `RunSQL` (see `0037`) |
| Changing `Meta.ordering` | Generates `AlterModelOptions` — **no SQL at all** | Harmless, but do not expect an index |
| Database objects Django does not manage (views, triggers, extensions) | Invisible | `RunSQL` |

### The safe way to add a non-nullable column

```
0041  AddField(..., null=True)                     # instant, no table rewrite
0042  RunPython(backfill)                          # in batches if the table is large
0043  AlterField(..., null=False)                  # now it is safe
```

On a table the size of `explorer_commit` this matters — a single-step
`AddField` with a default rewrites every row while holding a lock.

---

## 7. Multiple databases and routing

### The `DATABASES` dict

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': join(GLOBALS['PATH_ROOT'], 'cm_web_db'),
        ...
    }
}

DATABASE_ALIAS_FOR_WRITE = 'default'
```

overridden per environment; `settings_prod.py` replaces `default` with
PostgreSQL on RDS.

### `using=` — choosing a database explicitly

```python
Label.objects.using('default').all()
obj.save(using=settings.DATABASE_ALIAS_FOR_WRITE)
```

CMWEB's indexing code always names the write alias:

```python
using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE', DEFAULT_DB_ALIAS)
```

(`explorer/management/indexing.py`, `explorer/tasks.py`, `harvest/views.py`,
`rebase/views.py`.)

### Routers

A router is a class with up to four methods that Django consults for every
query:

```python
class MasterSlaveRouter(object):
    """Use 'master' for write and 'default' for read for selected apps."""

    def db_for_read(self, model, **hints):
        if model._meta.app_label in WRITE_HEAVY_APPS:
            return 'master'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label in WRITE_HEAVY_APPS:
            return 'master'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        db_list = ('default', 'master')
        if obj1._state.db in db_list and obj2._state.db in db_list:
            return True
        return None

    def allow_migrate(self, db, model):
        return True
```

Returning `None` means "no opinion, ask the next router".

**This router is currently disabled.** In `settings_prod.py`:

```python
# TODO disabled until we know what's causing pgpool-II to raise OOM
# DATABASE_ROUTERS = DATABASE_ROUTERS + ('cmweb.routers.MasterSlaveRouter',)
DATABASE_ALIAS_FOR_WRITE = 'default'
```

So the `using=` calls all resolve to `'default'` today. The pattern is kept
because re-enabling the replica must not require touching every write site.

> **Historical note on `allow_migrate`.** Its modern signature is
> `allow_migrate(self, db, app_label, model_name=None, **hints)`. This router
> still has the old two-argument form — another reason it is not currently
> wired in.

---

## 8. Transactions

```python
from django.db import transaction

with transaction.atomic():
    label.save()
    label.commits.add(*commits)
```

| Mode | Behaviour |
| --- | --- |
| Default (autocommit) | Every query commits immediately |
| `ATOMIC_REQUESTS = True` | Each HTTP request is one transaction |
| `transaction.atomic()` | Explicit block; nestable (inner ones become savepoints) |
| `transaction.on_commit(fn)` | Run `fn` only if the outer transaction commits |

Migrations are wrapped in a transaction automatically **on backends that
support transactional DDL** — PostgreSQL does, MySQL does not. Set
`atomic = False` on the `Migration` class for operations PostgreSQL refuses
inside a transaction (`CREATE INDEX CONCURRENTLY`).

`on_commit` is the correct fix for the classic bug where a task fires before
its row is visible — though in CMWEB, with eager Celery, the task runs inline
*inside* the transaction, which is its own hazard.

---

## 9. How a schema change reaches production

**The deploy does not run migrations.**

Say that again, because it is the operational fact of this chapter. The Ansible
`apache-server` role runs `make static`, freezes the manifest, installs the
vhost, and touches `wsgi.py`. There is no `manage.py migrate` anywhere in it.

Migrations are applied by a **separate Jenkins job**,
`cmweb-scripts/jobs_on_cloud/migrate_db.yaml`:

```yaml
- job-template:
    name: migrate_db
    description: |
      Migrate DB asynchronously against creating AMI
    parameters:
      - string:
          name: COMMANDS
          default:
            migrate
      - cmweb-parameter-gerrit-download-list
      - cmweb-parameter-manifest
    builders:
      - cmweb-setup-env
      - cmweb-setup-git
      - cmweb-mount-efs
      - cmweb-prepare-site
      - cmweb-generate-settings
      - cmweb-run-commands
```

Note the description: *"asynchronously against creating AMI"*. The web tier is
baked as an AMI; the database is migrated on a separate track.

### Shipping a schema change is therefore two operations

1. Merge the model change **and** its migration file.
2. Run the `migrate_db` Jenkins job.

And they can happen in either order, which means **your migration must be
compatible with both the old and the new application code**, at least
transiently:

| Change | Safe order |
| --- | --- |
| Adding a nullable column | Migrate first, then deploy |
| Adding a non-nullable column | Migrate (nullable) -> deploy -> migrate (non-null) |
| Removing a column | Deploy code that stops using it -> then migrate |
| Renaming | Never in one step. Add new -> backfill -> switch code -> drop old |

The rule: **additive changes go before the deploy, destructive changes go
after.**

### Locally, it is one command

```bash
make db          # == manage.py migrate
```

That target exists for development only. Do not assume it runs anywhere else.

---

## 10. Migrations in tests

`make test` passes `--keepdb`, which reuses the test database between runs
instead of recreating it. Fast, but it means:

- A **new migration is not picked up** by a `--keepdb` run until you drop the
  test database.
- If a test fails only on CI, a stale local test database is a prime suspect.

Drop it and re-run to check.

---

## 11. Try it

```powershell
cd local-cmweb
```

**A. See the applied history:**

```powershell
.venv\Scripts\python.exe manage.py showmigrations explorer
```

**B. Read the SQL of the interesting migration on both backends:**

```powershell
.venv\Scripts\python.exe manage.py sqlmigrate explorer 0037
```

On SQLite (`CM_WEB_ENVIRONMENT == 'dev'`) this prints nothing, because
`operations` is empty. That *is* the lesson.

**C. Prove the conditional.** Open
`cmweb-app/explorer/migrations/0037_alter_labelcomponentmembership_groups_id.py`
and confirm the `if env != 'dev':` guard sits in the class body. Then check
`local-cmweb/config/settings_local.py` for the matching `CM_WEB_ENVIRONMENT`
value.

**D. Check for model drift:**

```powershell
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Exit code 0 means models and migrations agree. This is the command CI should
run.

**E. Inspect the bookkeeping table:**

```powershell
.venv\Scripts\python.exe manage.py shell
```

```python
from django.db import connection
with connection.cursor() as c:
    c.execute("SELECT app, name FROM django_migrations "
              "WHERE app='explorer' ORDER BY id DESC LIMIT 5")
    print(c.fetchall())
```

**F. Look at the graph:**

```python
from django.db.migrations.loader import MigrationLoader
from django.db import connection
loader = MigrationLoader(connection)
loader.graph.node_map[('explorer', '0002_auto_20160728_0203')].parents
```

**G. Write a data migration** in a scratch app: `makemigrations --empty`, add a
`RunPython` that uses `apps.get_model()`, give it a reverse function, and run
`sqlmigrate` to see that it produces no DDL.

---

## 12. Check yourself

1. What table records applied migrations, and what are its columns?
2. Why are `dependencies` a graph rather than a linear chain? Give a case where
   a cross-app dependency is mandatory.
3. In a `RunPython` function, why must you use `apps.get_model()` and not a
   normal import?
4. Do custom `save()` methods and `post_save` signals run during a data
   migration? What follows from the answer?
5. Migration `0037` builds its `operations` list conditionally. Name three
   consequences.
6. What exact error do you get if `CM_WEB_ENVIRONMENT` is `'development'`
   instead of `'dev'`, and why?
7. How would you write `0037` portably today?
8. Give the three-migration recipe for adding a non-nullable column to a large,
   populated table.
9. What does `--fake` do, and when is it appropriate?
10. `DATABASE_ROUTERS` is `()` in production. Why does the indexing code still
    write with `using=`?
11. Deploying and migrating are separate operations in CMWEB. What is the safe
    ordering for an additive change? For a destructive one?
12. `make test` uses `--keepdb`. What can that hide?
