# CSM restore failure — investigation and complete file change list

Covers both **offbuild** and **isobuild**. Master document; see also
`jira-update.md` (ticket text) and `csm-code-changes.md` (commit-by-commit patches).

- **Symptom:** matrix restore fails on ubuntu20 cells, passes on ubuntu22/24, same build
- **Cause:** ubuntu20 ships codesyncmgr 2.0.1-0, which defaults to the TEST S3 bucket
- **Trigger:** `CSM_SOURCE=system` let each node use its own installed binary
- **Fix:** default `CSM_SOURCE` to `download` (pins the Generation B build everywhere)

---

# Part 1 — Investigation

## 1.1 What was reported

`get_csm_bin` was introduced so the pre-installed `codesyncmgr` could be used instead of
downloading it every build. After the change, matrix cells began failing at restore:

```
+ /usr/bin/codesyncmgr --verbose --id 42c1a993-... restore
INFO: [MainProcess] Exit 'aws s3 ls s3://.../42c1a993-.../code/' with 1
INFO: [MainProcess] Stdout:
INFO: [MainProcess]
INFO: [MainProcess] Stderr:
INFO: [MainProcess]
... RETRY 1-6 over ~34s ...
ERROR: Failed to get the list of S3 objects for workflow ID: 42c1a993-...
```

## 1.2 Hypotheses tested and discarded

Recorded because each cost time, and because a reviewer will raise them.

| # | Hypothesis | How it was excluded |
|---|---|---|
| 1 | The `get_csm_bin` refactor broke binary resolution | Trace shows `CSM_BIN=/usr/bin/codesyncmgr` — clean, single line. The earlier stdout-pollution bug was already fixed by routing diagnostics to stderr. |
| 2 | Job-level S3 bucket misconfiguration | No job-level bucket setting exists. The bucket is chosen inside codesyncmgr. |
| 3 | The 24h CSM retention window expired | **Disproved decisively**: the same workflow ID restored successfully on another cell in the same build. Data cannot be both expired and present. |
| 4 | IAM / credentials on ubuntu20 | `aws s3 ls` probes return `exit=0` against *both* buckets from the ubuntu20 node. Access is fine. |
| 5 | Transient S3 or network error | Six identical retries; empty stderr. A real error always writes to stderr. |
| 6 | AWS CLI v1 vs v2 exit-code difference | Measured: ubuntu20 has aws-cli 1.38.23, ubuntu24 has 2.36.34, and **both** exit 1 with empty streams on an empty prefix. Not a CLI difference. |
| 7 | The backup never ran | Ruled out with #3 — cells 22/24 restored that exact backup. |

## 1.3 The decisive observation

One build, one `WORKFLOW_ID`, two cells, **two different buckets**:

```
ubuntu20  FAILED
+ /usr/bin/codesyncmgr --verbose --id 68c9dbd7-... restore
INFO: Exit 'aws s3 ls s3://659398199407-apne1-jenkins-cm-workflow/68c9dbd7-.../code/' with 1

ubuntu22/24  SUCCESS
+ /tmp/codesyncmgr --verbose --id 68c9dbd7-... restore
INFO: START: s3://659398199407-ap-northeast-1-s3codesync/68c9dbd7-.../code/prebuilts.tar.lz4
```

Identical workflow ID in a single build controls for everything else. The only variable
is **which binary ran**, and the binary picks the bucket.

## 1.4 Method — how the tool was interrogated

The binaries turned out to be Python zipapps (`.pyz` = plain ZIP), so no decompiler was
needed. A Jenkins shell step (`csm-binary-diagnostic.sh`) collected, per node:

- `codesyncmgr --version` and `codesyncmgr config`
- `--help` bucket-related options
- `unzip -p <pyz> cli.py / app.py / res.py`
- direct `aws s3 ls` probes with exit code and stream byte counts
- `aws --version`, `aws sts get-caller-identity`

`csm-extract-source.sh` then archived the full source as a build artifact for the ticket.

