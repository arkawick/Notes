# Offbuild Failure Analysis — `commit-msg` hook install via `scp` fails on Ubuntu 24

**Job:** `offbuild_feature-a16-chikugo-ubuntu24-test_qssi_android`
**Branch:** `feature-a16-chikugo-ubuntu24-test`
**Build node:** EC2 `ci-cm-sandbox_CM_OFFBUILD` (Ubuntu 24.04, kernel `6.17.0-…-Ubuntu`)
**Result:** `FAILURE` (exit 1), triggered by `scp` exit status 255

---

## 1. Executive summary

The build completes successfully all the way through package upload and label
promotion, then fails at the **very last step** — installing the Gerrit
`commit-msg` hook into the cloned *delivery git*.

The failure is caused by an **OpenSSH behavior change on Ubuntu 24.04**: since
OpenSSH 9.0, `scp` uses the **SFTP protocol by default** instead of the legacy
SCP/RCP protocol. Gerrit's built-in SSH server **does not provide an SFTP
subsystem**, so the transfer is rejected.

**Fix:** add the `-O` flag to the failing `scp` command to force the legacy SCP
protocol. One-line change in the **`semctools/semcsystem`** repo, file
`misc/scriptutils.source` (checked out on disk at
`vendor/semc/build/semcsystem/misc/scriptutils.source`).

> **Repo-name correction:** an earlier version of this doc named the repo
> `platform/vendor/semc/build` — that was inferred from the on-disk *path* and is
> wrong. The `semcsystem/` segment of `vendor/semc/build/semcsystem/…` is the
> **mount point of the `semctools/semcsystem` repo**, which is a separate project
> nested under `platform/vendor/semc/build`. See §5.2.

---

## 2. The error (from the console log)

```
Cloning delivery git platform/vendor/semc/build/android-qssi-packages
Cloning into 'delivery-git'...
Total 16 (delta 0), reused 0 (delta 0)
Installing commit-msg hook
subsystem request failed on channel 0
scp: Connection closed
Failed to install commit-msg hook failed with exit status 255 at 2026-07-13 12:09 UTC.
+ _description='FAILED%20FEATURE-A16-CHIKUGO-UBUNTU24-TEST-260713-1028<br>'
+ _failed=true
...
+ exit 1
Build step 'Execute shell' marked build as failure
Finished: FAILURE
```

Note the important detail: the **clone succeeds** (`Total 16 (delta 0)`). Only
the subsequent `scp` of the hook fails.

---

## 3. Full build workflow (step by step)

This job is an **orchestrator**. It doesn't build Android itself — it prepares
the workspace, triggers child jobs (`_manifest`, `_matrix`,
`offbuild_intermediate`), and then runs a sequence of shell build steps that
Jenkins injects as `/tmp/jenkins*.sh` files. Each shell step calls a script from
the `offbuild` repo. The order below is exactly what the console log shows.

### 3.0 Inputs injected by Jenkins (EnvInject)

Before any script runs, Jenkins injects the job parameters. The load-bearing
ones:

| Variable | Value | Role |
|---|---|---|
| `BUILD_PRODUCTS` | `sssi_64 product_pdx267_globaleea` | products to build |
| `BUILD_VARIANTS` | `user userdebug` | variants to build |
| `MANIFEST_PROJECT` | `platform/qssimanifest` | repo manifest git |
| `BRANCH` | `feature-a16-chikugo-ubuntu24-test` | manifest + delivery branch |
| `DELIVERY_GIT` | `platform/vendor/semc/build/android-qssi-packages` | git that records the built label |
| `DELIVERY_GIT_BRANCH` | *(empty)* | falls back to `BRANCH` |
| `GERRIT_USER` | `xscm01` | Gerrit SSH user |
| `LABEL_COMPONENT` | `android-qssi` | SW label component |
| `DEBIANREPO_URL` | `https://dev.c2d.ptc.sony.co.jp/` | Debian repo for packages |
| `TRIGGER_OFFBUILD_INTERMEDIATE` | `true` | trigger the intermediate job |
| `USE_CODE_SYNC_MGR` | `true` | code-sync manager enabled |

