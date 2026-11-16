# Columbia / Columbia2: confidential repository merge missing — analysis and fix

## 1. Ticket summary

The changes to the confidential repository on the HQ release branch were not merged into the
`a16-columbia-2` dev branch by the merge job, so they had to be merged manually.

| Item | Value |
|---|---|
| Job | `merge_a16-columbia-2-hq_target` (build #27) |
| Release change | `platform/targetmanifest` change 3304359 on `odm/hq/android/a16-columbia-pdx-246-target2-release` |
| Affected file | `local_manifests/sony_protected.xml` (the confidential repository is defined here) |
| Dev branch | `a16-columbia-2` (Columbia2), `a16-columbia` (Columbia) |
| Script | `cm_tools/odm/merge-local-manifest.sh` |

**What is needed:** whenever `sony_protected.xml` changes on the release branch, the job must
merge that change into the dev branch, for both Columbia and Columbia2.

> Note: the Jenkins console and Gerrit links could not be opened from here. This analysis comes from
> reading the job YAML and the script.

---

## 2. How the job works today

1. The Gerrit trigger starts the job when a change is merged on:
   - the release branch (`...-target2-release`), any file, or
   - the dev branch (`a16-columbia-2`), only for `local_manifests/sony_protected.xml`.
2. `merge-local-manifest.sh`:
   - runs `repo init` on the **dev** branch (`TARGET_BRANCH`)
   - links `.repo/local_manifests` to `manifests/local_manifests` (the dev branch's `sony_protected.xml`)
   - checks out the **release** branch in a worktree
   - compares `somc_push_version_android` on the release and dev branches (`SOURCE_DATE` / `TARGET_DATE`)
   - picks one of three cases (below), regenerates `default.xml` with `repo manifest`, commits, pushes and submits.

```bash
if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
# In the case of *-release update from HQ
    git merge ${SOURCE_BRANCH} -s ours --no-commit
    git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
    COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
elif [ "${LOCAL_MANIFEST_DIFF}" != "" ] ; then
# In the case of local_manifests/sony_protected.xml update
    git checkout ${SOURCE_BRANCH} -- default.xml
    COMMIT_MESSAGE="Update default.xml by the latest sony_protected.xml"
else
# In the case of no update
    exit 0
fi
repo manifest -o new-default.xml
```

---

## 3. Problems found

### Problem 1: `sony_protected.xml` is never taken from the release branch

`git merge -s ours` keeps **every** dev branch file as it is. Only the files named in the
`git checkout ${SOURCE_BRANCH} -- ...` line are copied from the release branch:

```
default.xml  ${PRODUCT}.xml  daily  somc_push_version_android
```

`local_manifests/sony_protected.xml` is not in that list, so release changes to it (for example
change 3304359) are dropped. Git still records a merge commit, so the change looks merged in the
history even though the file content was never brought over.

### Problem 2: the new `default.xml` uses the old confidential revisions

`repo manifest -o new-default.xml` builds the full manifest from `default.xml` **plus**
`.repo/local_manifests/*.xml`. That folder points to the **dev** branch's `sony_protected.xml`, which
still has the old content (Problem 1). So the regenerated `default.xml` also keeps the confidential
project on its old revision. The official build therefore uses the old code.

### Problem 3: a release change that touches only `sony_protected.xml` is skipped

When HQ pushes a change that only edits `sony_protected.xml`:

- `somc_push_version_android` doesn't change, so `SOURCE_DATE == TARGET_DATE` and case 1 is skipped.
- `LOCAL_MANIFEST_DIFF` is computed as `git diff HEAD^ HEAD` on the **dev** branch, not the release
  branch. It only detects edits made directly on dev, so it is usually empty here.
- The script reaches `exit 0` and does nothing. The job shows as successful, but nothing was merged.

### Problem 4: the same problem exists for Columbia

`merge_a16-columbia-hq_amss_target` (dev branch `a16-columbia`) calls the same script, so Columbia has
all three problems too.

### Constraint: the script is shared

`merge-local-manifest.sh` is used by 8 jobs (`a16-columbia`, `a16-columbia-2`, `a16-columbia-caf2`,
`a16-elbe2`, `a16-elbe2-caf`, `u-columbia`, `v-columbia`, `v-columbia-caf`). Changing its default
behaviour could affect projects that rely on the old behaviour, so the fix has to be opt-in.

---

## 4. The fix

### 4.1 Script: `cm_tools/odm/merge-local-manifest.sh`

**a) Find what changed on the release branch (opt-in with `MERGE_SONY_PROTECTED=true`).**

```bash
PROTECTED_XML=local_manifests/sony_protected.xml
SOURCE_PROTECTED_DIFF=""
if [ "${MERGE_SONY_PROTECTED}" = "true" ]; then
    MERGE_BASE=`git merge-base HEAD ${SOURCE_BRANCH} || true`
    if [ -z "${MERGE_BASE}" ]; then
        echo "ERROR: no merge-base between ${TARGET_BRANCH} and ${SOURCE_BRANCH}; cannot merge ${PROTECTED_XML}"
        exit 1
    fi
    SOURCE_PROTECTED_DIFF=`git diff --name-only ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML}`
fi
```

