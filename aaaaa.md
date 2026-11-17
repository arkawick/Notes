### G. Downstream job: sync_manifest_oss_tag

> **Sources:** [Code] only: `project-aosp.yaml` lines 61-76 (project `oss-tag`), template `sync_manifest_{remote}_{branch}` in [`template-sync.yaml`](../../code-sync-refs_heads_master/jenkins-jobs/template-sync.yaml) lines 111-250, and [`ohd.sh`](../../code-sync-refs_heads_master/ohd.sh) (`PUSH_MODE=tag` branch). No live `config.xml` or console has been provided for this job yet. [Unconfirmed] Compare with `https://codesync.ptc.sony.co.jp/job/sync_manifest_oss_tag/config.xml`.

**Identification**

| Field | Value |
|---|---|
| **Job Name** | `sync_manifest_oss_tag` (display name: *Sync Manifest - oss tag*) |
| **Job URL** | `https://codesync.ptc.sony.co.jp/job/sync_manifest_oss_tag/` |
| **Category** | Manifest Sync |
| **Source -> Target** | `https://aosp-mirror.ptc.sony.co.jp:8443/platform/manifest` at `refs/tags/<TAG>` -> `git://review.ptc.sony.co.jp` |
| **Node** | `prod-codesync` |
| **Trigger** | No timer (`trigger: ''`). Started by this job (`buildWithParameters?TAG=<tag>`), or by hand. Builds do not run concurrently, so several new tags queue one after another. |
| **Criticality** | **High** [Proposed]. It is the step that actually brings each AOSP release tag into Sony's review server. Unlike `monitor_refs`, it pushes. |

**Parameters** (defaults from the YAML; `monitor_refs` only overrides `TAG`)

| Parameter | Value | Note |
|---|---|---|
| `TAG` | set by `monitor_refs`, one new `android-*` tag | Template default is `android-7.1.1_r4`. A manual *Build* without changing it re-syncs that old tag. |
| `BRANCH` | `tag` | `tag` means "use `TAG`" |
| `MANIFEST` | `platform/manifest` | |
| `REMOTE` | `oss` | Prefix of the branches created on the review server (`oss/...`) |
| `SOURCE_GERRIT` | `https://aosp-mirror.ptc.sony.co.jp:8443` | Also selects the local reference mirror `/mnt/ebs2/gitmirror/android.googlesource.com` |
| `PUSH_MODE` | `tag` | |
| `GIT_PUSH_ARGS` | empty | The daily `sync_manifest_oss_android-latest-release` job uses `--force -o skip-validation`; this one does not |
| `REPO_INIT_ARGS` / `REPO_FORALL_ARGS` | empty / `-j4 -v` | |
| `SKIP_SYNC` / `SKIP_PUSH` | false / false | Set `SKIP_PUSH=true` for a dry run |
| `EXCLUDED_PROJECTS` | empty | Projects to leave out (one per line); written as `<remove-project>` entries |
| `SECURITY_PATCH_IMPORT` | false | |
| Credential | `NETRC_CS_FILE` (`3046b660-f7ae-4137-b118-90f83b608625`) | Same `.netrc` credential as `monitor_refs` |

**What it does** [Code]

1. **Prepare:** same set-up builders as `monitor_refs` (`.netrc`, `prepare-gitconfig-oss`), plus `prepare-gitconfig-sec` (no effect unless `SECURITY_PATCH_IMPORT`) and a fresh clone of `code-sync.git`.
2. **Mirror the tag:** `ohd.sh` runs `repo init --mirror -u <aosp-mirror>/platform/manifest -b refs/tags/<TAG> --groups=all --reference=/mnt/ebs2/gitmirror/android.googlesource.com`, then `repo sync`. The `ohd/` folder in the workspace is reused between builds.
3. **Create missing projects:** `ensure-projects-exist.sh admin/meta/android-standard` creates any project in the tag's manifest that does not yet exist on the review server.
4. **Push, per project** (`repo forall -j4`):
   - `platform/manifest`: pushes `refs/tags/<TAG>`, and the manifest as branch `oss/<TAG>`.
   - Every other project: pushes each upstream branch that contains the tagged revision to `oss/<branch>` (only if the review server is behind). If no branch contains it, pushes the revision to `semc/oss/<TAG>-cache` so the commit is kept. Finally pushes the revision itself (the tag) if the review server does not already have it.
5. **Verify:** waits 180 seconds for replication, then `repo init -u git://review.ptc.sony.co.jp/platform/manifest -b refs/tags/<TAG>` and `repo sync -c` from the review server. If the sync fails, it wipes the folder and retries once; a second failure fails the build.
6. **Record:** writes `repo manifest -r` to `result-dir/static_manifest.xml` and the manifest commit to `result-dir/manifest_revision` (both archived), and sets the build description to the tag.

**Expected output**

- On `review.ptc.sony.co.jp`: tag `<TAG>` on `platform/manifest` and on every project in the release, plus updated `oss/<branch>` branches and the manifest branch `oss/<TAG>`.
- Archived `result-dir/static_manifest.xml` (every project pinned to a SHA-1) and `manifest_revision`.
- Build description = the tag name.

**Validation**

```bash
# tag is on the review server
git ls-remote git://review.ptc.sony.co.jp/platform/manifest refs/tags/<TAG>
# spot-check one project
git ls-remote git://review.ptc.sony.co.jp/platform/build refs/tags/<TAG>
# the job already did this, but a fresh check from another host proves replication
repo init -u git://review.ptc.sony.co.jp/platform/manifest -b refs/tags/<TAG> --groups=all
repo sync -d -c -j8
```

In the console: no `rejected`, `remote: error` or `fatal:` lines in the `repo forall` push loop, and the final `repo sync` completes.

**Failures and rerun**

- **Rerun is safe.** Every push first checks whether the review server already has the commit, and pushing an existing tag to the same commit changes nothing. A rerun for the same `TAG` only fills in what is missing.
- **Partly pushed tag:** if a build fails in the push loop, some projects have the tag and some do not. Rerun the same `TAG`; do not delete the pushed tags.
- **Final sync fails after 180 s:** usually slow replication to the review mirrors. Wait and rerun.
- **New project rejected:** check the `ensure-projects-exist.sh` output; the service account may lack create rights for that path.
- **A tag was missed by `monitor_refs`:** start this job by hand with `TAG=<tag>` (Appendix F).

**Known risks** [Proposed]

| Risk | Detail | Mitigation |
|---|---|---|
| Old default tag | A plain *Build with Parameters* uses `TAG=android-7.1.1_r4` | Always set `TAG` when starting it by hand. Proposed patch: empty default and fail when empty. |
| Downstream trigger to a job that does not exist | The template triggers `build_oss_tag` on success. No such job is defined anywhere in `master`. | [Unconfirmed] Check the console for a "No such project" warning. Harmless, but noise. |
| Fixed 180 s replication wait | `sleep 180` before the verification sync; slow replication fails the build after the push succeeded | Rerun (safe) |
| Push target written as `git://` | `GERRIT_PUSH_URL=git://review.ptc.sony.co.jp`. Pushing only works because the `code-sync` user's git config rewrites it to SSH. | [Unconfirmed] Which config holds the rewrite; keep it when the node is rebuilt |
| `timeout: 600` in the template | Not a JJB job option at that level, so probably ignored | [Unconfirmed] Check the live config for a build timeout |
| Shared `.netrc` and git identity | Same as `monitor_refs` (Appendix E) | |