> Two false starts worth noting: a `--dryrun` probe was added to make the tool reveal its
> bucket, but `app.py` replaces the command with `true` under `--dryrun`, so it prints
> nothing. And an early version of the script died silently because Jenkins runs shell
> steps as `/bin/bash -xe` when the shebang is not the literal first line — a `grep` with
> no match aborted the run. Both fixed; the script now forces `set +e` and traps EXIT.

## 1.5 Root cause, proven from source

There are **two code generations**, not three versions. `app.py` and `cli.py` are
byte-identical between Artifactory `1.9.0` and the ubuntu24 package `2.1.0`; only
`res.py` (the version constant) differs.

### Generation B — `1.9.0`, `2.1.0` — `app.py:17-18, 181-187`

```python
TEST_BUCKET = "659398199407-apne1-jenkins-cm-workflow"
PROD_BUCKET = "659398199407-ap-northeast-1-s3codesync"

def choose_bucket(args):
    if args.devmode:
        bucket = TEST_BUCKET
    else:
        bucket = PROD_BUCKET
    return bucket
```

### Generation A — `2.0.1-0` — `cli.py:15, 42-45`

```python
DEFAULT_BUCKET = "659398199407-apne1-jenkins-cm-workflow"
...
parser.add_argument(
    "--bucket",
    dest="bucket",
    default=os.environ.get(f"{ APP_NAME.upper() }_BUCKET", DEFAULT_BUCKET),
    help=f"The name of bucket [{ APP_NAME.upper() }_BUCKET]",
)
```

**Generation A defaults to the bucket Generation B calls `TEST_BUCKET`.** It expected
callers to pass `--bucket` or set `CODESYNCMGR_BUCKET`; offbuild never has.

| Node | OS | Version | Generation | Effective bucket |
|------|----|---------|------------|------------------|
| ubuntu20 | 20.04.6 | `2.0.1-0` | **A** | `apne1-jenkins-cm-workflow` (TEST) |
| ubuntu24 | 24.04.4 | `2.1.0` | B | `ap-northeast-1-s3codesync` (PROD) |
| downloaded | any | `1.9.0` | B | `ap-northeast-1-s3codesync` (PROD) |

Version numbers are not one lineage — `2.0.1-0` is a Debian package revision (Apr 2024),
`1.9.0` an Artifactory archive (Jul 2024). Different channels, so
`codesyncmgr --version` and `CODE_SYNC_MGR_VERSION` **can never compare equal**.

## 1.6 Why the failure was opaque

`app.py:148` — `run_cmd()` retries any non-zero exit and logs only the captured streams:

```python
def run_cmd(cmdline, args, *, expect=lambda x: x if x.returncode == SP_RUN_SUCCESS else None):
    while retries < args.retries:
        ret = SP.run(cmdline, capture_output=True, shell=True, text=True, executable=BASH)
        result = expect(ret)
        if not result:
            if args.verbose:
                logging.info("Exit '%s' with %d", cmdline, ret.returncode)
                logging.info("Stdout:"); logging.info(ret.stdout)
                logging.info("Stderr:"); logging.info(ret.stderr)
            time.sleep(interval); retries += 1
            logging.warning("RETRY %d", retries)
```

An empty prefix exits 1 with both streams empty — indistinguishable from a transient
error to this loop. Hence six retries at five-second intervals (`--retries` 6,
`--interval` 5) before aborting.

`app.py:257-292` — `restore()` makes **two** listings. The first, of the bucket root,
**succeeded** (no `Not found bucket` in the log), proving the bucket is reachable. Only
the second, of the workflow prefix, came back empty:

```python
def restore(args):
    url = S3_URL_BUCKET.format(args.bucket)         # s3://<bucket>/
    ret = run_cmd(f"{args.awscli} s3 ls {url}", args)
    if not ret:
        logging.error("Not found bucket: %s", args.bucket)
        return False
    ...
    url = S3_URL_BASE.format(args.bucket, args.id)  # s3://<bucket>/<id>/code/
    ret = run_cmd(f"{args.awscli} s3 ls {url}", args)
    ...
    else:
        logging.error("Failed to get the list of S3 objects for workflow ID: %s", args.id)
        return False
```

The final error names the **workflow ID but not the bucket** — which is why this read as
"the backup is missing" rather than "we are looking in the wrong place".

