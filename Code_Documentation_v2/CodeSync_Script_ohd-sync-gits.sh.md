## CodeSync Script Documentation
#### Script: [ohd-sync-gits.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd-sync-gits.sh)
#### Purpose:
`Sync the tags of the Android Mainline gits in a manifest from partner-android to review.ptc.sony.co.jp`

It takes the gits under `platform/prebuilts/module_sdk/` and `platform/vendor/partner_modules/` from the manifest and runs `git.sh` for each one.

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [ohd-sync-gits.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/ohd-sync-gits.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: all `sync_manifest_and_gits_ohd_*` jobs, defined in [template-sync.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/template-sync.yaml#254-330) and run through the [sync-gits-in-manifest](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/macros.yaml#73-82) macro, right after `ohd.sh`
  - Enabled on prod: `v-`, `b-`, `c-`, `c1-`, `c2-aml-prebuilt-release`, eg; [sync_manifest_and_gits_ohd_c-aml-prebuilt-release](https://codesync.ptc.sony.co.jp/job/sync_manifest_and_gits_ohd_c-aml-prebuilt-release/)
  - Disabled: `t-`, `t-go-`, `u-aml-prebuilt-release`

- `Parent Scripts(s)` : None

**Calls Internal Scripts:**<br>

- [git.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/git.sh)

**External Tools/Python packages dependencies**<br>

- git
- grep, sed

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: [sync_manifest_and_gits_ohd_c-aml-prebuilt-release](https://codesync.ptc.sony.co.jp/job/sync_manifest_and_gits_ohd_c-aml-prebuilt-release/)

```bash
export SOURCE_MIRROR=/mnt/ebs2/gitmirror/partner-android.googlesource.com
export GIT_SYNC_PERSISTENT_VAR_DIR=$(realpath $WORKSPACE/../sync-git-persistent-data)
code-sync/ohd-sync-gits.sh "repo/static_manifest.xml"
```

**Manual Execution**<br>

Run from the folder that has `code-sync/` in it.
```bash
export GIT_SYNC_PERSISTENT_VAR_DIR="$HOME/sync-git-manual"
```
> eg; use your own folder so the saved state of the Jenkins job is not touched
```bash
bash code-sync/ohd-sync-gits.sh repo/static_manifest.xml
```
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| $1 manifest_file | Y | Manifest XML to read the git list from. In the job: `repo/static_manifest.xml` |

---
**Input**<br>

- `Input file(s)`: manifest XML written by `ohd.sh`, one project per line
- `Environment Variables`:

| Variable | Description |
| :---: | :---: |
| GIT_PUSH_ARGS | Extra push options, passed to every `git.sh` call |
| SOURCE_MIRROR, GIT_SYNC_PERSISTENT_VAR_DIR | Not used here, passed on to `git.sh` |

Fixed in the script:

| Setting | Value |
| :---: | :---: |
| Gits selected | `platform/prebuilts/module_sdk/*`, `platform/vendor/partner_modules/*` |
| Source | `https://partner-android.googlesource.com/<git>` |
| Target | `git://review.ptc.sony.co.jp/<git>` |
| Refspec | `refs/tags/*:refs/tags/*` |

---
**Output**<br>

- `Log files`: Jenkins console only
- `Reports`: N/A
- `Generated artifacts`: clones and sha1sum files kept by `git.sh` in `sync-git-persistent-data/`, new tags on the review server

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [Check arguments](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd-sync-gits.sh#14-15) | Stop if no manifest is given |
| [Select gits](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd-sync-gits.sh#17-19) | Pick the `module_sdk` and `partner_modules` gits from the manifest |
| [Sync loop](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd-sync-gits.sh#21-27) | Run `git.sh` for each git. A failure only prints a warning. |

---
**Notes**<br>
- A failed git does not fail the build. Search the console for `WARNING: git.sh terminates`.
- Only tags are synced here. Branches are pushed earlier by `ohd.sh` in the same job.
- Source and target hosts are hard-coded, so it works only for partner-android.
- A rerun only pushes gits that changed or failed before.
