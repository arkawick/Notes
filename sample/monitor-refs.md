# monitor_refs_aosp-platform-manifest (Monitor refs)

> **Scope:** the only `monitor_refs_*` job on prod. Stage has the same job plus five partner-android instances, all disabled (see Appendix A).
> **Job definition:** [`jenkins-jobs/codesync.ptc.sony.co.jp/project-aosp.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/codesync.ptc.sony.co.jp/project-aosp.yaml) line 11, using template `monitor_refs_{name}-{repo-name}` in [`jenkins-jobs/template-notification.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/template-notification.yaml) (branch `master`).
> **Background:** [CodeSync KT reference](../../CodeSync_KT.md)

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `monitor_refs_aosp-platform-manifest` (display name: *Monitor refs - aosp platform-manifest*) |
| **Job URL** | `https://codesync.ptc.sony.co.jp/job/monitor_refs_aosp-platform-manifest/` |
| **Category** | Utility |
| **Vendor / Source** | AOSP, read through Sony's AOSP mirror host `https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` |
| **Component** | `platform/manifest` (AOSP) |
| **Criticality** | **High** [Proposed]. It is the only automatic trigger for `sync_manifest_oss_tag`, which brings each new AOSP `android-*` release tag into `review.ptc.sony.co.jp`. If it stops working, new AOSP releases are not synced, and in most failure modes nobody is told (see Appendix E). |

## 2. Purpose / Job Description

**What does this job actually do?**

Once a day it takes a snapshot of every branch and tag on the AOSP `platform/manifest` git and compares it with the snapshot from the previous successful run. The build steps, in order:

| # | Step (JJB source) | What it does |
|---|---|---|
| 1 | Shell, `set-netrc-file` (`macros.yaml`) | Deletes `$HOME/.netrc` and rebuilds it from `$NETRC_FILE` and `$NETRC_JK_FILE`. Neither variable is bound in this job, so both `cat` commands read empty stdin (console shows a bare `+ cat`). Leftover; the real `.netrc` is written in step 3. |
| 2 | Shell, `prepare-gitconfig-oss` | Removes the `insteadOf` rewrite (`ssh://jp21771@git-lb-jdc.ptc.sony.co.jp:29418/` to `https://android.googlesource.com/`) from `/home/code-sync/.gitrc/review.conf`, and sets the **global** git `user.name` / `user.email` to `jp21771` / `jp21771@sony.com`. |
| 3 | Shell, `prepare-netrc-file` | Deletes `$HOME/.netrc` again and writes it from the bound credential `NETRC_CS_FILE`, then `chmod og-rw`. |
| 4 | Copy Artifact | Copies `result-dir/refs.txt` from the **last successful** build of this same job into `.previous/` (flattened, optional, so the first ever run does not fail). |
| 5 | Shell (`bash -x`) | Resets `result-dir/`, `diff.txt`, `new-android-tags.txt`. Runs `git ls-remote -t -h https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest > result-dir/refs.txt`. If the result is empty, deletes it and exits. If there is no previous snapshot, exits. Otherwise writes `diff.txt` (every added `>` or removed `<` line under `refs/heads` or `refs/tags`) and `new-android-tags.txt` (only **added** `refs/tags/android*` lines). |
| 6 | Shell (`bash -ex`) | If `diff.txt` is non-empty, writes `result-dir/email-body.txt` (*"The following changes have been detected in aosp's (https://aosp-mirror.ptc.sony.co.jp:8443 platform/manifest)."* followed by the diff). Otherwise creates `result-dir/no-changes`. |
| 7 | Shell (`bash -ex`) | Only if `$JOB_NAME` contains `platform-manifest` and `new-android-tags.txt` is non-empty: strips peeled `^{}` lines, extracts tag names into `tags.txt`, and for each tag runs `curl --netrc -f -d "" ${JENKINS_URL}job/sync_manifest_oss_tag/buildWithParameters?TAG=<tag>`. |

After the build, it archives `result-dir/**/*`, mails failures to `sec-mc-sw-cm-codesync@sony.com`, and sends a change notice to `somc-cm@sony.com` (currently blocked, see section 7). Publisher details are in Appendix B.

**Why is this job required?**

