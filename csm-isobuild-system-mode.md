# isobuild — adopting `CSM_SOURCE=system`

Target state: isobuild resolves `codesyncmgr` from the node instead of downloading it on
every matrix cell. Assumes the ubuntu20 image is being moved onto Generation B.

Companion to `csm-investigation-and-changes.md`, which covers the offbuild fix and the
root-cause investigation. This document is isobuild-only and forward-looking.

---

## 1. Why `system` is currently blocked

isobuild matrix cells run on ubuntu20 labels (`template-isobuild.yaml`,
`android-qssi` / `android-target` → `CM_20_ANDROID`). The ubuntu20 image ships
codesyncmgr **2.0.1-0 (Generation A)**, which breaks isobuild in two independent ways:

| # | Generation A behaviour | Consequence for isobuild |
|---|---|---|
| 1 | `cli.py:15` `DEFAULT_BUCKET` = `apne1-jenkins-cm-workflow` (the TEST bucket) | restore reads a bucket the backup never wrote to |
| 2 | No `--exclude` flag (it has `--root` instead) | `isobuild-superlabel-manifest-init.sh:18` passes `--exclude result-dir` → argparse error |

Generation B (`1.9.0`, `2.1.0`) fixes both: `choose_bucket()` defaults to `PROD_BUCKET`,
and `--exclude` exists.

**So the gate is: ubuntu20 agents must run Generation B before `system` is safe.**

---

## 2. The gate — verify before enabling

Run `csm-binary-diagnostic.sh` on an ubuntu20 agent. Required result:

```
system : version=2.1.0   bucket=659398199407-ap-northeast-1-s3codesync
pinned : version=1.9.0   bucket=659398199407-ap-northeast-1-s3codesync
RESULT : OK -- both target 659398199407-ap-northeast-1-s3codesync on this node.
```

Plus, in the same output:

```
-- bucket-related options in --help --
  --dev-mode               Enable dedicated bucket for verification
  --exclude EXCLUDE        The comma separated list of excluded directories
```

`--dev-mode` and `--exclude` present, `--bucket` and `--root` absent. That is Generation B.

> Do not gate on the version string. `2.1.0` is a Debian package revision and `1.9.0` an
> Artifactory archive name — different channels, never comparable. Gate on the flags.

---

## 3. Make `system` self-protecting

Even after the image lands, agents update at different times, and an image can be rolled
back. Rather than trusting the fleet to be uniform, have `get_csm_bin` **verify the
generation and fall back to download** when it does not match.

This is the piece that makes `system` safe to enable before the rollout is 100% complete:
a stale agent silently downloads the pinned build instead of failing the job.

### Add to `offbuild/common_functions.sh`

```bash
# Test whether a codesyncmgr binary is the generation our scripts expect.
#
# Version strings cannot be used for this: the installed package numbers
# releases 2.0.1-0 / 2.1.0 while the buildrepo archive numbers them 1.9.0.
# They come from different distribution channels and never compare equal.
# Test for the capabilities that actually matter instead.
#
#   Generation A (2.0.1-0)       : --bucket / --root, defaults to the TEST bucket
#   Generation B (1.9.0, 2.1.0)  : --exclude / --dev-mode, defaults to PROD
#
# Mandatory parameters:
# $1: path to the codesyncmgr binary.
#
# Return:
#   0 : Generation B -- safe to use
#   1 : anything else
#
function _csm_is_supported()
{
    local _bin=$1 _help
    _help="$("$_bin" --help 2>&1)" || return 1

    grep -q -- '--dev-mode' <<< "$_help" || return 1   # Gen B marker
    grep -q -- '--exclude'  <<< "$_help" || return 1   # flag isobuild passes
    if grep -q -- '--bucket' <<< "$_help"; then        # Gen A marker
        return 1
    fi
    return 0
}
```

### Replace `get_csm_bin`

```bash
# Resolve the codesyncmgr binary to use, based on CSM_SOURCE.
#
# Optional environment variables:
#   CSM_SOURCE : system   : use the node's binary if it is a supported
#                           generation; download otherwise.
#                download : always fetch the pinned build.
#                default  : download
#
# The 'system' path verifies capabilities rather than trusting the node, so a
# partially-updated fleet degrades to a download instead of failing the build.
#
# Return:
#   0 + binary path on stdout   : success
#   1                           : binary unavailable or invalid CSM_SOURCE
#
function get_csm_bin()
{
    local _path
    case "${CSM_SOURCE:-download}" in
        system)
            _path="$(command -v codesyncmgr 2>/dev/null)"
            if [ -n "$_path" ] && _csm_is_supported "$_path"; then
                echo "$_path"
            else
                if [ -n "$_path" ]; then
                    echo "codesyncmgr at $_path is an unsupported generation" >&2
                    echo "(no --dev-mode/--exclude, or still has --bucket); downloading ..." >&2
                else
                    echo "codesyncmgr not found in PATH; downloading ..." >&2
                fi
                _download_csm_bin
            fi
            ;;
        download)
            _download_csm_bin
            ;;
        *)
            echo "ERROR: invalid CSM_SOURCE=${CSM_SOURCE} (expected: system, download)" >&2
            return 1
            ;;
    esac
}
```

Note `_csm_is_supported` is written so its final statement always sets the return value
explicitly — a trailing `grep … && return 1` would make a *missing* `--bucket` look like
a failure.

---

## 4. Files to change

`offbuild/isobuild/scriptutils.source:5` already does
`source ${CURRENT_SCRIPT_DIR}/../common_functions.sh`, so both isobuild scripts pick up
`get_csm_bin` with no extra plumbing.

