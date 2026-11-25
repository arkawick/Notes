## CodeSync Script Documentation
#### Script: [ohd.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh)
#### Purpose:
`Sync a manifest and all its gits from AOSP or partner-android to review.ptc.sony.co.jp, then create the semc/<remote>/<branch> manifest`

The `semc/<remote>/<branch>` manifest points every git to the imported `<remote>/...` branches. The script checks it with a full `repo sync` from the review server.

| PUSH_MODE | What is pushed for each git |
| :---: | :---: |
| single | The manifest revision, to `<remote>/<branch>` |
| all | Every upstream branch that has the manifest revision, to `<remote>/<br>`. For the manifest git also `builds/<branch>/*`. |
| tag | The tag and the branches that have it. The manifest is pushed as `<remote>/<tag>`. |

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [ohd.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/ohd.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: all `sync_manifest_*` and `sync_manifest_and_gits_*` jobs, defined in [template-sync.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/template-sync.yaml#109-250)
  - [sync_manifest_oss_tag](https://codesync.ptc.sony.co.jp/job/sync_manifest_oss_tag/): AOSP, tag mode, started by `monitor_refs_aosp-platform-manifest`
  - `sync_manifest_oss_<branch>`: AOSP, single mode, in [project-aosp.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/codesync.ptc.sony.co.jp/project-aosp.yaml)
  - `sync_manifest_ohd_<branch>`: partner-android, single or all mode, in [project-partner.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/codesync.ptc.sony.co.jp/project-partner.yaml)
  - `sync_manifest_and_gits_ohd_<branch>`: partner-android, all mode, eg; [sync_manifest_and_gits_ohd_c-aml-prebuilt-release](https://codesync.ptc.sony.co.jp/job/sync_manifest_and_gits_ohd_c-aml-prebuilt-release/)

- `Parent Scripts(s)` : None

**Calls Internal Scripts:**<br>

- [config.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh): default URLs and `find_repo_manifest`
- [ensure-projects-exist.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ensure-projects-exist.sh): creates missing gits on the review server. It uses [common.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/common.sh).

**External Tools/Python packages dependencies**<br>

- repo
- git
- ssh to Gerrit port 29418
- python3

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: [sync_manifest_oss_tag](https://codesync.ptc.sony.co.jp/job/sync_manifest_oss_tag/)

```bash
[ "$BRANCH" = "tag" ] && export BRANCH=$TAG
export GERRIT_PUSH_URL=git://review.ptc.sony.co.jp
mkdir -p repo result-dir && cd repo
../code-sync/ohd.sh $MANIFEST $BRANCH $REMOTE
cp -v repo/static_manifest.xml repo/manifest_revision result-dir/
```

**Manual Execution**<br>
```bash
mkdir -p repo && cd repo
```
```bash
export SOURCE_GERRIT="https://aosp-mirror.ptc.sony.co.jp:8443"
export PUSH_MODE="single"
export GERRIT_PUSH_URL="git://review.ptc.sony.co.jp"
export SKIP_PUSH="true"
```
> eg; SKIP_PUSH=true skips the git pushes, but the manifest branches are still pushed
```bash
bash ../code-sync/ohd.sh platform/manifest <branch> oss
```
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| $1 manifest | Y | Manifest git, eg; `platform/manifest` |
| $2 branch | Y | Manifest branch, or the tag name in tag mode |
| $3 remote | Y | Branch prefix on the review server, eg; `oss`, `ohd` |
| SOURCE_GERRIT | Y | Source server URL, eg; `https://aosp-mirror.ptc.sony.co.jp:8443` |
| PUSH_MODE | Y | `single`, `all` or `tag` |
| REPO_INIT_ARGS | N | Extra `repo init` options |
| REPO_FORALL_ARGS | N | Extra `repo forall` options, eg; `-j20` |
| GIT_PUSH_ARGS | N | Extra `git push` options, eg; `--force -o skip-validation` |
| SKIP_SYNC | N | true: reuse the existing mirror, no `repo sync` |
| SKIP_PUSH | N | true: skip the git pushes |
| EXCLUDED_PROJECTS | N | Gits to leave out, one per line |

---
**Input**<br>

- `Input file(s)`: N/A. The script creates `ohd/` and `ref/` in the current folder and reuses them.
- `Environment Variables`:

| Variable | Description |
| :---: | :---: |
| AOSP_MIRROR | Local mirror for the source sync. The job sets it from SOURCE_GERRIT. |
| REPO_MIRROR | Local mirror for the reference sync |
| GERRIT_PUSH_URL | Push URL. Default `git://review.ptc.sony.co.jp` |

---
**Output**<br>

- `Log files`: Jenkins console only
- `Reports`: N/A
- `Generated artifacts`:
  - `static_manifest.xml`: final manifest with every git pinned to a SHA-1
  - `manifest_revision`: SHA-1 of the manifest commit
- On the review server:
  - git branches `<remote>/<branch>`, and tags in tag mode
  - manifest branches `<remote>/<branch>` and `semc/<remote>/<branch>`
  - `semc/<remote>/<tag>-cache` for tag commits that are on no branch
  - new gits, created under `admin/meta/android-standard`

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [Check parameters](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#5-38) | Stop if a required value is missing |
| [Mirror source](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#41-64) | `repo init --mirror` and `repo sync` from upstream in `ohd/` |
| [Create gits](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#70-77) | Create missing gits on the review server |
| [Push gits](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#79-131) | Push each git based on PUSH_MODE. Refs already on the review server are skipped. |
| [Push manifest](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#133-137) | Push the manifest branch `<remote>/<branch>` |
| [Reference manifest](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#139-184) | Update `semc/<remote>/<branch>` to use the `<remote>/...` branches, sync it, push it, sync again from the review server |
| [Verify tag](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#185-194) | Tag mode: wait 180 s, then sync the tag from the review server |
| [Save results](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#196-204) | Write the output files and delete old temp pack files |

---
**Notes**<br>
- Rerun is safe. Anything already on the review server is skipped.
- If upstream rewrites a branch, the push fails with "non-fast-forward". Move the old branch aside on the review server, or add `--force` to `GIT_PUSH_ARGS`.
- `SKIP_PUSH=true` still pushes the manifest branch and the `semc/...` branch.
- If the last `repo sync` fails after the push, replication was probably slow. Rerun.
- If `ref/.repo` gets broken, delete it by hand.
- If nothing changed since the last good build, the job marks itself `NONEW` and stops.
