# Script: config.sh

> **Source:** `code-sync-refs_heads_master/config.sh` (branch `master`, 28 lines). Every statement below is read from the code unless marked [Unconfirmed].

## Purpose

Common environment set-up for CodeSync scripts. It is **sourced**, not executed. It sets default Gerrit URLs, the CPU count, the CodeSync script directory and common `repo init` arguments, checks that required variables are set, and provides the helper `find_repo_manifest`.

## Location

[`code-sync-refs_heads_master/config.sh`](../../code-sync-refs_heads_master/config.sh)

## Called By

| Caller | How |
|---|---|
| **Parent script:** [`ohd.sh`](CodeSync_Script_ohd.sh.md) | `source $(readlink -f $(dirname $0))/config.sh` (line 3). This is the only script on `master` that sources it. |
| **Jenkins jobs** (indirect, through `ohd.sh`) | `sync_manifest_<remote>_<branch>`, `sync_manifest_and_gits_<remote>_<branch>` |

The Qualcomm import scripts (`qcom-*.sh`) do **not** source it. They get the same variables (`CODE_SYNC_DIR`, `CPU_NO`, `HY11_SUFFIX`, ...) from `qcom-prepare.sh` / `qcom-simple-prepare.sh` through Jenkins EnvInject.

## Calls Internal Scripts

None.

## External Tools / Dependencies

| Tool | Used for |
|---|---|
| `bash` (4.2+) | `[ -v var ]` test |
| `/proc/cpuinfo`, `grep`, `wc` | CPU count |
| `readlink`, `dirname`, `sed`, `cat` | Paths and manifest lookup |

## Usage

### Jenkins

Not called by a job directly. Used through `ohd.sh`.

### Manual Execution

```bash
# from a script that lives in the code-sync folder
required_vars="SOURCE_GERRIT PUSH_MODE"   # optional
source $(readlink -f $(dirname $0))/config.sh
```

## Parameters

No arguments. Behaviour is controlled by the environment (see Input).

## Input

**Input files:** none.

**Environment variables:**

| Variable | Read / Set | Description |
|---|---|---|
| `GERRIT_FETCH_URL` | read, default set | Default `git://review.ptc.sony.co.jp` if empty |
| `GERRIT_PUSH_URL` | read, default set | Default `$GERRIT_FETCH_URL` if empty |
| `HY11_CHIPSET` | read | If set, exports `HY11_SUFFIX=-<chipset>` |
| `required_vars` | read | Space-separated variable names. The script exits 1 with `ERROR: Variable <v> must be set to run this script!` for each one not set. |
| `REPO_MIRROR` | read | If set, appended to `COMMON_REPO_INIT_ARGS` as `--reference=$REPO_MIRROR` |

## Output

**Log files / Reports:** none.

**Exported variables:**

| Variable | Value |
|---|---|
| `GERRIT_FETCH_URL` | `git://review.ptc.sony.co.jp` (unless already set) |
| `GERRIT_PUSH_URL` | `$GERRIT_FETCH_URL` (unless already set) |
| `HY11_SUFFIX` | `-$HY11_CHIPSET` (only if `HY11_CHIPSET` set) |
| `CPU_NO` | Number of `processor` lines in `/proc/cpuinfo` |
| `CODE_SYNC_DIR` | Absolute directory of the **calling** script (`dirname $0`) |
| `COMMON_REPO_INIT_ARGS` | `--repo-branch stable --no-repo-verify [--reference=$REPO_MIRROR]` |

**Generated artifacts:** none.

## Key Functions / Logic

| Function | Purpose |
|---|---|
| `find_repo_manifest <path>` | Returns the real manifest file behind `.repo/manifest.xml`. If the path is a symlink (older repo), it is returned as-is. If it is a regular file (newer repo writes a small file with `<include name="...">`), returns `.repo/manifests/<included name>`. Used by `ohd.sh` to read the source remote name. |

## Notes

- **`CODE_SYNC_DIR` depends on `$0`:** it is the directory of the script that sources `config.sh`, not of `config.sh` itself. Sourcing from an interactive shell gives the shell's directory.
- **`required_vars` is not used by any caller** on `master` (`ohd.sh` checks its variables itself). It is kept for older scripts.
- **`COMMON_REPO_INIT_ARGS` is not used** by `ohd.sh` (it builds its own `args`). This is where the old documentation says the mirror gets wired in; on `master` `ohd.sh` adds `--reference=$REPO_MIRROR` itself.
- **`find_repo_manifest` limit:** only the first `include` line is read. A manifest with several includes gives a broken path.
- **No shebang:** the file is meant to be sourced only. Running it directly does nothing useful.
