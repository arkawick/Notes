# Script: common.sh

> **Source:** `code-sync-refs_heads_master/common.sh` (branch `master`, 24 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Shared shell library. It is **sourced**, not executed. It defines one function, `change_project_names`, a wrapper around `change_project_names.py` that normalises project names in a manifest or project list (so Qualcomm and CodeLinaro names match the names on `review.ptc.sony.co.jp`). In Jenkins, a failure stops the calling shell so that no push goes to the wrong project.

## Location

[`code-sync-refs_heads_master/common.sh`](../../code-sync-refs_heads_master/common.sh)

## Called By

| Caller | How |
|---|---|
| **Parent scripts** | `ensure-projects-exist.sh` (line 3), `qcom-import.sh` (lines 5, 985, 1013, 1063), `qcom-ref.sh` (line 4), all with `source $CODE_SYNC_DIR/common.sh` |
| **Jenkins jobs** (indirect) | Every job that runs those scripts: `sync_manifest_*` / `sync_manifest_and_gits_*` (via `ohd.sh` > `ensure-projects-exist.sh`), `import_qcom_*` (via `qcom-import.sh`, `qcom-ref.sh`) |
| **Unit tests** | `tests/unit/test_change_project_names.py` sources it and compares with the old shell implementation |

## Calls Internal Scripts

- `change_project_names.py` (same directory), run as `python3 -I`

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `python3` | Runs `change_project_names.py` (standard library only: `argparse`, `re`, `xml.etree`) |
| `realpath`, `dirname` | Locate the script directory |

## Usage

### Jenkins

Not called by a job directly. Used through the scripts above.

### Manual Execution

```bash
source code-sync/common.sh

# manifest file -> stdout
change_project_names AU_TAG.bak_change.xml > AU_TAG.xml

# project list on stdin
change_project_names <<< "clo/la/platform/build.git"

# edit in place
change_project_names -i project.list
```

## Parameters

All arguments are passed to `change_project_names.py` unchanged:

| Parameter | Required (Y/N) | Description |
|---|---|---|
| `path` | N | File to process. Reads stdin if omitted. |
| `-o`, `--output` | N | Write to this file instead of stdout |
| `-i`, `--in-place` | N | Rewrite the input file |
| `--xml [yes/no]` | N | `--xml` / `--xml=yes` forces XML mode, `--xml=no` forces plain text. Default: XML for files ending in `.xml`, plain text otherwise. |

`-o` and `-i` cannot be used together (exit 1).

## Input

**Input files:** a repo manifest XML or a plain project list (one name per line).

**Environment variables:**

| Variable | Effect |
|---|---|
| `JOB_NAME` | In `common.sh`: if set (i.e. running in Jenkins), a failure calls `exit` and stops the whole calling shell; if unset, the function only returns the error status. In the Python script: used to decide the manifest type and whether the Qualcomm rules apply. |
| `AU_TAG` | Python script: when set, the Qualcomm rules are applied. |
| `TREE_TYPE` | Python script: Qualcomm tree type (kernel, vendor, QSSI), selects the tree-specific rules such as the `dtc` rename. |

For a manual test of Qualcomm rules, set `AU_TAG` and `TREE_TYPE` the same way the import job does, or the output will differ from Jenkins.

## Output

**Log files / Reports:** on failure, `change_project_names: failed with status <n>` on stderr.

**Generated artifacts:** the normalised manifest or list (stdout, `-o` file, or in place).

## Key Functions / Logic

| Function | Purpose |
|---|---|
| `change_project_names [args]` | Runs `python3 -I <script_dir>/change_project_names.py "$@"`. `-I` (isolated mode) stops Python from importing stray modules from the current directory, which matters inside `repo forall`. Returns 0 on success. On failure: exits the shell in Jenkins, returns the status otherwise. |

Name rules applied by `change_project_names.py` (from its header):

| Manifest type | Rule |
|---|---|
| All | Remove `.git` suffix, `revision-history/` prefix, `clo/la/` prefix |
| Qualcomm only | Remove `_repo` suffix, remove `_group/` from directories, rename `platform/external/dtc` to `platform/external/dtc-kernel` on kernel trees (CM-4851, since 2025-spf-1-0 / Chikugo A16 RTL) |
| Exceptions | `platform/prebuilts/maven_repo/bumptech` keeps `maven_repo/`; `build_group/` in private QSSI manifests differs from `build/` in public ones |

## Notes

- **Why it exits in Jenkins:** a wrong project name means pushing to the wrong Gerrit project. Stopping the build is safer than continuing with an un-normalised list.
- **Inside `$(...)` the exit only leaves the subshell.** `qcom-import.sh` calls `REPO_PROJECT_OURS=$(change_project_names <<<$REPO_PROJECT)`; there the caller must check the result (or run with `-e`) for the failure to stop the build.
- **Changing a rule:** edit `change_project_names.py`, then run `python3 -m unittest tests.unit.test_change_project_names -v` from the repo root. A rename affects every future import and the projects that `ensure-projects-exist.sh` creates.
- **No shebang effect:** the `#!/bin/bash` line is only for editor syntax detection.
