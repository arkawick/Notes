# 02 — The indexing flow

How a build that exists in C2D becomes rows in PostgreSQL that the website can
render. This is the operation CMWEB exists to perform; nearly everything else
is a view onto its output.

---

## 1. The shape of the problem

CMWEB does not own any of the data it displays. It is an **index** over four
external systems:

| System | Supplies |
| --- | --- |
| **C2D** | The build ("label") catalogue and per-build metadata packages |
| **Gerrit** | The project list, review scores, `refs/notes/review` |
| **git mirrors** | Commits, manifests, file contents (via dulwich) |
| **JIRA / M+** | Issues referenced from commit messages |

Indexing is the process of pulling from those four and producing the
`Project → Branch → ManifestBranch → Label → Commit` chain. It runs as Jenkins
jobs, not as part of any HTTP request.

---

## 2. The pipeline, top to bottom

```
                    Jenkins (hourly, 08:00–20:00)
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
            index_labels           index_latest
         (official C2D builds)   (branch tips / LATEST)
                    │                    │
                    │                    └──► on completion: sync_commits, sync_issues
                    ▼
        ┌───── per label ─────┐
        │   index_label       │
        └──────────┬──────────┘
                   │
      ┌────────────┼────────────┬──────────────┬──────────────────┐
      ▼            ▼            ▼              ▼                  ▼
 get_label_    index_        index_label_   index_sublabels   index_decoupled
 metadata      components    commits                          index_boot_packages
 (C2D)         (manifest     (git walk +                      (packages app)
               XML → rows)   Gerrit notes)
                   │
                   ▼
      label.save(update_counts=True)
      → recomputes commits_count, components_count, …
      → clears *_incomplete flags
```

Supporting jobs feed the same database on their own schedules:

```
mirror_gits (hourly)          repo sync --mirror  →  the bare git mirrors everything else reads
sync_projects_from_gerrit     the Project table
sync_projects (H 4)           Project rows from the mirror
update_manifestbranches       applies Included/ExcludedBranchRule
detect_branchpoints (H 1)     where branches diverged
index_delta_labels (H/30)     diffs between builds
```

---

## 3. Stage by stage

### 3.1 `mirror_gits` — the foundation

```bash
repo init -u git://review.ptc.sony.co.jp/mirror/manifest --mirror
repo sync -v -t MAGIC-MIRROR-ALL-EVERYTHING -j8 --prune
```

Hourly, into an EFS volume mounted at `/mnt/nfs`, symlinked as `repository/`.
Every other indexing job mounts the same EFS (`cmweb-mount-efs`) and reads from
it with dulwich via `Project.git_path()`:

```python
def git_path(self):
    return os.path.join(settings.GLOBALS['PATH_REPOSITORY'],
                        self.name + '.git')
```

**If `mirror_gits` is broken, everything downstream silently indexes stale or
missing commits.** Check it first when commit data looks wrong.

### 3.2 `index_labels` — discover builds

Runs hourly 08:00–20:00 with `--days=0.5`, and again at 02:00 with `--days 4`.

```python
def handle(self, *args, **options):
    configure_logging(**options)

    query = Project.objects.system_manifests()
    if query.exists():
        manifests = query.values_list('name', flat=True)
    else:
        logging.warning("System manifest not found.")
        return

    threshold_time = timezone.now() - timedelta(days=options['days'])

    # Fetch labels from each C2D site in separate threads
    for site in C2D_SITES:
        fetcher = LabelFetcher(C2D_SITES[site], threshold, branch=options['branch'])
        fetcher.start()
    ...
    for entry in labels:
        deeper = entry['created'] > threshold_time
        call_command('index_label', label_name=entry['name'], ..., 
                     components=deeper, commits=deeper)
```

What it does:

1. **Threads out to every C2D site** (`LabelFetcher`), collecting labels newer
   than the threshold.
2. **Filters** on name pattern (`RE_LABEL`, `RE_GOOGLE_LABEL`), dropping
   `TEST-` prefixed builds, and on `statusLocal` ∈ `{INTERNAL, OFFICIAL,
   CUSTOMER}`.
3. **Resolves the manifest** from metadata — either `XB-SONY-Component-Manifest-Git`
   directly, or by looking up `XB-SEMC-Manifest-Revision` in each system
   manifest repo until one contains that sha1.
4. **Saves each affected branch first**, so `LATEST` labels are newer than the
   versioned ones about to be created.
5. **Calls `index_label` per label**, sorted by creation date.

