#!/bin/bash
#
# CSM binary comparison — paste directly into a Jenkins shell build step.
#
# Run once per node type (ubuntu20 / 22 / 24) to record which codesyncmgr
# version each image ships and which S3 bucket it actually targets.
# Read-only: uses --dryrun, never backs up or restores.
#
# Robustness notes:
#   - 'set +e' is forced: Jenkins runs shell steps as /bin/bash -xe when the
#     shebang is not the literal first line, and a grep with no match would
#     otherwise abort the whole script.
#   - 'set +x' is forced: tracing would echo the buildrepo API response, which
#     carries live Artifactory tokens, into the console log.
#   - An EXIT trap always prints the END marker, so a truncated run is obvious.
#

set +e
set +x

CODE_SYNC_MGR_VERSION="${CODE_SYNC_MGR_VERSION:-1.9.0}"
BUILDREPO_API_URL="https://api.ptc.sony.co.jp/buildrepo/mc-k3f9b2q1"
BUILDREPO_CSM_URL="https://ptcrepo.jfrog.io/artifactory/globaltools/archives"
PROBE_ID="00000000-0000-0000-0000-000000000000"

SYS_BIN="$(command -v codesyncmgr 2>/dev/null)"
DL_BIN="${TMPDIR:-/tmp}/codesyncmgr-diag-${CODE_SYNC_MGR_VERSION}"
WORKDIR="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/csmdiag.$$")"

# Capture the status at trap entry and exit with it explicitly. Without the
# explicit exit, the trap's own last command sets the script's exit status,
# which made Jenkins mark a clean run as FAILURE.
trap '_trc=$?; echo; echo "===== CSM-BINARY-DIAG END (exit=$_trc) ====="; rm -rf "$WORKDIR" >/dev/null 2>&1; exit $_trc' EXIT

echo "===== CSM-BINARY-DIAG BEGIN ====="
echo "date_utc : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "node     : $(hostname) / ${NODE_NAME:-unknown}"
echo "os       : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "job      : ${JOB_NAME:-unknown} #${BUILD_NUMBER:-?}"
echo "pinned   : $CODE_SYNC_MGR_VERSION"
echo "system   : ${SYS_BIN:-NOT FOUND IN PATH}"

# ------------------------------------------------------------------ step 1 --
echo
echo "### STEP 1/5: fetch pinned build $CODE_SYNC_MGR_VERSION"
_resp="$(curl --no-progress-meter -fSL "$BUILDREPO_API_URL" 2>/dev/null)"
if [ -n "$_resp" ]; then
    _u="$(jq -r .globaltools.username <<< "$_resp" 2>/dev/null)"
    _p="$(jq -r .globaltools.password <<< "$_resp" 2>/dev/null)"
    curl -u "$_u:$_p" -sL "$BUILDREPO_CSM_URL/codesyncmgr-$CODE_SYNC_MGR_VERSION" -o "$DL_BIN" 2>/dev/null
    unset _u _p _resp
    if [ -s "$DL_BIN" ]; then
        chmod a+x "$DL_BIN"
        echo "downloaded: $DL_BIN ($(stat -c %s "$DL_BIN" 2>/dev/null) bytes)"
    else
        echo "WARNING: download failed -- continuing with system binary only"
        DL_BIN=""
    fi
else
    echo "WARNING: buildrepo API unreachable -- continuing with system binary only"
    DL_BIN=""
fi

# ----------------------------------------------------------------- helpers --
#
# Effective bucket, works on EVERY version.
#
# 2.0.1-0 prints 'bucket:' in its config output; 2.1.0 dropped both --bucket and
# the config line, so config alone cannot answer this. A verbose dry-run restore
# against a dummy workflow ID always echoes the s3:// URI it intends to list,
# which is the bucket that actually matters. Retries are pinned low so a missing
# prefix costs a second rather than the default 6 x 5s.
#
effective_bucket() {
    _b="$1"
    ( cd "$WORKDIR" 2>/dev/null || cd /tmp
      timeout 90 "$_b" --verbose --dryrun --retries 1 --interval 1 \
              --id "$PROBE_ID" restore </dev/null 2>&1 \
        || timeout 90 "$_b" --verbose --dryrun --id "$PROBE_ID" restore </dev/null 2>&1
    ) | grep -oE 's3://[A-Za-z0-9._-]+' | head -1 | sed 's|s3://||'
}

# Raw dry-run output, for when the probe above finds no URI.
effective_bucket_raw() {
    ( cd "$WORKDIR" 2>/dev/null || cd /tmp
      timeout 90 "$1" --verbose --dryrun --retries 1 --interval 1 \
              --id "$PROBE_ID" restore </dev/null 2>&1
    ) | head -15
}

