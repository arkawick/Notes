# CSM restore fails on ubuntu20 — restore reads the TEST S3 bucket

*Paste-ready JIRA update. Evidence is from job
`TEST_DRY_RUN_CM_Cherry-pick_shimanto-1.1.0-rel_system` builds #4–#9 and the archived
codesyncmgr source (`csm-src` artifacts).*

---

## Summary

Matrix builds using Code Sync Manager fail on ubuntu20 cells while the **same workflow
ID succeeds on ubuntu22 and ubuntu24 in the same build**. The cells read different S3
buckets.

The codesyncmgr binary — not the job config — decides which bucket to use. The ubuntu20
image ships codesyncmgr **2.0.1-0**, whose default bucket is the one every later version
names `TEST_BUCKET`. Backup writes to the production bucket, so the ubuntu20 restore
looks in a bucket that never held the data, gets an empty listing, retries six times and
aborts.

Introduced by defaulting `CSM_SOURCE=system`, which lets each node use its own installed
binary instead of the pinned build.

**Fix:** default `CSM_SOURCE` to `download`. Restores pre-change behaviour and unblocks
ubuntu20 immediately.

---

## Impact

- All CSM-enabled matrix builds fail on any ubuntu20 cell (label `CM_20_ANDROID_CSM`).
- Failure mode is opaque: 34 seconds of silent retries, then
  `Failed to get the list of S3 objects for workflow ID`, with no mention of the bucket.
- No data loss. Backups are intact in the production bucket; only restore is affected.
- ubuntu22 / ubuntu24 cells are unaffected.

---

## Root cause

### There are two code generations, not three versions

The three binaries in play carry three version strings, but only **two** distinct
codebases. `app.py` and `cli.py` are byte-identical between the Artifactory archive
`1.9.0` and the ubuntu24 package `2.1.0`; only `res.py` (the version constant) differs.

| Generation | Version strings | Built | Bucket selection | Flags |
|---|---|---|---|---|
| **A** | `2.0.1-0` | Apr 2024 | `cli.py:15` `DEFAULT_BUCKET`, overridable by `CODESYNCMGR_BUCKET` | `--bucket`, `--root` |
| **B** | `1.9.0`, `2.1.0` | Jul 2024 / Jan 2025 | `app.py:181` `choose_bucket()` | `--exclude`, `--dev-mode` |

Note the version numbers are not one lineage: `2.0.1-0` is a Debian package revision,
`1.9.0` is an Artifactory archive name. They come from different distribution channels,
so **`codesyncmgr --version` and `CODE_SYNC_MGR_VERSION` are not comparable**.

### Generation B — bucket chosen by `--dev-mode`

`app.py:17-18, 181-187`

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

Default is PROD. The test bucket requires an explicit `--dev-mode`.

### Generation A — bucket defaults to TEST

`cli.py:15, 42-45`

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
callers to pass `--bucket` or set `CODESYNCMGR_BUCKET`. offbuild has never set either.

### Why that only started failing now

Before `CSM_SOURCE` was introduced, every node ran `download_csm`, which fetches the
pinned build — Generation B — so backup and restore always agreed. `CSM_SOURCE=system`
made each node use its installed binary, and the ubuntu20 image is the only one still on
Generation A.

Backup still downloads the pinned build (`offbuild/offbuild/ch/android/manifest/init.sh:117`),
so within one workflow:

| Stage | Binary | Bucket |
|---|---|---|
| backup (manifest job) | pinned 1.9.0 — Gen B | `ap-northeast-1-s3codesync` |
| restore (ubuntu20 cell) | `/usr/bin/codesyncmgr` 2.0.1-0 — Gen A | `apne1-jenkins-cm-workflow` |
| restore (ubuntu22/24 cell) | `/usr/bin/codesyncmgr` 2.1.0 — Gen B | `ap-northeast-1-s3codesync` |

---

## Evidence

### 1. Same workflow, same build, two buckets

ubuntu20 cell — **FAILED**:

