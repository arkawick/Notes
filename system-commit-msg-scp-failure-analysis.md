# Offbuild Failure Analysis — `_system` job: `commit-msg` hook install via `scp` fails on Ubuntu 24

**Job:** `offbuild_feature-a16-chikugo-ubuntu24-test_system`
**Branch:** `feature-a16-chikugo-ubuntu24-test`
**Build:** `#6`, node `EC2 (AWSJ2) ci-cm-sandbox_CM_OFFBUILD_SBE` (label `CM_OFFBUILD_SBE`), instance `m6i.large`
**OS:** Ubuntu 24.04, kernel `6.17.0-1019-aws #19~24.04.1-Ubuntu … x86_64`
**Result:** `FAILURE` (exit 1), triggered by `scp` exit status 255 at 2026-07-27 13:03 UTC

> **Companion doc:** [`commit-msg-scp-failure-analysis.md`](commit-msg-scp-failure-analysis.md) covers the
> `_qssi_android` job. This is the **same root cause and the same failing function**, reached through a
> different job wiring. **One fix covers both jobs** — see §6.

---

## 1. Executive summary

The build runs cleanly through metadata packaging, package upload, label
promotion, and snapshot-XML creation, then fails at the **very last step** —
installing the Gerrit `commit-msg` hook into the cloned *delivery git*
(`system-snapshot`).

The cause is the **OpenSSH behavior change on Ubuntu 24.04**: since OpenSSH 9.0,
`scp` uses the **SFTP protocol by default** instead of the legacy SCP/RCP
protocol. Gerrit's built-in SSH server **does not provide an SFTP subsystem**, so
the transfer is rejected with `subsystem request failed on channel 0` and `scp`
exits **255**.

**Fix:** add the `-O` flag to the failing `scp` command in
`get_delivery_git()`. That function lives in the **`semctools/semcsystem`** repo,
file **`misc/scriptutils.source`** (checked out on disk at
`vendor/semc/build/semcsystem/misc/scriptutils.source`). This is the **same
shared helper** the `_qssi_android` job uses, so the single `-O` change fixes
both jobs.

---

## 2. The error (from the console log)

```
Cloning delivery git platform/vendor/semc/build/system-snapshot
Cloning into '.../delivery-git'...
Total 25 (delta 0), reused 10 (delta 0)          ← clone SUCCEEDS
...
Installing commit-msg hook
+ scp -p -P 29418 xscm01@review.ptc.sony.co.jp:hooks/commit-msg .git/hooks
subsystem request failed on channel 0            ← Gerrit rejected the SFTP subsystem
scp: Connection closed                           ← scp gives up
+ check_exitstatus 'Failed to install commit-msg hook' 255
Failed to install commit-msg hook failed with exit status 255 at 2026-07-27 13:03 UTC.
+ exit 1
Build step 'Execute shell' marked build as failure
Finished: FAILURE
```

The important detail (console lines 2047–2066): the **clone succeeds**
(`Total 25 (delta 0)`) and even the revision-sync retry loop passes
(`9fdcdc4eff51…` == `9fdcdc4eff51…`). Only the subsequent `scp` of the hook
fails.

---

## 3. How this job differs from the `_qssi_android` job

The two jobs are wired completely differently (different `config.xml`), yet both
funnel into the *same* `get_delivery_git()` function.

| | `_qssi_android` (companion doc) | `_system` (this doc) |
|---|---|---|
| Node label | `CM_OFFBUILD` | `CM_OFFBUILD_SBE` |
| Orchestrator script | `.offbuild/offbuild/android/master/collect.sh` | `.offbuild/offbuild/system/main.sh` |
| Build entry point | `run-offbuild-collect.sh` | `./build/system-offbuild.sh` |
| `MANIFEST` | `platform/qssimanifest` | `platform/systemmanifest` |
| `DELIVERY_GIT` | `platform/vendor/semc/build/android-qssi-packages` | `platform/vendor/semc/build/system-snapshot` |
| Child jobs | `_manifest`, `_matrix`, `offbuild_intermediate` | none — builds inline; triggers `offbuild_intermediate` + postbuild |
| Failing function | `get_delivery_git()` | `get_delivery_git()` |
| Failing command | `scp …:hooks/commit-msg` (no `-O`) | **identical** |
| Result | exit 255, `subsystem request failed on channel 0` | **identical** |