New AOSP release tags must reach Sony's review server. This job detects them and starts `sync_manifest_oss_tag` once per new tag. It also sends CM (`somc-cm@sony.com`) a change notice whenever branches or tags on the AOSP manifest change.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Scheduled (`Started by timer`, runs as `SYSTEM`) |
| **Schedule** | `H H * * *`: once a day at a time hashed from the job name |
| **Manual Trigger Allowed?** | Yes. The job has no parameters; use *Build Now*. |
| **When to trigger manually** | An AOSP release was announced and you don't want to wait for the daily run; the previous run failed; after fixing the credential, the mirror host or the downstream job |
| **Triggered by another job?** | No |
| **Downstream Jobs** | `sync_manifest_oss_tag`, one build per new `android-*` tag, with parameter `TAG=<tag>`. Defined in the same `project-aosp.yaml` (project `oss-tag`, lines 61-76): `PUSH_MODE=tag`, no timer, node `prod-codesync`. |

**Flow:** `aosp-mirror.ptc.sony.co.jp:8443/platform/manifest -> monitor_refs_aosp-platform-manifest -> sync_manifest_oss_tag (TAG=<tag>) -> review.ptc.sony.co.jp`

## 4. Job Parameters

> **Screenshot:** _the job has no build parameters; the rows below are the job settings that control it. Add a sample build page showing the `result-dir` artifacts_ -> `../images/monitor-refs-build.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| `source-gerrit` + `repo` | Yes | `https://aosp-mirror.ptc.sony.co.jp:8443` + `platform/manifest` | Git whose refs are snapshotted | `project-aosp.yaml` lines 7 and 13 | Monitors the wrong git, so new tags are missed |
| `repo-name` | Yes | `platform-manifest` | Becomes part of the job name. The trigger in step 7 only runs when the job name contains `platform-manifest`. | `project-aosp.yaml` line 12 | Any rename silently turns off the downstream trigger |
| `NETRC_CS_FILE` | Yes | file credential `3046b660-f7ae-4137-b118-90f83b608625` (wrapper `cm-account-netrc-credentials`) | `.netrc` used by `git ls-remote` and by the `buildWithParameters` call | Jenkins > Credentials | Expired or wrong: `ls-remote` fails silently (green build, no detection), or the trigger `curl` fails |
| `CODESYNC_SUBJECT` (EnvInject) | No | `[Ref Monitor] Change(s) detected in aosp platform/manifest` | Email subject | Template, from `{name}` and `{repo}` | Cosmetic |
| `monitor-recipients` | No | `somc-cm@sony.com` | Change-notice recipients | `project-aosp.yaml` line 8 | CM is not told about changes |
| `monitor-sendor` | No | `Code Sync <noreply-codesync-j2cm@sony.com>` | Sender address | `project-aosp.yaml` line 14 | Mail may be rejected by the relay |
| `recipients` | No | `sec-mc-sw-cm-codesync@sony.com` | Failure alert recipients (Mailer) | `template-sync-defaults.yaml` | The CodeSync team is not told about failed builds |
| `build-node` | Yes | `prod-codesync` | Where the job runs | `project-aosp.yaml` line 6 | The job queues forever or runs without the `code-sync` home and credentials |
| Log rotation | No | 180 days / 50 builds; artifacts kept as long as the build | Build history | `template-sync-defaults.yaml` | The baseline comes from the last successful build, so it is lost only if all 50 kept builds fail |

## 5. Expected Output

- **`result-dir/refs.txt`** (archived): a full, non-empty list of every `refs/heads/*` and `refs/tags/*` on the AOSP manifest git. This is the baseline for the next run.
- **When something changed:** `result-dir/email-body.txt` (archived) containing the diff, and an email to `somc-cm@sony.com` (currently not delivered, see section 7).
- **For each new `android-*` tag:** one queued `sync_manifest_oss_tag` build with `TAG=<tag>`. That build then pushes the tag to every project on `git://review.ptc.sony.co.jp`.
- **When nothing changed:** `result-dir/no-changes` (archived) and no email.
- Nothing is pushed by this job itself. The only side effects on the node are the rewritten `/home/code-sync/.netrc`, `/home/code-sync/.gitrc/review.conf` and the global git identity.

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **Job status:** SUCCESS, and the archived `result-dir/refs.txt` exists and is non-empty. SUCCESS alone does not prove the job worked: step 5 runs without `-e`, so a failed `git ls-remote` still gives a green build with no detection and no trigger; and an email failure does not fail the build.
- **Expected final stage:** `Archiving artifacts`, then the email-ext publisher, then `Finished: SUCCESS`.
- **No unexpected errors in console log:** `Copied 1 artifact from "Monitor refs - aosp platform-manifest" build number <N>` is present; after `+ git ls-remote -t -h ...` there is no `fatal:`, `401`, `403` or `Could not resolve host`; for each new tag there is one `curl ... buildWithParameters?TAG=...` line with no `curl: (22)`; the email publisher prints `[Pre-send Script] ...`, not `RejectedAccessException`.

