# code_sync_deploy_jenkins_jobs (Deploy code-sync jobs)

> **Sources:** ✅ `jenkins-jobs/codesync.ajdc.sony.co.jp/project-deploy-jenkins-jobs.yaml`, `Makefile` (older checkout; it uses branch `scps`, while the current branches are `master` (prod) and `stage`) · 🎙 KT Session 2 · 🧭 proposed
> **Background:** [CodeSync_KT.md §5](../../CodeSync_KT.md#5-change-management-how-you-ship-a-change)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `code_sync_deploy_jenkins_jobs` (display: *Deploy code-sync jobs*) |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/code_sync_deploy_jenkins_jobs/` · Stage: `https://codesync.ptc-stage.sony.co.jp/job/code_sync_deploy_jenkins_jobs/` |
| **Category** | Utility (deployment) |
| **Vendor / Source** | Sony `review-plus.ptc.sony.co.jp`, `code-sync` repo |
| **Component** | All CodeSync Jenkins job definitions (JJB) |
| **Criticality** | 🧭 **Critical.** It creates, updates and deletes **every** CodeSync job. A bad deploy can break or remove all jobs. |

## 2. Purpose / Job Description

**What does this job actually do?**
✅ It checks out `code-sync`, then runs `make -C jenkins-jobs clean deployment-env` and `make update`. Jenkins Job Builder renders the `template-*.yaml` + `project-*.yaml` files for this Jenkins host and **creates or updates** the jobs. It then runs `make test` and `make delete` to **remove jobs that no longer exist** in YAML (comparing with the previous revision). An optional `GERRIT_REFSPEC` deploys an **unmerged** patch.

**Why is this job required?**
🎙 It is the only sanctioned way to change jobs. **Manual edits in the Jenkins UI are outside review and are overwritten by the next deploy** (see the standalone-QSSI incident in [08](08-import-qcom-qssi.md#7-failure--troubleshooting-history)).

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Webhook (Gerrit `ref-updated` on `code-sync`, file path `jenkins-jobs/**`) + Scheduled |
| **Schedule** | ✅ `H H * * *` (nightly) |
| **Manual Trigger Allowed?** | 🎙 **Prod: No.** Sony asked that prod deploys happen only through the Gerrit trigger, so the `GERRIT_REFSPEC` parameter was removed from the prod job. **Stage: Yes**, with `GERRIT_REFSPEC` to test an unmerged patch. |
| **When to trigger manually** | Stage only: to deploy an unmerged patch for verification |
| **Triggered by another job?** | No (Gerrit event) |
| **Downstream Jobs** | None. Affects every job. |

**Flow:** `patch on stage → code_sync_test_jenkins_jobs (+1) → deploy to Stage (GERRIT_REFSPEC) → verify → +1 internal → +1 Ashun-san → Sony review → merge stage → cherry-pick master → (ref-updated) deploy to Prod`

## 4. Job Parameters

> 📷 **Screenshot:** _add the Stage "Build with Parameters" page_ → `../images/deploy-jobs-stage-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `GERRIT_REFSPEC` | Stage: Yes for a patch test. Prod: **not present**. | `refs/changes/61/314061/1` | Refspec of `code-sync` to deploy | Gerrit change → *Download* → refspec | Deploys someone else's patch, or an old patchset. 🎙 **Stage is shared: deploying your patch overwrites another person's test.** |

## 5. Expected Output

- Jobs created or updated in Jenkins to match YAML. Jobs removed from YAML are deleted.
- Console shows the JJB `Updating job …` / `Deleting job …` lines
- Changed jobs' *Configure* pages reflect the patch

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS**. `make update`, `make test` and `make delete` all completed.
- The list of `Updating`/`Creating`/`Deleting` jobs matches the intent of the patch. **No unexpected deletions.**

### Level 2: Git / Mirror
```bash
git ls-remote ssh://review-plus.ptc.sony.co.jp:29418/code-sync refs/heads/master   # prod deploy revision
```
Matches the revision in the console log.

### Level 3: Manifest
Open each affected job → *Configure*. Parameters, defaults, schedule and node match the YAML.

### Level 4: Sync validation
🎙 **Template-only change:** confirming the job was created correctly on stage is enough. **Any `.sh` change:** run the affected job on stage and attach the results to the ticket before review. (Stage sync jobs are disabled or dry-run, which proves the job definition, not the sync.)

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ (KT Session 2) | Stage test results invalid | Two people deployed unmerged patches to stage at the same time | Job config doesn't match your patch | Coordinate and redeploy | — | 🎙 Announce stage deploys in the team channel |
| ❓ | Manual Jenkins config fix disappeared | Overwritten by the nightly or triggered deploy | Config reverted | Make the fix through a patch | — | No manual prod edits |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes** (idempotent: it renders the YAML at a revision). **But** a rerun deploys whatever is at that revision. Make sure that is what you want.

**Before rerun check:**

| Check | How |
|---|---|
| Is the source available? | `git ls-remote` of `code-sync` on review-plus |
| Did the previous build partially apply anything? | JJB updates jobs one by one, so some jobs may be updated. Rerun to converge. |
| Is the Jenkins workspace clean? | The job does `rm -rf code-sync` and re-clones (`prepare-code-sync`) |
| Is another deploy running? | Don't overlap deploys. On stage, check that nobody else is testing. |
| Does anything need rollback? | Revert the patch in Gerrit (revert change → merge → auto deploy). Don't hand-edit jobs. |
| Has the Makefile or configurator changed? | Check `configurator` submodule updates in the patch |

**Rerun steps:** Prod: a reverted or fixed merge triggers it automatically. Stage: *Build with Parameters* with `GERRIT_REFSPEC`.
