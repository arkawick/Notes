# Proposal: make the `system_diff` delta check trustworthy, fast and self-evaluating

| | |
|---|---|
| **Status** | Proposal, ready for review |
| **Scope** | `cm_tools/hudson-scripts/system-diff.sh`, `system-diff-matrix.sh`, `system-diff-collect.sh` and the Jenkins jobs `system_diff` / `system_diff_matrix` |
| **Reference build** | `system_diff #23` = `system_diff_matrix #23`, `SYSTEM_LABEL_1=73.0.A.1.53` (chikugo-1.0.0, stage) vs `SYSTEM_LABEL_2=73.0.A.2.36` (chikugo-1.0.0-rel, rel) |
| **Deliverables** | `system_diff_issue/system-diff.sh`, `system_diff_issue/system-diff-matrix.sh`, `system_diff_issue/system-diff-collect.sh`, `system_diff_issue/manifest_project_delta.py`, `system_diff_issue/system-diff-improvements.patch` |

---

## 1. Summary

The `system_diff` job does the right comparison, but it hands back a raw HTML page that a human has to interpret, and it pays for a full multi-component `repo sync` to produce it. Three things follow from that:

| # | Problem today | Proposed fix |
|---|---|---|
| 1 | **The job never states whether the two labels are equal.** The pass criteria live in people's heads, and the report always contains a non-empty `.repo/manifests/` section, so "empty report" can never be the rule. | Compute a **verdict** (`NO_DELTA` / `DELTA_FOUND`), print it in the console, put it in `verdict.properties` + `summary.json`, show it as a summary table at the top of the HTML, and let the build result carry it. |
| 2 | **Several failure modes are indistinguishable from "no delta".** Added/removed projects, per-project git errors and a failed manifest extraction all render as silence. | Compare the project **sets** explicitly, keep `stderr` out of the report and fail the build on it, add `set -o pipefail`. |
| 3 | **It syncs the whole tree to find a two-file change.** `--reference` is passed a literal placeholder, so there is not even mirror acceleration. | Sync only the projects whose pinned revision can differ, and pass a real `$REPO_MIRROR`. |

In build #23 the entire genuine source delta between stage and rel was **two customization files** in `device/somc/pdx267` — everything else in the report was manifest metadata or label-pointer bookkeeping. Producing that answer required syncing four complete component trees.

---

## 2. The question that triggered this

> *"Again pls check after running this delta job, how will u confirm that there is no delta between stage and rel branch. What's the criteria?"*

The job cannot answer this today, because:

* the report is a flat list of `<h1>`/`<h2>`/`<li>` with no notion of "expected" versus "unexpected";
* `.repo/manifests/` **always** differs when comparing two branches (the default revision is literally `chikugo-1.0.0` on one side and `chikugo-1.0.0-rel` on the other), so a completely equal pair of labels still produces a report with content in it;
* the default `EXCLUDE_PROJECTS` removes the four packaging projects but not the manifest project, even though the script already supports excluding it.

Section 6 defines the criteria explicitly; sections 4 and 5 make the job enforce them.

---

## 3. How the process works today

```
system_diff  (freestyle, node CM)
  1. write ~/.netrc from credentials
  2. clone cm_tools
  3. system-diff.sh
        repository list <label> -g build-metadata -xml        (both labels)
        repository labelmetadata <label>                       -> job description
        -> properties.txt: SYSTEM_DIFF_MATRIX_INPUT="pkg|ver1|ver2 pkg|ver1|ver2 ..."
  4. trigger system_diff_matrix (blocking) with that axis + EXCLUDE_PROJECTS
        |
        +-- system_diff_matrix (matrix, node CM_UTIL, one run per DIFF_INPUT)
              system-diff-matrix.sh
                repository getpackage <pkg> <ver>              (both versions)
                dpkg-deb -I                                    -> component metadata
                dpkg --fsys-tarfile | tar xOf ./static_manifest.xml
                repo init -u <manifest git> -b <branch>
                repo init -m manifest_static_1.xml ; repo sync ; repo init -m manifest_static_2.xml
                git diff rev1..rev2            in .repo/manifests   -> "project .repo/manifests/"
                repo forall -cvp 'git diff HEAD..$REPO_RREV'        -> the real source delta
                sed out EXCLUDE_PROJECTS                            -> *_diff_excluded.txt
              archive result-dir/*.txt
  5. MATRIX_BUILD_NUMBER=$TRIGGERED_BUILD_NUMBER_system_diff_matrix -> properties.txt
  6. copyartifact result-dir/*.txt from that matrix build
  7. system-diff-collect.sh -> all_diff.html, all_diff_excluded.html, diff/<md5>.txt
  8. archive result-dir/*.html, result-dir/diff/*
```