| # | File | Change |
|---|------|--------|
| 1 | `offbuild/common_functions.sh` | add `_csm_is_supported`, replace `get_csm_bin` (§3) |
| 2 | `cm_tools/hudson-scripts/isobuild-superlabel-manifest-init.sh` | backup → `get_csm_bin` (:16, :18) |
| 3 | `cm_tools/hudson-scripts/isobuild-superlabel-android-matrix.sh` | restore → `get_csm_bin` (:20, :21) |
| 4 | `offbuild/jenkins-jobs/template-isobuild.yaml` | `csm-source` default at :77 |
| 5 | `offbuild/jenkins-jobs/template-isobuild-manifest.yaml` | inject `CSM_SOURCE` at :19 |
| 6 | `offbuild/jenkins-jobs/template-isobuild-superlabel-android-matrix.yaml` | inject `CSM_SOURCE` at :47 |
| 7 | `offbuild/jenkins-jobs/template-isobuild-superlabel-android.yaml` | *optional* — inject at :77 for visibility |

File 1 is shared with offbuild. If the offbuild change already landed, this replaces the
`get_csm_bin` it added.

### 4.1 Backup — `isobuild-superlabel-manifest-init.sh`

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

### 4.2 Restore — `isobuild-superlabel-android-matrix.sh`

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

Both scripts are `#!/bin/bash -ex`, and `CSM_BIN` is assigned inside the `( … )` subshell
where it is used, so `|| exit 1` propagates correctly.

### 4.3 Templates

isobuild uses the **hyphen** placeholder convention — `{use-code-sync-mgr}`, not the
offbuild `{use_code_sync_mgr}`. Keep `csm-source` consistent between the default and the
inject lines or JJB expands nothing and fails silently.

```yaml
# template-isobuild.yaml:77
     use-code-sync-mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: 'download'          # flip to 'system' per section 5

# template-isobuild-manifest.yaml:19
# template-isobuild-superlabel-android-matrix.yaml:47
             USE_CODE_SYNC_MGR={use-code-sync-mgr}
             CODE_SYNC_MGR_VERSION={code-sync-mgr-version}
+            CSM_SOURCE={csm-source}
```

`template-isobuild-superlabel-android.yaml:77` injects only `USE_CODE_SYNC_MGR` — that
job mints the workflow UUID (line 121) and never runs codesyncmgr, so `CSM_SOURCE` there
is optional.

---

## 5. Staged rollout

Land the code with the default still at `download`, then widen by opting projects in.
`csm-source` is a JJB default, so a project yaml can override it without touching the
templates.

| Stage | Action | Confirms |
|---|---|---|
| 1 | Land §3 and §4 with `csm-source: 'download'` | No behaviour change; migration is inert |
| 2 | Override `csm-source: 'system'` in **one** sandbox project yaml | The capability check accepts or rejects correctly |
| 3 | Run one full superlabel build — backup on the manifest node, restore on an ubuntu20 cell | Both stages log the same bucket |
| 4 | Widen to remaining projects | — |
| 5 | Flip the `template-isobuild.yaml:77` default to `'system'` | Fleet-wide |

Stage 2 override, in the project yaml alongside `use-code-sync-mgr`:

```yaml
    use-code-sync-mgr: 'true'
    csm-source: 'system'
```

### What each outcome looks like

Node on Generation B — `system` accepted:

```
+ CSM_BIN=/usr/bin/codesyncmgr
+ echo 'Using codesyncmgr: /usr/bin/codesyncmgr'
INFO: START: s3://659398199407-ap-northeast-1-s3codesync/<id>/code/...
```

Node still on Generation A — falls back, build still succeeds:

```
codesyncmgr at /usr/bin/codesyncmgr is an unsupported generation
(no --dev-mode/--exclude, or still has --bucket); downloading ...
+ CSM_BIN=/tmp/codesyncmgr
INFO: START: s3://659398199407-ap-northeast-1-s3codesync/<id>/code/...
```

The second case is the point of the capability check: a lagging agent costs one download,
not a failed build.

---

## 6. Verification

1. **Grep the bucket across every cell of a full build** — all cells must show
   `ap-northeast-1-s3codesync`. Any `apne1-jenkins-cm-workflow` means a Generation A
   binary was accepted, i.e. the capability check is wrong.
2. **Confirm the fallback fires** — run stage 2 against a known Generation A agent and
   check for the "unsupported generation" line followed by a successful restore.
3. **Confirm `--exclude` is honoured** — after a `system` backup, the workflow prefix
   must not contain `result-dir`.
4. **Compare timings** — `system` removes a buildrepo API call plus a download per cell.
   Small, but it is the reason for the change; worth recording.

## 7. Rollback

Set `csm-source: 'download'` in the project yaml (stage 2–4) or the template default
(stage 5). No script changes needed — the migrated call sites behave identically under
`download`, which is the pre-change behaviour.

---

## 8. Open items

1. **Confirm the real label sets.** The `CM_20_ANDROID` mapping above is from the DUMMY
   default block in `template-isobuild.yaml`. Check `jenkins_label_sets` per project —
   if any isobuild Android component runs on a label whose agents are not yet on
   Generation B, that project must stay on `download`.
2. **`get_source_code` runs between resolution and backup.** In
   `isobuild-superlabel-manifest-init.sh` the binary is resolved, then `get_source_code`
   runs, then `backup`. Under `download` the binary sits in `/tmp` across that step.
   Confirm `get_source_code` does not clear `/tmp` on these agents; if it does, move the
   `get_csm_bin` call to immediately before the `backup` line.
3. **Decide whether backup and restore must agree on generation.** The capability check
   guarantees both are Generation B, which is sufficient today because both generations
   agree on the S3 key layout (`<bucket>/<id>/code/`). If a future generation changes the
   layout, a capability check will not catch it — a bucket-agreement check (backup
   records its bucket, restore compares) would be needed then.