## 1.7 Why it only started failing now

Before `CSM_SOURCE`, every node ran `download_csm` → Generation B → PROD bucket. Backup
and restore always agreed, and the 2.0.1-0 binary on the ubuntu20 image was never
executed. `CSM_SOURCE=system` exposed it.

Backup and restore are also pinned to **independent** node pools:

```yaml
manifest_label:    'CM_REPOSYNC_CSM'      # backup  (template-*-manifest.yaml)
matrix_cell_label: 'CM_ANDROID_CSM_SBE'   # restore (template-*-matrix.yaml)
```

Nothing in the configuration ties the backup node's codesyncmgr generation to the
restore node's. Two consequences:

1. **Backups are always correct today** — the manifest job runs on ubuntu22/24, so the
   backup always lands in PROD. No data loss; the data is simply in the bucket ubuntu20
   is not reading.
2. **The reverse failure is worse and unguarded** — if the manifest job ever lands on an
   ubuntu20 agent under `CSM_SOURCE=system`, backup would write to TEST, and then *every*
   ubuntu22/24 cell would fail. Today's failure is partial; that one would be total.

## 1.8 Second defect — CLI incompatibility

The CLI changed incompatibly in **both** directions:

| Generation | Has | Lacks |
|---|---|---|
| A (`2.0.1-0`) | `--bucket`, `--root` | `--exclude`, `--dev-mode` |
| B (`1.9.0`, `2.1.0`) | `--exclude`, `--dev-mode` | `--bucket`, `--root` |

`cm_tools/hudson-scripts/isobuild-superlabel-manifest-init.sh:18` passes
`--exclude result-dir`. On a Generation A node that is an unrecognized argument —
argparse error, immediate failure. Invisible today only because that path still
downloads Generation B.

**This is why `CSM_SOURCE=system` cannot be made safe by fixing the bucket alone.** The
offbuild and isobuild scripts are written against a specific CLI contract, and node
images drift independently of them.

## 1.9 Incidental findings

**Console logs leak service credentials.** `download_csm` runs under `set -x`, so the
buildrepo API response — live Artifactory reftokens for swerepo, gradle, pypi,
sonybuildenv and globaltools — is echoed into every CSM build's console log. Fixed in
commit 1. Existing logs still contain them; rotation should be raised separately.

**STS unreachable on ubuntu20.** `aws sts get-caller-identity` hangs for 90s+ while
`aws s3 ls` works normally. Credentials are fine; only the STS endpoint is blocked.
Unrelated to this failure.

---

# Part 2 — Complete file change list

19 files. Grouped by commit; **commit 2 alone unblocks ubuntu20.**

## 2.1 Master inventory

