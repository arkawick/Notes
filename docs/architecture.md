# Architecture

This document covers the Django application — `cmweb-project` (configuration) plus `cmweb-app` (all the
code). For the servers it runs on, see [infrastructure.md](infrastructure.md).

## The two halves

`cmweb-project` contains no models or views. It holds:

| Path | Purpose |
| --- | --- |
| `cmweb/settings.py` | Base settings, and the `GLOBALS` dict of CMWEB-specific configuration |
| `cmweb/settings_{prod,stage,test}.py` | Per-environment overrides; `settings_deployed.py` is a symlink to one of them |
| `cmweb/secure.py` | Credentials and host names. Generated at deploy time, never committed |
| `cmweb/urls.py` | Root URLconf **and** the site navigation tree (`sitetree` dynamic trees) |
| `cmweb/middleware.py` | PJAX versioning and the site-wide permission gate |
| `cmweb/celery.py` | Celery application |
| `cmweb/routers.py` | Read/write database router (currently disabled in production) |
| `templates/`, `static/` | Base templates and all vendored front-end assets |
| `Makefile` | The build, test and lint entry points |

`cmweb-app` holds every Django app. `settings.py` puts it on the path:

```python
APPS_DIR = join(GLOBALS['PATH_SITE'], 'apps')   # <cmweb-project>/apps
sys.path.append(APPS_DIR)
```

so apps are imported by bare name (`from explorer.models import Label`), not as `apps.explorer`.

### `GLOBALS`

CMWEB-specific settings live in a `GLOBALS` dict rather than as module-level names — filesystem paths,
Gerrit/JIRA/LDAP server names, and the Gerrit project names of every manifest CMWEB knows about
(`PLATFORM_MANIFEST`, `AMSS_MANIFEST`, `SYSTEM_MANIFEST`, `QSSI_MANIFEST`, …). `explorer/constants.py`
reads these into `LABEL_COMPONENT_MAP`, which is what lets a "system" build know that its Android
sub-build comes from `platform/manifest` and its modem sub-build from `platform/amssmanifest`.
`GLOBALS` is exposed to every template through `cmweb.context_processors.settings`.

## Domain model

Everything centres on the `explorer` app (`explorer/models.py`, ~2700 lines).

```
Project ──< Branch ─── ManifestBranch ──< Label ──< Commit
(a Gerrit         (a git branch;          (a build)      (a git commit)
 repository)       manifest branches
                   carry build config)
```

### `Project`

A Gerrit project, i.e. one git repository. `git_path()` resolves to a **bare mirror** under
`GLOBALS['PATH_REPOSITORY']`, which CMWEB reads directly with dulwich rather than talking to Gerrit —
the mirror is maintained by a separate Jenkins job. `is_manifest` marks projects whose branches are
manifest branches. `sync_branches()` walks `refs/heads/` and creates `Branch`/`ManifestBranch` rows.

### `ManifestBranch`

Multi-table inheritance on `Branch`. Adds the review configuration used to judge commits
(`review_label`, `review_score_pass`, `review_score_fail`), a `parent` branch for branch-point
detection, the AOD `System`/`SystemFamily` the branch belongs to, cached counters, and
`latest_label` / `latest_build` pointers used all over the UI.

### `Label` — a build

Despite the name, a `Label` is one build of one manifest branch. It is the join point of the whole
schema:

- `commits`, `all_commits` (through `CommitDelivery`), `components` (through
  `LabelComponentMembership`), `products` (through `LabelProduct`)
- `sublabels` — a self-referential M2M through `LabelMembership`. A "system" build aggregates an
  Android build, a modem build and so on; this is how they are attached
- `previous` — the preceding build, which defines what "the changes in this build" means. Delta builds
  (`status='DELTA'`, named `delta/<target>/<source>`) are synthetic `Label` rows created on demand with
  `is_previous_manually_set`

Two field groups exist purely for machinery and should be treated as derived state:

- **Counters** (`commits_count`, `all_commits_count`, `components_count`, `issues_count`, …) are
  denormalised for templates and recomputed by indexing, not by signals.
- **Completion flags** (`components_incomplete`, `commits_incomplete`, `sublabels_incomplete`,
  `decoupled_incomplete`, `incomplete`) drive re-indexing and tell the UI a build is only partly
  processed. `find_incomplete_labels` reports on them nightly.

### `Commit`

A git commit, enriched from Gerrit. Author, committer, submitter, approvers and verifiers are parsed
out of `refs/notes/review` — the notes ref that `repo sync` does *not* fetch by default, which is why
the mirror job fetches it explicitly. Commits link to `Issue`s (parsed from commit messages, both
legacy CR numbers and JIRA keys), to the commits they revert, and to the commits they cherry-pick.

### `ManifestComponent` and `LabelComponentMembership`

