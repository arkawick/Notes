# monitor_refs_* (Monitor refs)

> **Sources:** ⚙️ live `config.xml` of `monitor_refs_aosp-platform-manifest` (prod, provided 2026-11-12) · ✅ `jenkins-jobs/template-notification.yaml` (older checkout, used for comparison) · 🧭 proposed · ❓ unconfirmed
> **Scope:** this page is written from the **aosp platform-manifest** instance. Other `monitor_refs_*` instances use the same template. Only instances whose job name contains `platform-manifest` trigger a downstream job (see §2).

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `monitor_refs_aosp-platform-manifest` (display: *Monitor refs - aosp platform-manifest*). Template: `monitor_refs_{name}-{repo-name}`. ❓ List the other live instances from Jenkins. The older checkout had partner-android ones (`platform-manifest`, `pdk-*-manifest`, `platform-vendor-widevine`, `platform-system-libfmq`) and `monitor_refs_private-caf_*`. |
| **Job URL** | `https://codesync.ptc.sony.co.jp/job/monitor_refs_aosp-platform-manifest/` |
| **Category** | Utility (ref monitoring / notification / trigger) |
| **Vendor / Source** | AOSP, read through Sony's AOSP mirror host: `https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` ⚙️ |
| **Component** | `platform/manifest` (AOSP) |
| **Criticality** | 🧭 **High.** It is the **automatic trigger for `sync_manifest_oss_tag`** whenever a new AOSP `android-*` tag appears. If it silently stops working, new AOSP releases are not synced and nobody is told (see §6 Level 1). |

**Node:** ⚙️ `prod-codesync`. (The KT sessions said `prod-code-sync`. ❓ Check which label is correct. They may be a label and a node name.)

## 2. Purpose / Job Description

**What does this job actually do?**
⚙️ Once a day it takes a snapshot of every branch and tag on the monitored git and compares it with the previous snapshot:

1. **Credentials setup.** Rebuilds `$HOME/.netrc` from the Jenkins credential bound to `NETRC_CS_FILE`. Removes the `insteadOf` rewrite (`ssh://jp21771@git-lb-jdc.ptc.sony.co.jp:29418/` → `https://android.googlesource.com/`) from `/home/code-sync/.gitrc/review.conf`, and sets global git `user.name`/`user.email` to `jp21771`.
2. **Copy the previous snapshot.** Takes `result-dir/refs.txt` from the **last successful** build of this job into `.previous/`.
3. **Snapshot.** `git ls-remote -t -h <URL> > result-dir/refs.txt`
4. **Diff.**
   - `diff.txt` = every changed `refs/heads` / `refs/tags` line (added `>` and removed `<`)
   - `new-android-tags.txt` = only **added** `refs/tags/android*` lines
5. **Email.** If `diff.txt` is non-empty, it writes `result-dir/email-body.txt`. The email-ext publisher sends it to `somc-cm@sony.com` with the subject `[Ref Monitor] Change(s) detected in aosp platform/manifest`, from `Code Sync <noreply-codesync-j2cm@sony.com>`. If nothing changed, it writes `result-dir/no-changes`, and a pre-send script **cancels** the email.
6. **Trigger the sync** (only if `$JOB_NAME` contains `platform-manifest`). For each new tag (peeled `^{}` lines removed), it runs `curl --netrc -f -d "" ${JENKINS_URL}job/sync_manifest_oss_tag/buildWithParameters?TAG=<tag>`.

The standard Mailer also mails `sec-mc-sw-cm-codesync@sony.com`. That publisher fires on **failed / unstable / back-to-normal** builds, so it is the CodeSync team's failure alert.

**Why is this job required?**
New AOSP release tags must reach Sony's review server. This job detects them and kicks off `sync_manifest_oss_tag` per tag. It also sends CM a daily change notice for the monitored git.

**Changes since the older checkout** (✅ vs ⚙️), useful if you compare against old notes:

| | Older checkout | Live |
|---|---|---|
| Schedule | `H * * * *` (hourly) | `H H * * *` (**daily**) |
| Source | `{source-gerrit}/{repo}` via proxy | `https://aosp-mirror.ptc.sony.co.jp:8443/…`, no proxy lines |
| Mail | `s-nail` via `mrelay.ptc.sony.co.jp` inside the shell | email-ext publisher with a pre-send cancel |
| Trigger URL | hard-coded `android-ci-cm.swtools.sonymobile.net` | `${JENKINS_URL}` + `--netrc` auth |

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled |
| **Schedule** | ⚙️ `H H * * *` (once a day at a hashed time) |
| **Manual Trigger Allowed?** | Yes (no parameters) |
| **When to trigger manually** | An AOSP release was announced and you don't want to wait for the daily run; the previous run failed; after fixing the downstream job |
| **Triggered by another job?** | No |
| **Downstream Jobs** | **`sync_manifest_oss_tag`** (one build per new `android-*` tag, parameter `TAG`) ❓ *not yet documented here. Paste its config.xml to add it.* |

**Flow:**
```
AOSP ─► aosp-mirror.ptc.sony.co.jp:8443 ─► monitor_refs_aosp-platform-manifest (daily ls-remote + diff)
                                               ├─► email to somc-cm@sony.com (only if changes)
                                               └─► sync_manifest_oss_tag?TAG=android-… (per new tag)
```

## 4. Job Parameters

> 📷 **Screenshot:** _no build parameters. Add a sample build page showing the `result-dir` artifacts_ → `../images/monitor-refs-build.png`

The job has **no build parameters**. Its behaviour is set by:

