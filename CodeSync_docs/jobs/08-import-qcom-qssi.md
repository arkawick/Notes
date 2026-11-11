# Import_Qcom_<distro>_QSSI<ver>_<project> (and standalone QSSI)

> **Sources:** 📊 PPT slides 5–9 · 🎙 KT Sessions 3–5 · 🧭 proposed · ❓ unconfirmed. The current import scripts are not in the checkout.
> **Background:** [CodeSync_KT.md §10](../../CodeSync_KT.md#10-qualcomm-import-jobs), [§10.10 volatile branch](../../CodeSync_KT.md#1010-the-volatile-branch-case), [§10.12 standalone QSSI](../../CodeSync_KT.md#1012-standalone-qssi). The stage list and full parameter table are the same as for the kernel job: [07-import-qcom-kernel.md](07-import-qcom-kernel.md).

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `Import_Qcom_<distro>_QSSI<13|14|15|…>_<project>`. 📊 Examples: `Import_Qcom_2024-spf-1-0_QSSI15_V-Shimanto`, `Import_Qcom_2023-spf-2-0_QSSI14_V-Asahi`, `Import_Qcom_2022-spf-2-0_QSSI13_U-Yodo`. Plus 🎙 a **standalone QSSI** job family (e.g. QSSI17 standalone, distro `LA.QSSI.<ver>`). ❓ Current names: see Jenkins. |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/Import_Qcom_<distro>_QSSI<ver>_<project>/` |
| **Category** | Vendor Import |
| **Vendor / Source** | Qualcomm: Chipcode (proprietary) + CodeLinaro (open source) |
| **Component** | QSSI (Qualcomm Single System Image) → Sony manifest `platform/qssimanifest` |
| **Criticality** | 🧭 **Critical.** QSSI is **shared across Android versions and products**. A wrong import affects several products. |

## 2. Purpose / Job Description

**What does this job actually do?**
It imports one Qualcomm QSSI release (`AU_TAG`) through the same 10 stages as the kernel ([07 §2](07-import-qcom-kernel.md#2-purpose--job-description)), using the workspace `qssi_st/`, and ends by pinning `REF_BRANCH` and tagging all projects.

**QSSI-specific behaviour** (🎙):
- **Name rewrites at push:** strip `_group` (e.g. `build_group` → `build/blueprint`, `build/release`, `build/soong`) and `_repo` suffixes. Trade-federation variants are handled. A project genuinely named `…_repo` must **not** be truncated. Qualcomm is removing `_group` upstream on recent releases.
- **Shared ref branch.** The QSSI ref branch moves forward with the highest imported tag. Product-bundled QSSI **and** standalone QSSI both import into the **same** ref branch.
- **Volatile branch** when a release's QSSI is **behind** the ref branch (e.g. ref at 80, release needs 72).

**Why is this job required?**
Product builds use the QSSI system image from `platform/qssimanifest`. Each Qualcomm QSSI release must land there and be tagged.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | **Manual** |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes (the only way) |
| **When to trigger manually** | A new release for a Sony distro (`AMSS Standard OEM`) **and** `list_manifest_tags` shows the new QSSI tag on **both CodeLinaro and Chipcode** **and** the parameters have been peer-reviewed. ⚠️ **Also check the standalone `LA.QSSI.<ver>` distro's release list.** Another team normally imports it, but 🎙 a release (89) was missed. |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None automatic. Completion email. |

**Flow:** `Release email / QPM (product distro + standalone LA.QSSI) → list_manifest_tags (CLO + Chipcode) → [mirrors] → Import_Qcom_*_QSSI*_* → platform/qssimanifest @ REF_BRANCH + AU_TAG → email`

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters"_ → `../images/import-qssi-params.png`

Same parameter set as [07 §4](07-import-qcom-kernel.md#4-job-parameters). The QSSI-specific points:

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `AU_TAG` | **Yes** | `AU_LINUX_ANDROID_LA.QSSI.<ver>…` | QSSI tag | Release note → **QSSI** row. **Confirm the chipset matches your product.** Cross-check `list_manifest_tags` (CLO **and** Chipcode). | Wrong system image tagged on a shared branch |
| `AU_TAG_INTERNAL` | No | `test_01_<AU_TAG>` | Test tag (volatile branch on stage) | Testing only | — |
| `RELEASE_NUMBER` | **Yes** | full number | Vendor release | Release note | Import mismatch |
| `REF_BRANCH` | **Yes** (defaulted) | QSSI ref branch, or `volatile-…` | Branch pinned in `ref-push` | Default. **Use a volatile branch if the release's QSSI tag is older than what the ref branch carries.** Check the last imported release on **both** streams. | **Ref branch moved backwards** for every product on it |
| `PSEUDO_MIRROR_TREE` | No | ✅ | Workspace mirror | Enable, **unless the OSS path has moved public↔private and the script mirror path has not been updated** | 🎙 Standalone-QSSI incident: failure, then a very slow run without the mirror |
| `CLEANUP_WORKING_DIR` / `SKIP_STAGES_BEFORE` / `STOP_BUILD_AT_STAGE` | — | ✅ / blank / blank | Fresh run | See 07 | See 07 |

Project variables: `tree_type=LA_QSSI`, `hy11_suffix=-QSSI`, `workspace=qssi_st`. For standalone: `distro_full_name` uses the **HLOS-dev** branch of the name generator (🎙).

## 5. Expected Output

- Every QSSI project pushed. New ones auto-created.
- `_group` / `_repo` rewrites applied, and true `…_repo` projects left intact
- `prebuilt-hy11-QSSI` (prebuilt) git pushed
- `grease/$AU_TAG.xml` in `platform/qssimanifest`
- `REF_BRANCH` (or the volatile branch) pinned. **Every project tagged `$AU_TAG`** (the real tag, even on a volatile branch).
- `qssi_st` lock released

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS**, final stage **`ref-tag`**. Counters: `tag OK` + `tag exists` = all projects, `failed = 0`.
- No lock refusal. No unexpected errors outside retried network noise.

### Level 2: Git / Mirror
```bash
git ls-remote --tags git://review.ptc.sony.co.jp/platform/qssimanifest "$AU_TAG"
git ls-remote --tags git://review.ptc.sony.co.jp/platform/build/soong  "$AU_TAG"   # rewritten _group project
git ls-remote git://review.ptc.sony.co.jp/platform/build/soong refs/heads/$REF_BRANCH
```
Review UI spot-check: rewritten project → branches → log shows the new tag.

### Level 3: Manifest
- `grease/$AU_TAG.xml` present. `default.xml` on `REF_BRANCH` at `$AU_TAG`.
- `project_list.xml` (workspace) vs `default.xml` (ref branch): every `_group`/`_repo` difference is explained by the rewrite rules, and no `…_repo` project was wrongly truncated.

### Level 4: Sync validation
On VNC: `repo init -u git://review.ptc.sony.co.jp/platform/qssimanifest -b $REF_BRANCH && repo sync -c` before and after the import. SHA-1 diff of `remote_hashes.txt` (from `qssi_st`) vs `local_tags.txt`. **QSSI: expect zero differences.** Attach to Jira.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ (KT Session 4) | **Standalone QSSI release 89 not imported.** When run, it failed with the pseudo mirror enabled. | (1) The owning team didn't import it. (2) The OSS manifest moved **public → private**, and the job config was changed **manually in Jenkins**, but the **mirror path in the script** was still the old one. | Found by checking the standalone distro release list. Mirror reference didn't resolve. | Ran **without** `PSEUDO_MIRROR_TREE`. It was very slow, was interrupted once, and was re-triggered. | ❓ | Check **both** QSSI release streams. A public↔private move is a **3-place change** by patch (KT §15.3). No manual Jenkins edits. |
| ❓ | Release QSSI tag older than ref branch | QSSI shared across Android versions | Release number < last imported | Volatile branch from the previous lower tag. Import with the real tag. Say so in the email. | ❓ | Check the last imported number before triggering |
| ❓ recurring | Network failures in `syncsnap` / push | Network | Console | As for kernel: full rerun (syncsnap) or resume (later stages) | — | — |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Conditional.** Same rules as [07 §8](07-import-qcom-kernel.md#8-recovery--rerun-procedure): full rerun for a `syncsnap` failure, resume with cleanup **unchecked** for later stages.

**Before rerun check (QSSI additions):**

| Check | How |
|---|---|
| Was the upstream source available? | `git ls-remote --tags` on **both** the Chipcode and CLO QSSI manifests for `$AU_TAG`. Rerun `list_manifest_tags`. |
| Did the previous build partially push anything? | Stage ≥ 9 means the **shared** ref branch may be partly moved. Resume promptly and tell consuming teams. |
| Is the Jenkins workspace clean? | Resume: unchecked. Fresh run: checked. |
| Is another CodeSync job running against the same repository? | **Any** other QSSI import (any product, **including standalone**) shares `qssi_st` and the lock |
| Does anything need rollback or cleanup? | If a lower release was pushed onto the ref branch by mistake, stop and agree on a rollback with Sony |
| Has the Qualcomm import script changed? | Check the release note's `sync_snap_v2.sh` options / `snap_release.xml`, new `<remote>` prefixes, and the public/private path |
| Does the script need adapting for the new tag or branch? | New remotes → push filter. Path move → 3 places. New suffix pattern → rewrite rule. |
| Should an obsolete branch be moved aside? | Prefer the **volatile branch**. Only if Sony asks to reset the ref branch: back it up as `<REF_BRANCH>-obsolete-<yymmdd-HHMM>` using the service account, then rerun. |

**Rerun steps:** as in 07 §8. Then §6, and the volatile-branch note in the completion email if one was used.
