# Update Mirror Simple git.codelinaro.org on CHIPCODE_MIRROR

> **Sources:** 📊 PPT slide 15 · 🎙 KT Session 1 · 🧭 proposed · ❓ unconfirmed. This job is **not** in the older code checkout.
> **Background:** [CodeSync_KT.md §7.4](../../CodeSync_KT.md#74-the-codelinaro-exception)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `Update Mirror Simple git.codelinaro.org on CHIPCODE_MIRROR` (📊 display name) |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/<job-id>/` ❓ *job ID not in the checkout. Copy it from Jenkins.* |
| **Category** | Mirror Sync |
| **Vendor / Source** | CodeLinaro (`git.codelinaro.org`), Qualcomm's open-source host |
| **Component** | Local git mirror for CLO content used by Kernel / QSSI / Vendor Techpack imports |
| **Criticality** | 🧭 **High.** Every Qualcomm import references this mirror for its open-source half. Rebuilding it is **undocumented** (see §8). |

## 2. Purpose / Job Description

**What does this job actually do?**
📊 It goes to the existing mirror path, runs `repo sync`, and cleans up temporary files older than one day. **It does not run `repo init`.** Quoting the deck: *"Here repo initialization will be handling manually."*

**Why is this job required?**
Qualcomm imports download the open-source part of each release from CodeLinaro. With `PSEUDO_MIRROR_TREE` enabled, the import references this mirror so it only fetches the delta (🎙). If the mirror is stale, imports still work but take much longer.

> ❓ **Why is `repo init` manual for this mirror only?** 🎙 *"We still don't know the reason why they do the repo init manually only for the codelinaro side."* Neither the outgoing owner nor Yamanouchi-san knows. The practice was inherited.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled ❓ (assumed, like the other mirror jobs) |
| **Schedule** | ❓ Read it from the job's *Configure* page |
| **Manual Trigger Allowed?** | Yes |
| **When to trigger manually** | Before a Qualcomm import if CLO content has moved; after a failed scheduled run; after someone **manually** re-inits the mirror with new gits |
| **Triggered by another job?** | None known |
| **Downstream Jobs** | None formally. `Import_Qcom_*` jobs reference it at runtime. |

**Flow:** `git.codelinaro.org → (manual repo init, once) → Update Mirror Simple → (referenced by) Import_Qcom_*`

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters"_ → `../images/update-mirror-clo-params.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `MIRROR_NAME` | Yes (defaulted) | `git.codelinaro.org` | Directory name under `MIRROR_ROOT` | Job default | Syncs a non-existent or wrong directory. `repo sync` fails with "not a repo client". |
| `MIRROR_ROOT` | Yes (defaulted) | `/mnt/efs/gitmirror` | Mirror parent directory | Job default | Same as above |
| `REPO_SYNC_ARGS` | Yes (defaulted) | `-j12` | Arguments passed to `repo sync` | Job default | Too high `-j` gets throttled by CLO |

## 5. Expected Output

- `/mnt/efs/gitmirror/git.codelinaro.org/` updated with the latest CLO commits and tags for every project in the **manually initialised** manifest
- Temporary files older than one day removed
- No change to the mirror's manifest or project list (only a manual `repo init` changes that)

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- Status **SUCCESS**. Console shows `repo sync` completing.
- 🎙 Expect occasional transient fetch errors on very large gits. Treat the same git failing repeatedly as a real problem.

### Level 2: Git / Mirror
```bash
cd /mnt/efs/gitmirror/git.codelinaro.org
git --git-dir .repo/manifests.git config --get remote.origin.url   # RECORD THIS (needed for any rebuild)
git --git-dir .repo/manifests.git branch -a                        # RECORD the manifest branch
repo list | wc -l
git ls-remote https://git.codelinaro.org/<project> refs/tags/<latest AU tag>
git --git-dir <project>.git show-ref <latest AU tag>              # should exist after sync
```

### Level 3: Manifest
Check that the new release's CLO projects and tags are present. Use the same AU tag you will import (`list_manifest_tags`, [10](10-list-manifest-tags.md), shows the CLO side).

### Level 4: Sync validation
After the next import with `PSEUDO_MIRROR_TREE` enabled, `git_start.html` should show the workspace pseudo-mirror path, and the `syncsnap` stage should take noticeably less time than a run without the mirror.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ recurring | Fetch errors (`invalid pack`, socket, 503) | Network, very large gits (🎙 transient) | Console. Different git each run. | Wait for the next run or retrigger | ❓ owed (KT §16.1 #1) | — |
| ❓ | New release gits are not mirrored | Mirror was manually initialised with an older manifest. The job never re-inits. | Project missing under the mirror path | Manual `repo init` with the newer manifest, then rerun (❓ exact command unknown) | ❓ | 🧭 **Document the manual `repo init` command** (owed, KT §16.2 #1) |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes**, as long as the manually-initialised `.repo` is intact. **Never delete `.repo` in this mirror.** The job cannot recreate it.

**Before rerun check:**

| Check | How |
|---|---|
| Was the upstream source available? | `git ls-remote https://git.codelinaro.org/<failing-project>` |
| Did the previous build partially push anything? | N/A. Fetch only. |
| Is the Jenkins workspace clean? | Not relevant. Check for stale `*.lock` files in the mirror if the previous run was killed. |
| Is another CodeSync job running against the same repository? | Make sure no other build of this job is running |
| Does anything need rollback or cleanup? | No |
| Has the Qualcomm import script changed? / Does the script need adapting for a new branch or tag? | If a new release uses a new CLO manifest branch or path (public ↔ private), the mirror needs a **manual re-init**. Also check the mirror path in the import script ([KT §15.3](../../CodeSync_KT.md#153-a-release-moves-from-public-to-private-or-back)). |
| Should an obsolete branch be moved aside? | N/A |

**Rerun steps:**
1. Transient error: *Build Now*.
2. Missing gits or new manifest: the `repo init` must be done **manually on the node** (❓ procedure undocumented). Escalate to the outgoing owner or Yamanouchi-san, record the exact command, and add it to this section.