Because every run records a merge commit (`-s ours`), `git merge-base` is the release commit from
the last successful merge. Comparing `MERGE_BASE` with the release branch therefore shows only the
**new** release-side changes. Each change is picked up once and never re-applied. *(Fixes Problem 3.)*

**b) Run the merge when the version date changed OR `sony_protected.xml` changed.**

```bash
if [ ${SOURCE_DATE} != ${TARGET_DATE} ] || [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
    git merge ${SOURCE_BRANCH} -s ours --no-commit
    if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
        git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
        COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
    else
        COMMIT_MESSAGE="Merge ${PROTECTED_XML} from ${SOURCE_BRANCH}: `git log -1 --pretty=format:%s ${SOURCE_BRANCH} -- ${PROTECTED_XML}`"
    fi
```

**c) Apply only the release-side changes to `sony_protected.xml` with a 3-way merge.**

```bash
    if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
        if ! git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} | git apply --3way --index ; then
            echo "ERROR: conflict while merging ${PROTECTED_XML} from ${SOURCE_BRANCH}; manual merge needed"
            git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} || true
            exit 1
        fi
    fi
```

- The file is **not** simply overwritten with the release version. That would delete entries that
  exist only on the dev branch (the dev branch has its own trigger for edits to this file).
- Only the release changes are applied on top of the dev branch's file. *(Fixes Problem 1.)*
- This runs **before** `repo manifest`, so the regenerated `default.xml` contains the new confidential
  revisions. *(Fixes Problem 2.)*
- If both sides changed the same or neighbouring lines, the job **fails** and prints the changes. It
  never commits or pushes a file with conflict markers.

**d) Include the file in the commit.**

```bash
git add default.xml ${PRODUCT}.xml daily somc_push_version_android
if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
    git add ${PROTECTED_XML}
fi
```

The existing `git push ... refs/for/${TARGET_BRANCH}` and the auto-submit loop are unchanged.

### 4.2 Job YAMLs: enable the fix for Columbia and Columbia2 only

Added to the `inject` → `properties-content` section of:

- `merge/jenkins-jobs/ci-cm-odm.ptc.sony.co.jp/project-merge-a16-columbia-2-hq_target.yaml`
- `merge/jenkins-jobs/ci-cm-odm.ptc.sony.co.jp/project-merge-a16-columbia-hq_amss_target.yaml`

```yaml
            PRODUCT=pdx246
            MERGE_SONY_PROTECTED=true
```

*(Fixes Problem 4.)* The other 6 jobs don't set the flag and behave exactly as before.

---

## 5. Behaviour after the fix

| Release branch change | Before | After |
|---|---|---|
| New version date, `sony_protected.xml` unchanged | Merged | Merged (same as before) |
| New version date + `sony_protected.xml` changed | Merged, **confidential change dropped** | Merged **including** `sony_protected.xml`; `default.xml` uses the new revisions |
| Only `sony_protected.xml` changed | **Skipped (`exit 0`)** | Merged; commit message `Merge local_manifests/sony_protected.xml from <branch>: <subject>` |
| `sony_protected.xml` changed on dev branch (dev trigger) | `default.xml` regenerated | Unchanged |
| Release and dev edited the same lines of `sony_protected.xml` | Release change silently lost | **Job fails** with an error and the changes; merge it manually |
| Re-run with nothing new | `exit 0` | `exit 0` (no duplicate push) |

---

## 6. Testing

The merge steps were run on throwaway git repositories that copy the dev/release layout (not on
the real job):

| Scenario | Result |
|---|---|
| Release changes `conf` revision; dev changes a different, non-adjacent entry | Applied cleanly; both changes kept |
| Re-run after the merge | No new changes found, nothing to merge |
| Release and dev change neighbouring lines | `git apply --3way` failed and the script stops with `exit 1`; no commit |

The script also passes `bash -n` (syntax check).

---

## 7. Deployment and follow-up

1. Review and commit the changes in `cm_tools` (script) and `merge` (two YAMLs), then deploy the
   jobs with the usual `merge-deploy-jenkins-jobs` job.
2. Change 3304359 is already merged on the release branch. It will be picked up on the next run: the
   next HQ release push, or a manual run of `merge_a16-columbia-2-hq_target` with `Component=target`.
   If the content was already merged by hand, the 3-way merge sees it as already applied. If it is
   only partly there, the job will fail with a conflict and needs a manual check.