| Setting | Mandatory? | Value (⚙️) | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| Monitored URL (in shell) | Yes | `https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` | Git whose refs are snapshotted | YAML `source-gerrit` + `repo` | Monitors the wrong git, so tags are missed |
| Job name contains `platform-manifest` | — | yes | Turns on the downstream trigger | Job naming | A rename turns off the sync trigger **silently** |
| `NETRC_CS_FILE` | Yes | credential `3046b660-f7ae-4137-b118-90f83b608625` (file) | `.netrc` for git and for the Jenkins `buildWithParameters` call | Jenkins → Credentials | Expired credential: the `ls-remote` fails (silently, see §6) or the trigger curl fails |
| `CODESYNC_SUBJECT` (EnvInject) | — | `[Ref Monitor] Change(s) detected in aosp platform/manifest` | Email subject | YAML | — |
| Recipients | — | email-ext: `somc-cm@sony.com`. Mailer: `sec-mc-sw-cm-codesync@sony.com`. | Change notice / failure alert | YAML | People are not told |
| Log rotation | — | 180 days / 50 builds | Build history | YAML | ⚠️ The baseline comes from the last successful build, so it survives rotation unless every kept build fails |

## 5. Expected Output

- `result-dir/refs.txt`: a full, **non-empty** snapshot of heads and tags (the baseline for the next run)
- When something changed: `result-dir/email-body.txt`, an email to `somc-cm@sony.com`, and for each new `android-*` tag a queued `sync_manifest_oss_tag` build with `TAG=<tag>`
- When nothing changed: `result-dir/no-changes`, and no email (the console shows `[Pre-send Script] Found 'no-changes' file. Canceling email notification.`)

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- Status **SUCCESS**
- ⚠️ **SUCCESS alone does not prove the job worked.** The snapshot step runs under `bash -x` (not `-e`). If `git ls-remote` fails (auth, network, mirror host down), `refs.txt` is empty, gets deleted, and the step exits 0. The next step then writes `no-changes`, and the build is **green with no email and no trigger**. **Always check that `result-dir/refs.txt` exists in the artifacts and is non-empty.**
- Console: `git ls-remote` printed no `fatal:` / `401` / `Could not resolve host`
- If new tags were found: one `curl … buildWithParameters?TAG=…` line per tag, with no `curl: (22)` error

### Level 2: Git / Mirror
```bash
# snapshot is current
git ls-remote -t -h https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest | wc -l   # ≈ line count of result-dir/refs.txt
# a newly reported tag really exists upstream
git ls-remote https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest refs/tags/<new-tag>
```

### Level 3: Manifest
For each tag listed in the email or console, there should be a `sync_manifest_oss_tag` build with that `TAG`, and it should succeed. ❓ The exact target ref on review depends on that job. Document it when its config is added.

### Level 4: Sync validation
Done by `sync_manifest_oss_tag`. Validate there.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| | | | | | | |

**Known risks to watch** (🧭 from reading the config, not incidents yet):

| Risk | Detail | Mitigation |
|---|---|---|
| Silent green on `ls-remote` failure | See §6 Level 1 | Check that `refs.txt` exists. 🧭 Propose a patch: `exit 1` when `refs.txt` is empty. |
| Re-trigger after a failed run | If a trigger `curl` fails mid-loop, the build fails. The next run diffs against the **last successful** snapshot, so it re-triggers **all** of those tags, including ones already triggered. | Make sure `sync_manifest_oss_tag` is safe to repeat for the same tag (❓ confirm) |
| Shared `$HOME/.netrc` rewritten every run | Steps 1 and 3 delete and recreate `/home/code-sync/.netrc`, which other jobs on the same node may be reading at that moment | ❓ Check whether other jobs depend on `$HOME/.netrc` |
| Leftover first step | Step 1 runs `cat $NETRC_FILE` / `cat $NETRC_JK_FILE`, but only `NETRC_CS_FILE` is bound, so `cat` falls back to stdin. It is harmless only because step 3 rewrites `.netrc`. | Clean up in a future patch |
| Modifies a shared git config | Step 2 edits `/home/code-sync/.gitrc/review.conf` and **global** git identity on every run | Be aware when debugging `insteadOf` behaviour of other jobs |
| Renaming the job | The trigger depends on `platform-manifest` being in `$JOB_NAME` | Keep the name |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes, with one caveat.** The job is read-only towards git. But a rerun after a failed build re-triggers `sync_manifest_oss_tag` for every new tag since the last **successful** run.

**Before rerun check:**

| Check | How |
|---|---|
| Was the upstream source available? | `git ls-remote -t -h https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` from the node (as `code-sync`, with the job's `.netrc`) |
| Did the previous build partially push anything? | It doesn't push. Check whether it **partially triggered** `sync_manifest_oss_tag`: compare the console's `curl` lines with that job's queue and history. |
| Is the Jenkins workspace clean? | Not required. `result-dir`, `diff.txt` and `new-android-tags.txt` are reset every run. |
| Is another CodeSync job running against the same repository? | A `sync_manifest_oss_tag` build is still running for the same tag → let it finish first |
| Does anything need rollback or cleanup? | Duplicate `sync_manifest_oss_tag` builds queued for the same tag can be cancelled from the queue |
| Has the source changed? | The mirror host or port changed, or the credential rotated → fix through the YAML patch or the Jenkins credential |
| Should an obsolete branch be moved aside? | N/A |

**Rerun steps:**
1. *Build Now*.
2. Check that `result-dir/refs.txt` is non-empty.
3. Match the new tags against the `sync_manifest_oss_tag` builds.

**Force a re-detection of a missed tag:** trigger `sync_manifest_oss_tag` manually with `TAG=<tag>`. That is easier than tampering with the baseline `refs.txt`.
