# 6. Database migrations

*How Django versions your database schema, and CMWEB's 103 migrations.*

---

## Part A — The Django concept

### The problem

Your models are Python classes; your database has tables. When you add a field
to a model, the table must gain a column. Doing that by hand across dev, test,
stage and production does not scale.

**Migrations** are Python files describing schema changes, applied in order and
recorded in the database so each runs exactly once.

### The two commands

```bash
./manage.py makemigrations myapp    # compare models to migrations, write a new file
./manage.py migrate                 # apply pending migrations to the database
```

`makemigrations` does **not** touch the database — it only writes a file, which
you review and commit. `migrate` executes them.

### What a migration looks like

A real CMWEB one (`aod/migrations/0002_auto_20180710_0838.py`):

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('aod', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='system',
            options={'ordering': ('-id',), 'verbose_name_plural': 'systems'},
        ),
    ]
```

Two attributes matter:

- **`dependencies`** — which migrations must run first. This forms a graph, not
  a simple sequence; Django works out a valid order across all apps.
- **`operations`** — the changes: `CreateModel`, `AddField`, `AlterField`,
  `RemoveField`, `RunPython`, `RunSQL`.

### How Django tracks what has run

A table called `django_migrations` records every applied `(app, name)` pair. On
`migrate`, Django compares the graph to that table and applies the difference.

**Never edit an applied migration.** Its filename is already recorded, so edits
are silently ignored on machines that ran it, and the schemas diverge. Write a
new migration instead.

### Useful subcommands

```bash
./manage.py showmigrations             # what has and has not run
./manage.py showmigrations explorer
./manage.py sqlmigrate explorer 0037   # print the SQL without running it
./manage.py migrate explorer 0036      # roll BACK to 0036 (if reversible)
./manage.py makemigrations --check --dry-run   # CI: fail if models drifted
```

### Data migrations

Schema changes move columns; **data** migrations move values. Use `RunPython`:

```python
def copy_uuid(apps, schema_editor):
    """Copy the old uuid onto the new field."""
    SystemFamily = apps.get_model('aod', 'SystemFamily')
    for sf in SystemFamily.objects.all():
        sf.uuid = sf.old_uuid
        sf.save()


class Migration(migrations.Migration):
    operations = [
        migrations.AddField(...),
        migrations.RunPython(copy_uuid),
    ]
```

> **The critical rule**: take models from the `apps` argument, **never** import
> them. `apps.get_model()` inside a migration returns a *historical* version of
> the model — as it existed at that point in the migration graph. A direct
> import gives you today's model, which may have fields that did not exist yet,
> and the migration breaks when replayed on a fresh database.

---

## Part B — CMWEB's migrations

### Inventory

103 migrations across 17 apps:

| App | Count | | App | Count |
| --- | --- | --- | --- | --- |
| `explorer` | 39 | | `rebase` | 3 |
| `request` | 19 | | `historian` | 2 |
| `harvest` | 8 | | `cmjenkins` | 2 |
| `users` | 7 | | `blog`, `base`, `backend` | 1 each |
| `issues` | 7 | | `packages`, `dashboards` | 1 each |
| `vendorsync`, `aod` | 4 each | | `type_approval`, `product_packages` | 1 each |

They were generated across Django 1.9 → 3.2, so style varies — older ones carry
`# -*- coding: utf-8 -*-` and `from __future__ import unicode_literals`.

**`explorer` 0018–0037 are a mechanical sweep**: twenty migrations converting
primary keys to `BigAutoField`, generated when `DEFAULT_AUTO_FIELD` was set.
Nothing interesting in them individually.

### The migration that will bite you

`explorer/migrations/0037_alter_labelcomponentmembership_groups_id.py`:

```python
from django.db import migrations
from django.conf import settings

env = settings.GLOBALS.get('CM_WEB_ENVIRONMENT')


class Migration(migrations.Migration):

    dependencies = [
        ('explorer', '0036_alter_projecttreenode_id'),
    ]

    operations = []

    # 'dev' env uses SQLite database engine. But column type cannot be altered
    # in SQLite database. Other env's use PostgreSQL. The migration shall only
    # apply to all env's except 'dev'.
    if env != 'dev':
        operations.append(migrations.RunSQL(
            'ALTER TABLE explorer_labelcomponentmembership_groups '
            'ALTER COLUMN id TYPE bigint;'))
```

Two unusual things here, and both matter:

1. **Raw PostgreSQL DDL** (`RunSQL`), because the automatic `AlterField` could
   not do it for this implicit many-to-many join table.
2. **The migration reads settings at import time and changes what it does.**

Consequences:

- On SQLite with `CM_WEB_ENVIRONMENT` set to anything other than exactly
  `'dev'`, `migrate` fails with `near "ALTER": syntax error`. This is why
  `local-cmweb` sets `GLOBALS['CM_WEB_ENVIRONMENT'] = 'dev'` despite being a
  "local" environment — the value is functional, not cosmetic.
