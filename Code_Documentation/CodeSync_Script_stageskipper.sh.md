# Script: stageskipper.sh

> **Source:** `code-sync-refs_heads_master/stageskipper.sh` (branch `master`, 150 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Small shell library that lets a multi-stage Jenkins import job **jump to a stage** (skip the stages before it) or **stop at a stage**. It is **sourced**, not executed. The state is kept in environment variables, so it survives across separate Jenkins build steps through EnvInject.

It is what makes the Qualcomm import parameters `SKIP_STAGES_BEFORE` and `STOP_BUILD_AT_STAGE` work.

## Location

[`code-sync-refs_heads_master/stageskipper.sh`](../../code-sync-refs_heads_master/stageskipper.sh)

## Called By

| Caller | Role |
|---|---|
| **Jenkins jobs:** `import_qcom_<distro>_<tree>_<target>` (template in `jenkins-jobs/template-qcom.yaml`) | Parameters `SKIP_STAGES_BEFORE`, `STOP_BUILD_AT_STAGE`; build step has `unstable-return: 22` |
| **Jenkins jobs:** `import_qcom_simple_<distro>_<tree>_<target>` | Same parameters, simple-import stage list |
| `qcom-prepare.sh`, `qcom-simple-prepare.sh` | **Set-up:** `init`, `add_stage`, `set_goto`, `exit_at`, `dump_vars` > `variables.txt` (injected by EnvInject) |
| `qcom-import.sh`, `qcom-hy11.sh`, `qcom-ref.sh`, `qcom-ref-tag.sh`, `qcom-simple-import.sh` and the `*-sdph2021.sh` variants | **Per stage:** `stageskipper_is_skipping <stage>` |

## Calls Internal Scripts

None.

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `bash` | `declare -gx`, `shopt`, arrays |
| `sed -E`, `grep` | Stage list matching |
| `gawk` | Prints the `=====` stage banner |
| `date` | Time in the banner |

## Usage

### Jenkins

- **Job name:** `import_qcom_<distro>_<tree-type-name>_<target-project>`, e.g. an import for QSSI17
- **Parameters the operator sets:**

| Parameter | Example | Effect |
|---|---|---|
| `SKIP_STAGES_BEFORE` | `ref-manifest` | Skip every stage before `ref-manifest`. Usually also uncheck `CLEANUP_WORKING_DIR`, so the earlier stages' work is still there. |
| `STOP_BUILD_AT_STAGE` | `syncsnap-push` | Stop at the entry of that stage, before it runs. Build result **UNSTABLE** (exit 22). |

Stage lists (execution order):

| Job type | Stages (set in) |
|---|---|
| `import_qcom_*` | `prepare-utilities syncsnap syncsnap-notdefault syncsnap-list syncsnap-push hy11 ref-manifest ref-repo-init ref-repo-sync ref-push ref-tag all` (`qcom-prepare.sh`) |
| `import_qcom_simple_*` | `repo-init-sync make-repo-list git-push ref-manifest ref-repo-init ref-repo-sync ref-push ref-tag all` (`qcom-simple-prepare.sh`) |

### Manual Execution

```bash
set -e                                    # required if exit_at is used
source code-sync/stageskipper.sh
stageskipper_init
stageskipper_add_stage prepare build push all
stageskipper_set_goto build               # optional: skip "prepare"
stageskipper_exit_at push                 # optional: stop before "push"
stageskipper_dump_vars > envs.txt         # pass state to later steps

if ! stageskipper_is_skipping prepare; then echo "do prepare"; fi
if ! stageskipper_is_skipping build;   then echo "do build";   fi
stageskipper_is_skipping push             # exits 22 here
```

## Parameters

| Function / argument | Required (Y/N) | Description |
|---|---|---|
| `stageskipper_add_stage <name>...` | Y | Stage names in execution order. Must not contain spaces or `:`. |
| `stageskipper_set_goto <stage>` | N | Stage to jump to. Must already be added. |
| `stageskipper_exit_at <stage> [status]` | N | Stage to stop at; status default `22`. A status that is a multiple of 256 (= 0) is refused. |
| `stageskipper_is_skipping [--no-banner] <stage>` | Y | Current stage name. `--no-banner` suppresses the banner. |

## Input

**Input files:** none. (In Jenkins, `variables.txt` from the prepare script is injected as environment.)

**Environment variables** (all exported by `stageskipper_init` and read by the other functions):

| Variable | Content |
|---|---|
| `STAGESKIPPER_INITIALIZED` | `1` after `init` |
| `STAGESKIPPER_STAGES` | `:stage1:stage2:...:` |
| `SKIPPED_STAGES` | `:stage1:...:` (stages before the goto stage) |
| `FORCE_EXIT_AT_STAGE` | Stop stage name |
| `FORCE_EXIT_STATUS` | Exit status for the stop (default 22) |

## Output

**Log files:** console banner per stage, e.g.

```
====================...
Stage: ref-manifest 14:03:27 --- SKIPPED
====================...
```

Suffix ` --- THE SCRIPT EXITS BEFORE MOVING ON TO THIS STAGE` for the stop stage. `FATAL: ...` messages on stderr for misuse.

**Reports / Generated artifacts:** `stageskipper_dump_vars` prints `NAME=value` lines (the caller redirects them to `variables.txt`).

## Key Functions / Logic

| Function | Purpose |
|---|---|
| `stageskipper_init` | Clear and export the five state variables; `STAGESKIPPER_STAGES=":"`. |
| `stageskipper_ensure_init` | Exit 1 with `FATAL: Stageskipper has not been initialized.` if `init` was not run (or the env was not injected). |
| `stageskipper_dump_vars` | Print the five variables as `NAME=value` for EnvInject. |
| `stageskipper_add_stage` | Append stage names to `STAGESKIPPER_STAGES`. |
| `stageskipper_set_goto` | Set `SKIPPED_STAGES` to every stage before the given one. Exit 1 if the stage is unknown. |
| `stageskipper_exit_at` | Set `FORCE_EXIT_AT_STAGE` / `FORCE_EXIT_STATUS`. Exit 1 if the stage is unknown or the status is 0. |
| `stageskipper_is_skipping` | Print the banner. If this is the stop stage, `exit $FORCE_EXIT_STATUS`. Return 0 (skip) if the stage is in `SKIPPED_STAGES`, 1 (run) otherwise. Exit 1 if the stage is unknown, or if a stop stage is set but the shell has no `-e`. |

## Notes

- **`-e` is required for `STOP_BUILD_AT_STAGE`.** The function refuses to run when a stop is set but `errexit` is off. The template's import step starts with `#!/bin/bash -ex` for this reason.
- **Why UNSTABLE:** exit 22 plus `unstable-return: 22` in the job makes a deliberate stop show as UNSTABLE, not FAILURE.
- **Typical rerun use:** an import failed in `ref-push`. Rerun with `SKIP_STAGES_BEFORE=ref-push` and `CLEANUP_WORKING_DIR` unchecked. The template refuses to reuse a working directory last used by a **different** job (`lock` file check).
- **Typo in a stage name** fails at once with `FATAL: ... cannot find the stage named "<x>"`. Stage names are case-sensitive.
- **Header comment mismatch:** the usage comment says `stageskipper_dump_envs`, but the function is `stageskipper_dump_vars`.
- **Stage names are used in a `sed` regex** by `set_goto`, so names with regex characters (`.`, `*`) could match wrongly. Current names are safe.
- **`all`** is a dummy last stage that no script checks with `stageskipper_is_skipping`. So `STOP_BUILD_AT_STAGE=all` is accepted but never stops anything; the job runs to the end. [Unconfirmed] Intended use; probably a "skip everything" target for `SKIP_STAGES_BEFORE`.
