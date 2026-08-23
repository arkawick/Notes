# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CMWEB is Sony's internal Configuration Management web app (`https://cmweb.ptc.sony.co.jp/`). It indexes
Android platform build metadata out of Gerrit, git and repo manifests — repositories, manifest branches,
builds ("labels"), commits, JIRA issues — and layers workflow automation (branch/repo requests,
cherry-picking, rebasing, vendor release sync) on top.

Fuller documentation lives in `README.md` and `docs/` — [architecture](docs/architecture.md),
[development](docs/development.md), [infrastructure](docs/infrastructure.md). This file is the
short form.

## Repository layout

This working directory holds three separate `repo` projects that are assembled into one site:

- `cmweb-project/` — the Django project: settings, root URLconf, WSGI, Celery, site-wide templates, static assets, Makefile
- `cmweb-app/` — all Django apps (the bulk of the code)
- `cmweb-scripts/` — Ansible, CloudFormation, Packer, git-mirroring scripts, and ~50 Jenkins Job Builder YAMLs

**`cmweb-app` must be checked out or symlinked at `cmweb-project/apps/`.** `settings.py` does
`sys.path.append(<project>/apps)` and reads `apps/.git` for the version string; `apps/` is in
`cmweb-project/.gitignore`. Nothing imports without this. Paths derived in settings assume the parent of
`cmweb-project` holds `repository/` (bare git mirrors), `cache/`, `var/log/` and the dev sqlite DB.

## Commands

All make targets run from `cmweb-project/` and drive a virtualenv at `../ENV` (override with
`VIRTUALENV_DIR=`). They are Linux-only (`apt-get`, `lsb_release`).

```bash
make install                       # apt packages + pip from etc/requirements-<20|22>.txt
make install NO_APT_INSTALL=1      # CI/Jenkins variant, skips sudo apt-get
make db                            # manage.py migrate
make static                        # collectstatic + django-compressor (COMPRESS_OFFLINE=True)
make test                          # full suite over TESTED_APPS, --keepdb, XML output to ../test-results
make kwalitee                      # pyflakes + pycodestyle + pydocstyle
make index-testdata / testdata     # regenerate apps/explorer/fixtures/testdata.json
make install-testdata              # loaddata that fixture (works best on a fresh DB)
```