```
+ /usr/bin/codesyncmgr --verbose --id 68c9dbd7-b2a9-4d70-b1ea-50d87fd1f456 restore
INFO: [MainProcess] Exit 'aws s3 ls s3://659398199407-apne1-jenkins-cm-workflow/68c9dbd7-.../code/' with 1
INFO: [MainProcess] Stdout:
INFO: [MainProcess]
INFO: [MainProcess] Stderr:
INFO: [MainProcess]
WARNING: [MainProcess] RETRY 1
...
ERROR: [MainProcess] Failed to get the list of S3 objects for workflow ID: 68c9dbd7-...
FAILED
```

ubuntu22 / ubuntu24 cells — **SUCCESS**:

```
+ /tmp/codesyncmgr --verbose --id 68c9dbd7-b2a9-4d70-b1ea-50d87fd1f456 restore
INFO: [ForkPoolWorker-1] START: s3://659398199407-ap-northeast-1-s3codesync/68c9dbd7-.../code/prebuilts.tar.lz4
INFO: [ForkPoolWorker-2] START: s3://659398199407-ap-northeast-1-s3codesync/68c9dbd7-.../code/vendor.tar.lz4
```

Identical workflow ID in one build, so this controls for everything else: **the backup
exists**, retention is irrelevant, credentials are fine, the workflow is fine. The only
variable is which binary ran.

### 2. Confirmed from the tool

```
ubuntu20  /usr/bin/codesyncmgr -> /opt/sys/somc/bin/codesyncmgr.pyz  (Apr 23 2024)
          --version : 2.0.1-0
          config    : bucket: 659398199407-apne1-jenkins-cm-workflow

ubuntu24  /usr/bin/codesyncmgr -> /opt/sys/somc/bin/codesyncmgr.pyz  (Jan  8 2025)
          --version : 2.1.0
          config    : (no bucket line -- not user-configurable in Gen B)
```

### 3. Not a permissions problem

Direct `aws s3 ls` probes, identical on both node types:

```
probe s3codesync-root  exit=0  stdout=828B  stderr=0B  lines=12
probe apne1-root       exit=0  stdout=69B   stderr=0B  lines=1
probe empty-prefix     exit=1  stdout=0B    stderr=0B  lines=0
```

Both nodes can read both buckets. The ubuntu20 role has access to the bucket it is
wrongly reading — it is simply empty for this workflow.

### 4. Why the failure looks like nothing went wrong

`app.py:148` — `run_cmd()` retries on any non-zero exit and only logs the streams:

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

An empty S3 prefix exits 1 with both streams empty, which is indistinguishable from a
transient error to this loop — hence six retries at five-second intervals (`--retries`
default 6, `--interval` default 5) before giving up.

`app.py:257-292` — `restore()` makes two listings. The first, of the bucket root,
**succeeded** (no `Not found bucket` in the log), proving the bucket is reachable. The
second, of the workflow prefix, returned empty:

```python
def restore(args):
    url = S3_URL_BUCKET.format(args.bucket)        # s3://<bucket>/
    ret = run_cmd(f"{args.awscli} s3 ls {url}", args)
    if not ret:
        logging.error("Not found bucket: %s", args.bucket)
        return False
    ...
    url = S3_URL_BASE.format(args.bucket, args.id) # s3://<bucket>/<id>/code/
    ret = run_cmd(f"{args.awscli} s3 ls {url}", args)
    ...
    else:
        logging.error("Failed to get the list of S3 objects for workflow ID: %s", args.id)
        return False
```

Note the final error names the **workflow ID but not the bucket**. That is why this
presented as "the backup is missing" rather than "we are looking in the wrong place".

---

## Fix

Three commits, separated so the fix can be reviewed and reverted on its own.

### Commit 1 — stop tracing buildrepo credentials *(unrelated; land independently)*

`offbuild/common_functions.sh`. Under `set -x`, `download_csm` echoes the full buildrepo
API response — live Artifactory reftokens for swerepo, gradle, pypi, sonybuildenv and
globaltools — into every CSM build's console log.

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
     ...
+    [ -n "$_xtrace" ] && set -x
     return 0
 }
```

### Commit 2 — default CSM_SOURCE to download *(this is the fix)*

Defaults, in `offbuild/jenkins-jobs/`:

```yaml
# template-offbuild.yaml:113 and :163, template-isobuild.yaml:77
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'
```

Propagate to the build shell — without this the default never reaches the script. Nine
`properties-content` blocks:

```yaml
      - inject:
          properties-content: |
            USE_CODE_SYNC_MGR={use_code_sync_mgr}
            CODE_SYNC_MGR_VERSION={code-sync-mgr-version}