**Everything that differs is job wiring. The thing that fails is shared.**

---

## 4. Full build workflow (step by step)

### 4.0 Inputs injected by Jenkins (EnvInject)

From `config.xml` `EnvInjectBuildWrapper` and the console header:

| Variable | Value | Role |
|---|---|---|
| `BRANCH` | `feature-a16-chikugo-ubuntu24-test` | manifest + delivery branch |
| `MANIFEST` | `platform/systemmanifest` | repo manifest git |
| `DELIVERY_GIT` | `platform/vendor/semc/build/system-snapshot` | git that records the built label |
| `DELIVERY_BRANCH` | `feature-a16-chikugo-ubuntu24-test` | delivery branch |
| `BUILD_JOB_REVISION` | `origin/master` | revision of the offbuild scripts to reset to |
| `GERRIT_USER` | `xscm01` | Gerrit SSH user |
| `GERRIT_URL` | `ssh://xscm01@review.ptc.sony.co.jp:29418/` | Gerrit SSH endpoint |
| `DEBIANREPO_URL` | `https://dev.c2d.ptc.sony.co.jp/` | Debian repo for packages |
| `SYSTEM_SNAPSHOT_DIRNAME` | `chikugo` | subdir in the snapshot delivery git |
| `SBE_IMAGE_REPO` | `aws` | SBE image repo |
| `TRIGGER_OFFBUILD_INTERMEDIATE` | `true` | trigger the intermediate job |
| `TRIGGER_OFFBUILD_POSTBUILD` | `true` | trigger postbuild |

### Step 1 — Bootstrap / node info (`config.xml` builder #1)
```sh
echo "AWS Instance Type: $(curl … instance-type)"    # m6i.large
echo "System Information: $(uname -a)"                # Linux … 6.17.0-…-Ubuntu … x86_64
```
**This is the root of the problem — the node is Ubuntu 24.04, so its OpenSSH is 9.x.**

### Step 2 — Clean workspace + clone the offbuild scripts  ← **GIT #1** (`config.xml` builder #2)
```sh
rm -rf   $WORKSPACE
mkdir -p $WORKSPACE/result-dir
git clone git://review.ptc.sony.co.jp/semctools/offbuild .offbuild
git --work-tree .offbuild --git-dir .offbuild/.git reset --hard origin/master   # → d58ae85e7
```
All of `.offbuild/offbuild/system/*` and `.offbuild/offbuild/common/*` comes from **this** clone of `semctools/offbuild`.

### Step 3 — Set up credentials (`config.xml` builder #3)
Concatenates two credential files into `~/.netrc` and `chmod og-rw` it (used by `curl --netrc` and Gerrit HTTP).

