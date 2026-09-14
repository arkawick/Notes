# CSM — code changes, split into commits

Companion to `csm-restore-failure-report.md`. Three commits, deliberately separated so
the one that matters can be reviewed, landed and reverted on its own.

| Commit | Scope | Files | Why separate |
|--------|-------|-------|--------------|
| **1** | Stop leaking buildrepo credentials | 1 | Unrelated to the incident; should land regardless of what happens to the rest |
| **2** | Default `CSM_SOURCE` to `download` | 12 | **The fix.** Minimal, so it reverts cleanly |
| **3** | Close the backup/restore asymmetry | 8 | Hardening; no urgency, bigger review surface |

Commit 2 alone unblocks ubuntu20. Commits 1 and 3 are independent of it and of each
other — land them in any order.

**Version matrix behind all of this** (from `csm-binary-diagnostic.sh`):

| Node | OS | codesyncmgr | Bucket source | Effective bucket |
|------|----|-------------|---------------|------------------|
| ubuntu20 | 20.04.6 | **2.0.1-0** | `cli.py` `DEFAULT_BUCKET` | `apne1-jenkins-cm-workflow` |
| ubuntu24 | 24.04.4 | **2.1.0** | `app.py` `choose_bucket()` | `ap-northeast-1-s3codesync` |
| downloaded | — | 1.9.0 | `app.py` `choose_bucket()` | `ap-northeast-1-s3codesync` |

---

# Commit 1 — stop tracing buildrepo credentials

**Files:** `offbuild/common_functions.sh`

Not part of the incident. `set -x` currently echoes the full buildrepo API response —
live Artifactory reftokens for swerepo, gradle, pypi and sonybuildenv — into every
console log of every CSM build. Anyone attaching a console log to a ticket distributes
them.

```bash
 function download_csm()
 {
     local _csm_bin=$1
     local _response _username _password
+    local _xtrace=""
+    case $- in *x*) _xtrace=1 ;; esac
+    set +x                                  # do not trace service credentials
     echo "Querying API for username / password ..." >&2
     _response="$(curl --no-progress-meter -fSL "${BUILDREPO_API_URL}")"
     _username="$(jq -r .globaltools.username <<< "$_response")"
     _password="$(jq -r .globaltools.password <<< "$_response")"
     echo "Downloading codesyncmgr from buildrepo ..." >&2
     curl -u $_username:$_password -sL $BUILDREPO_CSM_URL/codesyncmgr-$CODE_SYNC_MGR_VERSION -o $_csm_bin
     chmod a+x $_csm_bin
+    [ -n "$_xtrace" ] && set -x
     return 0
 }
```

Saving and restoring the trace state, rather than a bare `set -x` at the end, keeps the
function correct when called from a script that was not tracing.

### Commit message

```
Stop tracing buildrepo credentials in download_csm

The buildrepo API response carries Artifactory reftokens for swerepo,
gradle, pypi, sonybuildenv and globaltools. Under 'set -x' the whole
response is echoed into the console log, so every CSM build publishes
five service credentials to anyone who can read the job.

Disable tracing around the credential handling and restore the caller's
previous trace state afterwards.
```

> **Follow-up, not code:** these tokens are in existing console logs. Raise rotation
> with whoever owns the buildrepo credentials; this commit only stops new leakage.

---

# Commit 2 — default CSM_SOURCE to download

**Files:** 3 default blocks + 9 inject blocks. **This is the fix.**

Keep it minimal. It touches only JJB templates plus one default in the resolver, so it
reverts cleanly if anything unexpected surfaces.

## 2a. Defaults

```yaml
# offbuild/jenkins-jobs/template-offbuild.yaml:113  and  :163
     use_code_sync_mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'

# offbuild/jenkins-jobs/template-isobuild.yaml:77
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'
```

## 2b. Propagate to the build shell

Without this, 2a has no effect — the default never reaches the script.

```yaml
      - inject:
          properties-content: |
            USE_CODE_SYNC_MGR={use_code_sync_mgr}
            CODE_SYNC_MGR_VERSION={code-sync-mgr-version}
+            CSM_SOURCE={csm-source}
```

| Template (`offbuild/jenkins-jobs/`) | Line | Placeholder style |
|---|---|---|
| `template-offbuild-android-ch-matrix.yaml` | 36–37 | underscores |
| `template-offbuild-android-ch-manifest.yaml` | 24–25 | underscores |
| `template-offbuild-android-ch.yaml` | 76 | underscores |
| `template-offbuild-android-matrix.yaml` | 31–32 | underscores |
| `template-offbuild-android-manifest.yaml` | 27–28 | underscores |
| `template-offbuild-android.yaml` | 69 | underscores |
| `template-isobuild-manifest.yaml` | 19–20 | hyphens |
| `template-isobuild-superlabel-android-matrix.yaml` | 47–48 | hyphens |
| `template-isobuild-superlabel-android.yaml` | 77 | hyphens |