Running one app / class / test (the Makefile's `test` target just wraps `manage.py test`):

```bash
../ENV/bin/python3 manage.py test explorer --keepdb -v2
../ENV/bin/python3 manage.py test explorer.tests.test_label.LabelTestCase --keepdb
../ENV/bin/python3 manage.py test explorer.tests.test_label.LabelTestCase.test_name --keepdb
```

`manage.py` defaults to `DJANGO_SETTINGS_MODULE=cmweb.settings`. Deployed environments use
`cmweb.settings_prod` / `settings_stage` / `settings_test`, and `cmweb.settings_deployed` (generated,
gitignored) is what Celery expects.

**`cmweb/secure.py` is mandatory even though the import is in a `try/except`.** It supplies
`OPENSEARCH_HOST`, `OPENSEARCH_AUTH_*`, DB and cache host names that are referenced unguarded later in
`settings.py`; without it, settings fails with `NameError` rather than a readable message. Copy
`cmweb/dev_template.py` for a local settings override.

Lint rules that CI enforces: 80-column pycodestyle, and **pydocstyle over every non-migration file** —
every module, class and method needs a docstring, which is why trivial getters throughout the codebase
carry `"""Return ..."""` lines. Migrations, `secure.py`, `settings*.py`, `dev_template.py`, `celery.py`
are excluded from pyflakes/pydocstyle.

## Architecture

### Domain chain (`explorer/models.py` — 2700 lines, the heart)

`Project` (a Gerrit repo; `git_path()` points at a bare mirror under `PATH_REPOSITORY`, read with
dulwich) → `Branch` / `ManifestBranch` (multi-table inheritance; manifest branches carry review-label
config, a `parent` branch, the AOD `System`, and `latest_label` / `latest_build` pointers) → `Label` (one
build: M2M to `Commit`, `ManifestComponent`, `Product`, plus `sublabels` through `LabelMembership` and a
`previous` link that defines deltas) → `Commit` (sha1 plus author/committer/submitter/approvers/verifiers
parsed out of Gerrit's `refs/notes/review`, linked to `Issue`s, reverts and cherry-picks).

Two patterns to respect when touching `Label`:

- **Denormalized counters** (`components_count`, `commits_count`, `all_commits_count`, …) exist purely for
  templates and are recomputed by indexing, not by signals.
- **Indexing status flags** (`components_incomplete`, `commits_incomplete`, `sublabels_incomplete`,
  `incomplete`) drive whether a label gets re-indexed and whether the UI shows it as partial.

`IncludedBranchRule` / `ExcludedBranchRule` regexes decide which branches are indexed at all — with no
inclusion rule for a manifest project, nothing is picked up. This is the usual reason a new branch never
appears.

### Indexing pipeline

`explorer/management/indexing.py` (plus `historian/` and `packages/` equivalents) is the shared engine;
the `index_*` / `sync_*` management commands are thin wrappers. It uses `apps.get_model()` for every model
rather than direct imports to avoid circular-import problems — follow that in new indexing code. Writes go
to `settings.DATABASE_ALIAS_FOR_WRITE` (`using=`), not the default alias, because production once fronted
a read replica (`cmweb/routers.py::MasterSlaveRouter`, currently disabled).

In production these commands are **not** cron jobs but Jenkins jobs defined in
`cmweb-scripts/jobs_on_cloud/*.yaml` (e.g. `index_labels` runs hourly 08–20). Adding a scheduled indexing
command means adding a YAML there; `make update` on the `deploy_jenkins_jobs` job pushes them.

### Runtime configuration

Site behaviour is tuned at runtime through `base.models.Parameter` (a cached key/value table editable in
the admin), not settings — pagination sizes, sync intervals, Gerrit service credentials
(`gerrit-serviceusername` / `gerrit-servicepassword`), LDAP service account. `base.cache.cache` wraps
Django's cache with logging and a long default timeout. `base.models.Property` is a generic key/value
attached to any object, used by `PropertyCacheMixin` to memoize id lists.

### Access control

`cmweb.middleware.PermissionCheckMiddleware` gates the whole site on the `users.view_all_pages`
permission, redirecting everyone else to the branch-request list. Anonymous access is only possible for
paths matching `NO_AUTH_URLS` (RSS/XML feeds, `rpc/`, `api/` but not `api/a/`, `register`,
`access-denied`) or under `EXEMPT_URLS` (`accounts/`, `request/`). Authentication is LDAP
(`users.auth.AuthLDAPBackend`) plus Kerberos `RemoteUserMiddleware`. A new public endpoint needs a
middleware entry, not just a URL.

### Views and URLs

Class-based views composed from mixins in `base/views/mixins.py` and `explorer/views/mixins.py`:

- `FormatMixin` — a trailing `/json`, `/xml`, `/csv`, `/txt` URL segment (or `?format=`) selects both the
  content type and a template suffix, so one view serves HTML and data. Most explorer URLs end with an
  optional `(?P<format>json|html)` group.
- `ManifestMixin` — the `manifest` URL kwarg defaults to `settings.GLOBALS['PLATFORM_MANIFEST']`; most
  explorer URLs are addressable both with and without an explicit manifest prefix.
- `BranchNameDecoderMixin` — branch names contain slashes, so URLs encode them as `\`
  (`base.constants.URL_SLASH_ENCODE_CHAR`) and this mixin decodes during `dispatch`. Must sit above
  `UrlKwargsMixin` in the MRO.
- `AjaxableResponseMixin` / `PaginateMixin` / `GenericObjectMixin` for AJAX forms, non-ListView
  pagination, and `<app>/<model>/<pk>` generic editing.

URLconfs are built from shared regex fragments in `explorer/urls/__init__.py` (`BRANCH`, `MANIFEST`,
`LABEL_PREFIX`, `LABEL_SECTION`, `COMMIT_FILTER`, …); label sub-pages are `+`-prefixed segments
(`/+commits`, `/+allcommits`, `/+issues`, `/+repositories`, `/+browse`). The front end is Bootstrap 3 with
PJAX — `PjaxVersionMiddleware` stamps `X-PJAX-Version` from the app version plus the compressed-asset
hash, so stale clients force a full reload.

### Workflow apps

`request` uses `django-fsm`: `Request` is abstract with three parallel FSM fields (`state`, `arch_state`,
`swp_state`) and `ConcurrentTransitionMixin` for optimistic locking. `BranchRequest` / `RepositoryRequest`
call Gerrit's REST API on completion to actually create the branch or repo (`gerritproxy/restapi.py`,
retried via `somc_decorators.retry` on 401/502). `harvest` (cherry-pick policies) and `rebase` (rebase
policies) subclass `schedule.models.BranchPeriod`, as does `issues.TagPeriod` and `type_approval.TAPeriod`.

### Async and search

Celery (`cmweb/celery.py`, SQS broker, `django_celery_results` backend) with `@shared_task` modules per
app; `CELERY_TASK_ALWAYS_EAGER = True` in base settings so dev runs inline. `backend.tasks.json_result`
serializes Django objects out of tasks, and `backend.UserTaskRequest` tracks user-initiated jobs. Search is
OpenSearch via `django-opensearch-dsl` `documents.py` files, with `OPENSEARCH_DSL_AUTOSYNC = False` — the
index is refreshed by the `update_search_index` Jenkins job through
`search.search_signals.CustomSignalProcessor`, not on save.