| # | File | Commit | Change |
|---|------|--------|--------|
| 1 | `offbuild/common_functions.sh` | 1, 2 | Credential trace fix; `get_csm_bin` default → `download` |
| 2 | `offbuild/jenkins-jobs/template-offbuild.yaml` | 2 | `csm-source: 'download'` at **:113** and **:163** |
| 3 | `offbuild/jenkins-jobs/template-isobuild.yaml` | 2 | `csm-source: 'download'` at **:77** |
| 4 | `offbuild/jenkins-jobs/template-offbuild-android-ch-matrix.yaml` | 2 | inject `CSM_SOURCE` at **:36** |
| 5 | `offbuild/jenkins-jobs/template-offbuild-android-ch-manifest.yaml` | 2 | inject `CSM_SOURCE` at **:24** |
| 6 | `offbuild/jenkins-jobs/template-offbuild-android-ch.yaml` | 2 | inject `CSM_SOURCE` at **:76** |
| 7 | `offbuild/jenkins-jobs/template-offbuild-android-matrix.yaml` | 2 | inject `CSM_SOURCE` at **:31** |
| 8 | `offbuild/jenkins-jobs/template-offbuild-android-manifest.yaml` | 2 | inject `CSM_SOURCE` at **:27** |
| 9 | `offbuild/jenkins-jobs/template-offbuild-android.yaml` | 2 | inject `CSM_SOURCE` at **:69** |
| 10 | `offbuild/jenkins-jobs/template-isobuild-manifest.yaml` | 2 | inject `CSM_SOURCE` at **:19** |
| 11 | `offbuild/jenkins-jobs/template-isobuild-superlabel-android-matrix.yaml` | 2 | inject `CSM_SOURCE` at **:47** |
| 12 | `offbuild/jenkins-jobs/template-isobuild-superlabel-android.yaml` | 2 | *optional* — inject at **:77** for visibility only |
| 13 | `offbuild/offbuild/ch/android/manifest/init.sh` | 3 | backup → `get_csm_bin` (**:117, :125**) |
| 14 | `offbuild/offbuild/android/manifest/init.sh` | 3 | backup → `get_csm_bin` (**:135, :143**) |
| 15 | `offbuild/offbuild/android/matrix/main.sh` | 3 | restore → `get_csm_bin` (**:28, :29**) |
| 16 | `cm_tools/hudson-scripts/isobuild-superlabel-manifest-init.sh` | 3 | backup → `get_csm_bin` (**:16, :18**) |
| 17 | `cm_tools/hudson-scripts/isobuild-superlabel-android-matrix.sh` | 3 | restore → `get_csm_bin` (**:20, :21**) |
| 18 | `offbuild/jenkins-jobs/template-csm-backup-test.yaml` | 3 | → `get_csm_bin` |
| 19 | `offbuild/jenkins-jobs/template-csm-restore-test.yaml` | 3 | → `get_csm_bin` |

**No change needed:** `offbuild/offbuild/ch/android/matrix/main.sh` — already migrated.

**No change needed:** `offbuild/isobuild/scriptutils.source` — line 5 already does
`source ${CURRENT_SCRIPT_DIR}/../common_functions.sh`, so isobuild picks up
`get_csm_bin` automatically.

## 2.2 Commit 1 — stop tracing buildrepo credentials

`offbuild/common_functions.sh`

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

## 2.3 Commit 2 — default CSM_SOURCE to download

### Defaults

```yaml
# template-offbuild.yaml:113 and :163      (underscore convention)
     use_code_sync_mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'

# template-isobuild.yaml:77                (hyphen convention)
     use-code-sync-mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'
```

### Inject blocks — 8 required, 1 optional

```yaml
      - inject:
          properties-content: |
            USE_CODE_SYNC_MGR={use_code_sync_mgr}
            CODE_SYNC_MGR_VERSION={code-sync-mgr-version}
+            CSM_SOURCE={csm-source}
```

> **Placeholder style differs by family.** offbuild templates use
> `{use_code_sync_mgr}` (underscores); isobuild templates use `{use-code-sync-mgr}`
> (hyphens). Match whichever the file already uses and name the default to match, or JJB
> fails silently.

`template-isobuild-superlabel-android.yaml:77` injects only `USE_CODE_SYNC_MGR` — it is
the master job that mints the workflow UUID (line 121) and never runs codesyncmgr
itself, so `CSM_SOURCE` there is optional, for debugging visibility only.

### Script-level default

```bash
 function get_csm_bin()
 {
-    case "${CSM_SOURCE:-system}" in
+    case "${CSM_SOURCE:-download}" in
```

Belt and braces: a job missing the inject line still does the safe thing.

## 2.4 Commit 3 — migrate the remaining call sites

### offbuild backup — files 13, 14

```bash
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

### offbuild restore — file 15

```bash
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

### isobuild backup — file 16

```bash
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

### isobuild restore — file 17

```bash
 if [ "$USE_CODE_SYNC_MGR" = "true" ]; then
-    download_csm /tmp/codesyncmgr
-    time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID restore
+    CSM_BIN="$(get_csm_bin)" || exit 1
+    echo "Using codesyncmgr: $CSM_BIN"
+    time "$CSM_BIN" --verbose --id $WORKFLOW_ID restore
 else
     get_source_code
 fi
```

### CSM test templates — files 18, 19

```bash
 source offbuild/common_functions.sh
-download_csm /tmp/codesyncmgr
+CSM_BIN="$(get_csm_bin)" || exit 1
+echo "Using codesyncmgr: $CSM_BIN"
 ...
