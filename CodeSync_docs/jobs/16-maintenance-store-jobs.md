# maintenance_store_jobs

> **Sources:** ⚙️ live Stage job config (provided 2026-11-12: description, shell and post-build settings copied from the UI. The full `config.xml` did not render. Parameter definition and node not captured.) · 🧭 proposed · ❓ unconfirmed
> **Part of the maintenance set:** **16 store** → [17 disable](17-maintenance-disable-jobs.md) → *maintenance* → [18 enable](18-maintenance-enable-jobs.md)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `maintenance_store_jobs` |
| **Job URL** | Stage: `https://codesync.ptc-stage.sony.co.jp/job/maintenance_store_jobs/` · Prod: ❓ *check whether a prod copy exists* |
| **Category** | Utility (Jenkins maintenance) |
| **Vendor / Source** | Internal: Jenkins REST API |
| **Component** | The Jenkins instance's job list |
| **Criticality** | 🧭 **High during a maintenance window.** Without a correct list, you cannot restore exactly the jobs that were enabled before. Otherwise unused. |

## 2. Purpose / Job Description

**What does this job actually do?**
⚙️ *"Store jobs. Execute this before execute maintenance_disable_jobs."*
```bash
RESULT=`curl -f -u "admin:$JENKINS_TOKEN" https://stage-codesync.ajdc.sony.co.jp/api/json`
if [ "true" = "$ALL" ]; then
  echo "$RESULT" | jq -r '.jobs[].url' > enabled_jobs.txt                                   # every job
else
  echo "$RESULT" | jq -r '.jobs[]' | jq 'select(.color != "disabled")' | jq -r '.url' > jobs.txt   # only enabled jobs
fi
```
Post-build: **archive `jobs.txt`**.

The result is a list of job URLs (one per line) that were **enabled** before maintenance. You feed it into `maintenance_enable_jobs` afterwards, so jobs that were deliberately disabled **stay disabled**.

**Why is this job required?**
`maintenance_disable_jobs` disables **everything**. Without a snapshot of what was enabled beforehand, re-enabling would also turn on jobs that are meant to be off (for example retired syncs, or stage jobs disabled on purpose because stage must not push).

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Manual |
| **Schedule** | None |
| **Manual Trigger Allowed?** | Yes (the only way) |
| **When to trigger manually** | **First step** of a planned Jenkins maintenance (plugin or core upgrade, node or EBS work, restart) |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None automatic. Its `jobs.txt` artifact is the input (`JOB_LIST`) for [18 maintenance_enable_jobs](18-maintenance-enable-jobs.md). |

**Maintenance window procedure:**
```
1. maintenance_store_jobs   (ALL unchecked)  → download artifact jobs.txt, keep a copy in the ticket
2. Wait for running builds to finish (imports especially). Check the executors are idle.
3. maintenance_disable_jobs                  → everything disabled (including the maintenance jobs and the deploy job)
4. Do the maintenance
5. Re-enable maintenance_enable_jobs by hand (UI → Enable)      ← required, see page 17
6. maintenance_enable_jobs   JOB_LIST = jobs.txt from step 1
7. Check: enabled-job count = line count of jobs.txt
```

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters"_ → `../images/maintenance-store-jobs-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `ALL` | No ❓ (boolean presumed. Definition not captured.) | ☐ unchecked | Unchecked: list only **enabled** jobs into `jobs.txt`. Checked: list **all** jobs into `enabled_jobs.txt`. | **Leave unchecked** for the maintenance procedure | ⚠️ **Checked = no usable artifact.** The output goes to `enabled_jobs.txt`, but only `jobs.txt` is archived. If you then restored from the full list, disabled-on-purpose jobs would be switched on. |
| `JENKINS_TOKEN` | (credential) | ❓ presumably `jenkins_admin_password`, as on pages 17/18 | Admin auth for the REST API | Jenkins → Credentials | 401 means the job fails (`curl -f`) |

## 5. Expected Output

- Artifact **`jobs.txt`**: one URL per line, for every top-level job that was **not disabled** at that moment
- No change to any job

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS**. The artifact `jobs.txt` is present and **non-empty**.
- ⚠️ Check that the URLs in `jobs.txt` use the host of **this** Jenkins. The script queries `https://stage-codesync.ajdc.sony.co.jp`, which is the pre-Cloud-J2 hostname. ❓ Confirm it still resolves to the current stage Jenkins (`codesync.ptc-stage.sony.co.jp`). If it points anywhere else, the list belongs to a **different instance**.

### Level 2: Git / Mirror
N/A. Instead, cross-check the count against the Jenkins API:
```bash
curl -s -u admin:<token> https://codesync.ptc-stage.sony.co.jp/api/json \
  | jq '[.jobs[] | select(.color != "disabled")] | length'        # == wc -l jobs.txt
```

### Level 3: Manifest
N/A. Spot-check that jobs known to be disabled on purpose (e.g. stage sync jobs) are **absent** from `jobs.txt`.

### Level 4: Sync validation
N/A

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

**Known risks** (🧭 from reading the config):

| Risk | Detail | Mitigation |
|---|---|---|
| `ALL=true` archives nothing | Output file name mismatch (`enabled_jobs.txt` vs archived `jobs.txt`). The file name also suggests the opposite of what it holds. | Use `ALL` unchecked. 🧭 Patch: write to `jobs.txt` in both branches, or archive both. |
| Old hostname | Hard-coded `stage-codesync.ajdc.sony.co.jp` | ❓ Verify. Patch to `${JENKINS_URL}api/json`. |
| Folders not listed | `.jobs[]` from the top-level API does not descend into folders | Fine as long as CodeSync has no folders ❓ |
| Admin password in API calls | Uses the `admin` account and password, not a per-user token | Keep the credential scoped. Rotate it when people leave. |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes, but only before running `maintenance_disable_jobs`.** It is read-only. **Running it after disable produces an empty or near-empty list.** Never rerun it mid-maintenance. Use the artifact from the run before the disable.

**Before rerun check:**

| Check | How |
|---|---|
| Was the source available? | `curl -f -u admin:<token> <host>/api/json` returns JSON |
| Did a previous build partially do anything? | No (read-only) |
| Is the Jenkins workspace clean? | Not relevant. The file is overwritten each run. |
| Is another maintenance run in progress? | **Has `maintenance_disable_jobs` already run?** If yes, **do not** rerun this job. Fetch `jobs.txt` from the earlier build. |
| Does anything need rollback? | No |

**Rerun steps:** *Build with Parameters* → `ALL` ☐ → download `jobs.txt` → attach it to the maintenance ticket.
