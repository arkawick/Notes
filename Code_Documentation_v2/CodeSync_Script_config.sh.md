## CodeSync Script Documentation
#### Script: [config.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh)
#### Purpose:
`Set common variables (Gerrit URLs, CPU count, script folder, repo init options) for CodeSync scripts`

This file is sourced by other scripts, not run on its own.

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [config.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/config.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: not called directly. Used through `ohd.sh` by all `sync_manifest_*` jobs, eg; [sync_manifest_oss_tag](https://codesync.ptc.sony.co.jp/job/sync_manifest_oss_tag/)

- `Parent Scripts(s)` : [ohd.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ohd.sh#3)

**Calls Internal Scripts:**<br>

- No Internal Calls to other scripts

**External Tools/Python packages dependencies**<br>

- bash 4.2 or later
- grep, wc, sed, readlink

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: N/A

**Manual Execution**<br>
```bash
required_vars="SOURCE_GERRIT PUSH_MODE"
```
> eg; optional, the script stops if one of these is not set
```bash
source $(readlink -f $(dirname $0))/config.sh
```
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| N/A | N/A | No arguments. It reads the environment variables below. |

---
**Input**<br>

- `Input file(s)`: N/A
- `Environment Variables`:

| Variable | Description |
| :---: | :---: |
| GERRIT_FETCH_URL | Set to `git://review.ptc.sony.co.jp` if empty |
| GERRIT_PUSH_URL | Set to GERRIT_FETCH_URL if empty |
| HY11_CHIPSET | If set, HY11_SUFFIX becomes `-<chipset>` |
| required_vars | Variable names that must be set. The script stops if one is missing. |
| REPO_MIRROR | If set, added to COMMON_REPO_INIT_ARGS as `--reference` |

---
**Output**<br>

- `Log files`: N/A
- `Reports`: N/A
- `Generated artifacts`: N/A. It exports these variables:

| Variable | Value |
| :---: | :---: |
| GERRIT_FETCH_URL | `git://review.ptc.sony.co.jp` unless already set |
| GERRIT_PUSH_URL | GERRIT_FETCH_URL unless already set |
| HY11_SUFFIX | `-<HY11_CHIPSET>` |
| CPU_NO | Number of CPUs |
| CODE_SYNC_DIR | Folder of the script that sources this file |
| COMMON_REPO_INIT_ARGS | `--repo-branch stable --no-repo-verify`, plus the mirror reference |

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [Default URLs](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh#1-3) | Set the review server URLs and HY11_SUFFIX |
| [CPU_NO, CODE_SYNC_DIR](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh#5-7) | Set the CPU count and the script folder |
| [required_vars](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh#9-14) | Stop if a required variable is missing |
| [COMMON_REPO_INIT_ARGS](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh#16-20) | Common `repo init` options |
| [find_repo_manifest](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/config.sh#22-29) | Find the real manifest file behind `.repo/manifest.xml`. Used by `ohd.sh`. |

---
**Notes**<br>
- Only `ohd.sh` uses this file. The Qualcomm scripts get the same values from `qcom-prepare.sh`.
- `CODE_SYNC_DIR` is the folder of the script that sources this file.
- `required_vars` and `COMMON_REPO_INIT_ARGS` are not used by any script on `master`.
- Source this file. Do not run it directly.
