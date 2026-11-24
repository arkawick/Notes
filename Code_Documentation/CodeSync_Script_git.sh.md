# Script: git.sh

> **Source:** `code-sync-refs_heads_master/git.sh` (branch `master`, 130 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Mirrors one git repository from an upstream server into `review.ptc.sony.co.jp`. It fetches the refs named in a refspec into a local bare clone, and pushes them to the target only when something changed upstream since the last successful push.

Change detection uses a sidecar file: the SHA-1 of `git show-ref` from the last successful push. If the refs are unchanged, nothing is pushed.

## Location

[`code-sync-refs_heads_master/git.sh`](../../code-sync-refs_heads_master/git.sh)

At runtime it is cloned into each job workspace as `code-sync/git.sh` by the `prepare-code-sync` macro.

## Called By

| Caller | How |
|---|---|
| **Jenkins jobs:** `sync_git_<name>-<repo-name>` (template `sync_git_{name}-{repo-name}` in `jenkins-jobs/template-sync.yaml`) | Builder macro `sync-git` in `jenkins-jobs/macros.yaml`: `code-sync/git.sh $SOURCE_URL $TARGET_URL $REFSPEC $PUSH_ARGS` |
| Prod instances (from `project-aosp.yaml`, `project-partner.yaml`) | e.g. `sync_git_aosp-kernel-common`, `sync_git_aosp-kernel-build`, `sync_git_aosp-kernel-manifest`, `sync_git_aosp-kernel-msm`, `sync_git_aosp-kernel-prebuilts-build-tools`, `sync_git_aosp-kernel-common-modules-wonder`, `sync_git_partner-widevine`, `sync_git_partner-platform-system-libfmq`, ... |
| **Parent script:** [`ohd-sync-gits.sh`](CodeSync_Script_ohd-sync-gits.sh.md) | Calls it once per Mainline git, refspec `refs/tags/*:refs/tags/*` |

## Calls Internal Scripts

None. (`$here/proxy` is computed but only used in commented-out code.)

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `git` | `init --bare`, `fetch`, `push`, `show-ref`, `config` |
| `flock` (util-linux) | Exclusive lock per git, 60 s timeout |
| `sha1sum`, `sed`, `realpath`, `readlink` | Change detection, path handling |
| `bash` | Runs with `#!/bin/bash -xe` (trace + stop on first error) |

## Usage

### Jenkins

- **Job name:** `sync_git_<name>-<repo-name>`, e.g. `sync_git_aosp-kernel-common`
- **Macro shell:**

```bash
[ -d "{path-to-mirror}" ] && export SOURCE_MIRROR={path-to-mirror}
[ "{persistent-var-files}" = "true" ] && \
  export GIT_SYNC_PERSISTENT_VAR_DIR=$(realpath $WORKSPACE/../sync-git-persistent-data)
code-sync/git.sh $SOURCE_URL $TARGET_URL $REFSPEC $PUSH_ARGS
```

### Manual Execution

Run as `code-sync` on the CodeSync node, with `.netrc` and SSH keys in place:

```bash
git clone -b master git://review-plus.ptc.sony.co.jp/code-sync.git
export GIT_SYNC_PERSISTENT_VAR_DIR=$HOME/sync-git-manual     # optional
code-sync/git.sh https://android.googlesource.com/kernel/common \
                 ssh://xscm01@review.ptc.sony.co.jp:29418/kernel/common \
                 'refs/heads/*:refs/heads/oss/*' --tags
```

Use a separate `GIT_SYNC_PERSISTENT_VAR_DIR` for test runs, so you don't touch the sidecar file the Jenkins job relies on.

## Parameters

Positional arguments:

| Parameter | Required (Y/N) | Description |
|---|---|---|
| `$1` source | Y | Upstream git URL. Its basename (without `.git`) names the local clone and the sidecar file. |
| `$2` target | Y | Push URL on the review server. Added as remote `somc`. |
| `$3` refspec | Y | One or more refspecs separated by **commas**, e.g. `refs/heads/*:refs/heads/oss/*,refs/tags/*:refs/tags/*`. The left side is fetched, the full refspec is pushed. |
| `$4...` git push args | N | Passed to `git push` as-is, e.g. `--tags`, `--force`, `-o skip-validation`. |

The script exits with status 1 if any of the three required arguments is empty.

## Input

**Input files:**
- Sidecar file `<parent-dir>-<git-name>-ref-sha1sum` (previous `git show-ref | sha1sum`). It is created empty if missing.

**Environment variables:**

| Variable | Default | Effect |
|---|---|---|
| `GIT_SYNC_PERSISTENT_VAR_DIR` | unset | Directory that holds the bare clone and the sidecar file across builds. The Jenkins macro sets it to `$WORKSPACE/../sync-git-persistent-data` when the job's `persistent` value is true. Falls back to the current directory if not writable. |
| `USE_GIT_SYNC_PERSISTENT_VAR_DIR` | `true` | If not `true`, the persistent directory is ignored. Injected by the job template. |
| `SOURCE_MIRROR` | unset | Local mirror root. If `<SOURCE_MIRROR><url-path>.git` exists **and** its remote URL has the same path, it is used as git alternates (objects are borrowed, not downloaded). |
| `USE_SYSTEM_GIT_CONFIG` | unset | `false` sets `GIT_CONFIG_NOSYSTEM=1`. Injected by the job template. |
| `FLOCKER` | internal | Set by the script itself when it re-executes under `flock`. Do not set by hand. |

## Output

**Log files:** console only (`bash -x` trace). No log file is written.

**Reports:** none.

**Generated artifacts:**
- Bare clone `<git-name>.git/` in the persistent directory (or the workspace), remotes `origin` (source, `--mirror=fetch`) and `somc` (target).
- Updated sidecar file, written **only after all pushes succeed**.
- On the target server: the pushed branches and tags.

## Key Functions / Logic

The script has no functions. It runs in this order:

| Step | Lines | Purpose |
|---|---|---|
| Argument check | 21-30 | Read source, target, refspec, push args; exit 1 if any required one is empty. |
| Sidecar name | 50-72 | `SHA1SUM_NAME = <persistent dir>/<parent dir of source>-<git name>-ref-sha1sum`. The parent-dir prefix avoids clashes between gits with the same basename. |
| Lock | 79 | Re-executes itself under `flock -e -w 60` on the sidecar file. A second run for the same git waits 60 s, then fails with exit 1. |
| Bare clone | 84-88 | `git init --bare` (no-op if it exists), recreate remote `origin` with `--tags --mirror=fetch`. |
| Mirror alternates | 90-105 | Remove old alternates; add `SOURCE_MIRROR` objects if the mirror matches the source. |
| Fetch | 107-115 | For each comma-separated refspec, `git fetch origin +<lhs>:<lhs>` (forced, so upstream rewrites are always accepted locally). |
| Change check | 117-120 | Compare `git show-ref | sha1sum` with the sidecar. Same: `PUSH=0`, nothing is pushed. |
| Push | 122-130 | Add remote `somc` if missing; `git push <args> somc <refspec>` for each refspec; then write the new SHA-1 to the sidecar. |

## Notes

- **Non-fast-forward rejections:** the fetch is forced but the push is not (unless `PUSH_ARGS` has `--force`). When upstream rewrites a branch (common on AOSP `-sp` and beta branches), the push is rejected and the build fails. Because the sidecar is not updated on failure, the next run tries again. The fix is the obsolete-branch procedure on the review server, then a rerun.
- **Deleted target branch is not re-pushed:** if someone deletes a branch on the review server while upstream has not changed, the SHA-1 still matches and the script pushes nothing. Delete or empty the sidecar file to force a push.
- **Changed `TARGET_URL` is ignored:** `git remote | grep somc || git remote add somc` keeps an existing `somc` remote. In the persistent directory, an old URL survives a parameter change. Fix with `git remote set-url somc <new>` in the bare clone, or delete the clone directory.
- **Refspec separator is a comma,** not a space. The fetch loop uses `eval`, so refspecs must not contain shell metacharacters.
- **Lock timeout:** `flock` waits at most 60 s. A failure with *"flock: failed to get lock"* means another build or a manual run holds the same git.
- **Where to look on the node:** `/home/code-sync/workspace/sync-git-persistent-data/` when persistence is on; otherwise the job workspace. [Unconfirmed] Confirm the workspace root on `prod-codesync`.
- **`origin` grep is loose:** `git remote | grep 'origin'` also matches a remote named e.g. `origin2`. Harmless in practice.