# These .pyz files are Python zipapps holding plain source. Reading it is the
# definitive answer to which bucket a version selects -- 2.1.0 and 1.9.0 carry
# both bucket strings and expose no --bucket flag, so nothing else settles it.
dump_source() {
    _z="$1"
    unzip -l "$_z" >/dev/null 2>&1 || { echo "(not a zipapp)"; return 0; }

    echo "--- res.py ---"
    unzip -p "$_z" res.py 2>/dev/null | head -20

    echo "--- cli.py: bucket / dev-mode logic ---"
    unzip -p "$_z" cli.py 2>/dev/null \
      | grep -n -iE 'bucket|s3|dev.?mode|BUCKET' | head -25

    echo "--- app.py: bucket / dev-mode logic ---"
    unzip -p "$_z" app.py 2>/dev/null \
      | grep -n -iB1 -A3 -iE 'bucket|dev.?mode' | head -60
    echo "(end source)"
}

# One 'aws s3 ls' probe, reporting exit code and stream sizes.
#
# The distinction that matters: an empty listing exits non-zero with BOTH
# streams empty on AWS CLI v2, but exits 0 on v1. A genuine error always
# writes to stderr. Byte counts make that difference quotable.
probe_ls() {
    _label="$1"; _uri="$2"
    _o="$(mktemp)"; _e="$(mktemp)"
    timeout 60 aws s3 ls "$_uri" >"$_o" 2>"$_e" </dev/null
    _rc=$?
    printf 'probe %-18s exit=%-4s stdout=%sB stderr=%sB lines=%s\n' \
        "$_label" "$_rc" "$(wc -c <"$_o")" "$(wc -c <"$_e")" "$(grep -c . "$_o")"
    [ -s "$_e" ] && sed 's/^/    stderr: /' "$_e" | head -3
    rm -f "$_o" "$_e"
    return 0
}

config_bucket() {
    timeout 60 "$1" config </dev/null 2>&1 | awk '/^bucket:/ {print $2; exit}'
}

