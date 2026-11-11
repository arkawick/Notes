# Update Combined Mirror Manifest

> **Sources:** 📊 PPT slides 27–28 · 🎙 KT Session 1 · 🧭 proposed · ❓ unconfirmed. This job is **not** in the older checkout.
> **Background:** [CodeSync_KT.md §7.6](../../CodeSync_KT.md#76-combined-mirror-manifest-jobs)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `update_combined_mirror_manifest_partner-android.googlesource.com` · `update_combined_mirror_manifest_review-plus.ptc.sony.co.jp` |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/update_combined_mirror_manifest_partner-android.googlesource.com/` and `…/job/update_combined_mirror_manifest_review-plus.ptc.sony.co.jp/` ❓ verify |
| **Category** | Mirror Sync (manifest preparation) |
| **Vendor / Source** | Google partner (`partner-android.googlesource.com`); Sony `review-plus` (S-Link-Spica) |
| **Component** | AML prebuilt and FS release manifests (partner); LE1.0/LE3.0 kernel and vendor ref manifests for SA525M (review-plus) |
| **Criticality** | 🧭 **High** for partner-android (it feeds the partner mirror used by the Sync Manifest jobs). **Normal** for review-plus (❓ may no longer be needed). |

## 2. Purpose / Job Description

**What does this job actually do?**
It merges **several manifest branches into one XML at runtime** and then syncs the mirror against that combined list. This replaces one mirror job per branch. 🎙 **The combined XML is not committed anywhere.** It is generated, used and discarded inside the run.

| Job | Combines |
|---|---|
| partner-android | `platform/manifest`: `t-aml-prebuilt-release`, `t-go-aml-prebuilt-release`, `u-aml-prebuilt-release`, `v-aml-prebuilt-release`, `b-aml-prebuilt-release` · `platform/vendor/pdk/generic/fs/manifest`: `u-qpr1-fs-release`, `24Q3`…`25Q4-fs-release` |
| review-plus | `S-Link-Spica/kernelmanifest`: `sa525m-le1.0/le3.0-kernel-ref` (+ `volatile-test0-*`) · `S-Link-Spica/targetmanifest`: `sa525m-le1.0/le3.0-vendor-ref` (+ `volatile-test0-*`) |

**Why is this job required?**
Some upstreams need many branches mirrored. Combining them keeps one mirror per upstream that holds the objects for **all** active release branches, so every `sync_manifest_*` job for those branches can reference it.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled ❓ |
| **Schedule** | ❓ Read it from *Configure* |
| **Manual Trigger Allowed?** | Yes |
| **When to trigger manually** | After a release branch is added to or removed from the job; when the partner mirror is missing objects for a new branch |
| **Triggered by another job?** | No |
| **Downstream Jobs** | 🎙 partner-android → **`Update Mirror partner-android.googlesource.com on AOSP_MIRROR`** ([01](01-mirror-update-mirror.md)). review-plus → ❓ presumably `Update Mirror review-plus.ptc.sony.co.jp on codesync07`. |

**Flow:** `combined manifest (runtime XML) → Update Mirror partner-android → (referenced by) sync_manifest_* / sync_manifest_and_gits_*`

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters"_ → `../images/combined-mirror-manifest-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `USE_LOCAL_SCRIPTS` | No | unchecked | Overlay scripts from a local server directory onto the cloned `code-sync` (debugging) | Leave unchecked in prod | Runs uncommitted local scripts in prod, outside review |
| *(manifest / branch list)* | — | see §2 | Defined in the job YAML, not a build parameter | Changed **only by patch** when release branches change | A missing branch leaves its sync job without mirror backing. A dead branch wastes disk. |

## 5. Expected Output

- A combined manifest generated in the workspace (not committed)
- Downstream mirror job triggered and completed
- Mirror now holds objects for **every** branch listed in the job, including any just added

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- This job is **SUCCESS** and the downstream mirror job is **SUCCESS** (check the *Downstream builds* link)
- Console lists every expected branch being read

### Level 2: Git / Mirror
```bash
# a project only present on a newly added branch now exists in the mirror
ls /mnt/efs/gitmirror/partner-android.googlesource.com/<project>.git
git --git-dir /mnt/efs/gitmirror/partner-android.googlesource.com/platform/manifest.git branch -a | grep <new-branch>
```

### Level 3: Manifest
Compare the job's branch list with the active `sync_manifest_*` / `sync_manifest_and_gits_*` jobs. **The two lists must match** (🎙 the two-place rule).

### Level 4: Sync validation
The next `sync_manifest_ohd_<new-branch>` run should complete quickly with the mirror reference (no full download).

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ | Mirror still carries branches that are no longer needed (e.g. 25Q1/25Q2) | Sync job removed but branch left in the combined job | Branch list review | Remove the branch from the combined job by patch | ❓ | 🧭 Retirement checklist: **sync job + combined manifest** together |
| ❓ (open) | review-plus / S-Link-Spica job: no recent LE1/LE3 content | Possibly obsolete | Recent build history shows no new content | 🎙 Agreed to ask Sony whether it can be stopped | ❓ | Pending Sony answer (KT §16.2 #6) |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** It only generates a temporary XML and triggers a fetch-only mirror job.

**Before rerun check:**

| Check | How |
|---|---|
| Was the upstream source available? | `git ls-remote https://partner-android.googlesource.com/platform/manifest refs/heads/<branch>` for each branch |
| Did the previous build partially push anything? | No. Nothing is committed or pushed. |
| Is the Jenkins workspace clean? | The combined XML is regenerated every run. A stale workspace is harmless. |
| Is another CodeSync job running against the same repository? | Make sure the downstream mirror job is not already running |
| Does anything need rollback or cleanup? | No |
| Does the job need adapting for a new branch? | Yes. When a release branch is added or retired, patch **this job and the matching sync job** (stage → review → merge → cherry-pick to master). |
| Should an obsolete branch be moved aside? | N/A |

**Rerun steps:** *Build Now* → confirm the downstream mirror job ran → Level 2 check.
