# 01 — Management commands: full catalogue

**62 commands across 13 apps.** This is the complete inventory with each
command's purpose and arguments, taken from the source docstrings and
`add_arguments()` calls.

For *how to write* one, see
[learning/06](../learning/06-settings-and-management-commands.md). For which
ones are scheduled, see [the mapping table](README.md#the-one-table-to-remember).

---

## 1. Where they live and how they are found

```
cmweb-app/<app>/management/__init__.py
cmweb-app/<app>/management/commands/__init__.py
cmweb-app/<app>/management/commands/<name>.py    ->  manage.py <name>
```

The filename is the command name; the module must define a class called exactly
`Command`. Both `__init__.py` files must exist or Django will not see the
directory.

Distribution across apps:

| App | Commands | App | Commands |
| --- | --- | --- | --- |
| **explorer** | **20** | packages | 4 |
| base | 5 | rebase | 4 |
| historian | 5 | request | 3 |
| issues | 5 | vendorsync | 3 |
| users | 5 | dashboards | 2 |
| harvest | 4 | aod, product_packages | 1 each |

---

## 2. `explorer` — the 20 core commands

The `explorer` app owns the domain chain (`Project` → `Branch` →
`ManifestBranch` → `Label` → `Commit`), so it owns most of the indexing.

### Label indexing

| Command | Purpose | Key arguments |
| --- | --- | --- |
| **`index_labels`** | Fetch official labels from C2D and call `index_label` on each | `--days` (default 1.0), `--all-labels`, `--branch`, `--add-branch` |
| **`index_label`** | Index one label: metadata, components, commits, sublabels, decoupled apps, boot packages | `--label-name`, `--branch`, `--manifest`, `--created`, `--components`, `--commits`, `--decoupled`, `--boot-packages`, `--add-branch`, `--clear-notes` |
| **`index_label_commits`** | Index the commits that went into a label | `--all-labels`, `--days`, `--force`, `--manifest-git`, `--max-commits`, `--max-git-change-ratio`, `--database` |
| **`index_sublabels`** | Index the sub-builds associated with a label | `--components`, `--commits`, `--reindex-existing`, `--database` |
| **`index_latest`** | Refresh filtered manifest branches; create the virtual `LATEST` label per branch | `--max-latest-interval` (30), `--exclusion-threshold` (365), `--branch`, `--branch-heads`, `--exclude-from-regular` |
| **`index_delta_labels`** | Index delta (diff-between-two-builds) labels | `--days` |
| **`index_static_manifest`** | Index a pinned/static manifest file | `--label-name`, `--branch`, `--manifest`, `--path`, `--pattern`, `--alphabetical`, `--skip-name-update`, plus the usual `--components/--commits/--decoupled/--boot-packages` |
| **`index_jenkins_job`** | Index builds for a given Jenkins job URL | `--branch`, `--days`, `--manifest`, `--no-components`, `--no-commits`, `--no-decoupled`, `--no-boot-packages` |

Note the argument-polarity split: `index_label` uses positive `--components`
(default `True`), `index_jenkins_job` uses negative `--no-components`. Same
underlying switch, opposite spelling — check before scripting either.

### Repository and branch maintenance

| Command | Purpose | Key arguments |
| --- | --- | --- |
| `sync_projects` | Refresh `Project` rows from the git mirror | `--branches` |
| `sync_projects_from_gerrit` | Import the project list from Gerrit's REST API | — |
| `index_repository` | Index one repository | `--git-name`, `--branch` |
| `update_manifestbranches` | Update `ManifestBranch` rows against the include/exclude rules | — |
| `update_include_exclude_rules` | Update the rules themselves | — |
| `detect_branchpoints` | Work out where branches diverged | — |

> `IncludedBranchRule` / `ExcludedBranchRule` decide which branches get indexed
> at all. **With no inclusion rule for a manifest project, nothing is picked
> up** — the usual reason a new branch never appears in the UI.

### Commit and label sync

| Command | Purpose | Key arguments |
| --- | --- | --- |
| **`sync_commits`** | Refresh `Commit` metadata from git and Gerrit `refs/notes/review` | `--days`, `--all`, `--lines`, `--no-review` |
| `sync_labels` | Re-save all labels (recomputes counters via `save()`) | — |
| `sync_labels_jira` | Update label JIRA sync status | — |

`--lines` computes per-commit additions/deletions (expensive, which is why the
hourly job omits it and `sync_commits_more` at `H 1 * * *` includes it).
`--no-review` skips the Gerrit review-notes fetch.

### Audit and repair

| Command | Purpose |
| --- | --- |
| `find_incomplete_labels` | Audit for labels whose `*_incomplete` flags are still set (`--days`) |
| `fixup_manifestcomponents` | Repair `ManifestComponent` rows damaged by bad indexing runs |
| `index_testdata` | Regenerate `explorer/fixtures/testdata.json` (`--system-branch`, `--amss-branch`, `--outpath`) |

---

## 3. Every other app

### `base` (5) — plumbing

| Command | Purpose |
| --- | --- |
| `cmweb_version` | Print the CMWEB version string |
| `delete_cache_key` | Drop one cache key (`--key`) — the surgical alternative to flushing |
| `setup_auth` | Set up authentication |
| `sync_repo` | Sync a repo |
| `threading_example` | A worked example of a multi-threaded command, not a real task |

> **`delete_cache_key` matters.** Sessions live in memcached in production, so
> flushing the whole cache logs every user out. Use this instead.

### `issues` (5)

| Command | Purpose | Arguments |
| --- | --- | --- |
| `sync_issues` | Sync issues from the bug tracker | `--source`, `--full`, `--batch`, `--resync-titles`, `--stale-threshold` |
| `sync_tags_jira` | Sync tags from JIRA | — |
| `update_fix_delivered` | Update the "Fix Delivered" field on JIRA issues | `--days`, `--projects` |
| `create_bulk_schedules` | Create delivery tagging periods in bulk | `--file` |
| `fix_bad_tags` | Repair malformed tag names |

`update_fix_delivered` is the one command with **three** jobs pointing at it
(`update_fix_delivered_jiml`, `_jimodm18`, `_jimx`) — same command, different
`--projects`, different schedules.

### `users` (5)

`add_users` (`--filter`, `--create-profile`, `--fill-incomplete`,
`--all-incomplete`, `--filter-incomplete`, `--no-profile-user`),
`deactivate_users` (`--include-inactive-users`), `remove_empty_groups`,
`reconfigure_users`, `dump_awstats_userinfo`.

### `harvest` (4) — cherry-picking

| Command | Purpose | Arguments |
| --- | --- | --- |
| `update_cherries` | Apply cherry-pick policies | `--all`, `--full`, `--fuller`, `--manifest`, `--source`, `--target`, `--dry-run` |
| `deactivate_old_cherrypick_policies` | Retire stale policies | `--days`, `--dry-run` |
| `cherry_tag_digest` | Email digest | `--recipients`, `--dry-run` |
| `generate_cherrypick_yamls` | Generate Jenkins job YAML for cherry-picks | `-o` |

Note the escalating depth: `--full` and `--fuller` are distinct flags. The
hourly job runs plain `update_cherries`; the Sunday job runs `--full`.

### `rebase` (4)

`sync_rebase_records` (`--all`, `--full`, `--status`, `--force-status`),
`index_topic_changes`, `index_target_label` (`--force`, `--status`),
`import_rebases` (`--branch`, `--days`, `--manifest`, `--force`,
`--subject-pattern`).

The first three run together hourly, in that order — records first, then the
changes they reference, then the target labels.

### `packages` (4)

`index_boot_labels` (`--days`, `--manifest`), `index_boot_packages`
(`--all-labels`, `--force`), `index_boot_packages_revision` (`--label-name`,
`--boot-package`, `--boot-revision`), `index_decoupled` (`--all-labels`,
`--days`, `--force`, `--manifest-git`, `--database`).

### `historian` (5) — trends and activity history

`index_zeitgeist` and `index_zeitgeist_reviewplus` (`--years`, `--depth`,
`--child-depth`, `--limit`, `--no-root`), `index_issue_trend` (`--branch`,
`--dry-run`), `resave_issue_trend` (`--branch`),
`delete_old_zeitgeist_entries` (`--years`).

Only the deletion command is scheduled. If historian pages look stale, that is
why.

### `request` (3)

`update_branch_requests`, `update_repository_requests` (both `--dry-run`, both
run nightly), `branch_request_digest` (`--remind-days`, `--reject-days`,
`--dry-run`).

### `vendorsync` (3)

`index_releases` (`--branch`, `--days`, `--label`, `--manifest`),
`index_caf_release` (`--branch`, `--chipset`), `reindex_fixed_crs_xls`.

### `dashboards` (2), `aod` (1), `product_packages` (1)

`archive_activity`, `update_swprojects`; `update_aod_to_cod`;
`index_pp_apps` (`--days`, `--force`, `--label`, `--manifest`).

---

## 4. House conventions

Read these before writing or modifying a command.

### Models via the registry, not imports

```python
from django.apps import apps

Label = apps.get_model('explorer', 'label')
ManifestBranch = apps.get_model('explorer', 'manifestbranch')
Project = apps.get_model('explorer', 'project')
```

With 21 apps cross-referencing each other, module-level model imports create
cycles. `apps.get_model()` resolves lazily from the app registry.

### Writes go through the write alias

```python
using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE', DEFAULT_DB_ALIAS)
obj.save(using=using)
```

### Log, do not print

```python
from base.utils.log import configure_logging

def handle(self, *args, **options):
    configure_logging(**options)
    logging.info('Indexing labels for %s', manifests)
```

Every command starts this way. It wires `--verbosity` into the logging level.
Commands run unattended under Jenkins, where stdout is a build log — structured
logging is what makes a failure diagnosable afterwards. The Jenkins builder
passes `-v3 --traceback` to every command for exactly this reason.

### Chain with `call_command`

```python
call_command('index_label',
             label_name=entry['name'], branch=entry['branch'],
             manifest=entry['manifest'], created=entry['created'],
             components=deeper, commits=deeper,
             add_branch=options['add_branch'])
```

Keyword names are the `dest=` values from `add_arguments`.

### `help = __doc__`

Every command sets this, so `manage.py help <cmd>` shows the module docstring.

### Style gates CI enforces

- 80-column pycodestyle
- pydocstyle over every non-migration file — **every module, class and method
  needs a docstring**
- pyflakes

`make kwalitee` runs all three.

### Idempotent and resumable

Jenkins retries. A command that cannot safely run twice will eventually corrupt
data. Note how `index_labels` uses `Property` markers and the `*_incomplete`
flags rather than assuming a clean slate.

---

## 5. Running them

**Locally** (most explorer commands will raise `ShimNotAvailable` — no C2D,
Gerrit or git mirrors):

```powershell
cd local-cmweb
.venv\Scripts\python.exe manage.py help
.venv\Scripts\python.exe manage.py help index_labels
```

**In production** — never on a web server. Use the `run_commands` Jenkins job
with a semicolon-separated `COMMANDS` string:

```
index_latest ; index_labels --days 7
```

That job runs the shared `macros.yaml` builders, which do a fresh `repo sync`,
write their own `secure.py` and `settings_management.py`, and run against **the
same RDS instance the web servers read**. See [03](03-jenkins-jobs.md) for the
YAML and [07](07-anatomy-of-a-backend-run.md) for the run itself.

**Consequence worth internalising:** a broken command does not return a 500 to
anyone. It quietly writes wrong rows that the web tier then serves. Indexing
bugs surface as production *data* problems, which is why the `*_incomplete`
flags and `find_incomplete_labels` exist.