- The migration graph is not identical across environments, so `sqlmigrate`
  output differs by environment. Do not assume what you see locally is what
  production ran.

This is a pattern to **avoid** in new migrations. Prefer `schema_editor` checks:

```python
def forwards(apps, schema_editor):
    """Only do this on PostgreSQL."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    ...
```

That keys off the actual database, not a settings value someone might change.

### Data migrations in the tree

Five use `RunPython`: `aod` 0001 and 0004, `explorer` 0003, `users` 0002,
`vendorsync` 0002. All follow the correct pattern of taking models from `apps`.
**No migration in the tree imports application code at module level**, which is
what keeps them replayable — worth preserving.

### Squashing

Django can compress a long migration chain into one file
(`makemigrations --squash`). CMWEB has done it exactly once:

```
dashboards/migrations/0001_squashed_0005_auto_20180710_0838.py
```

> **A caveat worth knowing.** A proper squash carries a `replaces = [...]` list
> naming the migrations it supersedes, so Django can recognise databases that
> already applied the originals. **This file has no `replaces` list** — the
> originals were deleted outright. A database that predates the squash cannot be
> migrated forward cleanly against this tree.
>
> In practice everything has long since been migrated past it. But if you squash
> anything else, keep the `replaces` list.

### Lint exemption

Migrations are excluded from **every** quality gate — the `Makefile` filters
`/migrations/[^/]*\.py` out of pyflakes and pydocstyle, and pycodestyle excludes
the directory. Generated migrations need no docstrings and are not held to 80
columns. Do not add docstrings to generated files just to be tidy; the diff
noise is not worth it.

---

## Part C — Working with them

### Adding a field

```bash
cd cmweb-project
# 1. edit the model in apps/myapp/models.py
../ENV/bin/python3 manage.py makemigrations myapp
# 2. read the generated file before committing
../ENV/bin/python3 manage.py migrate --skip-checks
```

### Why `--skip-checks`

Django runs system checks before most commands. The checks import the root
URLconf → which imports views → and some views evaluate `Parameter` lookups at
class-body scope:

```python
class ReleaseList(...):
    paginate_by = Parameter.get_int(RELEASES_PAGINATE_BY_KEY, 25)
```

That is a database query at import time. On a database with no tables yet it
fails:

```
django.db.utils.OperationalError: no such table: django_site
```

`--skip-checks` bypasses the checks so `migrate` can create the tables. Once the
schema exists, it is no longer needed. See
[03-views.md](03-views.md#database-queries-at-import-time).

### Reviewing before committing

Read the generated file. `makemigrations` occasionally guesses wrong —
especially it may see a rename as a drop plus an add, which **destroys data**.
If you renamed a field, check the file uses `RenameField`, not
`RemoveField` + `AddField`.

Preview the SQL:

```bash
../ENV/bin/python3 manage.py sqlmigrate myapp 0002
```

### Deploying migrations

In production, migrations do **not** run as part of the Ansible deploy — the
`cmweb-node` role only runs `make static`. They run through a dedicated
**`migrate_db` Jenkins job**.

That separation is deliberate: schema changes are usually the risky part of a
release, and running them independently means you choose the moment.

Practical implication: a deploy adding a model needs *two* actions — the code
deploy and the `migrate_db` run — and the app will error between them.

---

## Part D — Common problems

| Symptom | Cause |
| --- | --- |
| `no such table: django_site` on `migrate` | Missing `--skip-checks` |
| `near "ALTER": syntax error` | `CM_WEB_ENVIRONMENT` is not `'dev'` on SQLite |
| `InconsistentMigrationHistory` | A migration was applied whose dependency was not; usually a rebase that reordered files |
| Conflicting migrations (`0005_a` and `0005_b`) | Two branches both added one. Fix with `./manage.py makemigrations --merge` |
| Your model change produces no migration | The app is not in `INSTALLED_APPS` |
| Migration works locally, fails in prod | Something SQLite tolerates and PostgreSQL does not — check `sqlmigrate` against both |

### Resetting locally

With `local-cmweb`, the fastest fix for a wedged database:

```powershell
.\setup.ps1 -Fresh
```

which deletes the SQLite file and rebuilds from scratch — migrate, load the
21,929-row fixture, post-setup. About three minutes.

---

## Checklist

```
[ ] model edited, makemigrations run
[ ] generated file READ — renames use RenameField, not remove+add
[ ] RunPython uses apps.get_model(), never a direct import
[ ] no settings-dependent branching (use schema_editor.connection.vendor)
[ ] reversible if practical
[ ] sqlmigrate checked for anything non-trivial
[ ] committed together with the model change, never separately
[ ] migrate_db Jenkins job planned as part of the release
```

**Next:** [07-apache-deployment.md](07-apache-deployment.md)