Two properties of this design are worth stating because the rest of the document depends on them:

* **Only one `repo sync` happens.** The tree is checked out at label 1; `repo init -m manifest_static_2.xml` only re-points `$REPO_RREV` at label 2. `git diff HEAD..$REPO_RREV` therefore means *"content of label 1 versus content of label 2"*, with `-` lines being label 1 and `+` lines label 2.
* **`repo forall` iterates the manifest that is active at the time**, which after step 3 is **label 2's** manifest.

---

## 4. Findings

Severity: **H** = can produce a wrong answer, **M** = operational cost or silent misconfiguration, **L** = quality.

### F-1 (H) Projects added or removed between the two labels are invisible

`repo forall` runs against label 2's manifest, so a project that exists only in label 1 is never visited and never reported. A project that exists only in label 2 was never synced, so it has no working tree. In both cases the report says nothing, which reads exactly like "no delta" — even though appearing or disappearing between stage and rel is a bigger event than a file change.

### F-2 (H) A failed per-project diff is reported as "no diff"

```bash
repo forall -cvp 'git diff HEAD..$REPO_RREV' 2>&1 | tee -a "result-dir/${component_name}_diff.txt"
```

`2>&1` folds `stderr` into the report, and the HTML generator only emits lines matching `^Diff`, `^project` or `^diff`. A `fatal: bad revision` is therefore dropped on the floor and the project renders as an empty `<ol>`. The job still finishes SUCCESS.

The same pattern exists for the manifest git diff (`git diff rev1..rev2 2>&1`): if either manifest revision has not been fetched, the error text becomes the "diff", the HTML generator discards it, and the section silently disappears (F-13).

### F-3 (H) A failed manifest extraction produces an empty diff, not an error

```bash
dpkg --fsys-tarfile "$deb_pkg_file_path_1" | tar xOf - ./$manifest_static_path_1 > manifest_static_1.xml
```

Without `set -o pipefail` only `tar`'s exit status is seen. A failure in `dpkg` leaves an empty `manifest_static_1.xml`, `repo` then works on an empty project set, and the component is reported as having no delta.

### F-4 (H) No verdict, and the criteria cannot be met by construction

The job produces two HTML pages and stops. There is no machine-readable result, nothing in the build description, and no build status difference between "the branches are identical" and "47 projects differ". Combined with the permanently non-empty `.repo/manifests/` section, there is no rule a reader can apply mechanically.

### F-5 (H) The full tree is synced, and the mirror reference is a placeholder

```bash
repo init -u git://review.ptc.sony.co.jp/$manifest_git -b $manifest_branch --reference={repo-mirror-location}
```

`{repo-mirror-location}` is a literal string; every other script in `cm_tools` uses `--reference=$REPO_MIRROR` (see `fullbuild/fullbuild_matrix.sh`, `hudson-scripts/aosp-build.sh`, `hudson-scripts/offbuild-intermediate-fail.sh`, …). So each matrix run is a cold clone of an entire component tree from Gerrit — for AMSS, QSSI, TARGET and SYSTEM in parallel — in order to discover, in build #23, that exactly one project per component produced any output at all.

### F-6 (M) `EXCLUDE_PROJECTS` is documented as optional but is mandatory

With an empty `EXCLUDE_PROJECTS`, no `*_diff_excluded.txt` is created, and `system-diff-collect.sh` starts with

```bash
cat result-dir/*/*_diff_excluded.txt >> result-dir/all_diff_excluded.txt
```

which fails under `bash -e`, so the whole job fails.

### F-7 (M) Exclusions fail silently when the project is not in that component