3. **Watch the first run:** for a change that touches only `sony_protected.xml`, the push reuses the
   topic `<TARGET_BRANCH>-<SOURCE_DATE>` from the last date-based merge. The submit loop only looks
   at `status:open` changes, so this should be fine, but check it once.
4. Known limitation: a real conflict (both sides edit the same entry) still needs a manual merge.
   Now it shows up as a failed job instead of silently losing the change.

---

## 8. Manual change guide: what to replace with what

There are 5 changes in 3 files. For each change, find the **FIND** text exactly (copy it from
here) and change it to the **REPLACE WITH** text. Keep the indentation (spaces) exactly as shown.

### File 1: `cm_tools/odm/merge-local-manifest.sh` (3 changes)

#### Change 1 of 3: add the release-branch check for `sony_protected.xml`

Location: around line 30, right after `TARGET_DATE=...`.

**FIND:**

```bash
LOCAL_MANIFEST_DIFF=`git diff --name-only HEAD^ HEAD local_manifests/sony_protected.xml`
cp default.xml old-default.xml
```

**REPLACE WITH:**

```bash
LOCAL_MANIFEST_DIFF=`git diff --name-only HEAD^ HEAD local_manifests/sony_protected.xml`

# Changes to the confidential manifest (sony_protected.xml) made on the
# *-release branch since the last merge into the target branch.
# Enabled per job with MERGE_SONY_PROTECTED=true.
PROTECTED_XML=local_manifests/sony_protected.xml
SOURCE_PROTECTED_DIFF=""
if [ "${MERGE_SONY_PROTECTED}" = "true" ]; then
    MERGE_BASE=`git merge-base HEAD ${SOURCE_BRANCH} || true`
    if [ -z "${MERGE_BASE}" ]; then
        echo "ERROR: no merge-base between ${TARGET_BRANCH} and ${SOURCE_BRANCH}; cannot merge ${PROTECTED_XML}"
        exit 1
    fi
    SOURCE_PROTECTED_DIFF=`git diff --name-only ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML}`
fi

cp default.xml old-default.xml
```

#### Change 2 of 3: replace the first `if` branch (the HQ release merge)

Location: right after `cp default.xml old-default.xml`. Replace only up to (not including) the
`elif` line. The `elif` and `else` branches stay as they are.

**FIND:**

```bash
if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
# In the case of *-release update from HQ
    git merge ${SOURCE_BRANCH} -s ours --no-commit
    git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
    COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
elif [ "${LOCAL_MANIFEST_DIFF}" != "" ] ; then
```

**REPLACE WITH:**

```bash
if [ ${SOURCE_DATE} != ${TARGET_DATE} ] || [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
# In the case of *-release update from HQ (version date and/or sony_protected.xml)
    git merge ${SOURCE_BRANCH} -s ours --no-commit
    if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
        git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
        COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
    else
        COMMIT_MESSAGE="Merge ${PROTECTED_XML} from ${SOURCE_BRANCH}: `git log -1 --pretty=format:%s ${SOURCE_BRANCH} -- ${PROTECTED_XML}`"
    fi
    if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
        # Apply only the release-side delta (3-way), so target-only entries are kept.
        # Must happen before 'repo manifest' so default.xml picks up the new revisions.
        if ! git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} | git apply --3way --index ; then
            echo "ERROR: conflict while merging ${PROTECTED_XML} from ${SOURCE_BRANCH}; manual merge needed"
            git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} || true
            exit 1
        fi
    fi
elif [ "${LOCAL_MANIFEST_DIFF}" != "" ] ; then
```

#### Change 3 of 3: add `sony_protected.xml` to the commit

Location: near the end, just before `git commit -m "${COMMIT_MESSAGE}"`.

**FIND:**

```bash
git add default.xml ${PRODUCT}.xml daily somc_push_version_android

git commit -m "${COMMIT_MESSAGE}"
```

**REPLACE WITH:**

```bash
git add default.xml ${PRODUCT}.xml daily somc_push_version_android
if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
    git add ${PROTECTED_XML}
fi

git commit -m "${COMMIT_MESSAGE}"
```

Nothing else in the script changes.

### File 2: `merge/jenkins-jobs/ci-cm-odm.ptc.sony.co.jp/project-merge-a16-columbia-2-hq_target.yaml` (Columbia2)

Location: `wrappers` → `inject` → `properties-content`, last line of the block.

**FIND:**

```yaml
            TARGET_BRANCH_AMSS=a16-columbia-sm6450-la2.0
            PRODUCT=pdx246
```

**REPLACE WITH:**

