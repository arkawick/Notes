## CodeSync Script Documentation
#### Script: [common.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/common.sh)
#### Purpose:
`Provide change_project_names, which converts Qualcomm and CodeLinaro project names to the names used on review.ptc.sony.co.jp`

This file is sourced by other scripts, not run on its own. In Jenkins, a failed name conversion stops the build.

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [common.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/common.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: not called directly. Used by
  - all `sync_manifest_*` jobs, through `ohd.sh` and `ensure-projects-exist.sh`
  - all `import_qcom_*` jobs, through `qcom-import.sh` and `qcom-ref.sh`

- `Parent Scripts(s)` :
  - [ensure-projects-exist.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/ensure-projects-exist.sh#3)
  - [qcom-import.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-import.sh#5)
  - [qcom-ref.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-ref.sh#4)
  - [test_change_project_names.py](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/tests/unit/test_change_project_names.py) (unit test)

**Calls Internal Scripts:**<br>

- [change_project_names.py](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/change_project_names.py)

**External Tools/Python packages dependencies**<br>

- python3, standard library only

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: N/A

**Manual Execution**<br>
```bash
source code-sync/common.sh
```
```bash
change_project_names AU_TAG.bak_change.xml > AU_TAG.xml
```
> eg; change_project_names <<< "clo/la/platform/build.git"
```bash
change_project_names -i project.list
```
> eg; for Qualcomm names, set AU_TAG and TREE_TYPE like the import job, or the result will be different
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| path | N | File to convert. Reads stdin if not given. |
| -o, --output | N | Write the result to a file |
| -i, --in-place | N | Change the file in place. Cannot be used with -o. |
| --xml | N | Force XML mode (`--xml=no` forces text). Default: XML for `.xml` files. |

---
**Input**<br>

- `Input file(s)`: manifest XML or project list, one name per line
- `Environment Variables`:

| Variable | Description |
| :---: | :---: |
| JOB_NAME | If set (Jenkins), a failure stops the build. Also used to find the manifest type. |
| AU_TAG | If set, the Qualcomm rules are used |
| TREE_TYPE | Qualcomm tree type, eg; kernel, vendor, QSSI |

---
**Output**<br>

- `Log files`: `change_project_names: failed with status <n>` on failure
- `Reports`: N/A
- `Generated artifacts`: converted manifest or project list

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [change_project_names](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/common.sh#5-24) | Run `change_project_names.py`. On failure, stop the shell in Jenkins, or return the error outside Jenkins. |
| [main](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/change_project_names.py#114) | Read the options, find the manifest type and apply the rules below |

| Manifest type | Rule |
| :---: | :---: |
| All | Remove `.git`, `revision-history/` and `clo/la/` |
| Qualcomm | Remove `_repo` and `_group/`. On kernel trees, rename `platform/external/dtc` to `dtc-kernel` (CM-4851). |
| Exceptions | Keep `maven_repo/` in `platform/prebuilts/maven_repo/bumptech` |

---
**Notes**<br>
- In Jenkins a failure stops the build, so nothing is pushed to a wrong project name.
- After changing a rule in `change_project_names.py`, run `python3 -m unittest tests.unit.test_change_project_names -v`.
- Source this file. Do not run it directly.