A `ManifestComponent` is "project X checked out at path P, revision R" — one `<project>` element of a
repo manifest. `LabelComponentMembership` joins it to a `Label` and carries a `status` field
enumerating everything that can go wrong while diffing two revisions (`no-git-repository`,
`git-missing-revision`, `ok-revision-rewound`, `git-walker-error`, …). When a build's repository list
looks wrong, that status field is where to look first.

## Indexing

Nothing in CMWEB is entered by hand. The database is built by indexing commands, and the shared engine
is `explorer/management/indexing.py` (with parallel engines in `historian/` and `packages/`). The
management commands under `explorer/management/commands/` are thin wrappers around it:

| Command | Job |
| --- | --- |
| `index_labels` | Import builds from C2D (the build system) |
| `index_latest` | Index the newest build on each branch |
| `index_label`, `index_sublabels`, `index_label_commits` | Index one build and its parts |
| `index_delta_labels` | Materialise delta builds requested from the UI |
| `index_repository`, `sync_projects_from_gerrit` | Repository list and metadata |
| `sync_commits` | Backfill commit details, review notes and line counts |
| `sync_labels`, `sync_labels_jira` | Reconcile builds; push build info to JIRA |
| `detect_branchpoints` | Work out branch parentage |
| `index_static_manifest`, `fixup_manifestcomponents` | Repair operations |

Conventions inside indexing code, worth matching in new code:

- **Models are fetched with `apps.get_model()`**, not imported, to keep the import graph acyclic.
- **Writes go to `settings.DATABASE_ALIAS_FOR_WRITE`** via `using=`, a leftover from the read-replica
  setup in `cmweb/routers.py`.
- Git operations retry (`somc_decorators.retry`, `GIT_UPDATE_MAX_TRIES`) because the mirror can be
  mid-sync.

### What gets indexed

`IncludedBranchRule` and `ExcludedBranchRule` hold regular expressions per manifest project. **With no
inclusion rule, no branches are indexed at all** — this is the usual explanation for a branch that
never appears in the UI. Rules are managed in the admin under Explorer.

## Runtime configuration: `Parameter`

Operational settings are not in `settings.py`. `base.models.Parameter` is a cached key/value table,
editable in the admin, read through `Parameter.get()` / `get_int()` / `get_list()`:

- pagination sizes (`base-default-paginate-by`)
- repository sync interval (`explorer-cachedbranch-updateinterval`)
- Gerrit service credentials (`gerrit-serviceusername`, `gerrit-servicepassword`, and the `-plus`,
  `-archive`, `-stage` variants)
- the LDAP service account

`base.models.Property` is the same idea attached to an arbitrary object via a generic foreign key;
`PropertyCacheMixin` uses it to memoise expensive id lists. `base.cache.cache` wraps Django's cache
with hit/miss logging and a long default timeout.

## Request handling

### Access control

Three layers, and a new public endpoint has to be opened in all the relevant ones:

1. **Apache** requires LDAP basic auth for everything except `/rpc/`, `/register`, `/access-denied` and
   the favicon (`ansible/roles/apache-server/templates/apache/cmweb.conf.j2`).
2. **`PermissionCheckMiddleware`** gates the site on the `users.view_all_pages` permission and
   redirects everyone else to the branch-request list. Anonymous requests are allowed only for paths
   matching `NO_AUTH_URLS` (feeds, `rpc/`, `api/` but *not* `api/a/`, `register`, `access-denied`) or
   under `EXEMPT_URLS` (`accounts/`, `request/`) — which is how external users can file requests
   without seeing the rest of CMWEB.
3. **Django auth**: `users.auth.AuthLDAPBackend` and `RemoteLDAPBackend`, plus Django's
   `RemoteUserMiddleware` picking up the Apache-authenticated user.

### View composition

Views are class-based and assembled from mixins in `base/views/mixins.py` and
`explorer/views/mixins.py`:

- **`FormatMixin`** — a trailing `/json`, `/xml`, `/csv` or `/txt` URL segment (or `?format=`) sets both
  the response content type and a template suffix, so one view serves the HTML page and its data feed.
  Most explorer URLs therefore end in an optional `(?P<format>json|html)` group.
- **`ManifestMixin`** — the `manifest` URL kwarg defaults to `GLOBALS['PLATFORM_MANIFEST']`, so nearly
  every explorer URL works both with and without an explicit manifest prefix.
- **`BranchNameDecoderMixin`** — branch names contain slashes, so URLs encode them as `\`
  (`base.constants.URL_SLASH_ENCODE_CHAR`). This mixin decodes during `dispatch()` and must sit above
  `UrlKwargsMixin` in the MRO.
- **`AjaxableResponseMixin`**, **`PaginateMixin`**, **`GenericObjectMixin`** — AJAX form submission,
  pagination for non-`ListView`s, and `<app>/<model>/<pk>` in-place editing.

### URL shapes

`explorer/urls/__init__.py` defines the regex fragments every explorer URLconf is built from — `BRANCH`
(allowing remote prefixes like `oss/`, `aosp/`, `caf/`), `MANIFEST`, `LABEL_PREFIX`, `LABEL_SECTION`,
`COMMIT_FILTER`, `COMPONENT_FILTER`. Build sub-pages are `+`-prefixed segments:

```
/builds/<manifest>/<label>/+summary
                          /+commits/<filter>
                          /+allcommits
                          /+subcommits/<sublabel>
                          /+issues
                          /+repositories/<filter>
                          /+changes
                          /+browse/<path>