> The templates mix `{use_code_sync_mgr}` (offbuild) and `{use-code-sync-mgr}`
> (isobuild). Use `{csm_source}` or `{csm-source}` to match the file being edited, and
> name the default in 2a to match — JJB fails silently on a mismatch.

## 2c. Make the script default safe too

Belt and braces: if a job is missing the inject line, the script should still do the
safe thing rather than pick up whatever the node ships.

```bash
 function get_csm_bin()
 {
-    case "${CSM_SOURCE:-system}" in
+    case "${CSM_SOURCE:-download}" in
```

And document why, above the function:

```bash
# Resolve the codesyncmgr binary to use, based on CSM_SOURCE.
#
#   CSM_SOURCE : download : always fetch the pinned build  (default)
#                system   : use the node's binary; download if absent
#
# WARNING: 'system' is unsafe while node images carry different codesyncmgr
# generations. The ubuntu20 image ships 2.0.1-0, whose cli.py DEFAULT_BUCKET
# is the bucket later versions call TEST_BUCKET, and which does not support
# --exclude. See the incident report before changing this default.
#
```

### Commit message

```
Default CSM_SOURCE to download to fix ubuntu20 restore

Restore failed on ubuntu20 matrix cells while the same workflow ID
restored successfully on ubuntu22 and ubuntu24 in the same build.
The cells were reading different S3 buckets.

The codesyncmgr binary selects the bucket, and node images carry
different generations. The ubuntu20 image ships 2.0.1-0, whose
cli.py sets DEFAULT_BUCKET to the bucket later versions call
TEST_BUCKET, expecting callers to pass --bucket or set
CODESYNCMGR_BUCKET. offbuild never did. 1.9.0 and 2.1.0 instead
default to PROD_BUCKET and gate the test bucket behind --dev-mode.

Backup still downloads the pinned 1.9.0, so a workflow backed up to
ap-northeast-1-s3codesync was restored from apne1-jenkins-cm-workflow,
which never held it -- an empty listing, six retries, then abort.

Default csm-source to 'download' so every node uses the pinned build,
restoring the behaviour that held before CSM_SOURCE was introduced,
and propagate CSM_SOURCE through the job templates so the default
reaches the build shell.
```

---

# Commit 3 — close the backup/restore asymmetry

**Files:** 6 shell call sites + 2 test templates. Hardening only; no urgency.

Only the restore sites were migrated to `get_csm_bin`. The backup sites still call
`download_csm` directly, which is the structural reason the two halves of a workflow
could resolve different binaries at all. Migrating both sides means one setting governs
the whole workflow.

## 3a. Backup call sites

```bash
# C1  offbuild/offbuild/ch/android/manifest/init.sh:117,125
# C2  offbuild/offbuild/android/manifest/init.sh:135,143

 if [ "$USE_CODE_SYNC_MGR" = "true" ]; then
-    download_csm /tmp/codesyncmgr
+    CSM_BIN="$(get_csm_bin)" || exit 1
+    echo "Using codesyncmgr: $CSM_BIN"
     mkdir $WORKSPACE/code
     (
     cd $WORKSPACE/code
     ...
-    time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID backup
+    time "$CSM_BIN" --verbose --id $WORKFLOW_ID backup
     )
 fi
```

```bash
# C3  cm_tools/hudson-scripts/isobuild-superlabel-manifest-init.sh:16,18

     cd $WORKSPACE/code
     ln -sfv $WORKSPACE/result-dir .
-    download_csm /tmp/codesyncmgr
+    CSM_BIN="$(get_csm_bin)" || exit 1
+    echo "Using codesyncmgr: $CSM_BIN"
     get_source_code
-    time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID --exclude result-dir backup
+    time "$CSM_BIN" --verbose --id $WORKFLOW_ID --exclude result-dir backup
     create_delta_report
```

> **C3 must stay on `download`.** It passes `--exclude result-dir`, and codesyncmgr
> 2.0.1-0 — the version on the ubuntu20 image — has no `--exclude` flag (it has `--root`
> instead). Running this path with `CSM_SOURCE=system` on ubuntu20 produces an argparse
> "unrecognized argument" failure, entirely separately from the bucket problem.