### Step 1 — Bootstrap / node info
Prints AWS instance type and `uname`. Confirms the node is Ubuntu 24.04
(`Linux … 6.17.0-…-Ubuntu … x86_64`). **This is the root of the problem — the
node's OpenSSH is 9.x.**

### Step 2 — Clean workspace + clone the offbuild scripts  ← **GIT #1**
```sh
rm -rf   $WORKSPACE
mkdir -p $WORKSPACE/result-dir
git clone git://review.ptc.sony.co.jp/semctools/offbuild .offbuild
git --work-tree .offbuild --git-dir .offbuild/.git reset --hard origin/master
```
Everything under `.offbuild/offbuild/android/master/*` (init.sh, post-*.sh,
collect.sh) comes from **this** clone of `semctools/offbuild`.

### Step 3 — Set up credentials
Writes `~/.netrc` and `chmod og-rw` it (used by `curl --netrc` and Gerrit HTTP).

### Step 4 — `init.sh` (compute job names, write `_propfile`)
`.offbuild/offbuild/android/master/init.sh`:
- Derives `MANIFEST_JOB_NAME`, `MATRIX_JOB_NAME` and their sanitized forms.
- Writes `_propfile` with all the derived vars; Jenkins injects it back as env.
- `curl … lastSuccessfulBuild/buildNumber` returns **404** (first build) →
  `LAST_SUCCESSFUL_BUILDNBR=` empty. **Benign.**

### Step 5 — Trigger the **manifest** child job
- Generates `WORKFLOW_ID` via `uuidgen`.
- Triggers `offbuild_feature-a16-chikugo-ubuntu24-test_qssi_android_manifest`
  `#4` → **SUCCESS**.
- The manifest job resolves the repo manifest and produces artifacts:
  `manifest_static.xml`, `buildid.txt`, `manifest_revision`,
  `manifest_res_variables.txt`, etc.

### Step 6 — `post-manifest.sh`
`.offbuild/offbuild/android/master/post-manifest.sh`:
- Reads the triggered manifest job number/result.
- **Copies 6 artifacts** from the manifest job into the workspace.

### Step 7 — `post-manifest-copy.sh`
`.offbuild/offbuild/android/master/post-manifest-copy.sh`:
- Sources `offbuild/common/scriptutils.source` and `common_functions.sh`
  (**note: these are the *offbuild* repo's helpers — different file from the one
  that fails later**).
- Reads `result-dir/buildid.txt` →
  `SONY_BUILD_ID = FEATURE-A16-CHIKUGO-UBUNTU24-TEST-260713-1028`.
- Sets the Jenkins build description via `submitDescription`.
- `repository -ru … createswlabel FEATURE-…:android-qssi` — **creates the SW
  label** in the Debian repo.

### Step 8 — Trigger **intermediate** + **matrix** child jobs
- `touch trigger-offbuild-intermediate` → triggers `offbuild_intermediate`.
- Triggers
  `offbuild_feature-a16-chikugo-ubuntu24-test_qssi_android_matrix` `#4` →
  **SUCCESS**. The matrix job is the **actual per-product / per-variant Android
  build**.

### Step 9 — `post-matrix.sh`
`.offbuild/offbuild/android/master/post-matrix.sh`:
- Reads the matrix job number.
- **Copies artifacts from the 4 matrix configurations** (label
  `CM_ANDROID_CSM_SBE`):
  - `product_pdx267_globaleea , user`
  - `product_pdx267_globaleea , userdebug`
  - `sssi_64 , user`
  - `sssi_64 , userdebug`

### Step 10 — `post-matrix-copy.py`
`.offbuild/offbuild/android/master/post-matrix-copy.py` — post-processes /
re-arranges the copied matrix result artifacts.

