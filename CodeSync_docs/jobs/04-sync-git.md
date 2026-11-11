# Sync Git jobs (`sync_git_*`)

> **Sources:** ✅ `jenkins-jobs/template-sync.yaml`, `git.sh`, `project-partner.yaml` (older checkout) · 📊 PPT slides 16–19 · 🎙 KT Session 2 · 🧭 proposed · ❓ unconfirmed
> **Background:** [CodeSync_KT.md §8](../../CodeSync_KT.md#8-sync-git-jobs)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `sync_git_{name}-{repo-name}` (✅ template). Instances below. |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/sync_git_<name>-<repo-name>/` |
| **Category** | Git Sync |
| **Vendor / Source** | Google: `partner-android.googlesource.com` (most), `android.googlesource.com` (`sync_git_kernel_aosp*`) |
| **Component** | One specific git per job |
| **Criticality** | 🧭 **Normal.** 🎙 This is the lowest-maintenance category. Failures are almost always transient, and a missed run is picked up by the next one. |

**Instances** (📊 slides 18–19; source prefix `https://partner-android.googlesource.com`, target prefix `git://review.ptc.sony.co.jp`):

| Job | Source → Target | Refspec | Push args |
|---|---|---|---|
| `sync_git_partner-platform-vendor-partner_gms` | `platform/vendor/partner_gms` | `refs/heads/*:refs/heads/ohd/*` | `-f --tags` |
| `sync_git_partner-platform-system-libfmq` | `platform/system/libfmq` | `refs/heads/*:refs/heads/ohd/*` | `-f` |
| `sync_git_partner-device-google-wahoo` | `device/google/wahoo` | `refs/heads/*:refs/heads/ohd/*` | |
| `sync_git_partner-widevine` | `platform/vendor/widevine` | `refs/heads/*:refs/heads/ohd/*` | |
| `sync_git_partner-platform-vendor-google_parntners-qcom-chre` | `platform/vendor/google_partners/qcom-chre` → `platform/vendor/google/qcom-chre` | `refs/heads/*:refs/heads/ohd/*` | |
| `sync_git_partner-platform-vendor_modules-*Prebuilt` (✅ many) | `platform/vendor/partner_modules/*` | `refs/tags/*:refs/tags/*` | per job |
| `sync_git_kernel_aosp*` (🎙) | AOSP kernel gits | ❓ | ❓ |

(The typo `parntners` and the source/target path mismatch on the chre job are as shipped.)

## 2. Purpose / Job Description

**What does this job actually do?**
📊 It downloads one source git, compares the source and target SHA-1s, and pushes only if the source has changed. ✅ `git.sh`:
1. Keeps a **bare** repo `<git>.git` with `origin` = source (`--mirror=fetch`).
2. Fetches the left-hand side of each refspec.
3. Computes `git show-ref | sha1sum` and compares it with the sidecar file `<git>-ref-sha1sum` from the last successful push.
4. If they differ, it pushes each refspec to `somc` (the target) with `PUSH_ARGS` and rewrites the sidecar. If they are the same, it skips the push.

🎙 The bare repos live in a **shared persistent directory** (`USE_GIT_SYNC_PERSISTENT_DIRECTORY=true`) used by all Sync Git jobs, not in the job workspace. Some gits are shared across manifests.

**Why is this job required?**
Sony teams need specific partner gits on `review.ptc.sony.co.jp` that are **not** covered by a synced manifest branch, under the `ohd/*` namespace (or as tags for prebuilt modules).

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled (✅ `timed: '{trigger}'`) |
| **Schedule** | ✅ Older checkout: `H * * * *` (widevine, libfmq, wahoo); `H H * * *` (partner_gms*); `H H/6 * * *` (partner_modules prebuilts). ❓ Confirm the current values. |
| **Manual Trigger Allowed?** | Yes |
| **When to trigger manually** | First sync of a newly added git; a consumer reports a missing branch or tag; after a failed run |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None |

**Flow:** `partner-android git → sync_git_* (shared bare repo) → review.ptc.sony.co.jp refs/heads/ohd/*`

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters"_ → `../images/sync-git-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `SOURCE_URL` | Yes (defaulted) | `https://partner-android.googlesource.com/platform/vendor/widevine` | Upstream git | Provided by Sony in the request | Wrong content pushed into the target git |
| `TARGET_URL` | Yes (defaulted) | `git://review.ptc.sony.co.jp/platform/vendor/widevine` | Sony git to push to | Must **already exist** on review (🎙 Sony raises the creation request) | Push fails, or worse, content lands in the wrong git |
| `REFSPEC` | Yes (defaulted) | `refs/heads/*:refs/heads/ohd/*` | Comma-separated `src:dst` refspecs | Branches → `ohd/*`. Prebuilt modules → `refs/tags/*:refs/tags/*`. | Overwrites Sony-owned branches if the destination is not namespaced |
| `PUSH_ARGS` | No | `-f --tags` | Extra `git push` arguments | Per job | `-f` without `ohd/` namespacing can rewrite history on Sony branches |
| *(injected)* `USE_SYSTEM_GIT_CONFIG` | — | `false` | ✅ Sets `GIT_CONFIG_NOSYSTEM=1` | Template default | — |
| *(injected)* `USE_GIT_SYNC_PERSISTENT_DIRECTORY` | — | `true` | 🎙 Use the shared bare-repo directory | Template default | — |

## 5. Expected Output

- New upstream commits, branches or tags appear on the target under `refs/heads/ohd/*` (or `refs/tags/*`)
- The sidecar `<git>-ref-sha1sum` is updated to the new checksum
- If nothing changed upstream: **no push** (the log shows a skip). This is a valid success.

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- Status **SUCCESS**
- Console shows either `git push … somc …` lines (changes) or no push (nothing changed)
- No `rejected`, `non-fast-forward`, `Permission denied` or `fatal:` lines

### Level 2: Git / Mirror
```bash
git ls-remote https://partner-android.googlesource.com/<git> refs/heads/<branch>
git ls-remote git://review.ptc.sony.co.jp/<git>              refs/heads/ohd/<branch>
# SHA-1s must match after a run
# tags jobs:
git ls-remote --tags <SOURCE_URL> | wc -l ;  git ls-remote --tags <TARGET_URL> | wc -l
```

### Level 3: Manifest
N/A. These jobs sync single gits. If the git is referenced by a Sony manifest, check that the revision the manifest expects (`ohd/<branch>`) exists.

### Level 4: Sync validation
Where a consumer uses it: `git clone git://review.ptc.sony.co.jp/<git> && git checkout ohd/<branch>`.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ (KT Session 2) | New sync job created but push failed: target git missing | Job added **before** the target repository existed on review ("quick share" git) | Push error: project not found | Asked Sony to raise the repository-creation request, waited, reran | ❓ owed (KT §16.1 #2) | 🎙 **Check that the target exists before adding the job.** See the checklist in KT §15.1. |
| ❓ recurring | Fetch or push failure | Network / disk space (🎙 transient) | Console | Rerun | — | — |
| 🧭 risk | Upstream changed but no push happened | Sidecar `*-ref-sha1sum` wrongly persisted | Source/target SHA-1 mismatch while the log says nothing changed | Delete the sidecar for that git in the persistent dir and rerun (forces a full push) | — | — |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** It is idempotent: the push is skipped if nothing changed, and pushes go to the `ohd/*` namespace.

**Before rerun check:**

| Check | How |
|---|---|
| Was the upstream source available? | `git ls-remote $SOURCE_URL` |
| Did the previous build partially push anything? | Possible (one refspec pushed, the next failed). Harmless, because the next run pushes the rest. The sidecar is only written after **all** pushes succeed. |
| Is the Jenkins workspace clean? | The state lives in the **shared persistent directory**, not the workspace. Do not wipe it casually, because other jobs share gits there. |
| Is another CodeSync job running against the same repository? | 🎙 Other `sync_git_*` jobs may share the same bare repo. Avoid concurrent manual runs of jobs that share a git. |
| Does anything need rollback or cleanup? | Only if the wrong `TARGET_URL` or `REFSPEC` pushed content to the wrong place. Ask Sony CM to delete the refs. |
| Does the script need adapting for a new branch or tag? | No. 🎙 `git.sh` has never needed changes. New branches arrive automatically through `refs/heads/*`. |
| Should an obsolete branch be moved aside? | Only for a `non-fast-forward` rejection on a non-`-f` job: back up the target ref (e.g. `ohd/<br>-obsolete-<yymmdd-HHMM>`) using the service account (`jp21771`), then rerun. Coordinate with Sony first. |

**Rerun steps:** *Build Now* → Level 2 check.