/builds/delta/<target>/<source>/+commits
```

`/labels/…` is an alias namespace for `/builds/…`, and Apache rewrites several older URL shapes onto
these.

### Front end

Bootstrap 3 with PJAX for partial page loads. `PjaxVersionMiddleware` stamps `X-PJAX-Version` with the
application version plus the compressed-asset hash so a client running stale JavaScript is forced into
a full reload. Assets are compressed **offline** (`COMPRESS_OFFLINE = True`), so templates that
reference new static files require a `make static` run before they work. Charts are d3/c3.

## Application catalogue

### Core

| App | Responsibility |
| --- | --- |
| `base` | `Parameter`, `Property`, cache wrapper, view mixins, and the git/Gerrit/JIRA/HTTP utilities in `base/utils/` |
| `explorer` | The domain model above, and the indexing engine |
| `issues` | `Issue`, `IssueType`, `IssueCollection`, `DeliveryTag` and tag periods; JIRA and legacy CR identifiers |
| `users` | LDAP-backed `Profile`, `Organisation`, `Discipline`, `Component`; user preferences |
| `aod` | `SystemFamily` / `System` — the product taxonomy branches are classified against |

### Workflow

| App | Responsibility |
| --- | --- |
| `request` | `BranchRequest` and `RepositoryRequest` approval workflows |
| `harvest` | `CherrypickPolicy` and the `Cherry` records produced by it |
| `rebase` | `RebasePolicy` and `RebaseRecord` |
| `schedule` | `BranchPeriod`, the abstract "a thing that applies to a branch for a time window" base model |
| `type_approval` | `TAPeriod` — type-approval windows, and label→TA mappings |

`request` is the most involved. `Request` is abstract, uses `django-fsm`, and carries **three parallel
state machines** — `state` (the main flow), `arch_state` (architect review) and `swp_state` (SW product
owner review) — with `ConcurrentTransitionMixin` for optimistic locking against concurrent voting.
Transitions are `approve`, `reject`, `abandon`, `reopen`, `veto`, `complete`. On completion the request
calls Gerrit's REST API to actually create the branch or repository, retrying on 401/502 through
`somc_decorators.retry`. `harvest`, `rebase`, `issues.TagPeriod` and `type_approval.TAPeriod` all
subclass `schedule.BranchPeriod`.

### Presentation and analysis

| App | Responsibility |
| --- | --- |
| `dashboards` | Per-user `Dashboard`, branch and system-family subscriptions, file-pattern watches, `Activity`, `Notification`, and `SWProject` / `TargetRelease` |
| `historian` | Issue trends and "zeitgeist" time series (day/week/month/year), family tree and timeline visualisations |
| `packages` | Debian package revisions per build, boot packages, decoupled apps |
| `product_packages` | Product package apps mapped to builds |
| `vendorsync` | Vendor/CAF release ingestion: chipsets, source branches, sync config, upload status |
| `blog` | News posts by category, surfaced in the sidebar |
| `search` | OpenSearch-backed site search |

### Integration

| App | Responsibility |
| --- | --- |
| `api` | DRF viewsets and router; browsable API at `/api/`, Swagger at `/api/docs/` |
| `gerritproxy` | Wrapper over the Gerrit REST API with an explicit allow-list of supported calls |
| `backend` | `UserTaskRequest` — tracking and polling long-running user-initiated Celery jobs |
| `cmjenkins` | Registry of Jenkins servers used to find build jobs |

## Asynchronous work

Celery (`cmweb/celery.py`, SQS broker, `django_celery_results` backend) with `@shared_task` functions in
each app's `tasks.py`. `CELERY_TASK_ALWAYS_EAGER = True` in base settings, so development runs tasks
inline. `backend.tasks.json_result` serialises Django objects out of tasks, and `backend.UserTaskRequest`
plus the `/backend/tasks/<id>/status` endpoint let the UI poll progress — Apache sets no-cache headers
on those paths specifically.

The heaviest task is `explorer.tasks.get_or_create_delta_label`, which builds a delta between two
arbitrary builds on request, reports progress through the Celery backend, and emails the requester on
completion.

## Search

OpenSearch through `django-opensearch-dsl`, with `documents.py` in `explorer`, `issues`, `users` and
`blog`. **`OPENSEARCH_DSL_AUTOSYNC = False`** — documents are not reindexed on save. The index is
rebuilt by the `update_search_index` Jenkins job every two hours, driving
`manage.py opensearch document …` through `search.search_signals.CustomSignalProcessor`. Search results
being stale by up to two hours is expected behaviour, not a bug.
