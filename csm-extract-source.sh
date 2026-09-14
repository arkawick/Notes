#!/bin/bash
#
# Extract codesyncmgr source into the workspace for archiving.
#
# Paste into a Jenkins shell build step, then add a post-build action:
#     Archive the artifacts -> csm-src/**
#
# Collects both the node's installed binary and the pinned buildrepo build,
# each as the original .pyz plus its unpacked source. Read-only.
#
# Run once per node type; the output directory is named by version, so
# artifacts from different nodes do not collide if you merge them later.
#

set +e
set +x

CODE_SYNC_MGR_VERSION="${CODE_SYNC_MGR_VERSION:-1.9.0}"
BUILDREPO_API_URL="https://api.ptc.sony.co.jp/buildrepo/mc-k3f9b2q1"
BUILDREPO_CSM_URL="https://ptcrepo.jfrog.io/artifactory/globaltools/archives"

OUT="$WORKSPACE/csm-src"
rm -rf "$OUT"
mkdir -p "$OUT"

echo "===== CSM-EXTRACT BEGIN ====="
echo "node : $(hostname) / ${NODE_NAME:-unknown}"
echo "os   : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"

collect() {
    _bin="$1" _label="$2"
    [ -n "$_bin" ] && [ -x "$_bin" ] || { echo "skip $_label (not available)"; return 0; }

    _real="$(readlink -f "$_bin" 2>/dev/null || echo "$_bin")"
    _ver="$(timeout 30 "$_bin" --version </dev/null 2>&1 | head -1 | tr -cd 'A-Za-z0-9._-')"
    _dir="$OUT/${_label}-${_ver:-unknown}"

    mkdir -p "$_dir/src"
    cp "$_real" "$_dir/codesyncmgr.pyz"
    unzip -o "$_real" -d "$_dir/src" >/dev/null 2>&1

    {
        echo "label   : $_label"
        echo "path    : $_bin"
        echo "real    : $_real"
        echo "version : $_ver"
        echo "md5     : $(md5sum "$_real" | cut -d' ' -f1)"
        echo "node    : $(hostname)"
        echo "os      : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
        echo "taken   : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    } > "$_dir/PROVENANCE.txt"

    echo "collected $_label -> $_dir ($(ls "$_dir/src" | tr '\n' ' '))"
}

# 1. the node's installed binary
collect "$(command -v codesyncmgr 2>/dev/null)" "system"

# 2. the pinned buildrepo build -- credentials never traced or echoed
_resp="$(curl --no-progress-meter -fSL "$BUILDREPO_API_URL" 2>/dev/null)"
if [ -n "$_resp" ]; then
    _u="$(jq -r .globaltools.username <<< "$_resp" 2>/dev/null)"
    _p="$(jq -r .globaltools.password <<< "$_resp" 2>/dev/null)"
    _dl="${TMPDIR:-/tmp}/codesyncmgr-pinned"
    curl -u "$_u:$_p" -sL "$BUILDREPO_CSM_URL/codesyncmgr-$CODE_SYNC_MGR_VERSION" -o "$_dl" 2>/dev/null
    unset _u _p _resp
    [ -s "$_dl" ] && { chmod a+x "$_dl"; collect "$_dl" "pinned"; }
else
    echo "skip pinned (buildrepo API unreachable)"
fi

echo
echo "-- archive contents --"
find "$OUT" -type f | sed "s|$WORKSPACE/||" | sort
echo "===== CSM-EXTRACT END ====="
exit 0