### Step 11 — `collect.sh`  ← **GIT #2 (repo manifest + synced projects)**
`.offbuild/offbuild/android/master/collect.sh` sets
`COLLECT_PRODUCTS`, `COLLECT_VARIANTS=user,userdebug`,
`COLLECT_MATRIX_LABEL=CM_ANDROID_CSM_SBE`, then:

```sh
repo init -q -u git://review.ptc.sony.co.jp/platform/qssimanifest \
     -b feature-a16-chikugo-ubuntu24-test --reference=$REPO_MIRROR
cp result-dir/manifest_static.xml .repo/
ln -sfv manifest_static.xml .repo/manifest.xml
```

Then it selectively `repo sync -c`'s only the projects it needs (each guarded by
a `grep` of the manifest):

| Project | On this branch? | Action |
|---|---|---|
| `semctools/semcsystem` | ✅ | **synced — provides `run-offbuild-collect.sh` + `scriptutils.source`** (mounted at `vendor/semc/build/semcsystem/`) |
| `platform/build` | ✅ | synced |
| `platform/vendor/semc/api` | ✅ | synced |
| `platform/vendor/semc/build` | ✅ | synced — parent tree (mounted at `vendor/semc/build/`) |
| `platform/vendor/semc/build/project` | ❌ | skipped ("does not exist on manifest branch") |
| `platform/vendor/semc/customization/nfc/common` | ❌ | skipped |
| `platform/vendor/semc/products/qssi` | ✅ | synced |

