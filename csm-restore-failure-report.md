# CSM restore failure — root cause report

**Workflow ID:** `68c9dbd7-b2a9-4d70-b1ea-50d87fd1f456` (also seen as `42c1a993-...`)
**Job:** `offbuild_feature-a16-chikugo-bpf-test_matrix`, label `CM_ANDROID_CSM_SBE`
**Date of analysis:** 2026-09-13
**Verdict:** Caused by `CSM_SOURCE=system`. Node images carry three different
codesyncmgr versions with incompatible bucket defaults and incompatible CLIs. The
ubuntu20 image ships 2.0.1-0, which defaults to a different S3 bucket than the one
the backup stage writes to.

---

## 1. The decisive evidence

One build. One workflow ID. Two matrix cells. Two different buckets.

**ubuntu20 cell — system binary:**

```
+ /usr/bin/codesyncmgr --verbose --id 68c9dbd7-b2a9-4d70-b1ea-50d87fd1f456 restore
INFO: [MainProcess] Exit 'aws s3 ls s3://659398199407-apne1-jenkins-cm-workflow/68c9dbd7-.../code/' with 1
INFO: [MainProcess] Stdout:
INFO: [MainProcess]
INFO: [MainProcess] Stderr:
INFO: [MainProcess]
WARNING: [MainProcess] RETRY 1
```

**ubuntu22 / ubuntu24 cells — downloaded 1.9.0 binary:**

```
+ /tmp/codesyncmgr --verbose --id 68c9dbd7-b2a9-4d70-b1ea-50d87fd1f456 restore
INFO: [ForkPoolWorker-1] START: s3://659398199407-ap-northeast-1-s3codesync/68c9dbd7-.../code/prebuilts.tar.lz4
INFO: [ForkPoolWorker-2] START: s3://659398199407-ap-northeast-1-s3codesync/68c9dbd7-.../code/vendor.tar.lz4
```

Because the workflow ID is identical and both cells ran in the same build, every
competing explanation is controlled for:

- **The backup exists** — cells 22/24 restored it.
- **Retention is not involved** — same ID, same window, one succeeded.
- **Credentials are not involved** — the listing returned cleanly, just with no keys.
- **The workflow is not involved** — it is the same workflow.

The only variable is which binary ran, and the binary decides which bucket to read.

## 2. Confirmed from the tool itself