### Step 4 — `main.sh` (the system orchestrator) (`config.xml` builder #4)
`.offbuild/offbuild/system/main.sh`:
- Line 6: `source ../common/scriptutils.source` — the **offbuild repo's** helper, which in turn sources `common_functions.sh`. **Note: this helper does NOT define `get_delivery_git`.**
- Clones `semctools/cm_tools` (`cd cm_tools` fails "No such file or directory" → falls back to a fresh `git clone`; **benign**, first build).
- `repo init -u platform/systemmanifest -b <branch>`, then a manifest-revision retry loop (waits until the local manifest HEAD matches Gerrit master).
- Builds a static manifest via `cm_tools/static_manifest.py`, `repo init -m manifest_static.xml`, then `repo sync -d -c --jobs=10` (**GIT #2** — see §4.1).
- Line 71: **`./build/system-offbuild.sh -u $BRANCH`** — the actual build/collect entry point.

### Step 5 — `system-offbuild.sh` (the build + delivery step)  ← **the failure lives here**
Runs from the synced tree. In order (from the console trace):
1. Sets up vars (`DELIVERY_GIT_DIR`, `SYSTEM_SNAPSHOT_XML=packages.xml`, `TEMPDIR`, `Found 2 CPUs, building with parallel jobs`).
2. Archives manifest metadata (`manifest_revision`, `default.xml`, `manifest_static.xml`) into `result-dir/`.
3. **Manifest comparison** against `lastSuccessfulBuild` — see §7 (the `xmllint` noise). Benign this run.
4. `getswlabelname.py` → resolves SW label `FEATURE-A16-CHIKUGO-UBUNTU24-TEST-260723-1059`.
5. `get_component_labels.py`, package listing, `extract_package_files.py` for `about.html` assembly.
6. Builds the **build-metadata package**, uploads it, **promotes packages** to labels.
7. `create_snapshot_xml.py` → `result-uploaded*-packages.xml`.
8. `aws sns publish` build-completion notification (succeeds).
9. Because delivery is enabled and `BRANCH` is non-empty, calls **`get_delivery_git platform/vendor/semc/build/system-snapshot …/delivery-git <branch>`**:
   ```sh
   git clone git://review.ptc.sony.co.jp/platform/vendor/semc/build/system-snapshot \
        delivery-git --single-branch --depth 1 --branch feature-a16-chikugo-ubuntu24-test   # ← SUCCEEDS
   # ... revision-sync retry loop: git ls-remote HEAD == local HEAD → break ...
   echo "Installing commit-msg hook"
   scp -p -P 29418 xscm01@review.ptc.sony.co.jp:hooks/commit-msg .git/hooks                 # ← FAILS (exit 255)
   ```
10. *(Never reached)* it would then write `packages.xml` with the label revision under `chikugo/`, `git commit`, and push to Gerrit for auto-submit.

Because `get_delivery_git` fails, `check_exitstatus` writes to `result-errors.txt`,
`system-offbuild.sh` exits 1, `main.sh` propagates it, and the job ends **FAILURE**.

### 4.1 Gits touched during the build

| # | Git (`name=`) | How it's fetched | On-disk path | Purpose |
|---|---|---|---|---|
| 1 | `semctools/offbuild` | `git clone` → `.offbuild` | `.offbuild/` | offbuild scripts (`system/main.sh`, `common/scriptutils.source`) |
| — | `semctools/cm_tools` | `git clone` | `cm_tools/` | `static_manifest.py` |
| 2 | `platform/systemmanifest` | `repo init` | `.repo/manifests` | the repo manifest |
| 2a | **`semctools/semcsystem`** | `repo sync -c` | **`vendor/semc/build/semcsystem/`** | **holds `system-offbuild.sh`'s helpers + `get_delivery_git()`** |
| 2b | `platform/vendor/semc/build` | `repo sync -c` | `vendor/semc/build/` | parent tree (packages, signatory, boot, etc.) |
| 2c | other manifest projects | `repo sync -c` | per manifest | build-metadata inputs |
| 3 | `platform/vendor/semc/build/system-snapshot` | `git clone` → `delivery-git` | `delivery-git/` | delivery git: records the built label, pushed to Gerrit |

### 4.2 One-line flow

```
EnvInject
  → clone semctools/offbuild (.offbuild)
  → main.sh
        source common/scriptutils.source        (offbuild — NO get_delivery_git)
        clone cm_tools
        repo init platform/systemmanifest @feature-a16-chikugo-ubuntu24-test
        static_manifest.py → repo sync (semcsystem, vendor/semc/build, …)
        → ./build/system-offbuild.sh -u <branch>
              build-metadata package → upload → promote labels
              create_snapshot_xml → aws sns publish            ✅
              get_delivery_git system-snapshot:
                  clone delivery-git                            ✅
                  scp commit-msg hook                           ❌  ← FAILS HERE (exit 255)
```

---

## 5. Root cause

### 5.1 What changed

| | Old nodes (Ubuntu ≤ 22 / OpenSSH < 9) | New node (Ubuntu 24 / OpenSSH ≥ 9) |
|---|---|---|
| `scp` default transfer protocol | Legacy SCP/RCP (runs over the exec channel) | **SFTP subsystem** |
| Works against Gerrit SSH? | ✅ Yes | ❌ No — Gerrit has no SFTP subsystem |

OpenSSH 9.0 release notes:

> *scp(1) now uses the SFTP protocol for transfers by default … The legacy
> behaviour can be requested using the new `-O` flag.*

### 5.2 Why Gerrit breaks

Gerrit implements a **custom SSH command set** (`gerrit review`, `gerrit query`,
hook download via legacy `scp`, etc.). It supports **legacy scp** but **not** the
`sftp` subsystem. When the new `scp` asks the server to start the `sftp`
subsystem, Gerrit refuses:

```
subsystem request failed on channel 0   ← Gerrit rejected the SFTP subsystem request
scp: Connection closed                   ← scp gives up
```

exit code **255** (SSH-level failure).

### 5.3 The fix concept

`scp -O` forces the **O**riginal (legacy) SCP protocol, which Gerrit supports.
`-O` is accepted by OpenSSH 8.6+, so it is safe to add unconditionally on any
node currently in use (old and new).

---

## 6. Exactly where the failing command lives (and why it was hard to find)

### 6.1 The repo/path mapping that caused confusion

The on-disk path is `vendor/semc/build/semcsystem/misc/scriptutils.source`, but
that path is **two nested repos**. The offbuild `collect.sh` proves it
(`SYNC_PROJECTS` lists both as separate projects):

| Git project (`name=` in manifest) | Checked out at (`path=`) |
|---|---|
| `platform/vendor/semc/build` | `vendor/semc/build/` |
| **`semctools/semcsystem`** | **`vendor/semc/build/semcsystem/`** |

So the `semcsystem/` segment of the path is **the mount point of the
`semctools/semcsystem` repo** — *not* a subfolder of `platform/vendor/semc/build`.
Inside the `semctools/semcsystem` repo, the file is simply
`misc/scriptutils.source`.

> ⚠️ The companion `_qssi_android` doc originally named the repo
> `platform/vendor/semc/build`. That was wrong — it inferred the git project name
> from the on-disk path. The correct project is **`semctools/semcsystem`**.

### 6.2 Why the `_system` script felt un-findable

`system-offbuild.sh` (invoked as `./build/system-offbuild.sh`) is only the
**caller** — it does not contain the `scp`. The `scp` is in the shared
`get_delivery_git()` that `system-offbuild.sh` sources from the
`semctools/semcsystem` repo:

```
main.sh (semctools/offbuild)
  └─ source common/scriptutils.source        ← offbuild helper, NO get_delivery_git
  └─ ./build/system-offbuild.sh              ← the CALLER (not where scp lives)
       └─ source …/semcsystem/misc/scriptutils.source   (semctools/semcsystem)
            └─ get_delivery_git()
                 └─ scp -p -P 29418 …:hooks/commit-msg   ← THE FAILING COMMAND
```

### 6.3 The file and function

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

This is the **only** `scp` in the file. The other Gerrit interaction,
`upload_change()`, uses `git push` and `ssh … gerrit review` — **not** `scp` — so
it is unaffected by the OpenSSH change.

---

## 7. The fix (recommended)

### 7.1 Minimal change — add `-O`

In `semctools/semcsystem : misc/scriptutils.source`, `get_delivery_git()`:

**Before:**
```sh
    scp -p -P 29418 $GERRIT_USER@review.ptc.sony.co.jp:hooks/commit-msg ${gitdir}/hooks
```

**After:**
```sh
    scp -O -p -P 29418 $GERRIT_USER@review.ptc.sony.co.jp:hooks/commit-msg ${gitdir}/hooks
```

### 7.2 More robust alternative — download over HTTPS (no scp/SFTP at all)

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

### 7.3 Where to commit — one fix covers both jobs

| | |
|---|---|
| **Repo** | `semctools/semcsystem` |
| **File** | `misc/scriptutils.source` |
| **Function** | `get_delivery_git()` |
| **Branch** | the revision pinned by the `feature-a16-chikugo-ubuntu24-test` static manifest for `semctools/semcsystem` |

Because `_system` (via `system-offbuild.sh`) and `_qssi_android` (via
`run-offbuild-collect.sh`) both call this **same shared function in the same
repo**, a single `-O` commit fixes **both** jobs. Do **not** edit
`system-offbuild.sh` — it is only the caller.

**Confirm the exact project + revision** on a synced workspace or from archived
artifacts:
```sh
# which git project provides the failing helper (expect: semctools/semcsystem):
grep -rn "get_delivery_git" vendor/semc/build/semcsystem/
git -C vendor/semc/build/semcsystem remote -v
git -C vendor/semc/build/semcsystem rev-parse --abbrev-ref HEAD

# the project's manifest entry (name/path/revision):
grep 'semcsystem' result-dir/manifest_static.xml
```

Push the change to `semctools/semcsystem`, get it merged, and the next offbuild
run on that branch picks it up automatically via `repo sync`.

---

## 8. Important clarification — why editing the offbuild folder does nothing

The scripts under `.offbuild/offbuild/**` and the workspace `cm_tools/` are **not**
what runs at the failing step:

- `get_delivery_git()` is defined in **`semctools/semcsystem`**
  (`misc/scriptutils.source`), which is **synced at build time** via `repo sync`.
  It is **not** in the offbuild repo checkout. Editing anything under
  `.offbuild/offbuild/common/scriptutils.source` (the offbuild helper) cannot
  change this failure — that helper does not even define `get_delivery_git`.
- The workspace is wiped (`rm -rf $WORKSPACE`) at the start of every build, so
  editing the file on the node directly is pointless — it must be fixed **in
  git**, in `semctools/semcsystem`.

---

## 9. Side observation — the `xmllint` parser errors (not the failure)

During manifest comparison, `system-offbuild.sh` fetches the previous build's
manifest:

```
curl … /lastSuccessfulBuild/artifact/result-dir/manifest_static.xml -o manifest-compare/last_manifest.xml -w %{http_code}
+ http_status_code=404
```

The fetch returns **404** (this is build `#6` but there is no *lastSuccessful*
build yet on this branch), so `last_manifest.xml` is actually the **HTML 404 error
page**, not XML. `xmllint --format` then spews:

```
manifest-compare/last_manifest.xml:10: parser error : xmlParseEntityRef: no name
… Opening and ending tag mismatch: link line 20 and head …
```

This is **benign for this run** — the 404 branch is handled (`[ 404 = 404 ] → true`)
and the build continues. But it means the "compare against last successful
manifest" step silently compared against an error page. Worth keeping in mind if
manifest-diff behaviour ever matters once a successful baseline exists.

---

## 10. Quick reference — one-liner for reviewers

> Ubuntu 24 ships OpenSSH 9.x, whose `scp` defaults to the SFTP protocol. Gerrit
> has no SFTP subsystem, so `scp user@gerrit:hooks/commit-msg …` fails with
> "subsystem request failed on channel 0" (exit 255). Add `scp -O` (legacy
> protocol) in `get_delivery_git()` in **`semctools/semcsystem`** →
> `misc/scriptutils.source`. This same function is shared by the `_system` and
> `_qssi_android` offbuild jobs, so one commit fixes both.