```sh
git -C .repo/manifests reset --hard d58409959bb3048e922554afe7a6e4a846c37440
```
(the pinned manifest revision — "Initial manifest of
feature-a16-chikugo-ubuntu24-test").

Finally `collect.sh` invokes the collect script (passing the delivery branch):
```sh
BRANCH=$DELIVERY_GIT_BRANCH \
  vendor/semc/build/semcsystem/parallelbuild/run-offbuild-collect.sh \
  -b CM_ANDROID_CSM_SBE -u -v user,userdebug product_pdx267_globaleea sssi_64
```

### Step 12 — `run-offbuild-collect.sh`  ← **GIT #3 (delivery git) + the failure**
`vendor/semc/build/semcsystem/parallelbuild/run-offbuild-collect.sh`:
1. Sources `vendor/semc/build/semcsystem/misc/scriptutils.source`.
2. `setup_buildvars` — computes paths, `$JOBS`, label component names.
3. Sorts / downloads the matrix results, `check_buildresult` per product+variant.
4. **Creates the build-metadata package** (`make … metadata_package`) and
   uploads it (`repository addpackage`).
5. **Promotes packages** to the labels and flips their status to `INTERNAL`:
   `android-qssi`, `android-qssi-debug`, `android-qssi-xpts`.
6. Because `-u` was passed (`OPT_UPLOAD_CHANGE=1`), calls **`get_delivery_git`**:
   ```sh
   git clone git://review.ptc.sony.co.jp/platform/vendor/semc/build/android-qssi-packages \
        delivery-git --single-branch --depth 1 \
        --branch feature-a16-chikugo-ubuntu24-test        # ← SUCCEEDS
   # ... revision-sync retry loop ...
   echo "Installing commit-msg hook"
   scp -p -P 29418 xscm01@review.ptc.sony.co.jp:hooks/commit-msg \
        delivery-git/.git/hooks                            # ← FAILS (exit 255)
   ```
7. *(Never reached because of the failure)* it would then write `packages.xml`
   with the label revision, `git commit`, and `upload_change` → `git push
   HEAD:refs/for/<branch>` + `gerrit review --code-review +2 --verified +1
   --submit`.

Because `get_delivery_git` fails, `check_exitstatus` logs to `$ERRORLOG`,
`run-offbuild-collect.sh` exits 1, `collect.sh` marks `_failed=true`, and the
job ends `FAILURE`.

### 3.1 Gits touched during the build

| # | Git | How it's fetched | Branch / revision | Purpose |
|---|---|---|---|---|
| 1 | `semctools/offbuild` | `git clone` → `.offbuild` | `origin/master` | the offbuild build scripts (init/post-*/collect) |
| 2 | `platform/qssimanifest` | `repo init` | `feature-a16-chikugo-ubuntu24-test` @ `d58409959…` | the repo manifest |
| 2a | `semctools/semcsystem` | `repo sync -c` | per manifest | **holds `run-offbuild-collect.sh` + `scriptutils.source`** (path `vendor/semc/build/semcsystem/`) |
| 2b | `platform/build` | `repo sync -c` | per manifest | build metadata inputs |
| 2c | `platform/vendor/semc/api` | `repo sync -c` | per manifest | build metadata inputs |
| 2d | `platform/vendor/semc/build` | `repo sync -c` | per manifest | parent tree (path `vendor/semc/build/`) |
| 2e | `platform/vendor/semc/products/qssi` | `repo sync -c` | per manifest | product data |
| 3 | `platform/vendor/semc/build/android-qssi-packages` | `git clone` → `delivery-git` | `feature-a16-chikugo-ubuntu24-test` | delivery git: records the built label, pushed to Gerrit |

### 3.2 Child jobs triggered

| Child job | Result | Role |
|---|---|---|
| `…_manifest` #4 | SUCCESS | resolve/produce the static manifest |
| `offbuild_intermediate` | (triggered) | intermediate offbuild stage |
| `…_matrix` #4 | SUCCESS | the actual per-product/per-variant Android build |

### 3.3 One-line flow

```
EnvInject
  → clone semctools/offbuild (.offbuild)
  → init.sh (job names, _propfile)
  → trigger _manifest ─────────────► SUCCESS
  → post-manifest.sh (copy 6 artifacts)
  → post-manifest-copy.sh (createswlabel)
  → trigger offbuild_intermediate + _matrix ──► SUCCESS
  → post-matrix.sh (copy 4 matrix configs)
  → post-matrix-copy.py
  → collect.sh
        repo init platform/qssimanifest @feature-a16-chikugo-ubuntu24-test
        repo sync semcsystem, build, api, vendor/semc/build, products/qssi
        → run-offbuild-collect.sh
              make metadata_package → upload → promote labels → INTERNAL
              get_delivery_git:
                  clone android-qssi-packages           ✅
                  scp commit-msg hook                    ❌  ← FAILS HERE (exit 255)
```

---

## 4. Root cause

### 4.1 What changed

| | Old nodes (Ubuntu ≤ 22 / OpenSSH < 9) | New node (Ubuntu 24 / OpenSSH ≥ 9) |
|---|---|---|
| `scp` default transfer protocol | Legacy SCP/RCP (runs over the exec channel) | **SFTP subsystem** |
| Works against Gerrit SSH? | ✅ Yes | ❌ No — Gerrit has no SFTP subsystem |

OpenSSH 9.0 release notes state:

> *scp(1) now uses the SFTP protocol for transfers by default … The legacy
> behaviour can be requested using the new `-O` flag.*

### 4.2 Why Gerrit breaks

Gerrit implements a **custom SSH command set** (`gerrit review`, `gerrit
query`, hook download via `scp`, etc.). It supports the **legacy scp** command
but **not** the `sftp` subsystem. When the new `scp` asks the server to start
the `sftp` subsystem, Gerrit refuses:

```
subsystem request failed on channel 0   ← Gerrit rejected the SFTP subsystem request
scp: Connection closed                   ← scp gives up
```

exit code **255** (SSH-level failure).

### 4.3 The fix concept

`scp -O` forces the **O**riginal (legacy) SCP protocol, which Gerrit supports.
`-O` is accepted by OpenSSH 8.6+ so it is safe to add unconditionally on any
node currently in use.

---

## 5. Exactly where the failing command lives

The failing `scp` is **not** in the offbuild repo and **not** in the job's shell
steps. It is reached through two levels of indirection:

### 5.1 Call chain

```
Jenkins job step
  └─ .offbuild/offbuild/android/master/collect.sh          (offbuild repo)
       └─ vendor/semc/build/semcsystem/parallelbuild/run-offbuild-collect.sh
            └─ get_delivery_git()   ← defined in the sourced helper below
                 └─ scp ...:hooks/commit-msg    ← THE FAILING COMMAND
```

- `collect.sh` (line 42) calls `run-offbuild-collect.sh`.
- `run-offbuild-collect.sh` sources
  `vendor/semc/build/semcsystem/misc/scriptutils.source` and calls
  `get_delivery_git "$DELIVERY_GIT" "$DELIVERY_GIT_DIR" "$BRANCH"`.
- `get_delivery_git()` clones the delivery git **and** installs the hook via
  `scp`.

### 5.2 The file and function

The on-disk path `vendor/semc/build/semcsystem/misc/scriptutils.source` is **two
nested repos**. The offbuild `collect.sh` proves it — its `SYNC_PROJECTS` lists
both as separate projects:

| Git project (`name=` in manifest) | Checked out at (`path=`) |
|---|---|
| `platform/vendor/semc/build` | `vendor/semc/build/` |
| **`semctools/semcsystem`** | **`vendor/semc/build/semcsystem/`** |

So the `semcsystem/` segment is **the mount point of the `semctools/semcsystem`
repo** — *not* a subfolder of `platform/vendor/semc/build`. Inside the
`semctools/semcsystem` repo, the file is simply `misc/scriptutils.source`.

**Repo:** `semctools/semcsystem`
**File (in repo):** `misc/scriptutils.source`
**On disk:** `vendor/semc/build/semcsystem/misc/scriptutils.source`
**Function:** `get_delivery_git()`

```sh
function get_delivery_git()
{
    local git=$1
    local path=$2
    local branch=$3

    echo "Cloning delivery git ${git}"
    git clone git://review.ptc.sony.co.jp/$git $path --single-branch --depth 1 --branch $branch
    check_exitstatus "Failed to clone delivery git" $?

    ( ...revision-sync retry loop... )

    echo "Installing commit-msg hook"
    (
    cd "$path"
    gitdir=$(git rev-parse --git-dir)
    scp -p -P 29418 $GERRIT_USER@review.ptc.sony.co.jp:hooks/commit-msg ${gitdir}/hooks   # <-- FAILS
    )
    check_exitstatus "Failed to install commit-msg hook" $?
}
```

This is the **only** `scp` in the file. The other Gerrit interaction in this
file, `upload_change()`, uses `git push` and `ssh … gerrit review` — **not**
`scp` — so it is unaffected by the OpenSSH change.

---

## 6. The fix (recommended)

### 6.1 Minimal change — add `-O`

In `semcsystem/misc/scriptutils.source`, function `get_delivery_git()`:

**Before:**
```sh
    scp -p -P 29418 $GERRIT_USER@review.ptc.sony.co.jp:hooks/commit-msg ${gitdir}/hooks
```

**After:**
```sh
    scp -O -p -P 29418 $GERRIT_USER@review.ptc.sony.co.jp:hooks/commit-msg ${gitdir}/hooks
```

### 6.2 More robust alternative — download over HTTPS (no scp/SFTP at all)

```sh
    echo "Installing commit-msg hook"
    (
    cd "$path"
    gitdir=$(git rev-parse --git-dir)
    curl --netrc -sSfL -o "${gitdir}/hooks/commit-msg" https://review.ptc.sony.co.jp/tools/hooks/commit-msg
    chmod +x "${gitdir}/hooks/commit-msg"
    )
    check_exitstatus "Failed to install commit-msg hook" $?
```

This removes the dependency on the legacy scp protocol entirely and is the
approach Gerrit itself documents.

### 6.3 Where to commit

| | |
|---|---|
| **Repo** | `semctools/semcsystem` |
| **File** | `misc/scriptutils.source` |
| **Function** | `get_delivery_git()` |
| **Branch** | The revision pinned by the `feature-a16-chikugo-ubuntu24-test` static manifest for `semctools/semcsystem` |

To find the exact revision/branch to fix, on the build node (or from archived
artifacts):

```sh
grep 'name="semctools/semcsystem"' result-dir/manifest_static.xml
# or, since repo already synced it into the workspace:
git -C vendor/semc/build/semcsystem remote -v          # confirms semctools/semcsystem
git -C vendor/semc/build/semcsystem rev-parse --abbrev-ref HEAD
git -C vendor/semc/build/semcsystem log -1
```

Push the change to `semctools/semcsystem`, get it merged, and the next offbuild
run on that branch picks it up automatically via `repo sync`.

---

## 7. Important clarification — why editing the offbuild folder did nothing

The scripts under `offbuild/` and `cm_tools/` in the workspace are **not** what
runs at the failing step:

- `run-offbuild-collect.sh` and `scriptutils.source` are **synced at build
  time** from the `semctools/semcsystem` git via `repo sync` (mounted at
  `vendor/semc/build/semcsystem/`). They are **not present in the offbuild repo
  checkout**, so editing anything in `offbuild/` cannot change this failure.
- The workspace is wiped (`rm -rf`) at the start of every build, so editing the
  file on the node directly is pointless — it must be fixed **in git**.

**This is the key reason a `-O` edit "wasn't working": it was being applied to
the wrong file/repo.**

---

## 8. Other scripts with the same latent bug

The same `scp … :hooks/commit-msg` pattern **without `-O`** exists elsewhere and
will break identically on any Ubuntu 24 node. Fix these too if the corresponding
jobs migrate to ubuntu24:

> ⚠️ The repo names below are inferred from on-disk paths and have **not** been
> verified against the manifest `name=` attribute. The first row is corrected
> (`semctools/semcsystem`); re-check the others the same way before trusting them
> — a path like `vendor/semc/build/…` may belong to a nested project, not
> `platform/vendor/semc/build`.

| Repo / file | Line |
|---|---|
| `semctools/semcsystem` → `misc/scriptutils.source` (path `vendor/semc/build/semcsystem/`) | `get_delivery_git()` — **this failure** |
| `offbuild/offbuild/amss/master/post-matrix.sh` | 62 |
| `offbuild/offbuild/ch/ramdump/common_functions.sh` | 145 |
| `cm_tools/binary_build/binary_file_updater.bash` | 135 |
| `cm_tools/project_search_replace.sh` | 124 |
| `cm_tools/odm/upload-merge-commit.sh` | 79 |
| `cm_tools/odm/odm-somc-branch.sh` | 241 |
| `cm_tools/odm/gapclose-branch-rebase.sh` | 401 |
| `cm_tools/hudson-scripts/update-somc-branch.sh` | 69 |
| `cm_tools/hudson-scripts/remove-pp-and-add-dummy-build.sh` | 8, 32 |
| `cm_tools/rebase_yaml_creation.sh` | 119 |
| `cm_tools/branch_close_supporter.py` | 146, 445, 658, 874, 1000 |
| `cm_tools/cherrypick.py` | 1388 |
| `cm_tools/experimental/jpto/*` | git_repository.py:239, jpto_cm_experimental_module.py:127 |

> Note: `upload_change()` in `scriptutils.source` and `gerrit.py`'s
> `run_gerrit_command()` use `git push` / `ssh gerrit …`, **not** scp, and are
> **not** affected.

---

## 9. Quick reference — one-liner for reviewers

> Ubuntu 24 ships OpenSSH 9.x, whose `scp` defaults to the SFTP protocol. Gerrit
> has no SFTP subsystem, so `scp user@gerrit:hooks/commit-msg …` fails with
> "subsystem request failed on channel 0" (exit 255). Add `scp -O` (legacy
> protocol) in `get_delivery_git()` in **`semctools/semcsystem`** →
> `misc/scriptutils.source` (on disk `vendor/semc/build/semcsystem/misc/scriptutils.source`).
