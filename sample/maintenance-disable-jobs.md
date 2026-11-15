# maintenance_disable_jobs

> **Part of the maintenance set:** [store](maintenance-store-jobs.md) -> **disable** -> *maintenance* -> [enable](maintenance-enable-jobs.md). The combined procedure is in [maintenance-job.md](maintenance-job.md).
> **Job definition:** template `maintenance_disable_jobs` in [`jenkins-jobs/template-maintenance.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/template-maintenance.yaml) lines 60-78 (branch `master`). No project YAML uses this template, so the live job is not managed by the deploy job (see Appendix B).
> **Background:** [CodeSync KT reference](../../CodeSync_KT.md)

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `maintenance_disable_jobs` (description: *"disable all jobs"*) |
| **Job URL** | Stage: `https://codesync.ptc-stage.sony.co.jp/job/maintenance_disable_jobs/` · Prod: not defined in any `master` YAML; [Unconfirmed] check whether a hand-made prod copy exists |
| **Category** | Utility |
| **Vendor / Source** | Internal: Jenkins REST API |
| **Component** | Every top-level job on the instance |
| **Criticality** | **High, destructive to operations** [Proposed]. One click stops all CodeSync automation on the instance until it is reversed. |

## 2. Purpose / Job Description

**What does this job actually do?**

[Live]

```bash
result=`curl https://stage-codesync.ajdc.sony.co.jp/api/json -u "admin:$JENKINS_TOKEN"`
urls=`echo $result | jq -r '.jobs[].url'`
for url in $urls ; do
  curl -X POST -u "admin:$JENKINS_TOKEN" "$url""disable"
done
```

It POSTs `.../job/<name>/disable` for **every** top-level job, with no exceptions. That includes `maintenance_enable_jobs`, `maintenance_store_jobs`, itself, and `code_sync_deploy_jenkins_jobs` / `code_sync_test_jenkins_jobs`.

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
| **Downstream Jobs** | None. Reversed by [maintenance_enable_jobs](maintenance-enable-jobs.md). |

**Flow:** `maintenance_store_jobs -> maintenance_disable_jobs -> maintenance work -> maintenance_enable_jobs`

## 4. Job Parameters

> **Screenshot:** _the job has no build parameters; the rows below are the job settings that control it. Add the console of a sample run_ -> `../images/maintenance-disable-jobs-console.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `JENKINS_TOKEN` | Yes | credential `jenkins_admin_password` (string) [Live] | Admin password for the REST API | Jenkins > Credentials | Wrong or expired: POSTs fail, but the job still goes green (see section 6) |
| Target host (in shell) | Yes | `https://stage-codesync.ajdc.sony.co.jp` | Instance whose jobs get disabled | Should be this Jenkins | If the old hostname now points at a **different** Jenkins, this disables that instance's jobs |

## 5. Expected Output

- Every top-level job shows as **disabled** (grey, *"This project is currently disabled"*)
- Builds already running are **not** stopped. They finish normally.
- No new scheduled or SCM/Gerrit-triggered builds start

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **Job status:** SUCCESS, which alone proves little. The POST `curl` has no `-f`, so a 401/403/404 on every job still gives a green build. [Unconfirmed] Jenkins normally requires a CSRF crumb for POSTs authenticated with a password (API tokens are exempt). If `jenkins_admin_password` is a real password, every POST may be rejected. Test this on stage before a real window.
- **Expected final stage:** one `curl -X POST .../disable` per job in the console
- **No unexpected errors in console log:** no HTML error pages. Look for `Error 403`, `No valid crumb`, `401`.

### Level 2: Git / Mirror
N/A. Verify through the API instead:

```bash
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq '[.jobs[] | select(.color != "disabled")] | length'      # expect 0
```

### Level 3: Manifest
N/A. Check the executors: no queued items waiting to start (the Build Queue is empty or only shows disabled items).

### Level 4: Sync validation
N/A

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** Yes. Disabling an already disabled job is harmless. Undoing it is the real recovery: see [maintenance_enable_jobs](maintenance-enable-jobs.md).

**Before rerun check:**

- [ ] **Was the upstream source available? (`git ls-remote`)** N/A for git. Check that `curl -u admin:<token> <host>/api/json` returns JSON and lists **this** instance's jobs.
- [ ] **Did the previous build partially push anything?** Count disabled jobs (Level 2). A partial run is fine; rerun to finish.
- [ ] **Is the Jenkins workspace clean?** Not relevant.
- [ ] **Is another CodeSync job running against the same repository?** Instead ask: was `maintenance_store_jobs` run **before** the first disable? If not, stop. Without its `jobs.txt` you cannot tell which jobs were disabled on purpose. Reconstruct the list from the YAML before going further: on stage, the `disabled: true` entries in `jenkins-jobs/codesync.ptc-stage.sony.co.jp/project-*.yaml`. Stage deploys from the `stage` branch, so check that branch rather than `master`. Jobs not managed by JJB (including the `maintenance_*` jobs) are not in the YAML.
- [ ] **Does anything need rollback or cleanup?** If it was run by mistake, enable `maintenance_enable_jobs` by hand, then run it with the latest `jobs.txt`.
- [ ] **Has the Qualcomm import script changed?** N/A.
- [ ] **Does the script need adapting to support a new branch or tag from the vendor?** N/A.
- [ ] **Should an obsolete branch be moved aside using the service account before rerunning?** N/A.

**Rerun steps:**

1. Click *Build Now*.
2. Confirm the Level 2 count is 0.

---

## Appendix

### A. Job details

**Node:** none assigned, `canRoam=true` [Live]. It can run on any executor, including the built-in node. (The template says `CODESYNC01`.) The job is listed in the Jenkins view **maintenance** (`view.yaml`, regex `maintenance_.*`).

### B. Code vs live

| Item | `template-maintenance.yaml` (master) | Live stage job |
|---|---|---|
| API host | `https://{fqdn}/api/json` | hard-coded `https://stage-codesync.ajdc.sony.co.jp/api/json` |
| Shell | `#!/bin/bash -ex`. With `-e`, a failed or unauthorised `api/json` call makes `jq` fail and stops the job; the per-job POSTs still have no `-f`. | [Unconfirmed] shebang not captured. Without `-e`, even the `api/json` failure goes green. |
| Node | `CODESYNC01` | none, `canRoam=true` |
| Credential | secret text `jenkins_admin_password` bound to `JENKINS_TOKEN` | same |
| Managed by JJB? | No project YAML in either instance folder uses this template | Not regenerated by `code_sync_deploy_jenkins_jobs`. Template changes have no effect until a project entry is added. |

### C. Known risks

[Proposed] From reading the config and the YAML.

| Risk | Detail | Mitigation |
|---|---|---|
| Locks itself out | It also disables `maintenance_enable_jobs`. A disabled job cannot be built, so the enable job cannot run until someone enables it by hand. | Before the enable step, enable `maintenance_enable_jobs` from its page (*Enable*), or `curl -X POST -u admin:<token> <host>/job/maintenance_enable_jobs/enable` |
| Silent failure | No `curl -f` on the POST | Always do the Level 2 count check. Proposed patch: add `-f`, and exclude the `maintenance_*` jobs. |
| Old hostname | `stage-codesync.ajdc.sony.co.jp` is the pre-migration host. The `master` template already uses `{fqdn}`, but the template is not deployed. | [Unconfirmed] Verify the host. Fix by adding a project entry for `template-maintenance.yaml` with `fqdn: codesync.ptc-stage.sony.co.jp`, or edit the live job by hand. |
| Not managed by JJB | No project YAML uses `template-maintenance.yaml` | Edits to the template change nothing in Jenkins. Back up the live `config.xml` before editing it in the UI. |
| Does not wait for running builds | Disabling does not abort running builds. Restarting Jenkins does. | Check the executors are idle before maintenance. An import killed mid-run must be recovered per [import recovery](../jobs/07-import-qcom-kernel.md#8-recovery--rerun-procedure). |
| Deploy job re-enables jobs | `code_sync_deploy_jenkins_jobs` runs `make -C jenkins-jobs update`, which rewrites every JJB-managed job, including its `disabled` flag, from the YAML (`disabled: false` on most projects). This job disables the deploy job too, so it cannot fire during the window. If someone enables it or runs `make update` by hand, JJB-managed jobs come back on mid-maintenance. On stage the deploy job also has a daily timer (`H H * * *`) and a Gerrit trigger on merges to `stage`; on prod it only triggers on merges to `master`. | Keep the deploy job disabled and don't merge `code-sync` changes during a maintenance window [Proposed] |
