## CodeSync Script Documentation
#### Script: [stageskipper.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh)
#### Purpose:
`Let Qualcomm import jobs start from a stage (SKIP_STAGES_BEFORE) or stop at a stage (STOP_BUILD_AT_STAGE)`

This file is sourced by other scripts. The stage settings are kept in environment variables, so they carry over between Jenkins build steps.

---
**Location**<br>

`Gerrit Repository` -> [code-sync](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master)<br>
`Gerrit` -> [stageskipper.sh](https://review-plus.ptc.sony.co.jp/plugins/gitiles/code-sync/+/refs/heads/master/stageskipper.sh)<br>

---
**Called By:**<br>

- `Jenkins Job`: all `import_qcom_*` and `import_qcom_simple_*` jobs, defined in [template-qcom.yaml](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/jenkins-jobs/template-qcom.yaml#106-120)

- `Parent Scripts(s)` :
  - Set up the stages: [qcom-prepare.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-prepare.sh#98-110), [qcom-simple-prepare.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-simple-prepare.sh#37-49)
  - Check each stage: [qcom-import.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-import.sh), [qcom-hy11.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-hy11.sh), [qcom-ref.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-ref.sh), [qcom-ref-tag.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-ref-tag.sh), [qcom-simple-import.sh](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/qcom-simple-import.sh), and the `*-sdph2021.sh` versions

**Calls Internal Scripts:**<br>

- No Internal Calls to other scripts

**External Tools/Python packages dependencies**<br>

- bash
- sed, grep
- gawk

---
**Usage**<br>
##### Jenkins<br>
`Job Name`: any `import_qcom_*` or `import_qcom_simple_*` job

| Parameter | Example | Effect |
| :---: | :---: | :---: |
| SKIP_STAGES_BEFORE | ref-manifest | Start the import at ref-manifest. Also untick CLEANUP_WORKING_DIR. |
| STOP_BUILD_AT_STAGE | syncsnap-push | Stop before syncsnap-push. The build is UNSTABLE. |

| Job type | Stages in order |
| :---: | :---: |
| import_qcom_* | prepare-utilities, syncsnap, syncsnap-notdefault, syncsnap-list, syncsnap-push, hy11, ref-manifest, ref-repo-init, ref-repo-sync, ref-push, ref-tag |
| import_qcom_simple_* | repo-init-sync, make-repo-list, git-push, ref-manifest, ref-repo-init, ref-repo-sync, ref-push, ref-tag |

**Manual Execution**<br>
```bash
set -e
source code-sync/stageskipper.sh
stageskipper_init
stageskipper_add_stage prepare build push all
stageskipper_set_goto build
stageskipper_exit_at push
stageskipper_dump_vars > envs.txt
```
> eg; this skips prepare, runs build and stops before push
```bash
if ! stageskipper_is_skipping prepare; then echo "do prepare"; fi
if ! stageskipper_is_skipping build;   then echo "do build";   fi
stageskipper_is_skipping push
```
---
**Parameters**<br>
| Parameter | Required (Y/N) | Description |
| :---: | :---: | :---: |
| stageskipper_add_stage <names> | Y | Stage names in run order. No spaces or `:` in a name. |
| stageskipper_set_goto <stage> | N | Stage to start from |
| stageskipper_exit_at <stage> [status] | N | Stage to stop at. Exit status 22 by default. |
| stageskipper_is_skipping [--no-banner] <stage> | Y | Name of the current stage |

---
**Input**<br>

- `Input file(s)`: N/A. In Jenkins the prepare script saves the settings in `variables.txt`, which is injected into the next step.
- `Environment Variables`:

| Variable | Description |
| :---: | :---: |
| STAGESKIPPER_INITIALIZED | 1 after init |
| STAGESKIPPER_STAGES | All stages, eg; `:stage1:stage2:` |
| SKIPPED_STAGES | Stages to skip |
| FORCE_EXIT_AT_STAGE | Stage to stop at |
| FORCE_EXIT_STATUS | Exit status for the stop, default 22 |

---
**Output**<br>

- `Log files`: Jenkins console only, eg; `Stage: ref-manifest 14:03:27 --- SKIPPED` between two lines of `=`
- `Reports`: N/A
- `Generated artifacts`: N/A

---
**Key Functions / Logic**
| Function | Purpose |
| :---: | :---: |
| [stageskipper_init](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#28-42) | Reset the stage settings |
| [stageskipper_ensure_init](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#44-50) | Stop if init was not run |
| [stageskipper_dump_vars](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#52-60) | Print the settings for the next build step |
| [stageskipper_add_stage](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#62-70) | Add stage names in run order |
| [stageskipper_set_goto](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#72-86) | Mark all stages before the given one as skipped |
| [stageskipper_exit_at](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#88-112) | Set the stage where the job stops |
| [stageskipper_is_skipping](https://www.unifys.sony.co.jp/opengrok/mc/CM/xref/master/code-sync/stageskipper.sh#114-150) | Print the stage banner. Stop the job, skip the stage or let it run. |

---
**Notes**<br>
- `STOP_BUILD_AT_STAGE` needs the shell to run with `-e`. The import job already does this.
- A stop at a stage shows the build as UNSTABLE, not FAILED.
- To restart a failed import from a stage, set `SKIP_STAGES_BEFORE=<stage>` and untick `CLEANUP_WORKING_DIR`.
- Stage names are case-sensitive. A wrong name fails the build at once.
- The usage comment in the script says `stageskipper_dump_envs`; the real name is `stageskipper_dump_vars`.
