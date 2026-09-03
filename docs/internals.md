# Internals — start here

Eight deep-dive guides on the subsystems you touch most when changing CMWEB.
Each one teaches the underlying Django (or Ansible) concept first, then shows how
CMWEB uses it, then lists the gotchas. **No prior Django knowledge assumed.**

| # | Guide | Covers |
| --- | --- | --- |
| 1 | [Django apps](01-django-apps.md) | Projects vs. apps, `INSTALLED_APPS`, the 24 CMWEB apps, adding one |
| 2 | [Management commands](02-management-commands.md) | `manage.py` subcommands, the 61 CMWEB defines, `Parameter` config |
| 3 | [Views, URLs, templates](03-views.md) | Class-based views, the mixin system, URL structure, the inlines system |
| 4 | [Middleware](04-middleware.md) | The request/response stack, the site-wide permission gate, PJAX versioning |
| 5 | [Celery and tasks](05-celery-tasks.md) | Task queues, the nine CMWEB tasks, the job-polling pipeline, signals |
| 6 | [Migrations](06-migrations.md) | Schema versioning, the 103 CMWEB migrations, the ones that bite |
| 7 | [Apache deployment](07-apache-deployment.md) | WSGI, mod_wsgi, the vhost, the settings chain, reload vs restart |
| 8 | [Ansible](08-ansible.md) | Config management, the 11 roles, vault, the rest of `cmweb-scripts` |

## Suggested reading order

**If you are new to Django**, read 1 → 3 → 6 → 4 first. That is the core loop:
what an app is, how a page is produced, how the database evolves, and what
happens around every request. Those four make the codebase navigable.

Then 2 and 5, which are about work happening *outside* a web request — the
indexing commands and the background tasks. Most of what CMWEB actually does at
runtime lives there.

Leave 7 and 8 until you need to deploy or debug the servers. They are reference
rather than reading.

## The ten things that surprise people

Collected from all eight, in rough order of how likely they are to cost you an
afternoon:

1. **`cmweb-app` must sit at `cmweb-project/apps/`.** Settings appends that
   directory to `sys.path`; apps import by bare name. → [1](01-django-apps.md)

2. **Several apps put real logic in `__init__.py`** and it runs at import time.
   `explorer/__init__.py` is the XML-RPC manifest server; `vendorsync/__init__.py`
   is ~400 lines of signal handlers. → [1](01-django-apps.md#part-d--the-__init__py-trap)

3. **`migrate` needs `--skip-checks` on an empty database.** System checks import
   the URLconf, which reaches views that query `Parameter` at class-body scope.
   → [6](06-migrations.md#why---skip-checks)

4. **One migration reads settings and changes behaviour.** `explorer/0037` runs
   PostgreSQL-only DDL unless `CM_WEB_ENVIRONMENT == 'dev'` exactly.
   → [6](06-migrations.md#the-migration-that-will-bite-you)

5. **Mixin order is behaviour.** `BranchNameDecoderMixin` must sit above
   `UrlKwargsMixin` or branch names reach templates still slash-encoded.
   → [3](03-views.md#branchnamedecodermixin--the-slash-problem)

6. **A public endpoint needs three edits** — URLconf, `NO_AUTH_URLS`, and an
   Apache `Require all granted` block. → [4](04-middleware.md#adding-a-public-endpoint)

7. **`PermissionCheckMiddleware` trusts the HTTP Basic username without checking
   the password.** Safe only because Apache authenticated first.
   → [4](04-middleware.md#the-logic)

8. **Saving a `Label` can make network calls.** `save()` → Celery task → signal
   → vendorsync handlers → Gerrit REST. → [5](05-celery-tasks.md#part-g--signals-and-why-saving-a-label-is-expensive)

9. **`CELERY_TASK_ALWAYS_EAGER = True` in dev** means tasks run inline and
   synchronously. Production behaviour differs. → [5](05-celery-tasks.md#the-setting-that-changes-everything-in-dev)

10. **Production caches pages for ten minutes** and unhandled exceptions render a
    Paste traceback, not Django's 500. → [7](07-apache-deployment.md)

## Two defects found while writing these

Neither is urgent; both are worth knowing before they confuse someone.

- The Ansible **`Restart WSGI` handler** has `changed_when: result.rc == 0` but
  never registers `result` — it reads whatever was last registered by another
  task. Its reported status is meaningless.
  → [7](07-apache-deployment.md#part-e--reload-vs-restart)
- **Infrastructure endpoints are duplicated** between
  `ansible/group_vars/<env>` and `jobs_on_cloud/macros.yaml`, with nothing
  enforcing agreement. → [8](08-ansible.md#part-e--environment-configuration)

## Related documents

- [how-the-site-works.md](how-the-site-works.md) — end to end: one request from browser to PostgreSQL, and how the server gets built
- [architecture.md](architecture.md) — the domain model and indexing pipeline
- [development.md](development.md) — setup, build, test, lint, review flow
- [infrastructure.md](infrastructure.md) — AWS topology and the Jenkins jobs
- [../local-cmweb/README.md](../local-cmweb/README.md) — running it on your machine
