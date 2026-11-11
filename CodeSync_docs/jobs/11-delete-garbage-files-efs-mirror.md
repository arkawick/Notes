# Delete garbage files in EFS mirror

> **Sources:** 📊 PPT slide 29 · 🧭 proposed · ❓ unconfirmed. This job is not in the older checkout.
> **Background:** [CodeSync_KT.md §11.1](../../CodeSync_KT.md#111-delete-garbage-files-in-efs-mirror)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | ❓ *Exact name: copy it from Jenkins* (📊 deck title: "Delete garbage files in EFS mirror") |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/<job-id>/` ❓ |
| **Category** | Cleanup |
| **Vendor / Source** | Internal (mirror storage) |
| **Component** | `/mnt/efs/gitmirror` (all external mirrors) |
| **Criticality** | 🧭 **Normal.** Disk hygiene. If it doesn't run for a while, the mirror disk fills up and mirror/import jobs start failing. |

## 2. Purpose / Job Description

**What does this job actually do?**
📊 It deletes temporary files created by git commands (e.g. leftover `tmp_pack_*`, `*.lock` ❓ exact pattern) under `/mnt/efs/gitmirror` that match a pattern defined in the job **and were last modified more than one day ago**.

**Why is this job required?**
Interrupted `repo sync` / `git fetch` runs leave temporary pack files in the mirror. On huge Chipcode/CLO gits these are large and pile up until the volume is full.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled ❓ |
| **Schedule** | ❓ Read it from *Configure* |
| **Manual Trigger Allowed?** | Yes |
| **When to trigger manually** | Mirror volume close to full (`df -h`); after many interrupted mirror runs |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None |

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters" / Configure showing the file pattern_ → `../images/delete-garbage-files-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| *(file pattern, in the job)* | Yes | ❓ `tmp_*` | Which files count as garbage | Defined in the job YAML. Change it by patch only. | A too-broad pattern **deletes real git objects** and corrupts the mirror |
| *(age, in the job)* | Yes | `> 1 day` | Minimum age | Fixed | A shorter age can delete temp files from a **running** sync |

## 5. Expected Output

- Matching temp files older than one day removed from `/mnt/efs/gitmirror`
- Free space on the mirror volume increased (or stable)
- No `.git` object or pack that is in use is touched

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS**. The log lists the deleted files or a count.

### Level 2: Git / Mirror
```bash
df -h /mnt/efs/gitmirror                     # before/after
find /mnt/efs/gitmirror -name '<pattern>' -mtime +1 | wc -l    # should be 0 after the run
git --git-dir /mnt/efs/gitmirror/<name>/<project>.git fsck --connectivity-only   # spot-check integrity
```

### Level 3: Manifest
N/A

### Level 4: Sync validation
The next scheduled mirror job for each mirror is **SUCCESS**.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** It only deletes files older than one day that match the pattern.

**Before rerun check:** no mirror job has been stuck on the same mirror for more than a day (its temp files would be deleted mid-run). The pattern has not been changed. **Rerun:** *Build Now*.