The `deeper` flag is the cost control: labels newer than the threshold get
components and commits indexed; older ones are only *primed* (the `Label` row is
created, the expensive work is skipped).

### 3.3 `index_label` — index one build

The longest single step. In order:

1. **Resolve the manifest project.** If `--manifest` was not given, try
   `PREFERRED_MANIFESTS` (system manifest first), then each system manifest that
   has a filtered branch matching `--branch`. If none matches:
   `'Branch %s not considered'` and return.

2. **Find or create the `Label`.** If the branch does not exist and
   `--add-branch` was passed, create an `IncludedBranchRule` for it and re-sync:

```python
from explorer.models import IncludedBranchRule
_rule, _created = IncludedBranchRule.objects.get_or_create(
    pattern="^{0}$".format(options['branch']))
ManifestBranch.objects.synced(forced_update=True)
```

   This is why the hourly job passes `--add-branch`: a brand-new branch appearing
   in C2D gets an inclusion rule automatically rather than being ignored forever.

3. **Set status to `C2D`** and, for new labels on the system/amss/qssi
   manifests, set `jira_synced = False`.

4. **Fix up sublabel tag periods** — any manifest branch that was a child of the
   previous label but not this one gets its `TagPeriod.parent` cleared.

5. **Fetch C2D metadata** (`get_label_metadata`) and apply it via
   `index_label_properties`, which extracts the `XB-SEMC-*` / `XB-SONY-*`
   fields — products, available variants, Android platform, security patch
   level, crash level, releasable flag. Resolves `XB-SEMC-Manifest-Revision`
   to a `Commit`.

6. **Chain to the sub-indexers:**

```python
index_components(static_manifest, label_obj)
call_command('index_label_commits', label_obj.name, manifest.name)
call_command('index_sublabels', ...)
call_command('index_decoupled', label_obj.name, manifest.name)
call_command('index_boot_packages', label_obj.name, manifest.name)
```

7. **`label_obj.save(update_counts=True)`** — recompute the denormalised
   counters.

### 3.4 `index_components` — manifest XML → rows

`explorer/management/indexing.py:48`. Takes the parsed repo manifest and
produces one `LabelComponentMembership` per repository in the build.

Two mechanisms worth knowing:

**A skip check that avoids redundant work:**

```python
num_gits_label = label_obj.component_memberships.count()
num_gits_xml = len(projects)
bad_components = label_obj.component_memberships.exclude(
    component__commit__isnull=False)
skip = num_gits_label == num_gits_xml
skip &= not bad_components.exists()
skip &= not label_obj.components_incomplete
if skip and not force:
    logging.info('%s: All projects indexed already', label_obj)
    return
```

Three conditions: the counts match, no membership is missing its commit, and the
incomplete flag is clear. Any one failing means re-index. `--force` overrides.

**A lock implemented in the `notes` field:**

```python
if label_obj.notes == 'Indexing components':
    # Loop and wait for 30 sec max 5 mins
    for i in range(0, 10):
        logging.info("Someone else is updating. Waiting...")
        time.sleep(30)
        ...
else:
    old_notes = label_obj.notes
    label_obj.notes = 'Indexing components'
    label_obj.save()
```

This is a **database-column mutex**, waiting up to five minutes for a concurrent
indexer on the same label. It is not atomic — two processes can both read
non-`'Indexing components'` and both proceed. It reduces collisions rather than
preventing them, and it is why a crashed indexing run can leave a label stuck
with `notes == 'Indexing components'` and every subsequent run waiting five
minutes before proceeding. If a label seems permanently slow to index, check
its notes field.

### 3.5 `index_label_commits` — the git walk

Commits are defined as **the delta from the previous label**, which is why
`Label.previous` matters so much.

```python
def index_for_label(self, label):
    if not label.previous:
        logging.info('%s: No previous label', label)
        if not label.components_incomplete:
            if label.is_previous_manually_set:
                # Do not require commit indexing for very first label in the
                # label chain.
                label.commits_incomplete = False
                label.save(using=self.options['database'])
                logging.info('%s: Suppressing commit indexing', label)
        return
```

**No previous label means no commits.** The first build in a chain legitimately
has none, and the flag is cleared only when the previous link was *deliberately*
set to nothing (`is_previous_manually_set`). Otherwise the label stays
`commits_incomplete` and will be retried.

