# maintenance_disable_jobs

> **Sources:** ⚙️ live Stage `config.xml` (provided 2026-11-12) · 🧭 proposed · ❓ unconfirmed
> **Part of the maintenance set:** [16 store](16-maintenance-store-jobs.md) → **17 disable** → *maintenance* → [18 enable](18-maintenance-enable-jobs.md). The full window procedure is in [16 §3](16-maintenance-store-jobs.md#3-trigger-information).

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `maintenance_disable_jobs` (description: *"disable all jobs"*) |
| **Job URL** | Stage: `https://codesync.ptc-stage.sony.co.jp/job/maintenance_disable_jobs/` · Prod: ❓ *check whether a prod copy exists* |
| **Category** | Utility (Jenkins maintenance) |
| **Vendor / Source** | Internal: Jenkins REST API |
| **Component** | **Every** top-level job on the instance |
| **Criticality** | 🧭 **High, destructive to operations.** One click stops all CodeSync automation on the instance until it is reversed. |

**Node:** ⚙️ none assigned, `canRoam=true`. It can run on any executor, including the built-in node.

## 2. Purpose / Job Description

**What does this job actually do?**
⚙️
```bash
result=`curl https://stage-codesync.ajdc.sony.co.jp/api/json -u "admin:$JENKINS_TOKEN"`
urls=`echo $result | jq -r '.jobs[].url'`
for url in $urls ; do
  curl -X POST -u "admin:$JENKINS_TOKEN" "$url""disable"
done
```
It POSTs `…/job/<name>/disable` for **every** top-level job. No exceptions: that includes `maintenance_enable_jobs`, `maintenance_store_jobs`, **itself**, and `code_sync_deploy_jenkins_jobs` / `code_sync_test_jenkins_jobs`.

**Why is this job required?**
It stops scheduled and triggered builds from starting during Jenkins maintenance (upgrade, restart, storage work), so nothing is interrupted half-way, such as an import mid-push or a mirror mid-sync.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Manual |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes (the only way) |
| **When to trigger manually** | Step 3 of the maintenance window, **after** `maintenance_store_jobs` has produced `jobs.txt` and running builds have finished |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None. Reversed by [18 maintenance_enable_jobs](18-maintenance-enable-jobs.md). |

## 4. Job Parameters

> 📷 **Screenshot:** _no parameters. Add the console of a sample run_ → `../images/maintenance-disable-jobs-console.png`

No build parameters.

| Setting | Mandatory? | Value (⚙️) | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `JENKINS_TOKEN` | Yes | credential `jenkins_admin_password` (string) | Admin password for the REST API | Jenkins → Credentials | Wrong or expired: POSTs fail, but **the job still goes green** (see §6) |
| Target host (in shell) | Yes | `https://stage-codesync.ajdc.sony.co.jp` | Instance whose jobs get disabled | Should be this Jenkins | ⚠️ If the old hostname now points at a **different** Jenkins, this disables **that instance's** jobs |

## 5. Expected Output

- Every top-level job shows as **disabled** (grey, *"This project is currently disabled"*)
- Builds already running are **not** stopped. They finish normally.
- No new scheduled or SCM/Gerrit-triggered builds start

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS** alone proves little. The POST `curl` has **no `-f`**, so a 401/403/404 on every job still gives a green build.
- Console: each `curl -X POST …/disable` should return no HTML error page. Look for `Error 403`, `No valid crumb`, `401`.
- ❓ **CSRF:** Jenkins normally requires a crumb for POSTs authenticated with a **password** (API tokens are exempt). If `jenkins_admin_password` is a real password rather than an API token, every POST may be rejected. Test this on stage before a real window.

### Level 2: Git / Mirror
N/A. Verify through the API instead:
```bash
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq '[.jobs[] | select(.color != "disabled")] | length'      # expect 0
```

### Level 3: Manifest
N/A. Check the executors: no queued items waiting to start (*Build Queue* is empty or only shows "disabled" items).

### Level 4: Sync validation
N/A

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

**Known risks** (🧭 from reading the config):

| Risk | Detail | Mitigation |
|---|---|---|
| **Locks itself out** | It also disables `maintenance_enable_jobs`. A disabled job cannot be built, so the enable job cannot be run until someone enables it by hand. | **Before step 6, enable `maintenance_enable_jobs` from its page (*Enable*)**, or `curl -X POST -u admin:<token> <host>/job/maintenance_enable_jobs/enable` |
| Silent failure | No `curl -f` on POST | Always do the Level 2 count check. 🧭 Patch: add `-f`, and exclude the `maintenance_*` jobs. |
| Old hostname | `stage-codesync.ajdc.sony.co.jp` is the pre-migration host | ❓ Verify. 🧭 Patch to `${JENKINS_URL}`. |
| Does not wait for running builds | Disabling does not abort running builds. Restarting Jenkins **does**. | Check the executors are idle before maintenance. An import killed mid-run must be recovered per [07 §8](07-import-qcom-kernel.md#8-recovery--rerun-procedure). |
| Deploy job also disabled | ❓ Unclear whether a JJB redeploy would re-enable jobs (the YAML sets `disabled: false` on most) | Don't merge `code-sync` changes during a maintenance window |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** Disabling an already disabled job is harmless. **Undoing it** is the real recovery: see [18](18-maintenance-enable-jobs.md).

**Before rerun check:**

| Check | How |
|---|---|
| Was the source available? | `curl -u admin:<token> <host>/api/json` returns JSON and lists **this** instance's jobs |
| Did the previous build partially do anything? | Count disabled jobs (Level 2). A partial run is fine. Rerun to finish. |
| Is the Jenkins workspace clean? | Not relevant |
| Was `maintenance_store_jobs` run **before** the first disable? | **If not, stop.** Without its `jobs.txt` you cannot tell which jobs were disabled on purpose. Reconstruct the list from the YAML (`disabled: true` entries) before going further. |
| Does anything need rollback? | Ran by mistake → enable `maintenance_enable_jobs` by hand, then run it with the latest `jobs.txt` |

**Rerun steps:** *Build Now* → Level 2 count = 0.