The path is resolved from `manifest_static_1.xml` only. When the project is absent, `exclude_path` is empty and the pattern degenerates to `^project \/$`, which matches nothing. Build #23's AMSS log shows this happening three times:

```
++ xmllint --xpath 'string(//manifest/project[@name="platform/vendor/semc/build/android-qssi-packages"]/@path)' manifest_static_1.xml
+ exclude_path=
+ start_pattern='^project \/$'
+ sed -i '/^project \/$/,/^$/d' result-dir/amss_diff_excluded.txt
```

Harmless here (those projects genuinely are not part of AMSS), but a typo in the parameter is indistinguishable from this.

### F-8 (M) Label compatibility is checked by package count only

`system-diff.sh` compares `count(//package)` of the two labels. Two labels with the same number of *differently named* components pass the check; the second version lookup then returns an empty string and the matrix child dies on `repository getpackage <name> ""`.

### F-9 (M) `all_diff.txt` is appended, not written

`cat ... >> result-dir/all_diff.txt` accumulates the previous run's content if the workspace was not wiped.

### F-10 (L) `DIFF_INPUT` is split by word splitting

`input=($(echo $DIFF_INPUT | tr '|' ' '))` breaks on any field containing whitespace and silently mis-assigns the versions.

### F-11 (L) HTML generator: leaked pipes, shell injection, no escaping

For every diff header the awk program opens `echo "..." | md5sum | cut ...` and never `close()`s it (file-descriptor exhaustion on large reports), interpolates the unsanitised header into a shell command, and emits it into HTML without escaping.

### F-12 (L) The console log is dominated by echoed diffs

`set -x` plus `manifest_diff=$(...)` plus `echo "$manifest_diff" | tee` means the same ~465-line manifest diff appears **four times** in the console. The AMSS configuration alone is a 122 KB / 1132-line log, of which ~95 % is that repetition.

### F-13 (H) See F-2 — manifest git diff shares the same `2>&1` problem

### F-14 (L) No commit-level view

The `repo forall … git log …` block exists but is commented out. A pure content diff cannot distinguish "no changes" from "a change and its revert", and cannot show which commits are unique to each branch.

---

## 5. Proposed changes

### 5.1 New helper: `hudson-scripts/manifest_project_delta.py`

Compares the project sets of the two static manifests **before anything is synced** and prints one TAB-separated record per project that is not provably identical:

```
<STATE>\t<name>\t<path_1>\t<path_2>\t<revision_1>\t<revision_2>
```

| STATE | Meaning | Needs sync + diff? |
|---|---|---|
| `ADDED` | only in manifest 2 | no — reported as a project set change |
| `REMOVED` | only in manifest 1 | no — reported as a project set change |
| `MOVED` | same revision, different path | no — content is identical |
| `CHANGED` | pinned revision differs, **or** either side is not a 40-character SHA-1 | yes |

The "not a SHA-1" rule is deliberate: a static manifest may still pin a branch or tag (`revision="common-16.2.0"`, `revision="refs/tags/6.00.46"` both occur in the AMSS manifests), and identical strings can resolve to different commits. Those projects are always compared.

Projects absent from the output are pinned to the same SHA-1 on both sides and therefore have identical content — they cannot contribute a delta and do not need to be fetched.

### 5.2 `system-diff.sh`

| Change | Fixes |
|---|---|
| Compare the package **name sets** of the two labels, not just the count, and print a `diff` of the two sets on mismatch | F-8 |
| `set -o pipefail`, quoted expansions, `if ! cmd; then` instead of `ret_val=$?` | F-10 |
| Guard against an empty resolved version before writing the axis value | F-8 |

The output contract (`SYSTEM_DIFF_MATRIX_INPUT=` in `$PROPERTIES_FILE`) is unchanged, so the Jenkins wiring keeps working.

### 5.3 `system-diff-matrix.sh`

