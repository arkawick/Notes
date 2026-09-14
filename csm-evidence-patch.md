# CSM evidence-collection patch (temporary — DO NOT MERGE)

A build-side harness that makes the Jenkins console log the evidence artifact for the
ticket. Everything runs inside the job, on the real node, as the real Jenkins user,
so no direct AWS or Jenkins-API access is needed.

Push as a **separate commit from the real fix**, on a sandbox branch, and drop it once
the ticket is filed.

---

## 1. Addition to `offbuild/common_functions.sh`

```bash
CSM_S3_BUCKET="${CSM_S3_BUCKET:-659398199407-ap-northeast-1-s3codesync}"

# Run one 'aws s3 ls' probe and report the exact outcome shape.
#
# The distinction that matters is exit-code-plus-stream-sizes: an empty listing
# exits non-zero with BOTH streams empty, while a genuine error always writes to
# stderr. Reporting byte counts makes that difference quotable.
#
# Mandatory parameters:
# $1: short label for the probe.
# $2: s3:// URI to list.
#
function _csm_probe()
{
    local _label=$1 _uri=$2
    local _o _e _rc
    _o=$(mktemp) ; _e=$(mktemp)
    aws s3 ls "$_uri" >"$_o" 2>"$_e" && _rc=0 || _rc=$?
    printf 'probe %-12s exit=%-4s stdout=%sB stderr=%sB lines=%s\n' \
        "$_label" "$_rc" "$(wc -c <"$_o")" "$(wc -c <"$_e")" "$(grep -c . "$_o" || true)"
    [ -s "$_e" ] && sed 's/^/    stderr: /' "$_e"
    [ -s "$_o" ] && head -5 "$_o" | sed 's/^/    stdout: /'
    rm -f "$_o" "$_e"
    return 0
}

# Print a delimited evidence block describing CSM S3 state at one stage.
#
# Never fails the build: every command is guarded and the function always
# returns 0, so it is safe to call from scripts running under 'set -e'.
#
# Mandatory parameters:
# $1: stage label, e.g. backup-post / restore-pre / restore-post-fail.
# $2: workflow ID.
#
function csm_evidence()
{
    local _stage=$1 _workflow_id=$2
    local _prefix="s3://${CSM_S3_BUCKET}/${_workflow_id}/code/"
    local _xtrace=""

    case $- in *x*) _xtrace=1 ;; esac       # remember tracing state
    set +x                                  # keep the block clean

    echo "===== CSM-EVIDENCE BEGIN ($_stage) ====="
    echo "stage            : $_stage"
    echo "workflow_id      : $_workflow_id"
    echo "epoch_utc        : $(date -u +%s)"
    echo "date_utc         : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "node             : $(hostname) / ${NODE_NAME:-unknown}"
    echo "os               : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
    echo "build_url        : ${BUILD_URL:-unknown}"
    echo "job_name         : ${JOB_NAME:-unknown}"
    echo "csm_source       : ${CSM_SOURCE:-unset}"
    echo "csm_bin          : ${CSM_BIN:-unset}"
    echo "csm_version_env  : ${CODE_SYNC_MGR_VERSION:-unset}"
    echo "csm_version_bin  : $(${CSM_BIN:-codesyncmgr} --version 2>&1 | head -1 || true)"
    echo "aws_cli          : $(aws --version 2>&1 || true)"
    echo "aws_identity     : $(aws sts get-caller-identity --output json 2>&1 | tr -d '\n' || true)"
    echo "s3_prefix        : $_prefix"
    echo

    echo "--- probes ---"
    _csm_probe "workflow"    "$_prefix"
    _csm_probe "known-empty" "s3://${CSM_S3_BUCKET}/00000000-0000-0000-0000-000000000000/code/"
    _csm_probe "bucket-root" "s3://${CSM_S3_BUCKET}/"
    _csm_probe "bad-bucket"  "s3://ptc-csm-nonexistent-probe-$$/"
    echo

    echo "--- workflow prefix, recursive ---"
    aws s3 ls "$_prefix" --recursive --summarize 2>&1 | tail -8 || true
    echo

    echo "--- bucket lifecycle configuration ---"
    aws s3api get-bucket-lifecycle-configuration --bucket "$CSM_S3_BUCKET" 2>&1 || true

    echo "===== CSM-EVIDENCE END ($_stage) ====="

    [ -n "$_xtrace" ] && set -x
    return 0
}
```

### Why each line earns its place

| Output | Excludes the hypothesis |
|---|---|
| `aws_identity`, `bucket-root` probe | IAM / credentials broken on this node |
| `bad-bucket` probe (stderr non-zero) | "exit 1 always means an error" |
| `known-empty` probe (exit 1, 0B/0B) | Establishes what an empty prefix looks like *here* |
| `workflow` probe matching `known-empty` | The failing call was an empty result, not an error |
| `lifecycle configuration` | Proves the deletion mechanism exists and its Days value |
| `epoch_utc` on both stages | Gives the T1 − T0 gap without Jenkins API access |
| `csm_version_bin` / `os` | Version drift across U20 / U22 / U24 |

