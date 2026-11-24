# Script: ohd.sh

> **Source:** `code-sync-refs_heads_master/ohd.sh` (branch `master`, 205 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Mirrors a whole **repo manifest** (manifest git + every project in it) from an upstream Gerrit (AOSP or partner-android) into `review.ptc.sony.co.jp`. It then builds and pushes a Sony **reference manifest** branch `semc/<remote>/<branch>` that points every project at the imported `<remote>/...` branches, and checks it with a full `repo sync` from the review server.

It has three push modes:

| `PUSH_MODE` | What is pushed per project |
|---|---|
| `single` | The manifest revision of each project, to `refs/heads/<remote>/<branch>` |
| `all` | Every upstream branch that contains the manifest revision, to `refs/heads/<remote>/<br>`; for the manifest git also its `builds/<branch>/*` branches |
| `tag` | Tag `<branch>` (a tag name) and the branches containing it; manifest pushed as `<remote>/<tag>` |

## Location

[`code-sync-refs_heads_master/ohd.sh`](../../code-sync-refs_heads_master/ohd.sh)

## Called By

| Caller | How |
|---|---|
| **Jenkins jobs:** `sync_manifest_<remote>_<branch>` and `sync_manifest_and_gits_<remote>_<branch>` (templates in `jenkins-jobs/template-sync.yaml`, shared shell anchor `shell_sync_manifest`) | `cd repo && ../code-sync/ohd.sh $MANIFEST $BRANCH $REMOTE` |
| Prod instances | `sync_manifest_oss_<branch>` (AOSP, `single`), `sync_manifest_oss_tag` (AOSP, `tag`, triggered by `monitor_refs_aosp-platform-manifest`), `sync_manifest_ohd_<branch>` (partner, `single`/`all`), `sync_manifest_and_gits_ohd_<branch>` (partner, `all`) |
| **Parent script:** none | |

## Calls Internal Scripts

- [`config.sh`](CodeSync_Script_config.sh.md) (sourced): `GERRIT_FETCH_URL`, `GERRIT_PUSH_URL`, `CODE_SYNC_DIR`, `find_repo_manifest`
- `ensure-projects-exist.sh admin/meta/android-standard`: creates missing projects on the review server. It sources [`common.sh`](CodeSync_Script_common.sh.md) and runs `change_project_names.py`.

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `repo` | `init --mirror`, `sync`, `forall`, `manifest -r` |
| `git` | `fetch`, `push`, `ls-remote`, `merge`, `commit` |
| `ssh` to Gerrit (port 29418) | `gerrit ls-projects` / `create-project` inside `ensure-projects-exist.sh` |
| `python3` | `change_project_names.py` (via `ensure-projects-exist.sh`) |
| `sed`, `grep -P`, `awk`, `find` | Manifest rewrite and cleanup |

## Usage

### Jenkins

- **Job name:** e.g. `sync_manifest_oss_tag`, `sync_manifest_ohd_<branch>`, `sync_manifest_and_gits_ohd_c-aml-prebuilt-release`
- **Job shell (simplified):**

```bash
[ "$BRANCH" = "tag" ] && export BRANCH=$TAG
export GERRIT_PUSH_URL=git://review.ptc.sony.co.jp
mkdir -p repo result-dir && cd repo
# AOSP_MIRROR = /mnt/ebs2/gitmirror/partner-android.googlesource.com  (partner)
#             = /mnt/ebs2/gitmirror/android.googlesource.com          (aosp-mirror)
../code-sync/ohd.sh $MANIFEST $BRANCH $REMOTE
cp -v repo/static_manifest.xml repo/manifest_revision result-dir/
```

### Manual Execution

Dry run (mirror and reference build, **no project pushes**). Note that the manifest-branch push in step 5 below still runs:

```bash
mkdir -p repo && cd repo
export SOURCE_GERRIT=https://aosp-mirror.ptc.sony.co.jp:8443
export PUSH_MODE=single
export GERRIT_PUSH_URL=git://review.ptc.sony.co.jp
export SKIP_PUSH=true
../code-sync/ohd.sh platform/manifest <branch> oss
```

## Parameters

Positional arguments (all required, exit 1 if empty):

| Parameter | Required (Y/N) | Description |
|---|---|---|
| `$1` manifest | Y | Manifest git path on the source, e.g. `platform/manifest` |
| `$2` branch | Y | Manifest branch, or the tag name when `PUSH_MODE=tag` |
| `$3` remote | Y | Prefix for the target branches, e.g. `oss` (AOSP), `ohd` (partner) |

Environment variables used as parameters (job parameters of the same name):

| Variable | Required (Y/N) | Description |
|---|---|---|
| `SOURCE_GERRIT` | Y | Source base URL, e.g. `https://aosp-mirror.ptc.sony.co.jp:8443` |
| `PUSH_MODE` | Y | `single`, `all` or `tag`. Anything else: `Unknown mode`, exit 1. |
| `REPO_INIT_ARGS` | N | Extra `repo init` arguments |
| `REPO_FORALL_ARGS` | N | Extra `repo forall` arguments, e.g. `-j20` |
| `GIT_PUSH_ARGS` | N | Extra `git push` arguments, e.g. `--force -o skip-validation` |
| `SKIP_SYNC` | N | `true`: reuse the existing `ohd/` mirror, no `repo init`/`sync` |
| `SKIP_PUSH` | N | `true`: skip the per-project pushes |
| `EXCLUDED_PROJECTS` | N | Project names (whitespace separated) written as `<remove-project>` into a local manifest |
| `AOSP_MIRROR` | N | `--reference` for the source mirror sync |
| `REPO_MIRROR` | N | `--reference` for the reference workspace sync |
| `GERRIT_PUSH_URL` | N | Push base URL. Default from `config.sh` = `GERRIT_FETCH_URL` = `git://review.ptc.sony.co.jp` |

## Input

**Input files:** none from the caller. The script creates `ohd/` and `ref/` under the current directory and reuses them between builds.

**Environment variables:** see Parameters. Hard-coded: `check_url=git://review.ptc.sony.co.jp`, `njobs=16`.

## Output

**Log files:** console only (`bash -xe`).

**Reports:** none.

**Generated artifacts** (in the current directory, archived by the job from `result-dir/`):
- `static_manifest.xml`: `repo manifest -r` of the final reference workspace (every project pinned to a SHA-1)
- `manifest_revision`: SHA-1 of the manifest commit that was pushed / synced

**On the review server:**
- Project branches `refs/heads/<remote>/<branch>` (or per-branch in `all` / `tag` mode), tags in `tag` mode
- Manifest branch `<remote>/<branch>` (copy of upstream)
- Reference manifest branch `semc/<remote>/<branch>` (not in `tag` mode)
- `semc/<remote>/<tag>-cache` branches for tag commits not on any branch
- Any missing projects, created under parent `admin/meta/android-standard`

## Key Functions / Logic

`ohd.sh` defines no functions of its own; it uses `find_repo_manifest` from `config.sh`.

| Step | Lines | Purpose |
|---|---|---|
| 1. Validate | 5-38 | Check the three arguments, `SOURCE_GERRIT`, `PUSH_MODE`. |
| 2. Mirror source | 41-64 | In `ohd/`: delete `.repo`, `repo init --mirror` (by branch, or `refs/tags/<branch>` in tag mode), write `EXCLUDED_PROJECTS` local manifest, `repo sync -d -j16`. Skipped with `SKIP_SYNC=true`. |
| 3. Create projects | 77 | `ensure-projects-exist.sh admin/meta/android-standard`. |
| 4. Push projects | 79-131 | `repo forall` per `PUSH_MODE`. Before every push, `git ls-remote` on the review server checks whether the target already has the commit, so already-pushed refs are skipped. `git-repo` is always skipped. Skipped with `SKIP_PUSH=true`. |
| 5. Push manifest branch | 133-137 | `git push semc origin/<branch>:refs/heads/<remote>/<branch>` from `.repo/manifests`. |
| 6a. Reference manifest (not tag) | 143-184 | In `ref/`: `repo init -b semc/<remote>/<branch>`, merge upstream `origin/<remote>/<branch>` with `-X theirs`, rewrite `default.xml` (revisions to `<remote>/...`, remote name `origin`, review URL `https://review.ptc.sony.co.jp`, drop `clone-depth`), commit or amend, `repo sync` (retries once after wiping), push `semc/<remote>/<branch>`, wait 30 s, final `repo init` + `repo sync` from the review server. |
| 6b. Verify tag | 185-194 | Wait 180 s for replication, `repo init -b refs/tags/<tag>` from the review server, `repo sync` (retries once after `rm -rf *`). |
| 7. Record | 196-197 | Write `static_manifest.xml` and `manifest_revision`. |
| 8. Cleanup | 201-204 | Delete `tmp_pack_*` / `.tmp-*` pack files older than ~2 days under the workspace. |

## Notes

- **Rerun is idempotent for pushes:** every push is guarded by an `ls-remote` check, so a rerun only pushes what is missing.
- **No force push by default:** an upstream history rewrite gives `! [rejected] (non-fast-forward)`. Either obsolete the branch on the review server, or the job's `GIT_PUSH_ARGS` must carry `--force` (the daily `sync_manifest_oss_android-latest-release` uses `--force -o skip-validation`).
- **`SKIP_PUSH=true` is not a full dry run:** step 5 (manifest branch) and step 6a (`semc/...` push) still push.
- **Workspace reuse:** `ohd/` and `ref/` persist between builds. A broken `.repo/` in `ref/` needs manual cleanup; `ohd/.repo` is deleted on every non-`SKIP_SYNC` run.
- **Fixed waits:** 30 s (branch mode) and 180 s (tag mode) for replication. Slow replication makes the final `repo sync` fail after a successful push; rerun.
- **Manifest rewrite caution:** `sed 's/name="\w+"/name="origin"/'` renames the first `name="..."` made only of word characters on each line. It targets `<remote name=...>`, but would also rename a project whose name has no `/`. [Unconfirmed] Whether any current manifest has such a project.
- **`git://` push URL:** the job sets `GERRIT_PUSH_URL=git://review.ptc.sony.co.jp`; pushes work only through the `code-sync` user's git `insteadOf` rewrite to SSH.
- **Downstream:** after `ohd.sh`, the job compares `static_manifest.xml` with the last successful build. If identical, it sets the description `NONEW` and stops itself; otherwise it triggers `build_<remote>_<branch>`.