| Change | Fixes |
|---|---|
| `set -o pipefail`; validate that both static manifests are non-empty and well-formed (`xmllint --noout`) | F-3 |
| `IFS='\|' read -r` instead of array word splitting; validate every metadata field; verify both packages describe the same component | F-10 |
| Run `manifest_project_delta.py` and emit `PROJECT-SET-CHANGE` lines into the report for `ADDED` / `REMOVED` / `MOVED` | F-1 |
| `repo sync` **only** the `CHANGED` paths; skip the sync entirely when the manifests pin identical revisions everywhere | F-5 |
| Use `--reference=$REPO_MIRROR` when it exists, warn loudly when it does not | F-5 |
| Manifest git diff: verify both revisions are present (fetch once if not), fail loudly if they are still missing, write to a file instead of echoing a giant variable | F-13, F-12 |
| `repo forall` keeps `stdout` and `stderr` separate; a non-zero return code, or any `stderr` when `STRICT_DIFF_ERRORS=1` (default), fails the build | F-2 |
| Re-enable the commit log as a separate artifact `<component>_gitlog.txt` using `git log --left-right --cherry-pick --oneline HEAD...$REPO_RREV` | F-14 |
| Always produce `<component>_diff_excluded.txt`, even with an empty `EXCLUDE_PROJECTS` | F-6 |
| Resolve exclusion paths from either manifest, treat the component's own manifest git (and the literal `.repo/manifests`) as the manifest section, escape regex metacharacters, and warn when an entry matched nothing | F-7 |

New optional inputs: `REPO_MIRROR`, `STRICT_DIFF_ERRORS` (default 1), `INCLUDE_MANIFEST_GIT_DIFF` (default 1), `INCLUDE_GIT_LOG` (default 1), `SYNC_JOBS` (default 8).

### 5.4 `system-diff-collect.sh`

| Change | Fixes |
|---|---|
| `nullglob` + explicit "nothing was copied" error; truncate instead of append; fall back to the full report when no `_excluded` files exist | F-6, F-9 |
| Summary table at the top of both HTML pages: component, both labels, projects with delta, files changed, project set changes, per-component verdict | F-4 |
| Explicit direction note (`-` is label 1, `+` is label 2) and a `.repo/manifests/` section marked *"manifest metadata, not a source delta"* and excluded from all counts | F-4 |
| `PROJECT-SET-CHANGE` lines rendered as their own "Project set changes" section | F-1 |
| Per-component stats to `result-dir/stats.tsv`, `result-dir/summary.json`, and `verdict.properties` at workspace root | F-4 |
| Console verdict block, plus `FAIL_ON_DELTA=1` to make a delta fail the build outright | F-4 |
| `close()` the `md5sum` pipe, sanitise the key before passing it to the shell, HTML-escape emitted text | F-11 |

Example console tail:

```
============================================================
VERDICT: DELTA_FOUND (73.0.A.1.53 vs 73.0.A.2.36)
------------------------------------------------------------
  amss             no source delta
  android-qssi     no source delta
  android-target   1 project(s), 2 file(s), 0 project set change(s)
  system           no source delta
============================================================
```

`summary.json`:

```json
{
  "system_label_1": "73.0.A.1.53",
  "system_label_2": "73.0.A.2.36",
  "verdict": "DELTA_FOUND",
  "delta_project_count": 1,
  "excluded_projects": "platform/vendor/semc/build/system-snapshot ...",
  "build_url": "https://ci-cm.ptc.sony.co.jp/job/system_diff/23/",
  "components": [
    {"component": "amss", "delta_projects": 0, "delta_files": 0, "project_set_changes": 0},
    {"component": "android-target", "delta_projects": 1, "delta_files": 2, "project_set_changes": 0}
  ]
}
```

---

## 6. The criteria, stated explicitly

**A pair of labels is delta-free when, in `all_diff_excluded.html`, every component reports zero projects with a delta and zero project set changes** — that is, `verdict == NO_DELTA` and `delta_project_count == 0`.

What does and does not count:

| Section in the report | Counts as a delta? | Why |
|---|---|---|
| `.repo/manifests/` | **No** | The manifest git itself: default revision, `cm_decisive_systems.json`, `upstreams/xperia/*`. Two different branches always differ here. |
| Projects listed in `EXCLUDE_PROJECTS` | **No** | Label-pointer bookkeeping (`system-snapshot`, `android-*-packages`, `pld-packages`) — they record *which* label a branch pins, not source code. |
| Any other `<h2>` project section | **Yes** | Real source content difference. |
| `Project set changes` (ADDED / REMOVED / MOVED) | **Yes** | The two labels do not contain the same set of projects. |