-time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID backup
+time "$CSM_BIN" --verbose --id $WORKFLOW_ID backup
```

All these scripts run under `set -e` (`#!/bin/bash -ex`, ch variants `-exu`), so
`|| exit 1` propagates correctly from inside the `( cd … )` subshells.

---

# Part 3 — isobuild-specific notes

## 3.1 isobuild must stay on `download`

`template-isobuild.yaml` maps the Android components to **ubuntu20** labels:

```yaml
android-qssi:   CM_20_ANDROID
android-target: CM_20_ANDROID
```

So isobuild matrix cells land on Generation A, which breaks `CSM_SOURCE=system` in two
independent ways:

1. Generation A defaults to the TEST bucket (§1.5)
2. Generation A has no `--exclude`, which the isobuild backup passes (§1.8)

Migrate isobuild to `get_csm_bin` for consistency, but treat `system` as **unavailable**
there until the ubuntu20 image moves off 2.0.1-0.

> The `CM_20_*` values above are from the DUMMY default block. Confirm the real
> `jenkins_label_sets` for each project before assuming this holds everywhere.

## 3.2 Ordering caveat in the isobuild backup

`get_source_code` runs *between* binary resolution and the backup call. Under `download`
the binary sits in `/tmp` across that step. Confirm `get_source_code` does not clear
`/tmp` on these agents; if it does, move the `get_csm_bin` call to immediately before the
`backup` line.

---

# Part 4 — Rejected approaches

| Approach | Why it fails |
|---|---|
| Set `CODESYNCMGR_BUCKET` | Only Generation A reads it (`os.environ.get`). Generation B's `choose_bucket()` has no environment lookup — silently ignored on ubuntu22/24. |
| Version check in `get_csm_bin` | `--version` reports package versions (`2.0.1-0`, `2.1.0`); `CODE_SYNC_MGR_VERSION` names an Artifactory archive (`1.9.0`). Different channels — never equal. |
| Preflight `aws s3 ls` before restore | Would hardcode a bucket. Pinned to PROD it would have *passed* on the failing cell, reporting "backup present" while codesyncmgr looked elsewhere — making this harder to find. A **bucket-agreement** check (backup records its bucket, restore compares) is the only version of this worth building. |

---

# Part 5 — Verification and follow-ups

## Verification

1. Re-run the failing matrix cell; confirm the console shows `/tmp/codesyncmgr` and
   bucket `ap-northeast-1-s3codesync`, and that restore succeeds.
2. Grep every cell of a full build for the bucket name; confirm all cells agree.
3. Run one isobuild superlabel build end to end (backup on the manifest node, restore on
   an ubuntu20 cell) and confirm both stages use the pinned build.

## Follow-ups (separate tickets)

1. **Rotate buildrepo credentials** — commit 1 stops new leakage only.
2. **Move the ubuntu20 image off codesyncmgr 2.0.1-0** — the durable fix; until then
   `CSM_SOURCE=system` cannot be enabled anywhere.
3. **Review matrix cell label membership** — if one label spans ubuntu20 and ubuntu22/24
   agents, cells land on either by scheduling and this failure is intermittent.
4. **Upstream request** — include the bucket in the `Failed to get the list of S3
   objects` error message.
5. **STS unreachable on ubuntu20** — unrelated, credentials otherwise fine.

---

# Appendix — supporting files in this folder

| File | Purpose |
|---|---|
| `jira-update.md` | Paste-ready ticket text |
| `csm-code-changes.md` | Commit-by-commit patches with commit messages |
| `csm-restore-failure-report.md` | Narrative root-cause report |
| `csm-binary-diagnostic.sh` | Jenkins shell step: version + bucket + probes per node |
| `csm-extract-source.sh` | Jenkins shell step: archive codesyncmgr source as artifacts |
| `artifacts_codesyncmgr/` | Archived `.pyz` + source for all three versions, with md5s |
| `logs.txt` | Original failing and passing console output |
| `codesyncmgr-chat.md` | Earlier working log (its §6 bucket observation was correct) |