# Bucket as decided by the source. This is the authoritative answer: the two
# generations resolve it differently and neither exposes it consistently.
#
#   2.0.1-0      : cli.py DEFAULT_BUCKET, overridable by CODESYNCMGR_BUCKET.
#                  Its default is the bucket later versions call TEST_BUCKET.
#   1.9.0 / 2.1.0: app.py choose_bucket() -> PROD_BUCKET, or TEST_BUCKET
#                  only when --dev-mode is passed. No override available.
#
source_bucket() {
    _z="$1" _d="" _p=""

    _d="$(unzip -p "$_z" cli.py 2>/dev/null \
          | sed -n 's/^DEFAULT_BUCKET *= *"\([^"]*\)".*/\1/p' | head -1)"
    if [ -n "$_d" ]; then
        echo "${CODESYNCMGR_BUCKET:-$_d}"
        return 0
    fi

    _p="$(unzip -p "$_z" app.py 2>/dev/null \
          | sed -n 's/^PROD_BUCKET *= *"\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$_p" ] && echo "$_p"
    return 0
}

version_of() {
    timeout 30 "$1" --version </dev/null 2>&1 | head -1
}

report() {
    _bin="$1"
    _tag="$2"
    _real="$(readlink -f "$_bin" 2>/dev/null || echo "$_bin")"

    echo
    echo "================================================================"
    echo "$_tag : $_bin"
    [ "$_real" != "$_bin" ] && echo "  -> resolves to: $_real"
    echo "================================================================"

    echo "-- identity --"
    ls -la  "$_bin"  2>&1
    [ "$_real" != "$_bin" ] && ls -la "$_real" 2>&1
    file    "$_real" 2>&1
    md5sum  "$_real" 2>&1
    dpkg -S "$_real" 2>/dev/null || echo "(not owned by a dpkg package)"

    echo
    echo "-- version --"
    version_of "$_bin"

    echo
    echo "-- config --"
    timeout 60 "$_bin" config </dev/null 2>&1 | head -40

    echo
    echo "-- bucket-related options in --help --"
    timeout 30 "$_bin" --help </dev/null 2>&1 \
      | grep -iE -- '--bucket|--dev-mode|--root|--exclude' | head -10
    echo "(end options)"

    echo
    echo "-- effective bucket (verbose dry-run restore probe) --"
    _eb="$(effective_bucket "$_bin")"
    if [ -n "$_eb" ]; then
        echo "$_eb"
    else
        echo "<no s3:// URI in dry-run output; raw output follows>"
        effective_bucket_raw "$_bin" | sed 's/^/    /'
    fi

    echo
    echo "-- bucket strings in the binary --"
    strings -a "$_real" 2>/dev/null | grep -aoE '[0-9]{12}-[A-Za-z0-9.-]+' | sort -u | head -10
    echo "(end strings)"

    echo
    echo "-- packaging --"
    unzip -l "$_real" 2>&1 | head -25
    echo "(end packaging)"

    echo
    echo "-- SOURCE: how this version picks its bucket --"
    dump_source "$_real"
}

# ---------------------------------------------------------------- steps 2-3 --
echo
echo "### STEP 2/5: system binary"
if [ -n "$SYS_BIN" ] && [ -x "$SYS_BIN" ]; then
    report "$SYS_BIN" "SYSTEM BINARY"
else
    echo "(no codesyncmgr in PATH on this node)"
fi

echo
echo "### STEP 3/5: pinned binary $CODE_SYNC_MGR_VERSION"
if [ -n "$DL_BIN" ] && [ -x "$DL_BIN" ]; then
    report "$DL_BIN" "PINNED $CODE_SYNC_MGR_VERSION"
else
    echo "(pinned binary unavailable)"
fi

# ------------------------------------------------------------------ step 4 --
echo
echo "### STEP 4/5: node environment"
echo "-- codesyncmgr config files --"
ls -la /etc/codesyncmgr* ~/.codesyncmgr* ~/.config/codesyncmgr* 2>/dev/null \
    || echo "(none found)"

echo
echo "-- aws --"
aws --version 2>&1
echo "NOTE: CLI v1 exits 0 on an empty prefix; v2 exits 1. This changes how the"
echo "      'Exit ... with 1' line in a failing restore log should be read."
echo
echo "identity (90s allowed -- a timeout here is itself a finding):"
_idout="$(timeout 90 aws sts get-caller-identity </dev/null 2>&1)"; _idrc=$?
echo "${_idout:-<no output -- STS did not respond>}" | head -10
echo "identity probe exit=$_idrc"

echo
echo "-- direct bucket access probes --"
probe_ls "s3codesync-root" "s3://659398199407-ap-northeast-1-s3codesync/"
probe_ls "apne1-root"      "s3://659398199407-apne1-jenkins-cm-workflow/"
probe_ls "empty-prefix"    "s3://659398199407-ap-northeast-1-s3codesync/$PROBE_ID/code/"
echo "(end probes)"

echo
echo "-- relevant environment --"
env | grep -iE '^AWS_|^CSM_|^CODE_?SYNC|^WORKFLOW_ID' | sort
echo "(end environment)"

# ------------------------------------------------------------------ step 5 --
echo
echo "### STEP 5/5: verdict"
echo "================================================================"
echo "VERDICT"
echo "================================================================"

SYS_V=""; SYS_B=""
DL_V="";  DL_B=""
# Source first: it is the only method that answers for every generation.
# config output covers 2.0.1-0; a dry-run probe covers neither reliably.
if [ -n "$SYS_BIN" ] && [ -x "$SYS_BIN" ]; then
    SYS_V="$(version_of "$SYS_BIN")"
    SYS_B="$(source_bucket "$(readlink -f "$SYS_BIN" 2>/dev/null || echo "$SYS_BIN")")"
    [ -z "$SYS_B" ] && SYS_B="$(config_bucket "$SYS_BIN")"
fi
if [ -n "$DL_BIN" ] && [ -x "$DL_BIN" ]; then
    DL_V="$(version_of "$DL_BIN")"
    DL_B="$(source_bucket "$DL_BIN")"
    [ -z "$DL_B" ] && DL_B="$(config_bucket "$DL_BIN")"
fi

printf 'node   : %s (%s)\n' "$(hostname)" "$(. /etc/os-release 2>/dev/null && echo "$VERSION_ID")"
printf 'system : version=%-12s bucket=%s\n' "${SYS_V:-?}" "${SYS_B:-UNKNOWN}"
printf 'pinned : version=%-12s bucket=%s\n' "${DL_V:-?}"  "${DL_B:-UNKNOWN}"

if [ -n "$SYS_B" ] && [ -n "$DL_B" ] && [ "$SYS_B" != "$DL_B" ]; then
    echo "RESULT : MISMATCH -- these binaries target different buckets."
    echo "         A workflow backed up by one and restored by the other finds"
    echo "         an empty prefix. CSM_SOURCE=system is unsafe on this node."
elif [ -n "$SYS_B" ] && [ "$SYS_B" = "$DL_B" ]; then
    echo "RESULT : OK -- both target $SYS_B on this node."
else
    echo "RESULT : INCONCLUSIVE -- see the 'effective bucket' sections above."
fi

# Always green: this is a diagnostic, not a gate.
# Change to 'exit 1' in the MISMATCH branch if you want it to fail loudly.
exit 0