---

## 2. Credential leak fix in `download_csm` (keep this one — it is not temporary)

`set -x` currently echoes the full buildrepo API response, including live Artifactory
reftokens for swerepo, gradle, pypi and sonybuildenv, into every console log.

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

---

## 3. Call sites

### Backup side — `offbuild/offbuild/ch/android/manifest/init.sh` (~line 125)

Captures the T0 state: objects present, count, total bytes, timestamp.

```bash
     time /tmp/codesyncmgr --verbose --id $WORKFLOW_ID backup
+    csm_evidence "backup-post" "$WORKFLOW_ID"
     )
 fi
```

### Restore side — `offbuild/offbuild/ch/android/matrix/main.sh` (~line 24)

Captures the T1 state before the attempt, and again on failure.

```bash
 if [ "$USE_CODE_SYNC_MGR" = "true" ]; then
     CSM_BIN="$(get_csm_bin)" || exit 1
     echo "Using codesyncmgr: $CSM_BIN"
+    csm_evidence "restore-pre" "$WORKFLOW_ID"
-    time "$CSM_BIN" --verbose --id $WORKFLOW_ID restore
+    time "$CSM_BIN" --verbose --id $WORKFLOW_ID restore || {
+        csm_evidence "restore-post-fail" "$WORKFLOW_ID"
+        exit 1
+    }
```

`csm_evidence` always returns 0 and both scripts run under `set -e`, so the harness
cannot itself change the build result. The `|| { ...; exit 1; }` preserves the original
failure exactly.

> **`set -u` note:** `ch/android/matrix/main.sh` runs `#!/bin/bash -exu`. Every variable
> read in `csm_evidence` uses `${VAR:-default}` for that reason — do not remove the
> defaults when adapting to another script.

---

## 4. Gerrit / Jenkins workflow

`clone-offbuild` (`macros.yaml:20`) runs `git reset --hard ${BUILD_JOB_REVISION}` against
a plain clone, which does **not** fetch `refs/changes/*`. A Gerrit change ref will fail
with "unknown revision". Use a branch.

```bash
# 1. Evidence commit on a sandbox branch of semctools/offbuild
git checkout -b sandbox/csm-evidence origin/master
git cherry-pick <your-existing-get_csm_bin-commit>
git commit -am "DO NOT MERGE: collect CSM S3 evidence for <TICKET-ID>"
git push origin HEAD:refs/heads/sandbox/csm-evidence

# 2. Point the sandbox job at it (project yaml)
#    build-job-revision: 'sandbox/csm-evidence'
#    -> resolves to origin/sandbox/csm-evidence via the ch template

# 3. Deploy jobs, then trigger the MASTER job (not the matrix cell)
```

If pushing to `refs/heads/*` is blocked by ACL, ask for a `sandbox/*` or `wip/*`
namespace — that is the only path that works with the current `clone-offbuild` macro
short of changing the macro itself.

---

## 5. Running the experiment

### Run 1 — control, same day

Trigger the Master job. Both blocks land in the console:

- `backup-post` in the manifest job — objects present, `exit=0`, non-zero size, epoch T0
- `restore-pre` in the matrix job — objects present, `exit=0`, epoch T1

This is the working baseline. It also proves the harness reports correctly.

### Run 2 — the reproduction, >24h later

Re-trigger **the matrix cell alone** from run 1 (the Rebuild that reuses `WORKFLOW_ID`).

- `restore-pre` — `workflow` probe now `exit=1 stdout=0B stderr=0B`, matching the
  `known-empty` probe on the same line
- `restore-post-fail` — same, after the six retries
- epoch difference vs. run 1's `backup-post` > 86400

Same workflow ID, same job, same node. **Elapsed time is the only variable.**

### Extracting for the ticket

```bash
curl --netrc -s "<build-url>consoleText" \
  | sed -n '/CSM-EVIDENCE BEGIN/,/CSM-EVIDENCE END/p'
```

Attach the blocks from both runs side by side. Redact the buildrepo API response if the
console predates the `download_csm` fix in §2.

---

## 6. What the ticket then asserts

| Claim | Backed by |
|---|---|
| Objects were written | `backup-post` block, run 1 |
| Objects were gone later | `restore-pre` block, run 2 |
| Gap exceeded retention | `epoch_utc` difference |
| Deletion is by lifecycle policy | `get-bucket-lifecycle-configuration` output |
| Not credentials | `aws_identity` + `bucket-root` probe, run 2 |
| Not a real S3 error | `bad-bucket` probe has stderr; `workflow` probe does not |
| Not the `get_csm_bin` change | `csm_bin` line shows a clean single path |
| Not node-specific | Same block from a U22/U24 cell |