`codesyncmgr config` was run on both node types (job
`TEST_DRY_RUN_CM_Cherry-pick_shimanto-1.1.0-rel_system` #4 and #5).

### ubuntu20 — `ip-10-26-21-62`, Ubuntu 20.04.6

```
/usr/bin/codesyncmgr -> /opt/sys/somc/bin/codesyncmgr.pyz   (symlink dated Apr 23 2024)
version : 2.0.1-0
  --bucket BUCKET   The name of bucket [CODESYNCMGR_BUCKET]
                    (default: 659398199407-apne1-jenkins-cm-workflow)
config output:
  bucket: 659398199407-apne1-jenkins-cm-workflow
```

### ubuntu24 — `ip-10-26-30-144`, Ubuntu 24.04.4

```
/usr/bin/codesyncmgr -> /opt/sys/somc/bin/codesyncmgr.pyz   (symlink dated Jan 8 2025)
version : 2.1.0
  (no --bucket option at all; --dev-mode "Enable dedicated bucket for verification")
config output:
  (no bucket line -- the bucket is no longer user-configurable)
embedded strings:
  659398199407-apne1-jenkins-cm-workflow
  659398199407-ap-northeast-1-s3codesync
```

### Version matrix

| Node | OS | codesyncmgr | Image dated | `--bucket` | Effective bucket |
|------|----|-------------|-------------|------------|------------------|
| ubuntu20 | 20.04.6 | **2.0.1-0** | Apr 2024 | yes, default `apne1-jenkins-cm-workflow` | `apne1-jenkins-cm-workflow` |
| ubuntu24 | 24.04.4 | **2.1.0** | Jan 2025 | removed | `ap-northeast-1-s3codesync` |
| downloaded | — | 1.9.0 | pinned by `CODE_SYNC_MGR_VERSION` | — | `ap-northeast-1-s3codesync` |

The effective bucket for 2.1.0 and 1.9.0 is taken from the restore logs, where both
printed `s3://659398199407-ap-northeast-1-s3codesync/...` and succeeded.

**2.0.1-0 is the outlier.** 1.9.0 and 2.1.0 agree; the ubuntu20 image is stranded on a
release whose default points elsewhere.

### Proven from the source

The binaries are Python zipapps (`.pyz`) containing four plain source files, so the
bucket logic is directly readable with `unzip -p`. No inference is required.

**1.9.0 and 2.1.0** — `app.py`:

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

**2.0.1-0** — `cli.py`:

```python
DEFAULT_BUCKET = "659398199407-apne1-jenkins-cm-workflow"
...
default=os.environ.get(f"{ APP_NAME.upper() }_BUCKET", DEFAULT_BUCKET),
```

**2.0.1-0 defaults to the bucket that every other version calls `TEST_BUCKET`.** It
expected callers to pass `--bucket` or set `CODESYNCMGR_BUCKET`; offbuild never did.
1.9.0 and 2.1.0 default to `PROD_BUCKET` and gate the test bucket behind `--dev-mode`.

So the ubuntu20 image runs the one version where taking no action means "use the test
bucket". Restore then lists a bucket the backup never wrote to.

Note also that `2.0.1-0` is a Debian package revision from Apr 2024 while the
Artifactory archive `codesyncmgr-1.9.0` is from Jul 2024 — these are two different
distribution channels with unrelated numbering. `codesyncmgr --version` and
`CODE_SYNC_MGR_VERSION` are therefore **not comparable**, and any check that compares
them directly would never match on any node.

## 3. Root cause

`get_csm_bin()` with `CSM_SOURCE=system` resolves whatever `codesyncmgr` is installed on
the node, with no version check:

```bash
system)
    if command -v codesyncmgr 2>/dev/null; then
        :                     # accepts any version present on the node
    else
        ...
```

On ubuntu20 that is 2.0.1-0, whose default bucket is
`659398199407-apne1-jenkins-cm-workflow`. The backup stage, which still calls
`download_csm` pinned to `CODE_SYNC_MGR_VERSION=1.9.0`, wrote the tree to
`659398199407-ap-northeast-1-s3codesync`.

Backup and restore therefore used different storage locations within a single workflow.
The restore listed a bucket that never held this data, got an empty result, retried, and
aborted.

Before this change every node downloaded 1.9.0, so backup and restore always agreed and
the 2.0.1-0 binary on the ubuntu20 image was never executed. The change exposed it.

### Why the log looks like nothing is wrong

`aws s3 ls` exits 1 with **both stdout and stderr empty** when a prefix has no keys. A
genuine error (`NoSuchBucket`, `AccessDenied`, missing credentials) always writes to
stderr. Silence on both streams means the call succeeded and found nothing — exactly
what reading the wrong bucket produces.

This was measured directly on both node types, with identical results:

```
probe s3codesync-root  exit=0  stdout=828B  stderr=0B  lines=12
probe apne1-root       exit=0  stdout=69B   stderr=0B  lines=1
probe empty-prefix     exit=1  stdout=0B    stderr=0B  lines=0
```

Two things follow. **Both nodes can read both buckets**, so this is not a permissions
problem — the ubuntu20 role has access to the bucket it is wrongly reading. And the
`exit=1 / 0B / 0B` signature is reproducible on demand, which is what makes the failing
log's identical signature meaningful.

> An earlier revision of this report attributed that exit code to an AWS CLI v1-vs-v2
> difference. That was wrong: ubuntu20 runs aws-cli 1.38.23 and ubuntu24 runs 2.36.34,
> and both produce `exit=1` with empty streams on an empty prefix. The conclusion is
> unchanged; the explanation was.

The retry loop is stock behaviour: `--retries` defaults to 6 and `--interval` to 5 on
every version, matching the six retries at five-second spacing in the log.

## 4. A second, latent break

The CLI surface changed incompatibly in **both** directions:

| Version | Has | Lacks |
|---------|-----|-------|
| 2.0.1-0 | `--bucket`, `--root` | `--exclude` |
| 2.1.0 | `--exclude`, `--dev-mode` | `--bucket`, `--root` |

`cm_tools/hudson-scripts/isobuild-superlabel-manifest-init.sh:18` runs:

```bash
time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID --exclude result-dir backup
```

On a 2.0.1-0 node `--exclude` is an unrecognized argument — argparse error, immediate
failure. This is invisible today only because that path still downloads 1.9.0. Migrating
it to `CSM_SOURCE=system` would break ubuntu20 in a second, unrelated way.

This is the strongest argument for the ticket: **the offbuild scripts are written
against a specific codesyncmgr CLI contract, and that contract changed incompatibly
across 1.9.0 → 2.0.1-0 → 2.1.0.** `CSM_SOURCE=system` cannot be safe while node images
drift independently of the scripts that call them.

## 5. Fix

**Set `CSM_SOURCE=download` as the default.** This pins 1.9.0 everywhere, restores the
pre-change behaviour exactly, and unblocks ubuntu20 immediately.

### `CODESYNCMGR_BUCKET` is not a substitute

Setting the bucket explicitly looks attractive but does not generalise. The source shows
why: 2.0.1-0 reads `os.environ.get("CODESYNCMGR_BUCKET", DEFAULT_BUCKET)`, while 1.9.0
and 2.1.0 have no such lookup at all — `choose_bucket()` consults only `--dev-mode`.

So the variable is honoured on 2.0.1-0 and silently ignored everywhere else. It would
patch ubuntu20 and do nothing on any other node. Harmless as defence in depth, but not
the fix.

### Re-enabling `system` later

Requires three things confirmed per label, not one:

1. the installed version resolves the same bucket the backup stage writes to,
2. it supports every flag the calling scripts pass (`--exclude`, etc.), and
3. the fleet is uniform, so a matrix cannot mix generations within one workflow.

Note that a naive version check cannot deliver (1): `codesyncmgr --version` reports a
package version (`2.0.1-0`, `2.1.0`) while `CODE_SYNC_MGR_VERSION` names an Artifactory
archive (`1.9.0`). They are different numbering schemes from different channels and will
never compare equal. A meaningful guard has to read the resolved bucket, not the version
string.

The durable answer is to stop the drift: get the ubuntu20 image moved off 2.0.1-0 so the
fleet is uniform. Until then, `download` is not a fallback but the correct setting.

## 5a. Incidental findings

Two issues surfaced during this investigation that are unrelated to the restore failure
and should be tracked separately.

### Console logs leak service credentials

`download_csm` runs under `set -x`, so the buildrepo API response is echoed into every
CSM build's console log — live Artifactory reftokens for swerepo, gradle, pypi,
sonybuildenv and globaltools. Anyone attaching a console log to a ticket distributes
five service credentials.

This is fixed in **commit 1** of `csm-code-changes.md`, which is deliberately separate
from the restore fix so it can land on its own. Note that the fix only stops new
leakage — the tokens are already present in existing console logs, so rotation should be
raised with whoever owns the buildrepo credentials.

### STS appears blocked on ubuntu20

On both ubuntu20 nodes tested, `aws sts get-caller-identity` hung for the full 90s
timeout while `aws s3 ls` worked normally against both buckets. Credentials themselves
are fine; only the STS endpoint is unreachable. Worth raising with whoever owns the
image.

See `csm-code-changes.md` for the full change list.

## 6. Status of earlier analyses

**`codesyncmgr-chat.md` §6 was substantially right.** It observed the two buckets and
raised "is it the codesyncmgr version?" as an open question. That open question is the
answer. Its framing should be sharpened from "root cause is the job's S3 bucket
configuration" to: *the codesyncmgr version determines the bucket, and `CSM_SOURCE=system`
selects a different version per node image.* No job-level bucket setting is involved.

**The 24h retention-expiry conclusion is withdrawn.** The same-workflow-ID comparison in
§1 rules it out: one cell restored the data successfully while another failed in the same
build.

**The earlier `42c1a993` anomaly is explained.** That log showed an ubuntu20 system-binary
run listing the *correct* bucket and still finding it empty, which did not fit. With the
version matrix in §2 it does: node images are not uniform, so "ubuntu20" is not a single
configuration. Confirming that specific node's version would close it.

## 7. Verification

1. Re-run the failing matrix cell with `CSM_SOURCE=download`; confirm the console shows
   `/tmp/codesyncmgr` and the bucket `ap-northeast-1-s3codesync`, and that restore succeeds.
2. Grep every cell of a full build for the bucket name; confirm all cells agree.
3. Run `csm-binary-diagnostic.sh` on a **ubuntu22** node to complete the version matrix —
   if it is a fourth version, that strengthens the provisioning ask.
4. Record the version matrix in the ticket before considering `system` again.