For each component, the indexer walks git between the two revisions
(`add_walker_commits`, `add_component_commits`), capped by
`MAX_COMMIT_COUNT_PER_PROJECT = 1000` and `--max-git-change-ratio` — guards
against a rebase or a branch switch producing a million-commit "delta".

Commit metadata beyond the git object — submitter, approvers, verifiers, review
scores — comes from Gerrit's `refs/notes/review`, parsed by `sync_commits`.

### 3.6 `index_latest` — the virtual builds

Different job, different purpose:

> *Refreshes the git repository information contained in filtered manifest
> branches according to the include/exclusion rules, adding new branches and
> excluding inactive branches in the process. Creates a virtual label with the
> same name as the manifest branch name, and assigns the latest build as its
> previous build if it exists.*

So `index_latest` does three things:

1. Applies the include/exclude rules — **adds** newly active branches, **excludes**
   ones inactive beyond `--exclusion-threshold` (365 days).
2. Marks branches active within `--max-latest-interval` (30 days).
3. Creates the `LATEST` pseudo-label per branch — what you see as `p-kumano`
   rather than `55.0.A.0.477`.

On completion it triggers `sync_commits` and `sync_issues`.

---

## 4. The incompleteness model

The single most important operational concept. `Label` carries five boolean
flags, all defaulting to `True`:

```python
components_incomplete = models.BooleanField(default=True)
commits_incomplete = models.BooleanField(default=True)
sublabels_incomplete = models.BooleanField(default=True)
decoupled_incomplete = models.BooleanField(default=True)
incomplete = models.BooleanField(default=True)
```

They mean **"this aspect has not been proven complete"**, and they drive two
things:

- whether an indexing run picks the label up again
- whether the UI shows the build as partial

A freshly created `Label` is assumed incomplete until an indexer clears the
flag. `find_incomplete_labels` (daily, 08:00) audits for labels still carrying
them.

Alongside them are the **denormalised counters**:

```python
# COUNT(*) caching for templates
components_count = models.IntegerField(null=True, editable=False)
commits_count = models.IntegerField(null=True, editable=False)
all_commits_count = models.IntegerField(null=True, editable=False)
...
```

These are maintained by `Label.update_counts()`, called from indexing —
**not by signals and not by `save()` on its own.** If you change a label's
membership by hand, the counters lie until something recomputes them.

---

## 5. Where indexing runs

Not on the web servers. Each job runs on a Jenkins slave (`CMWEB_SLAVE_22`)
which:

1. mounts the EFS git mirror
2. does a fresh `repo init` + `repo sync` of the CMWEB code
3. writes its own `cmweb/secure.py` and `cmweb/settings_management.py`
4. `make install` into a throwaway virtualenv
5. runs `./manage.py <command> -v3 --traceback`

against **the same RDS instance the web servers read**. Details in
[03](03-jenkins-jobs.md).

Two consequences:

- **A Jenkins job is not a service call.** It is a full checkout and a fresh
  process every time.
- **Indexing bugs are data bugs.** Nobody gets a 500. Wrong rows are written and
  then served.

---

## 6. Troubleshooting

| Symptom | Look at |
| --- | --- |
| A new branch never appears | `IncludedBranchRule` — with no inclusion rule for the manifest project, nothing is indexed. `index_labels --add-branch` creates one automatically; `update_include_exclude_rules` manages them |
| A build appears but has no commits | `Label.previous` is null. Check `seek_previous()` / `update_previous()`, and whether `is_previous_manually_set` |
| A build shows as partial in the UI | One of the `*_incomplete` flags. Run `find_incomplete_labels`, then re-run `index_label` for it |
| Counts in the UI look wrong | Denormalised counters drifted. `sync_labels` re-saves all labels; `index_label` ends with `save(update_counts=True)` |
| Commit metadata missing (no approvers/scores) | `sync_commits` — and check whether the job ran with `--no-review` |
| Everything is stale by hours | `mirror_gits`, then the `indexing` Jenkins view |
| A label is permanently slow to index | `label.notes == 'Indexing components'` left behind by a crashed run — each subsequent run waits up to 5 minutes |
| Indexing stopped overnight on stage | `disable_indexing_jobs` runs at 20:00 and disables the whole `indexing` view in the stage Jenkins |

### Re-indexing one build by hand

Via the `run_commands` Jenkins job:

```
index_label --label-name 55.0.A.0.477 --manifest platform/systemmanifest --branch p-kumano
```

Add `--components --commits` to force the deep path, or use
`index_label_commits --force` for just the commits.