```yaml
            TARGET_BRANCH_AMSS=a16-columbia-sm6450-la2.0
            PRODUCT=pdx246
            MERGE_SONY_PROTECTED=true
```

### File 3: `merge/jenkins-jobs/ci-cm-odm.ptc.sony.co.jp/project-merge-a16-columbia-hq_amss_target.yaml` (Columbia)

Same change as File 2 (this file has the same two lines).

**FIND:**

```yaml
            TARGET_BRANCH_AMSS=a16-columbia-sm6450-la2.0
            PRODUCT=pdx246
```

**REPLACE WITH:**

```yaml
            TARGET_BRANCH_AMSS=a16-columbia-sm6450-la2.0
            PRODUCT=pdx246
            MERGE_SONY_PROTECTED=true
```

> `MERGE_SONY_PROTECTED=true` must have exactly the same indentation (12 spaces) as `PRODUCT=pdx246`.
> Don't add it to any other job YAML.

### Checks before committing

Run these from the `cm_tools` repository:

```bash
# 1. Syntax check: must print nothing
bash -n odm/merge-local-manifest.sh

# 2. The script must stay executable. If you edited it on Windows, the mode may change to 100644,
#    and every job that calls the script would then fail with "Permission denied".
git update-index --chmod=+x odm/merge-local-manifest.sh
git diff --cached --summary -- odm/merge-local-manifest.sh   # must NOT show "mode change 100755 => 100644"

# 3. Line endings must stay LF (a CRLF script fails with "/bin/bash^M: bad interpreter")
file odm/merge-local-manifest.sh   # must NOT say "with CRLF line terminators"
```

The full diff of the script should look like this (`git diff odm/merge-local-manifest.sh`):

```diff
@@ -28,12 +28,40 @@
 SOURCE_DATE=`cat ${SOURCE_BRANCH##*/}/somc_push_version_android`
 TARGET_DATE=`cat somc_push_version_android`
 LOCAL_MANIFEST_DIFF=`git diff --name-only HEAD^ HEAD local_manifests/sony_protected.xml`
+
+# Changes to the confidential manifest (sony_protected.xml) made on the
+# *-release branch since the last merge into the target branch.
+# Enabled per job with MERGE_SONY_PROTECTED=true.
+PROTECTED_XML=local_manifests/sony_protected.xml
+SOURCE_PROTECTED_DIFF=""
+if [ "${MERGE_SONY_PROTECTED}" = "true" ]; then
+    MERGE_BASE=`git merge-base HEAD ${SOURCE_BRANCH} || true`
+    if [ -z "${MERGE_BASE}" ]; then
+        echo "ERROR: no merge-base between ${TARGET_BRANCH} and ${SOURCE_BRANCH}; cannot merge ${PROTECTED_XML}"
+        exit 1
+    fi
+    SOURCE_PROTECTED_DIFF=`git diff --name-only ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML}`
+fi
+
 cp default.xml old-default.xml
-if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
-# In the case of *-release update from HQ
+if [ ${SOURCE_DATE} != ${TARGET_DATE} ] || [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
+# In the case of *-release update from HQ (version date and/or sony_protected.xml)
     git merge ${SOURCE_BRANCH} -s ours --no-commit
-    git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
-    COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
+    if [ ${SOURCE_DATE} != ${TARGET_DATE} ] ; then
+        git checkout ${SOURCE_BRANCH} -- default.xml ${PRODUCT}.xml daily somc_push_version_android
+        COMMIT_MESSAGE="Merge `git log -1 --pretty=format:%s ${SOURCE_BRANCH}`"
+    else
+        COMMIT_MESSAGE="Merge ${PROTECTED_XML} from ${SOURCE_BRANCH}: `git log -1 --pretty=format:%s ${SOURCE_BRANCH} -- ${PROTECTED_XML}`"
+    fi
+    if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
+        # Apply only the release-side delta (3-way), so target-only entries are kept.
+        # Must happen before 'repo manifest' so default.xml picks up the new revisions.
+        if ! git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} | git apply --3way --index ; then
+            echo "ERROR: conflict while merging ${PROTECTED_XML} from ${SOURCE_BRANCH}; manual merge needed"
+            git diff ${MERGE_BASE} ${SOURCE_BRANCH} -- ${PROTECTED_XML} || true
+            exit 1
+        fi
+    fi
 elif [ "${LOCAL_MANIFEST_DIFF}" != "" ] ; then
@@ -70,6 +98,9 @@
 git add default.xml ${PRODUCT}.xml daily somc_push_version_android
+if [ -n "${SOURCE_PROTECTED_DIFF}" ] ; then
+    git add ${PROTECTED_XML}
+fi
 
 git commit -m "${COMMIT_MESSAGE}"
```
