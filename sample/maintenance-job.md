# Jenkins Maintenance Jobs (maintenance_*)

> **Scope:** the three jobs form a single maintenance procedure and are documented here as one family. Per-job detail: [store](maintenance-store-jobs.md) · [disable](maintenance-disable-jobs.md) · [enable](maintenance-enable-jobs.md).
> **Job definition:** templates in [`jenkins-jobs/template-maintenance.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/template-maintenance.yaml) (branch `master`). No project YAML uses these templates, so the live jobs are not managed by the deploy job (see Appendix C).
> **Background:** [CodeSync KT reference](../../CodeSync_KT.md)

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `maintenance_store_jobs`, `maintenance_disable_jobs`, `maintenance_enable_jobs` (see Appendix A) |
| **Job URL** | Stage: `https://codesync.ptc-stage.sony.co.jp/job/<job-name>/` (Jenkins view **maintenance**) · Prod: not defined in any `master` YAML; [Unconfirmed] check whether hand-made prod copies exist |
| **Category** | Utility |
| **Vendor / Source** | Internal: Jenkins REST API (`/api/json`, `/job/<name>/disable`, `/job/<name>/enable`) |
| **Component** | The Jenkins instance's job list (every top-level job) |
| **Criticality** | **High** [Proposed]. Disable stops all CodeSync automation with one click; store and enable decide whether the instance comes back exactly as it was. Unused outside a maintenance window. |

## 2. Purpose / Job Description

**What does this job actually do?**

Together, the three jobs let an operator pause all CodeSync automation for Jenkins maintenance and then restore exactly the previous state.

1. **Store** [Live]: snapshots which jobs are currently enabled.
   ```bash
   RESULT=`curl -f -u "admin:$JENKINS_TOKEN" https://stage-codesync.ajdc.sony.co.jp/api/json`
   if [ "true" = "$ALL" ]; then
     echo "$RESULT" | jq -r '.jobs[].url' > enabled_jobs.txt                                   # every job
   else
     echo "$RESULT" | jq -r '.jobs[]' | jq 'select(.color != "disabled")' | jq -r '.url' > jobs.txt   # only enabled jobs
   fi
   ```
   Post-build: archive `jobs.txt`.

2. **Disable** [Live]: disables every top-level job, with no exceptions. That includes all three maintenance jobs and `code_sync_deploy_jenkins_jobs` / `code_sync_test_jenkins_jobs`.
   ```bash
   result=`curl https://stage-codesync.ajdc.sony.co.jp/api/json -u "admin:$JENKINS_TOKEN"`
   urls=`echo $result | jq -r '.jobs[].url'`
   for url in $urls ; do
     curl -X POST -u "admin:$JENKINS_TOKEN" "$url""disable"
   done
   ```

3. **Enable** [Live]: re-enables only the jobs in the list produced by step 1.
   ```bash
   for url in `cat JOB_LIST` ; do
     curl -f -X POST -u "admin:$JENKINS_TOKEN" "$url"enable
   done
   ```

**Why is this job required?**

During Jenkins maintenance (plugin or core upgrade, restart, node or EBS work), no scheduled or triggered build should start, so nothing is interrupted half-way, such as an import mid-push or a mirror mid-sync. Disabling everything is easy, but re-enabling everything would also turn on jobs that are meant to be off (retired syncs, or stage jobs disabled on purpose because stage must not push). The stored list is what makes an exact restore possible.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Manual (all three) |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes (the only way) |
| **When to trigger manually** | During a planned Jenkins maintenance window, in the order given in Appendix B |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None automatic. The `jobs.txt` artifact of store is the `JOB_LIST` input of enable. After enable, scheduled jobs resume on their own timers. |

**Flow:** `maintenance_store_jobs -> maintenance_disable_jobs -> maintenance work -> maintenance_enable_jobs`

## 4. Job Parameters

> **Screenshot:** _add "Build with Parameters" for store and enable, and a sample console of disable_ -> `../images/maintenance-store-jobs-params.png`, `../images/maintenance-enable-jobs-params.png`, `../images/maintenance-disable-jobs-console.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `ALL` (store) | No (boolean, default `false`) | unchecked | Unchecked: list only enabled jobs into `jobs.txt`. Checked: list all jobs into `enabled_jobs.txt`. | **Leave unchecked** | Checked = no usable artifact, because only `jobs.txt` is archived. Restoring from a full list would switch on jobs that are disabled on purpose. |
| `JOB_LIST` (enable) | **Yes** (file upload) | `jobs.txt` containing `https://stage-codesync.ajdc.sony.co.jp/job/code_sync_deploy_jenkins_jobs/` ... | Jobs to enable, one URL per line, ending in `/` | The `jobs.txt` artifact from the store build run **before** the disable | A list taken after the disable is empty, so nothing is re-enabled. A list from another instance means every POST is a 404. |
| `JENKINS_TOKEN` (all three) | Yes (credential) | `jenkins_admin_password` (string) | Admin password for the REST API | Jenkins > Credentials | Store and enable fail with 401 (`curl -f`). Disable **still goes green** (no `-f`). |
| Target host in shell (store, disable) | Yes | `https://stage-codesync.ajdc.sony.co.jp` | Instance whose jobs are listed or disabled | Should be this Jenkins | If the old hostname now points at a different Jenkins, the list belongs to, and the disable acts on, that other instance |

## 5. Expected Output

- **After store:** artifact `jobs.txt`, one URL per line for every top-level job that was enabled. No job changed.
- **After disable:** every top-level job shows *"This project is currently disabled"*. Running builds are not stopped; they finish normally. No new scheduled or SCM/Gerrit-triggered builds start.
- **After enable:** every job in `jobs.txt` is enabled again. Jobs disabled before maintenance are still disabled. Scheduled jobs run at their next timer.

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **Job status:** store: SUCCESS, and `jobs.txt` is archived and non-empty. Disable: SUCCESS proves little; the POST `curl` has no `-f`, so a 401/403/404 on every job still gives a green build. Enable: SUCCESS means every listed job was enabled (`curl -f` with `bash -e`).
- **Expected final stage:** store archives `jobs.txt`; disable and enable print one `curl -X POST` line per job. The URLs in `jobs.txt` must use the host of **this** Jenkins; [Unconfirmed] confirm `stage-codesync.ajdc.sony.co.jp` (pre-Cloud-J2 hostname) still resolves to `codesync.ptc-stage.sony.co.jp`.
- **No unexpected errors in console log:** look for `Error 403`, `No valid crumb`, `401`, `curl: (22)`. On an enable failure, the console shows which URL failed; every job after it in the list is still disabled. [Unconfirmed] Jenkins normally requires a CSRF crumb for POSTs authenticated with a password (API tokens are exempt); test disable and enable on stage before a real window.

### Level 2: Git / Mirror
N/A. Verify through the Jenkins API instead:

```bash
# after store: count must equal wc -l jobs.txt
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq '[.jobs[] | select(.color != "disabled")] | length'

# after disable: expect 0 (same command)

# after enable: enabled set must equal jobs.txt
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq -r '.jobs[] | select(.color != "disabled") | .url' | sort > now.txt
sort jobs.txt | diff - now.txt          # expect no differences
```

### Level 3: Manifest
N/A. Instead: after store, jobs known to be disabled on purpose (for example stage sync jobs) are **absent** from `jobs.txt`; after disable, the Build Queue is empty or only shows disabled items; after enable, jobs disabled on purpose are still grey.

### Level 4: Sync validation
Over the next schedule cycle after enable, the mirror jobs and `monitor_refs_*` run and succeed on their own. This confirms the nodes and credentials survived the maintenance.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** Conditional. Store: yes, but **only before** disable has run; afterwards it produces an empty or near-empty list, so never rerun it mid-maintenance. Disable: yes; disabling an already disabled job is harmless. Enable: yes; enabling an already enabled job is a no-op.

**Before rerun check:**

- [ ] **Was the upstream source available? (`git ls-remote`)** N/A for git. Check that `curl -f -u admin:<token> <host>/api/json` returns JSON and lists **this** instance's jobs. For enable: the job itself is enabled, and Jenkins is healthy (nodes online, credentials present, plugins loaded).
- [ ] **Did the previous build partially push anything?** Store: no, read-only. Disable: count disabled jobs (Level 2); a partial run is fine, rerun to finish. Enable: jobs up to the failed URL are enabled; harmless, rerun the whole list.
- [ ] **Is the Jenkins workspace clean?** Not relevant for any of the three.
- [ ] **Is another CodeSync job running against the same repository?** Instead ask: has disable already run? If yes, do not rerun store; fetch `jobs.txt` from the earlier build. Was store run before the first disable? If not, stop and reconstruct the list from the YAML: on stage, the `disabled: true` entries in `jenkins-jobs/codesync.ptc-stage.sony.co.jp/project-*.yaml` on the `stage` branch (stage deploys from `stage`, not `master`). Jobs not managed by JJB, including the `maintenance_*` jobs, are not in the YAML.
- [ ] **Does anything need rollback or cleanup?** Disable run by mistake: enable `maintenance_enable_jobs` by hand, then run it with the latest `jobs.txt`. Wrong list re-enabled too much: disable the extra jobs by hand, or rerun disable and then enable with the correct file. Listed job no longer exists: remove it from the file.
- [ ] **Has the Qualcomm import script changed?** N/A.
- [ ] **Does the script need adapting to support a new branch or tag from the vendor?** N/A.
- [ ] **Should an obsolete branch be moved aside using the service account before rerunning?** N/A.

**Rerun steps:**

1. **Store:** *Build with Parameters* with `ALL` unchecked, download `jobs.txt`, attach it to the maintenance ticket.
2. **Disable:** *Build Now*, then confirm the Level 2 count is 0.
3. **Enable:** enable the job by hand if needed, *Build with Parameters* with `jobs.txt`, then confirm the Level 2 diff is empty.

---

## Appendix

### A. Instances

| Job | Description (from Jenkins) | Action | Parameters | Node | Credential |
|---|---|---|---|---|---|
| `maintenance_store_jobs` | *"Store jobs. Execute this before execute maintenance_disable_jobs."* | Read-only. Lists enabled job URLs into `jobs.txt` (archived). | `ALL` (boolean, default `false`) | [Unconfirmed] live not captured (template: `CODESYNC01`) | `jenkins_admin_password` (template) |
| `maintenance_disable_jobs` | *"disable all jobs"* | POSTs `disable` to every top-level job | none | none, `canRoam=true` | `jenkins_admin_password` |
| `maintenance_enable_jobs` | *"enable listed jobs. the list is generated by maintenance_store_jobs"* | POSTs `enable` to each URL in the uploaded list | `JOB_LIST` (file) | none, `canRoam=true` | `jenkins_admin_password` |

### B. Maintenance window procedure

```
1. maintenance_store_jobs   (ALL unchecked)  -> download artifact jobs.txt, keep a copy in the ticket
2. Wait for running builds to finish (imports especially). Check the executors are idle.
3. maintenance_disable_jobs                  -> everything disabled (including the maintenance jobs and the deploy job)
4. Do the maintenance
5. Enable maintenance_enable_jobs by hand (job page -> Enable)   <- required, disable also disabled it
6. maintenance_enable_jobs   JOB_LIST = jobs.txt from step 1
7. Check: enabled-job count = line count of jobs.txt
```

Do not merge `code-sync` changes and do not run `make update` while jobs are disabled. The deploy job rewrites the `disabled` flag of every JJB-managed job from the YAML (see Appendix D).

### C. Code vs live

| Item | `template-maintenance.yaml` (master) | Live stage jobs |
|---|---|---|
| API host (store, disable) | `https://{fqdn}/api/json` | hard-coded `https://stage-codesync.ajdc.sony.co.jp/api/json` (pre-Cloud-J2 hostname) |
| Shell | `#!/bin/bash -ex` for all three | enable: same. store, disable: [Unconfirmed] shebang not captured. |
| Node | `CODESYNC01` for all three | disable, enable: none, `canRoam=true`. store: [Unconfirmed] not captured. |
| Credential | secret text `jenkins_admin_password` bound to `JENKINS_TOKEN` | same (store binding not captured) |
| `ALL` (store) | bool, default `false` | same behaviour |
| `JOB_LIST` (enable) | file parameter, description *"enabled jobs before maintenance"* with example URLs | same |
| Managed by JJB? | No. Neither `codesync.ptc.sony.co.jp/` nor `codesync.ptc-stage.sony.co.jp/` has a project that lists these templates. | The live jobs are not regenerated by `code_sync_deploy_jenkins_jobs`. They were created by hand or by an older deployment that rendered `{fqdn}` as `stage-codesync.ajdc.sony.co.jp`. Template changes have no effect until a project entry is added. |

### D. Known risks

[Proposed] From reading the configs and the YAML; no incidents recorded yet.

| Risk | Job | Detail | Mitigation |
|---|---|---|---|
| `ALL=true` archives nothing | store | Output goes to `enabled_jobs.txt`, but only `jobs.txt` is archived. The file name also suggests the opposite of what it holds. | Use `ALL` unchecked. Proposed patch: write to `jobs.txt` in both branches, or archive both. |
| Locks itself out | disable | It also disables `maintenance_enable_jobs`, which then cannot be built | Enable `maintenance_enable_jobs` by hand before step 6, or `curl -X POST -u admin:<token> <host>/job/maintenance_enable_jobs/enable` |
| Silent failure | disable | No `curl -f` on the POST | Always do the Level 2 count check. Proposed patch: add `-f` and exclude the `maintenance_*` jobs. |
| Stops at the first failure | enable | One deleted or renamed job in the list aborts the rest | Remove that line from the file and rerun |
| Old hostname | store, disable (and the URLs fed to enable) | Hard-coded `stage-codesync.ajdc.sony.co.jp` in the live jobs. The `master` template already uses `{fqdn}`, but it is not deployed. | [Unconfirmed] Verify the host. Fix by adding a project entry for `template-maintenance.yaml` with `fqdn: codesync.ptc-stage.sony.co.jp`, or edit the live jobs by hand. If needed, `sed` the URLs in `jobs.txt` to `codesync.ptc-stage.sony.co.jp` before uploading. |
| Not managed by JJB | all | No project YAML uses `template-maintenance.yaml` | Edits to the template change nothing in Jenkins. Back up each live `config.xml` before editing it in the UI. |
| Does not wait for running builds | disable | Disabling does not abort running builds; restarting Jenkins does | Check executors are idle before maintenance. An import killed mid-run must be recovered per [import recovery](../jobs/07-import-qcom-kernel.md#8-recovery--rerun-procedure). |
| Deploy job overrides the enabled/disabled state | disable, enable | `code_sync_deploy_jenkins_jobs` runs `make -C jenkins-jobs update`, which rewrites every JJB-managed job, including its `disabled` flag, from the YAML. Disable also disables the deploy job, so it cannot fire during the window, but enabling it or running `make update` by hand brings JJB-managed jobs back on mid-maintenance. After the window, the next deploy run sets them to their YAML state whatever `jobs.txt` said. Stage: daily timer (`H H * * *`) plus merges to `stage`. Prod: merges to `master` only. | Keep the deploy job disabled and don't merge `code-sync` changes during the window. If a job must stay off permanently, set `disabled: true` in its YAML too. [Proposed] |
| Folders not listed | store, disable | `.jobs[]` from the top-level API does not descend into folders | Fine as long as CodeSync has no folders [Unconfirmed] |
| Admin password in API calls | all | Uses the `admin` account and password, not a per-user token | Keep the credential scoped. Rotate it when people leave. |