### Level 2: Git / Mirror
```bash
# run on prod-codesync as code-sync, with the job's .netrc in place
# the snapshot is current: counts should match
git ls-remote -t -h https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest | wc -l
curl -sn https://codesync.ptc.sony.co.jp/job/monitor_refs_aosp-platform-manifest/lastSuccessfulBuild/artifact/result-dir/refs.txt | wc -l

# a newly reported tag really exists on the mirror
git ls-remote https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest refs/tags/<new-tag>
```

### Level 3: Manifest
For each new tag, a `sync_manifest_oss_tag` build with that `TAG` exists and succeeded, and the tag is on the review server: `git ls-remote git://review.ptc.sony.co.jp/platform/manifest refs/tags/<new-tag>`. The tag push mode in `ohd.sh` also pushes the manifest branch as `refs/heads/oss/<new-tag>`.

### Level 4: Sync validation
```bash
repo init -u git://review.ptc.sony.co.jp/platform/manifest -b refs/tags/<new-tag> --groups=all
repo sync -d -c -j8
```
Confirm a downstream workspace can use the imported code. The downstream job runs the same check at its end.

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| Build #213 (date not in console) | Changes detected (`diff.txt` non-empty) but no email reached `somc-cm@sony.com`. Console: `Pre-send script tried to access secured objects: Scripts not permitted to use method hudson.FilePath exists` followed by `ERROR: Unexpected error while sending email.` Build still **SUCCESS**. | The email-ext pre-send Groovy script runs in the script-security sandbox, and the method `hudson.FilePath exists` has not been approved. The exception aborts the send. | Console of the build, after `Sending email for trigger: Always` | Open. A Jenkins admin approves the signature under *Manage Jenkins > In-process Script Approval*, then rerun. Alternative: replace the pre-send script with a check that needs no approval. [Unconfirmed] When this started; likely since the pre-send script was added. | [Unconfirmed] | Check the console for `RejectedAccessException` after every Jenkins or plugin upgrade |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** Conditional. The job never pushes to git, so a rerun cannot damage anything. But a rerun after a failed build re-triggers `sync_manifest_oss_tag` for every new tag since the last successful run.

**Before rerun check:**

- [ ] **Was the upstream source available? (`git ls-remote`)** Run `git ls-remote -t -h https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest | head` on `prod-codesync` as `code-sync`. It must list refs, not an error.
- [ ] **Did the previous build partially push anything?** It does not push. Check whether it partially **triggered** `sync_manifest_oss_tag`: compare the `curl ... TAG=` lines in its console with that job's queue and build history.
- [ ] **Is the Jenkins workspace clean?** Not required. Step 5 resets `result-dir/`, `diff.txt` and `new-android-tags.txt` on every run.
- [ ] **Is another CodeSync job running against the same repository?** If a `sync_manifest_oss_tag` build is running for a tag that the rerun will trigger again, let it finish first.
- [ ] **Does anything need rollback or cleanup?** No rollback. Cancel duplicate `sync_manifest_oss_tag` builds for the same tag from the queue if needed.
- [ ] **Has the Qualcomm import script changed?** N/A. Instead check whether the mirror host or port, or the `NETRC_CS_FILE` credential, has changed. Fix in `project-aosp.yaml` (deployed by `code_sync_deploy_jenkins_jobs`) or in Jenkins > Credentials.
- [ ] **Does the script need adapting to support a new branch or tag from the vendor?** Only if AOSP changes its release tag naming away from `android*` (the filter in step 5).
- [ ] **Should an obsolete branch be moved aside using the service account before rerunning?** N/A.

**Rerun steps:**

1. Click *Build Now*.
2. Check that `result-dir/refs.txt` is archived and non-empty.
3. Check the console for `RejectedAccessException`. If present, the email was not sent; read `result-dir/email-body.txt` instead.
4. Match the new tags in the console against the `sync_manifest_oss_tag` builds.

---

## Appendix

### A. Job details and instances

**Job description in Jenkins:** *"Checks for new refs on aosp. - URL: "https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest""* (managed by Jenkins Job Builder; do not edit in the UI).

**Node:** `prod-codesync` (node label `CODESYNC`), `canRoam=false`. Workspace: `/home/code-sync/workspace/monitor_refs_aosp-platform-manifest`. Confirmed by the console of build #213: *"Building remotely on prod-codesync (CODESYNC)"*.

**Instances defined in the `master` branch:**