Applied to build #23:

| Component | Result |
|---|---|
| AMSS | manifest metadata only → no delta |
| ANDROID-QSSI | manifest metadata only → no delta |
| ANDROID-TARGET | **delta** — `device/somc/pdx267`, `config/copy-files/odm/etc/customization/c002110/config.prop` and `.../c002514/config.prop` |
| SYSTEM | manifest metadata only → no delta |

**Verdict for #23: `DELTA_FOUND`** — 73.0.A.1.53 and 73.0.A.2.36 are *not* equivalent; one real code delta remains.

---

## 7. Jenkins configuration changes required

1. **Add the manifest project to the `EXCLUDE_PROJECTS` default** so the metadata section disappears from the excluded report and "empty means equal" becomes literally true:

   ```
   platform/vendor/semc/build/system-snapshot
   platform/vendor/semc/build/android-qssi-packages
   platform/vendor/semc/build/android-target-packages
   platform/vendor/semc/build/pld-packages
   platform/systemmanifest
   ```

   The patched script also accepts the literal `.repo/manifests`, and matches the component's own manifest git automatically.

2. **Export `REPO_MIRROR`** on the `CM_UTIL` nodes (the same value the fullbuild and offbuild jobs already use).

3. **Widen the archived artifacts** of `system_diff`:

   ```xml
   <artifacts>result-dir/*.html,result-dir/diff/*,result-dir/*.json,result-dir/stats.tsv,result-dir/all_diff*.txt</artifacts>
   ```

   and of `system_diff_matrix` (already `result-dir/*.txt`, which now also captures `*_gitlog.txt`, `*_diff_errors.txt` and `*_project_delta.tsv`).

4. **Surface the verdict.** Minimal wiring with the existing plugins — inject `verdict.properties` (EnvInject already runs for `$PROPERTIES_FILE`) and mark the build with a Groovy postbuild step:

   ```groovy
   if (manager.build.getEnvironment(manager.listener).get('SYSTEM_DIFF_VERDICT') == 'DELTA_FOUND') {
       manager.build.result = hudson.model.Result.UNSTABLE
   }
   ```

   Alternatively set `FAIL_ON_DELTA=1` if a delta should fail the job outright (useful when the job is used as a release gate).

5. **Optional, recommended:** trigger `system_diff` automatically whenever a rel-branch label is created, comparing it against the stage label it was cut from, so drift is detected on the day it appears rather than on request.

---

## 8. Expected effect

| | Today | After |
|---|---|---|
| Answering "are stage and rel equal?" | read two HTML pages, know which sections to ignore | build status + one console line + `summary.json` |
| Project added / removed between labels | invisible | own report section, counts as a delta |
| `git diff` failure in a project | renders as "no changes", build SUCCESS | build FAILURE with the error text |
| Manifest extraction failure | renders as "no changes" | build FAILURE |
| Projects fetched per component | the entire tree | only those whose pinned revision can differ (zero when the manifests are identical) |
| Local mirror | not used (literal placeholder) | `--reference=$REPO_MIRROR` |
| Empty `EXCLUDE_PROJECTS` | job fails | works |
| Typo in `EXCLUDE_PROJECTS` | silently ignored | `WARNING: … nothing excluded for it` |

---

## 9. Rollout and validation

1. **Review the patch** (`system_diff_issue/system-diff-improvements.patch`, applies cleanly to `cm_tools` master).
2. **Shadow run:** copy the three scripts plus the helper into a scratch branch of `cm_tools`, point a cloned `system_diff` job at it, and re-run the exact inputs of build #23 (`73.0.A.1.53` vs `73.0.A.2.36`).
3. **Compare:** the new `all_diff_excluded.html` must contain the same real delta as #23 — `device/somc/pdx267` with two `config.prop` files — and must report `DELTA_FOUND` with `delta_project_count = 1`.
4. **Negative test:** run a label against itself-equivalent pair (or two consecutive stage labels with no content change) and confirm `NO_DELTA` and "No diff" for every component.
5. **Error test:** set `STRICT_DIFF_ERRORS=1` and point one component at a label whose manifest revision was never pushed; the build must fail instead of reporting no delta.
6. Merge, update the two job configs (section 7), keep `FAIL_ON_DELTA=0` for the first weeks so the verdict is observed before it gates anything.

