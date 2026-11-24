# Script: ohd-sync-gits.sh

> **Source:** `code-sync-refs_heads_master/ohd-sync-gits.sh` (branch `master`, 27 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Imports the **tags** of every Android Mainline (APEX / module SDK) git listed in a manifest from `partner-android.googlesource.com` into `review.ptc.sony.co.jp`. It picks the projects under `platform/prebuilts/module_sdk/` and `platform/vendor/partner_modules/`, and calls [`git.sh`](CodeSync_Script_git.sh.md) once for each.

## Location

[`code-sync-refs_heads_master/ohd-sync-gits.sh`](../../code-sync-refs_heads_master/ohd-sync-gits.sh)

## Called By

| Caller | How |
|---|---|
| **Jenkins jobs:** `sync_manifest_and_gits_ohd_<branch>` (template `sync_manifest_and_gits_{remote}_{branch}` in `jenkins-jobs/template-sync.yaml`) | Builder macro `sync-gits-in-manifest` in `jenkins-jobs/macros.yaml`, run **after** [`ohd.sh`](CodeSync_Script_ohd.sh.md): `code-sync/ohd-sync-gits.sh repo/static_manifest.xml` |
| Prod instances (`project-partner.yaml`) | Enabled: `v-`, `b-`, `c-`, `c1-`, `c2-aml-prebuilt-release`. Disabled: `t-`, `t-go-`, `u-aml-prebuilt-release`. |
| **Parent script:** none | |

## Calls Internal Scripts

- [`git.sh`](CodeSync_Script_git.sh.md), called as `code-sync/git.sh` (relative path)

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `grep -E`, `sed -E`, `cat` | Extract project names from the manifest |
| Everything `git.sh` needs | `git`, `flock`, `sha1sum` |

## Usage

### Jenkins

- **Job name:** `sync_manifest_and_gits_ohd_<branch>`, e.g. `sync_manifest_and_gits_ohd_c-aml-prebuilt-release`
- **Macro shell:**

```bash
[ -d "/mnt/ebs2/gitmirror/partner-android.googlesource.com" ] && \
  export SOURCE_MIRROR=/mnt/ebs2/gitmirror/partner-android.googlesource.com
export GIT_SYNC_PERSISTENT_VAR_DIR=$(realpath $WORKSPACE/../sync-git-persistent-data)
code-sync/ohd-sync-gits.sh "repo/static_manifest.xml"
```

### Manual Execution

Run from the directory that **contains** `code-sync/` (the path to `git.sh` is relative):

```bash
cd $WORKSPACE
export GIT_SYNC_PERSISTENT_VAR_DIR=$HOME/sync-git-manual   # keep test sidecars apart
export GIT_PUSH_ARGS=""                                     # optional
code-sync/ohd-sync-gits.sh repo/static_manifest.xml
```

## Parameters

| Parameter | Required (Y/N) | Description |
|---|---|---|
| `$1` manifest_file | Y | Path to a repo manifest XML. In the job: `repo/static_manifest.xml` written by `ohd.sh`. Exits 1 if empty. |

## Input

**Input files:**
- The manifest XML in `$1`. One `<project>` per line is assumed: the `name="..."` value is cut from each matching line with `sed`.

**Environment variables:**

| Variable | Effect |
|---|---|
| `GIT_PUSH_ARGS` | Passed to every `git.sh` call as push arguments (job parameter `GIT_PUSH_ARGS`) |
| `SOURCE_MIRROR`, `GIT_SYNC_PERSISTENT_VAR_DIR` | Not read here; inherited by `git.sh` (see that page) |

**Fixed values in the script:**

| Value | Setting |
|---|---|
| Project filter | `platform/prebuilts/module_sdk/` or `platform/vendor/partner_modules/` |
| Source | `https://partner-android.googlesource.com/<project>` |
| Target | `git://review.ptc.sony.co.jp/<project>` |
| Refspec | `refs/tags/*:refs/tags/*` (tags only) |

## Output

**Log files:** console only (`bash -x`).

**Reports:** none.

**Generated artifacts:**
- Per git: the bare clone and sidecar file that `git.sh` keeps in `$WORKSPACE/../sync-git-persistent-data/`.
- On the review server: new tags on each Mainline git.

## Key Functions / Logic

The script has no functions.

| Step | Lines | Purpose |
|---|---|---|
| Argument check | 14-15 | Exit 1 if no manifest file is given. |
| Select gits | 17-19 | `grep` the two Mainline path prefixes, `sed` out the `name` attribute. |
| Sync loop | 21-27 | For each git: `code-sync/git.sh <src> <target> 'refs/tags/*:refs/tags/*' $GIT_PUSH_ARGS`. A failure only prints `WARNING: git.sh terminates with non-zero exit code.` and the loop continues. |

## Notes

- **Failures are not fatal:** a failed `git.sh` call does not fail the build. Search the console for `WARNING: git.sh terminates` after every run.
- **Hard-coded hosts:** source and target hosts are fixed in the script. Any other manifest (AOSP, Qualcomm) cannot be used with it.
- **Tags only:** branches of the Mainline gits are not synced here. Branch pushes come from `ohd.sh` (`PUSH_MODE=all`) earlier in the same job.
- **Target is `git://`:** the push only works because the `code-sync` user's git config rewrites `git://review.ptc.sony.co.jp` to SSH. [Unconfirmed] Which config file holds the rewrite on the node.
- **Fast reruns:** `git.sh` skips gits whose refs did not change, so a rerun only pushes to the gits that changed or failed.
- **Fragile parsing:** a project whose `name` is not on the same line as its path prefix is missed. `repo manifest -r` output (one project per line) is safe.
