# maintenance_store_jobs

> **Part of the maintenance set:** **store** -> [disable](maintenance-disable-jobs.md) -> *maintenance* -> [enable](maintenance-enable-jobs.md). The combined procedure is in [maintenance-job.md](maintenance-job.md).
> **Job definition:** template `maintenance_store_jobs` in [`jenkins-jobs/template-maintenance.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/template-maintenance.yaml) lines 1-28 (branch `master`). No project YAML uses this template, so the live job is not managed by the deploy job (see Appendix B).
> **Background:** [CodeSync KT reference](../../CodeSync_KT.md)

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `maintenance_store_jobs` |
| **Job URL** | Stage: `https://codesync.ptc-stage.sony.co.jp/job/maintenance_store_jobs/` · Prod: not defined in any `master` YAML; [Unconfirmed] check whether a hand-made prod copy exists |
| **Category** | Utility |
| **Vendor / Source** | Internal: Jenkins REST API |
| **Component** | The Jenkins instance's job list |
| **Criticality** | **High during a maintenance window** [Proposed]. Without a correct list, you cannot restore exactly the jobs that were enabled before. Otherwise unused. |

## 2. Purpose / Job Description

**What does this job actually do?**

[Live] Job description: *"Store jobs. Execute this before execute maintenance_disable_jobs."*

```bash
RESULT=`curl -f -u "admin:$JENKINS_TOKEN" https://stage-codesync.ajdc.sony.co.jp/api/json`
if [ "true" = "$ALL" ]; then
  echo "$RESULT" | jq -r '.jobs[].url' > enabled_jobs.txt                                   # every job
else
  echo "$RESULT" | jq -r '.jobs[]' | jq 'select(.color != "disabled")' | jq -r '.url' > jobs.txt   # only enabled jobs
fi
```

Post-build: **archive `jobs.txt`**.

The result is a list of job URLs (one per line) that were **enabled** before maintenance. It is fed into `maintenance_enable_jobs` afterwards, so jobs that were deliberately disabled stay disabled.

**Why is this job required?**

`maintenance_disable_jobs` disables everything. Without a snapshot of what was enabled beforehand, re-enabling would also turn on jobs that are meant to be off (for example retired syncs, or stage jobs disabled on purpose because stage must not push).

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Manual |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes (the only way) |
| **When to trigger manually** | First step of a planned Jenkins maintenance (plugin or core upgrade, node or EBS work, restart). The full window procedure is in [maintenance-job.md, Appendix B](maintenance-job.md#b-maintenance-window-procedure). |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None automatic. Its `jobs.txt` artifact is the input (`JOB_LIST`) for [maintenance_enable_jobs](maintenance-enable-jobs.md). |

**Flow:** `maintenance_store_jobs -> maintenance_disable_jobs -> maintenance work -> maintenance_enable_jobs`

## 4. Job Parameters

> **Screenshot:** _add "Build with Parameters"_ -> `../images/maintenance-store-jobs-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `ALL` | No (boolean, default `false`, from the template) | unchecked | Unchecked: list only **enabled** jobs into `jobs.txt`. Checked: list **all** jobs into `enabled_jobs.txt`. | **Leave unchecked** for the maintenance procedure | **Checked = no usable artifact.** The output goes to `enabled_jobs.txt`, but only `jobs.txt` is archived. Restoring from a full list would switch on jobs that are disabled on purpose. |
| `JENKINS_TOKEN` | (credential) | secret text `jenkins_admin_password` (template; same as the disable and enable jobs) | Admin auth for the REST API | Jenkins > Credentials | 401 means the job fails (`curl -f`) |

## 5. Expected Output

- Artifact **`jobs.txt`**: one URL per line, for every top-level job that was not disabled at that moment
- No change to any job

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **Job status:** SUCCESS
- **Expected final stage:** artifact `jobs.txt` archived, present and **non-empty**. The URLs in it must use the host of **this** Jenkins: the script queries `https://stage-codesync.ajdc.sony.co.jp`, the pre-Cloud-J2 hostname. [Unconfirmed] Confirm it still resolves to the current stage Jenkins (`codesync.ptc-stage.sony.co.jp`); if it points anywhere else, the list belongs to a different instance.
- **No unexpected errors in console log:** no `curl: (22)` or `401`

### Level 2: Git / Mirror
N/A. Instead, cross-check the count against the Jenkins API:

```bash
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq '[.jobs[] | select(.color != "disabled")] | length'        # == wc -l jobs.txt
```

### Level 3: Manifest
N/A. Spot-check that jobs known to be disabled on purpose (for example stage sync jobs) are **absent** from `jobs.txt`.

### Level 4: Sync validation
N/A

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** Conditional. Yes, but only **before** `maintenance_disable_jobs` has run. It is read-only, but running it after the disable produces an empty or near-empty list. Never rerun it mid-maintenance; use the artifact from the run before the disable.

**Before rerun check:**

- [ ] **Was the upstream source available? (`git ls-remote`)** N/A for git. Check that `curl -f -u admin:<token> <host>/api/json` returns JSON.
- [ ] **Did the previous build partially push anything?** No. The job is read-only.
- [ ] **Is the Jenkins workspace clean?** Not relevant. The file is overwritten each run.
- [ ] **Is another CodeSync job running against the same repository?** Instead ask: has `maintenance_disable_jobs` already run? If yes, **do not** rerun this job. Fetch `jobs.txt` from the earlier build.
- [ ] **Does anything need rollback or cleanup?** No.
- [ ] **Has the Qualcomm import script changed?** N/A.
- [ ] **Does the script need adapting to support a new branch or tag from the vendor?** N/A.
- [ ] **Should an obsolete branch be moved aside using the service account before rerunning?** N/A.

**Rerun steps:**

1. *Build with Parameters*, with `ALL` unchecked.
2. Download `jobs.txt`.
3. Attach it to the maintenance ticket.

---

## Appendix

### A. Job details

**Node:** template `CODESYNC01`; live value not captured [Unconfirmed]. The job is listed in the Jenkins view **maintenance** (`view.yaml`, regex `maintenance_.*`).

### B. Code vs live

| Item | `template-maintenance.yaml` (master) | Live stage job |
|---|---|---|
| API host | `https://{fqdn}/api/json` | hard-coded `https://stage-codesync.ajdc.sony.co.jp/api/json` (pre-Cloud-J2 hostname) |
| Shell | `#!/bin/bash -ex` | [Unconfirmed] shebang not captured |
| Node | `CODESYNC01` | [Unconfirmed] not captured |
| `ALL` parameter | bool, default `false`, description *"true if generate list including all jobs, false if generate list including enabled jobs only."* | same behaviour |
| Credential | secret text `jenkins_admin_password` bound to `JENKINS_TOKEN` | [Unconfirmed] binding not captured; presumably the same |
| Archived artifact | `jobs.txt` | `jobs.txt` |
| Managed by JJB? | No. Neither `codesync.ptc.sony.co.jp/` nor `codesync.ptc-stage.sony.co.jp/` has a project that lists these templates. | The live job is not regenerated by `code_sync_deploy_jenkins_jobs`. It was created by hand or by an older deployment that rendered `{fqdn}` as `stage-codesync.ajdc.sony.co.jp`. Changes to the template have no effect until a project entry is added. |

### C. Known risks

[Proposed] From reading the config and the YAML.

| Risk | Detail | Mitigation |
|---|---|---|
| `ALL=true` archives nothing | Output file name mismatch (`enabled_jobs.txt` vs archived `jobs.txt`). The file name also suggests the opposite of what it holds. | Use `ALL` unchecked. Proposed patch: write to `jobs.txt` in both branches, or archive both. |
| Old hostname | Hard-coded `stage-codesync.ajdc.sony.co.jp` in the live job. The `master` template already uses `{fqdn}`, but the template is not deployed. | [Unconfirmed] Verify the host. Fix by adding a project entry for `template-maintenance.yaml` with `fqdn: codesync.ptc-stage.sony.co.jp`, or edit the live job by hand. |
| Not managed by JJB | No project YAML uses `template-maintenance.yaml` | Edits to the template change nothing in Jenkins. Back up the live `config.xml` before editing it in the UI. |
| Redeploy overrides the restored state | `code_sync_deploy_jenkins_jobs` runs `make update`, which writes each JJB-managed job's `disabled` flag from the YAML. On stage it also runs daily (`H H * * *`). | After maintenance, the next deploy run sets JJB-managed jobs to their YAML state regardless of `jobs.txt`. `jobs.txt` matters most for the hours until then and for jobs not managed by JJB. [Proposed] |
| Folders not listed | `.jobs[]` from the top-level API does not descend into folders | Fine as long as CodeSync has no folders [Unconfirmed] |
| Admin password in API calls | Uses the `admin` account and password, not a per-user token | Keep the credential scoped. Rotate it when people leave. |