| Instance | Jenkins | Monitored git | State |
|---|---|---|---|
| `monitor_refs_aosp-platform-manifest` | prod | `aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` | **enabled** |
| `monitor_refs_aosp-platform-manifest` | stage | same | disabled (`project-aosp.yaml`, `disabled: true`, node `stage-codesync`) |
| `monitor_refs_partner-platform-manifest`, `-pdk-mini_armv7a_neon-manifest`, `-pdk-mini_arm64-manifest`, `-pdk-generic-fs-manifest`, `-platform-vendor-widevine`, `-platform-system-libfmq` | stage only | `partner-android.googlesource.com/...` | disabled (`project-partner.yaml`, `disabled: true`) |

### B. Publishers (post-build)

| Publisher | Configuration | When it fires |
|---|---|---|
| Archive artifacts (`archive-resultdir`) | `result-dir/**/*`, `allowEmptyArchive=false` | Every build. The archived `refs.txt` becomes the baseline for the next run. |
| Mailer | `sec-mc-sw-cm-codesync@sony.com` (from `sync-defaults`) | Failed, unstable and back-to-normal builds. This is the CodeSync team's failure alert. |
| Editable Email (email-ext) | To `somc-cm@sony.com`, from `Code Sync <noreply-codesync-j2cm@sony.com>`, subject `$CODESYNC_SUBJECT`, body `${FILE,path="./result-dir/email-body.txt"}`, trigger **Always** | Every build. A Groovy pre-send script is meant to cancel the email when `result-dir/no-changes` exists. It is currently blocked by Jenkins script security, so no change notice is sent at all (see section 7). |

### C. Detailed flow

```
AOSP --> aosp-mirror.ptc.sony.co.jp:8443/platform/manifest
           |
           v
monitor_refs_aosp-platform-manifest   (daily: ls-remote, diff against last successful snapshot)
           |-- email to somc-cm@sony.com when anything changed   (currently blocked, see section 7)
           `-- sync_manifest_oss_tag?TAG=android-...   (one build per new android-* tag)
                   `-- pushes refs/tags/<TAG> for every project to git://review.ptc.sony.co.jp
```

### D. Example: build #213

Console provided by the user. Baseline copied from build #212; `diff.txt` was non-empty, so an email body was written; `new-android-tags.txt` was empty, so no `sync_manifest_oss_tag` build was triggered; the email failed with a script-security error; result **SUCCESS**.

### E. Known risks

[Proposed] From reading the config and the YAML.

| Risk | Detail | Mitigation |
|---|---|---|
| Change notice email never sent | See section 7. Because the script fails in both cases (changes or no changes), CM gets no email at all. | Approve the script signature. Until then, read `result-dir/email-body.txt` from the build artifacts. |
| Silent green on `ls-remote` failure | Step 5 has no `-e` and exits 0 when the snapshot is empty | Check that `refs.txt` is archived. Proposed patch: `exit 1` when `refs.txt` is empty. |
| Re-trigger after a failed run | If a trigger `curl` fails mid-loop, the build fails. The next run diffs against the last **successful** snapshot, so it re-triggers every tag since then, including ones already triggered. | Re-pushing an existing tag to the same commit is a no-op, so a duplicate `sync_manifest_oss_tag` build should be harmless [Unconfirmed]. Cancel duplicates from the queue if they pile up. |
| Removed or moved tags are not acted on | Only **added** `refs/tags/android*` lines trigger a sync. A tag that AOSP re-points is shown as removed plus added, so it is re-synced; a deleted tag is only reported. | None needed; be aware when reading the diff |
| Shared `$HOME/.netrc` rewritten every run | Steps 1 and 3 delete and recreate `/home/code-sync/.netrc`, which other jobs on `prod-codesync` may be reading at that moment | [Unconfirmed] Check whether other jobs on the node can fail during that window |
| Leftover step 1 | `set-netrc-file` reads `$NETRC_FILE` / `$NETRC_JK_FILE`, which are not bound here | Harmless because step 3 overwrites `.netrc`. Proposed patch: drop `set-netrc-file` from the template. |
| Modifies shared git config | Step 2 edits `/home/code-sync/.gitrc/review.conf` and the global git identity on every run | Keep in mind when debugging `insteadOf` behaviour of other jobs on the node |
| Renaming the job | The trigger depends on `platform-manifest` being in `$JOB_NAME` | Keep the name |
| Live differs slightly from YAML | The template adds a `timestamps` wrapper, but the live `config.xml` has none | [Unconfirmed] Check whether the Timestamper plugin is installed; redeploying the job may change the config |

### F. A tag was missed

Trigger `sync_manifest_oss_tag` manually with `TAG=<tag>` (leave the other parameters at their defaults). That is safer than editing the baseline `refs.txt`.
