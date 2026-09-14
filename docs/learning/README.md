# CMWEB / Django learning track

A self-study course that teaches Django's **MVT** pattern and then immediately
shows the same idea in **CMWEB's own source code**. Every chapter follows the
same shape:

1. **The concept** — what Django actually does, in plain terms.
2. **The mechanism** — the classes and files inside Django that implement it.
3. **In CMWEB** — real file paths and real code from `cmweb-app/`,
   `cmweb-project/` and `cmweb-scripts/`, quoted, not invented.
4. **Try it** — something to run against the local instance in `local-cmweb/`.
5. **Check yourself** — questions you should be able to answer before moving on.

Nothing here is a generic Django tutorial that happens to mention CMWEB. The
examples are the code that runs in production.

---

## Chapters

| # | Chapter | Covers |
| --- | --- | --- |
| 01 | [The MVT design pattern](01-mvt-pattern.md) | MVC vs MVT, where the controller went, the full request lifecycle, fat-model/thin-view rules |
| 02 | [Django project layout](02-django-project-layout.md) | `startproject` vs `startapp`, the standard layout, building one from scratch, how and why CMWEB deviates |
| 03 | [Models and the ORM](03-models-and-orm.md) | Fields, relations, `Meta`, managers, querysets, multi-table inheritance, denormalised counters, signals |
| 04 | [Views and request/response](04-views-and-request-response.md) | `HttpRequest`/`HttpResponse`, FBV vs CBV, generic views, the mixin/MRO game, URL routing |
| 05 | [Templates: DTL and Jinja2](05-templates-dtl-and-jinja.md) | Template inheritance, context processors, custom tags/filters, DTL vs Jinja2 side by side, where each is used here |
| 06 | [Settings and management commands](06-settings-and-management-commands.md) | Settings layering, `DJANGO_SETTINGS_MODULE`, `BaseCommand`, `add_arguments`, runtime config via `Parameter` |
| 07 | [Migrations and the database](07-migrations-and-database.md) | The migration graph, autodetector, `RunPython`/`RunSQL`, multi-DB, transactions, the deploy split |
| 08 | [Ansible templates and Apache config](08-ansible-and-apache.md) | Apache + mod_wsgi, the vhost, Jinja2 in Ansible, roles/handlers/vars, the whole deploy path |
| 09 | [CMWEB vs textbook MVT](09-cmweb-vs-mvt.md) | Side-by-side comparison, one URL traced end to end, where CMWEB bends the pattern and why |

---

## How this maps to the topic list

| Assigned topic | Chapter |
| --- | --- |
| MVT design pattern and its implementation in Django | **01** |
| CMWEB structure w.r.t. Django; setting up a project with the standard layout | **02** |
| Basic tools — Ansible templates, Apache configuration | **08** |
| Django models and their role in database interactions | **03** |
| Views and request/response handling | **04** |
| Templates and frontend rendering; Jinja templates and DTL | **05** |
| Management commands and settings | **06** |
| Migrations and database integration | **07** |
| Comparing MVT with existing CMWEB applications | **09** (and the "In CMWEB" section of every chapter) |

---

## Suggested order

Read **01** and **02** first — they are the frame everything else hangs on.
Then **03 → 04 → 05** is the MVT triangle in dependency order (data, then
logic, then presentation). **06** and **07** are the operational layer. **08**
is a different discipline (infrastructure, not Django) and can be read at any
point. **09** is the wrap-up and only makes sense last.

```
        01 MVT                        08 Ansible / Apache
           │                                  (standalone)
           ▼
        02 Layout
           │
   ┌───────┼───────┐
   ▼       ▼       ▼
 03 M    04 V    05 T
   └───────┼───────┘
           ▼
   06 Settings/commands
           │
           ▼
   07 Migrations/DB
           │
           ▼
     09 Comparison
```

---

## Prerequisites

Python 3, and a working local instance. From `local-cmweb/`:

```powershell
.\setup.ps1     # virtualenv, migrate, load the sample fixture
.\run.ps1       # http://127.0.0.1:8000/
```

The "Try it" sections assume `local-cmweb\.venv\Scripts\python.exe manage.py`
works from inside `local-cmweb/`. See
[local-cmweb/README.md](../../local-cmweb/README.md) for the limits — indexing,
search, Gerrit workflow and git-backed pages need infrastructure that is not
present locally.

## How this differs from `docs/01-*` … `docs/08-*`

There is deliberate overlap, and the two sets are for different moments:

| | **This track** (`docs/learning/`) | **The deep dives** (`docs/01-…08-*.md`) |
| --- | --- | --- |
| Shape | A course — concept, then mechanism, then CMWEB, then exercises | Reference — what CMWEB does and where |
| Ordered? | Yes, read 01 → 09 | No, dip in as needed |
| Assumes | No Django knowledge | Some orientation in the codebase |
| Answers | "How does Django work, and how did *they* use it?" | "Where is X and what will bite me?" |
| Has exercises | Yes, against `local-cmweb/` | No |

Use this track while learning the framework. Use the deep dives once you are
working in the code and need to look something up.

## Related documents

- [docs/operations/](../operations/README.md) — the operational reference: commands, indexing, Jenkins jobs, Ansible, Apache
- [docs/how-the-site-works.md](../how-the-site-works.md) — one request end to end
- [docs/architecture.md](../architecture.md) — the domain model and app catalogue
- [docs/internals.md](../internals.md) — index to the eight deep-dive guides
- [docs/infrastructure.md](../infrastructure.md) — AWS, Ansible, Jenkins
- [docs/development.md](../development.md) — local setup, build/test/lint, review flow