+            CSM_SOURCE={csm-source}
```

`template-offbuild-android-ch-matrix.yaml:36`, `-ch-manifest.yaml:24`, `-ch.yaml:76`,
`-android-matrix.yaml:31`, `-android-manifest.yaml:27`, `-android.yaml:69`,
`template-isobuild-manifest.yaml:19`, `-superlabel-android-matrix.yaml:47`,
`-superlabel-android.yaml:77`.

*The offbuild templates use underscores (`{use_code_sync_mgr}`), isobuild uses hyphens.
Match the file being edited or JJB fails silently.*

Make the script default safe too:

```bash
 function get_csm_bin()
 {
-    case "${CSM_SOURCE:-system}" in
+    case "${CSM_SOURCE:-download}" in
```

### Commit 3 — close the backup/restore asymmetry *(hardening)*

Only the restore sites were migrated to `get_csm_bin`; backup sites still call
`download_csm` directly, which is the structural reason the two halves of a workflow can
resolve different binaries.

Migrate `ch/android/manifest/init.sh:117,125`, `android/manifest/init.sh:135,143`,
`isobuild-superlabel-manifest-init.sh:16,18`, `android/matrix/main.sh:28,29`,
`isobuild-superlabel-android-matrix.sh:20,21`, and both CSM test templates.

⚠️ `isobuild-superlabel-manifest-init.sh:18` passes `--exclude result-dir`, which
**Generation A does not support** (it has `--root` instead). That path must stay on
`CSM_SOURCE=download` regardless — otherwise ubuntu20 fails there with an argparse
error, separately from the bucket problem.

---

## Rejected approaches

| Approach | Why it fails |
|---|---|
| Set `CODESYNCMGR_BUCKET` | Only Generation A reads it. Generation B's `choose_bucket()` has no environment lookup, so it is silently ignored on ubuntu22/24. |
| Version check in `get_csm_bin` | `--version` reports package versions (`2.0.1-0`, `2.1.0`); `CODE_SYNC_MGR_VERSION` names an Artifactory archive (`1.9.0`). Different channels — they never compare equal. |
| Preflight `aws s3 ls` before restore | Would have to hardcode a bucket. Pinned to the production bucket it would have *passed* on the failing cell, reporting "backup present" while codesyncmgr looked elsewhere — making this harder to find. |

---

## Verification

1. Re-run the failing matrix cell with `CSM_SOURCE=download`; confirm the console shows
   `/tmp/codesyncmgr` and bucket `ap-northeast-1-s3codesync`, and that restore succeeds.
2. Grep every cell of a full build for the bucket name; confirm all cells agree.
3. Confirm the ubuntu20 cell completes the full matrix.

---

## Follow-up items (separate tickets)

1. **Rotate buildrepo credentials.** Commit 1 stops new leakage, but Artifactory
   reftokens for five services are already present in historical console logs.
2. **Move the ubuntu20 image off codesyncmgr 2.0.1-0.** While node images carry
   different generations, `CSM_SOURCE=system` cannot be made safe — the two generations
   differ in both bucket default and CLI surface. This is the durable fix.
3. **Upstream request to codesyncmgr owners:** include the bucket in the
   `Failed to get the list of S3 objects` error. The message names the workflow ID only,
   which sent this investigation toward "missing backup" rather than "wrong bucket".
4. **STS unreachable on ubuntu20.** `aws sts get-caller-identity` hangs for 90s+ while
   `aws s3 ls` works normally. Unrelated to this failure; credentials themselves are fine.

---

## Attachments

- `csm-src/system-2.0.1-0/` — ubuntu20 binary + source, md5 `7339ea9e78fbdc6443452eb81a68e1e2`
- `csm-src/system-2.1.0/` — ubuntu24 binary + source, md5 `0964efd51c39b0c208861b47e8a9fb06`
- `csm-src/pinned-1.9.0/` — Artifactory build + source, md5 `c04b724b78a7ad61b69c1049d6323de2`
- Console logs: builds #4–#9 of `TEST_DRY_RUN_CM_Cherry-pick_shimanto-1.1.0-rel_system`

*Redact the buildrepo API response from any console log predating commit 1.*