## 3b. Restore call sites

B1 (`ch/android/matrix/main.sh`) is already migrated and needs nothing.

```bash
# B2  offbuild/offbuild/android/matrix/main.sh:28,29
# B3  cm_tools/hudson-scripts/isobuild-superlabel-android-matrix.sh:20,21

 if [ "$USE_CODE_SYNC_MGR" = "true" ]; then
-    download_csm /tmp/codesyncmgr
-    time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID restore
+    CSM_BIN="$(get_csm_bin)" || exit 1
+    echo "Using codesyncmgr: $CSM_BIN"
+    time "$CSM_BIN" --verbose --id $WORKFLOW_ID restore
 else
     sync_static_manifest $MANIFEST_PROJECT $BRANCH ...
 fi
```

All these scripts run under `set -e` (`#!/bin/bash -ex`, the ch variants `-exu`), so
`|| exit 1` propagates correctly even from inside the `( cd … )` subshells.

## 3c. Test job templates

Migrating these means the test jobs exercise the same resolution path as production.

```bash
# offbuild/jenkins-jobs/template-csm-backup-test.yaml
# offbuild/jenkins-jobs/template-csm-restore-test.yaml

 source offbuild/common_functions.sh
-download_csm /tmp/codesyncmgr
+CSM_BIN="$(get_csm_bin)" || exit 1
+echo "Using codesyncmgr: $CSM_BIN"

 mkdir code
 (
 cd code
-time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID backup
+time "$CSM_BIN" --verbose --id $WORKFLOW_ID backup
 )
```

### Commit message

```
Resolve codesyncmgr via get_csm_bin on the backup side too

Only the restore call sites were migrated to get_csm_bin; the backup
sites still called download_csm directly. That asymmetry let the two
halves of one workflow resolve different binaries, which is how a
workflow could be backed up to one S3 bucket and restored from another.

Migrate the remaining backup and restore call sites and the CSM test
job templates, so a single CSM_SOURCE setting governs the whole
workflow.

isobuild-superlabel-manifest-init.sh passes --exclude, which
codesyncmgr 2.0.1-0 does not support; that path must stay on
CSM_SOURCE=download until the node images are uniform.
```

---

# Approaches considered and rejected

## `CODESYNCMGR_BUCKET`

Pinning the bucket by environment variable would survive version drift — but only
2.0.1-0 reads it:

```python
# 2.0.1-0, cli.py -- honours the variable
DEFAULT_BUCKET = "659398199407-apne1-jenkins-cm-workflow"
default=os.environ.get(f"{ APP_NAME.upper() }_BUCKET", DEFAULT_BUCKET)

# 1.9.0 and 2.1.0, app.py -- no environment lookup at all
def choose_bucket(args):
    if args.devmode:  bucket = TEST_BUCKET     # apne1-jenkins-cm-workflow
    else:             bucket = PROD_BUCKET     # ap-northeast-1-s3codesync
```

It patches ubuntu20 and is silently ignored everywhere else.

## A version check in `get_csm_bin`

`codesyncmgr --version` reports a Debian package version (`2.0.1-0` Apr 2024, `2.1.0`
Jan 2025) while `CODE_SYNC_MGR_VERSION` names an Artifactory archive (`1.9.0` Jul 2024).
Different channels, unrelated numbering — they never compare equal, so the guard would
fall through to download on every node. A meaningful guard would have to compare the
**resolved bucket**, not the version string.

## A bare existence preflight

An earlier draft proposed `assert_csm_backup_exists()` listing the prefix before
restore, against a hardcoded `CSM_S3_BUCKET`. Do not ship that. The bucket is chosen by
the binary, so a preflight pinned to one bucket would have *passed* on the failing
ubuntu20 cell — reporting "backup present" while codesyncmgr looked elsewhere — making
this bug harder to find, not easier.

The guard that would have caught it is a **bucket-agreement check**: have backup record
the bucket it wrote to, and have restore fail loudly when its own binary resolves a
different one. Worth building only if `system` is ever re-enabled.

---

# Re-enabling `system` later

Requires three things confirmed per label, not one:

1. the installed version resolves the same bucket the backup stage writes to,
2. it supports every flag the calling scripts pass — see C3 and `--exclude`, and
3. the fleet is uniform, so a matrix cannot mix generations within one workflow.

The durable answer is to stop the drift — get the ubuntu20 image moved off 2.0.1-0. Until
that lands, `download` is not a fallback but the correct setting, and the ticket should
carry both asks.
