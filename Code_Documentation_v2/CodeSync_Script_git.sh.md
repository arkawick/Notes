## CodeSync Script Documentation
#### Script: [git.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh)
#### Purpose:
`Sync one git from upstream to review.ptc.sony.co.jp. Push only when the upstream refs changed since the last successful push.`

The script keeps a bare clone and a `<name>-ref-sha1sum` file with the state of the last push. If the fetched refs give the same sha1sum, nothing is pushed.

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [git.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/git.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: all `sync_git_*` jobs, defined in [template-sync.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/template-sync.yaml#4-50) and run through the [sync-git](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/macros.yaml#62-71) macro
  - [sync_git_aosp-kernel-common](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-common/)
  - [sync_git_aosp-kernel-build](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-build/)
  - [sync_git_aosp-kernel-manifest](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-manifest/)
  - [sync_git_aosp-kernel-msm](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-msm/)
  - [sync_git_aosp-kernel-prebuilts-build-tools](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-prebuilts-build-tools/)
  - [sync_git_aosp-kernel-common-modules-wonder](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-common-modules-wonder/)
  - `sync_git_partner-*` jobs in [project-partner.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/codesync.ptc.sony.co.jp/project-partner.yaml)

- `Parent Scripts(s)` : [ohd-sync-gits.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd-sync-gits.sh#21-27), once per Mainline git, tags only

**Calls Internal Scripts:**<br>

- No Internal Calls to other scripts

**External Tools/Python packages dependencies**<br>

- git
- flock
- sha1sum, sed, realpath

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: [sync_git_aosp-kernel-common](https://codesync.ptc.sony.co.jp/job/sync_git_aosp-kernel-common/)

```bash
[ -d "{path-to-mirror}" ] && export SOURCE_MIRROR={path-to-mirror}
[ "{persistent-var-files}" = "true" ] && \
  export GIT_SYNC_PERSISTENT_VAR_DIR=$(realpath $WORKSPACE/../sync-git-persistent-data)
code-sync/git.sh $SOURCE_URL $TARGET_URL $REFSPEC $PUSH_ARGS
```

**Manual Execution**<br>

Run as `code-sync` on the CodeSync node.
```bash
git clone -b master git://review-plus.ptc.sony.co.jp/code-sync.git
```
```bash
export GIT_SYNC_PERSISTENT_VAR_DIR="$HOME/sync-git-manual"
```
> eg; use your own folder so the saved state of the Jenkins job is not touched
```bash
bash code-sync/git.sh https://android.googlesource.com/kernel/common \
     ssh://xscm01@review.ptc.sony.co.jp:29418/kernel/common \
     'refs/heads/*:refs/heads/oss/*' --tags
```
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| $1 source | Y | Upstream git URL. Its name is used for the clone and the sha1sum file. |
| $2 target | Y | Review server git URL, added as remote `somc` |
| $3 refspec | Y | Refspecs to sync, comma separated, eg; `refs/heads/*:refs/heads/oss/*,refs/tags/*:refs/tags/*` |
| $4... push args | N | Extra `git push` options, eg; `--tags`, `--force`, `-o skip-validation` |

The script stops with exit 1 if source, target or refspec is empty.

---
**Input**<br>

- `Input file(s)`: `<parent>-<name>-ref-sha1sum`, the state of the last push. Created empty if missing.
- `Environment Variables`:

| Variable | Default | Description |
| :---: | :---: | :---: |
| GIT_SYNC_PERSISTENT_VAR_DIR | not set | Folder that keeps the clone and the sha1sum file between builds. The job sets it to `$WORKSPACE/../sync-git-persistent-data`. |
| USE_GIT_SYNC_PERSISTENT_VAR_DIR | true | Set to false to ignore the folder above |
| SOURCE_MIRROR | not set | Local mirror. If it has the same git, its objects are reused instead of downloaded. |
| USE_SYSTEM_GIT_CONFIG | not set | Set to false to skip the system git config |

---
**Output**<br>

- `Log files`: Jenkins console only
- `Reports`: N/A
- `Generated artifacts`:
  - bare clone `<name>.git` with remotes `origin` (upstream) and `somc` (review server)
  - updated sha1sum file, written only after all pushes worked
  - pushed branches and tags on the review server

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [Check arguments](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#21-30) | Stop if source, target or refspec is missing |
| [sha1sum file name](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#49-72) | Build the file name from the parent folder and git name, so two gits with the same name don't clash |
| [Lock](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#74-79) | Allow only one run per git. A second run waits 60 s, then fails. |
| [Prepare clone](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#81-88) | Create the bare clone and set remote `origin` |
| [Use mirror](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#90-105) | Link the local mirror if it has the same git |
| [Fetch](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#107-115) | Force-fetch each refspec from upstream |
| [Check for changes](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#117-120) | Compare the new sha1sum with the saved one. Same means no push. |
| [Push](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh#122-130) | Push each refspec to `somc`, then save the new sha1sum |

---
**Notes**<br>
- If upstream rewrites a branch, the push fails with "non-fast-forward". Move the old branch aside on the review server and rerun.
- If a branch is deleted on the review server and upstream has not changed, the script will not push it again. Delete the `<name>-ref-sha1sum` file to force a push.
- If `TARGET_URL` changes, the old URL is still used. Delete the saved clone or run `git remote set-url somc <new-url>` in it.
- Separate multiple refspecs with a comma, not a space.
- "flock: failed to get lock" means another run is syncing the same git. Wait and rerun.