---

## 10. Risks and rollback

| Risk | Mitigation |
|---|---|
| Selective sync misses a project that would have shown a delta | Only projects pinned to the **same SHA-1** on both sides are skipped; anything non-SHA (branch or tag) is always compared. The selection is written to `<component>_project_delta.tsv` for audit. |
| `STRICT_DIFF_ERRORS=1` turns previously "green" runs red | That is the intent — those runs were reporting an unknown, not a "no delta". Set `STRICT_DIFF_ERRORS=0` temporarily if a noisy but harmless `stderr` source is found. |
| Report format change breaks something downstream | The `Diff of <component> <ver1> and <ver2>` / `project <path>/` / `diff --git …` line format is unchanged; only additions (`PROJECT-SET-CHANGE`, summary table) were made. The old reports still render correctly with the new generator. |
| `python3` unavailable on `CM_UTIL` | `repo` itself is Python, so it is present. The helper uses only the standard library. |
| Rollback | Revert the single commit; no state outside the workspace is touched. |

---

## Appendix A — Files in this proposal

| File | Purpose |
|---|---|
| `system_diff_issue/system-diff.sh` | patched step 1 (parent) |
| `system_diff_issue/system-diff-matrix.sh` | patched step 2 (per component) |
| `system_diff_issue/system-diff-collect.sh` | patched step 3 (collect, render, verdict) |
| `system_diff_issue/manifest_project_delta.py` | new helper, manifest project set comparison |
| `system_diff_issue/system-diff-improvements.patch` | all four as one unified diff, `git apply`-able from the `cm_tools` root |

Apply with:

```bash
PATCH=$PWD/system_diff_issue/system-diff-improvements.patch   # from the JenkinsError root
cd cm_tools
git apply --check "$PATCH"     # verify
git apply "$PATCH"             # apply
```

## Appendix B — Formats introduced

**`<component>_project_delta.tsv`** (one line per non-identical project):

```
CHANGED  platform/adsp-sm8850  LPAIDSP.HT.1.2/adsp_proc  LPAIDSP.HT.1.2/adsp_proc  <sha1>  <sha1>
ADDED    platform/brand-new    -                         vendor/brand-new          -       <sha1>
```

**`PROJECT-SET-CHANGE` marker line** in `<component>_diff.txt`:

```
PROJECT-SET-CHANGE <STATE> <name> <path_1> <path_2> <revision_1> <revision_2>
```

**`verdict.properties`**:

```
SYSTEM_DIFF_VERDICT=NO_DELTA|DELTA_FOUND
SYSTEM_DIFF_DELTA_COUNT=<n>
```

**Exit codes of `system-diff-collect.sh`**: `0` normal, `1` job error, `2` delta found and `FAIL_ON_DELTA=1`.

## Appendix C — Verification performed on the proposed scripts

* `bash -n` on all three scripts — clean.
* `system-diff-collect.sh` run against a fixture reproducing build #23's shape (AMSS with a manifest section plus an excluded `system-snapshot`, ANDROID-TARGET with a `device/somc/pdx267` delta, plus an `ADDED` project): produced the summary table, the project set change section, `stats.tsv`, `summary.json`, `verdict.properties` and `VERDICT: DELTA_FOUND` with the correct per-component counts.
* Same script against a metadata-only fixture with **no** `*_diff_excluded.txt` present (the empty `EXCLUDE_PROJECTS` case that fails today): produced `VERDICT: NO_DELTA` and rendered "No diff".
* `manifest_project_delta.py` against synthetic manifests covering identical / changed / moved / added / removed / branch-pinned / tag-pinned projects: identical SHA-1 projects correctly skipped, branch- and tag-pinned projects correctly forced to `CHANGED`, sync and forall path lists correctly taken from manifest 1 and manifest 2 respectively.
* `git apply --check` of the patch against `cm_tools` master — applies cleanly.
