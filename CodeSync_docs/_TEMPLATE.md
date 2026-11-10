# <Job name>

> Copy this file to `jobs/NN-<short-name>.md` when documenting a new job. Tag claims with their source: ✅ code · 📊 PPT · 🎙 KT session · 🧭 proposed / operational judgement · ❓ unconfirmed.

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | Exact Jenkins job name |
| **Job URL** | Direct Jenkins URL |
| **Category** | Mirror Sync / Vendor Import / Manifest Sync / Git Sync / Utility / Cleanup |
| **Vendor / Source** | Qualcomm / CodeLinaro / AOSP / GitHub / etc. |
| **Component** | QSSI / Kernel / Vendor Techpack / LE / AOSP / specific repository |
| **Criticality** | Critical / High / Normal |

## 2. Purpose / Job Description

**What does this job actually do?**

**Why is this job required?**

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled / Manual / Upstream Job / Webhook |
| **Schedule** | Daily / Weekly / Cron expression |
| **Manual Trigger Allowed?** | Yes / No |
| **When to trigger manually** | Missing vendor tag / previous sync failure / release import preparation |
| **Triggered by another job?** | Job name |
| **Downstream Jobs** | Jobs depending on this job |

**Flow:** `Vendor Source → Mirror Update → Import`

## 4. Job Parameters

> 📷 **Screenshot:** _add the Jenkins "Build with Parameters" page here_ → `../images/<job>-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| | | | | | |

## 5. Expected Output

_Not just "Jenkins Job = SUCCESS". Say what has changed._

-

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- Job status:
- Expected final stage:
- No unexpected errors in console log:

### Level 2: Git / Mirror
```bash
git ls-remote <mirror>
git show-ref <tag>
```

### Level 3: Manifest
Verify the expected tag, revision or branch.

### Level 4: Sync validation
```bash
repo sync
```
Confirm a downstream workspace can use the imported code.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| yyyy-mm-dd | | | | | CM-xxxx | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** Yes / No / Conditional

**Before rerun check:**

- [ ] Was the upstream source available? (`git ls-remote`)
- [ ] Did the previous build partially push anything?
- [ ] Is the Jenkins workspace clean?
- [ ] Is another CodeSync job running against the same repository?
- [ ] Does anything need rollback or cleanup?
- [ ] Has the Qualcomm import script changed?
- [ ] Does the script need adapting to support a new branch or tag from the vendor?
- [ ] Should an obsolete branch be moved aside using the service account before rerunning?

**Rerun steps:**

1.
