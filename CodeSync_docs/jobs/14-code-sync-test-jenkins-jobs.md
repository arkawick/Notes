# code_sync_test_jenkins_jobs (Test code-sync jobs)

> **Sources:** ✅ `jenkins-jobs/codesync.ajdc.sony.co.jp/project-test-jenkins-jobs.yaml` (older checkout: branch pattern `master`) · 🎙 KT Session 2 · 🧭 proposed
> **Background:** [CodeSync_KT.md §5](../../CodeSync_KT.md#5-change-management-how-you-ship-a-change)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `code_sync_test_jenkins_jobs` (display: *Test code-sync jobs*) |
| **Job URL** | `https://codesync.ptc.sony.co.jp/job/code_sync_test_jenkins_jobs/` ❓ confirm which instance hosts it |
| **Category** | Utility (CI / validation) |
| **Vendor / Source** | Sony `review-plus`, `code-sync` repo |
| **Component** | JJB job definitions |
| **Criticality** | 🧭 **Normal.** It blocks nothing at runtime, but its +1 is the first gate in change management. |

## 2. Purpose / Job Description

**What does this job actually do?**
✅ On every new patchset to `code-sync`, it:
1. Renders the **current** job XML (`make -C jenkins-jobs`) → `result-dir/xml-master`
2. Fetches `GERRIT_REFSPEC`, runs `git diff --check HEAD~1..` (whitespace errors), and renders the patched XML → `xml-<sha>`
3. Runs `make test-delete` to list jobs the patch would delete (`delete_names.txt`)
4. Writes `xml.diff` = exactly how every Jenkins job config would change
5. Archives `result-dir/**`. 🎙 Gives the automatic **+1** on the change.

**Why is this job required?**
It catches YAML/JJB syntax errors and shows reviewers the **real effect** of a patch on job configs before anything is deployed.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Webhook (Gerrit `patchset-created`, `draft-published` on project `code-sync`) |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes, by retriggering from Gerrit ❓ (needs `GERRIT_REFSPEC`; it fails without it) |
| **When to trigger manually** | Failed for an infrastructure reason; a new patchset did not trigger it |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None (gates review → [13 deploy](13-code-sync-deploy-jenkins-jobs.md)) |

## 4. Job Parameters

> 📷 **Screenshot:** _add a sample build page with `xml.diff` artifact_ → `../images/test-jobs-artifacts.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `GERRIT_REFSPEC` | Yes (injected by the Gerrit trigger) | `refs/changes/61/314061/1` | Patchset to test | Set automatically | Missing → `ERROR: GERRIT_REFSPEC is not set` |

## 5. Expected Output

- **+1 Verified** on the Gerrit change
- Artifacts: `xml-master/`, `xml-<sha>/`, `xml.diff`, `delete_names.txt`, `revision`

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS** and a Gerrit **+1**. `git diff --check` is clean.

### Level 2: Git / Mirror
The `revision` artifact = the patchset's commit SHA-1.

### Level 3: Manifest
**Read `xml.diff`:** only the jobs you intended changed. **Read `delete_names.txt`:** no unintended job deletions.

### Level 4: Sync validation
N/A. Continue with the stage deploy ([13](13-code-sync-deploy-jenkins-jobs.md)).

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** It is read-only (renders XML, touches no jobs).

**Before rerun check:** make sure the patchset still exists and the `configurator` submodule can be fetched. **Rerun:** retrigger from Gerrit, or upload a new patchset.
