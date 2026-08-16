# CodeSync — Knowledge Transfer Document

**System:** CodeSync SCPS (Source Code Provisioning / mirroring & import automation)
**Handover:** outgoing CodeSync owner → incoming L&T CM team
**Compiled from:** `CodeSync_Jobs_ptc.pptx` (33 slides), 5 recorded KT sessions, and the `code-sync` git checkout
**Status:** working reference — see [§16 Open items](#16-open-items-and-unanswered-questions) for what is still unconfirmed

---

## How to read this document

Every factual claim is tagged with where it came from, because the three sources have very different reliability:

| Tag | Source | Reliability |
|---|---|---|
| ✅ | Read directly from the `code-sync` checkout in this folder | High — quoted from the file |
| 📊 | `CodeSync_Jobs_ptc.pptx` (slide text, tables, SmartArt, diagrams) | High — authored deliberately |
| 🎙 | KT session transcripts | **Medium** — machine-transcribed audio, see warning below |
| ❓ | Open question / unconfirmed | Needs an answer before you rely on it |

> **⚠️ Warning about the transcripts.** The five session `.vtt` files are automatic speech-to-text and were then run through `anonymize_vtt.py --scrub-body`. Two consequences:
> 1. **Product codenames, tool names and commands are frequently garbled.** The same platform appears as "Chikugo", "Shingo", "Chiku", "Chip Yuko" and "Yuko" across a single session. "Gitification" is transcribed as "getification", "guidification", "identification" and "certification". Treat every proper noun from a 🎙 claim as approximate and confirm against the PPT tables or the live Jenkins job names.
> 2. **The body scrub replaced participant first/last names with "Speaker N" wherever they appeared in speech**, so some sentences read oddly. Other names (Yamanouchi, Watanabe, Anupam, Onishi, Ashun, Karthik, Suman) survived and are kept here as they appeared, per the handover request.
>
> Where a 🎙 claim and a 📊 claim disagree, **the PPT wins** — job names and parameter tables there were written down deliberately.

> **⚠️ Warning about the code checkout.** The `code-sync/` directory in this folder is an **older snapshot** of the repository. It contains the mirror, sync-git and sync-manifest machinery that is still in use (`git.sh`, `ohd.sh`, `template-sync.yaml`, `template-mirroring.yaml`) — those sections are code-verified. It does **not** contain the current Qualcomm import machinery described in KT sessions 3–5 (`prepare.sh`, the stage driver with `SKIP_STAGES_BEFORE`, `stage_skipper.sh`, the gitification checksum checks, the `qcom-yamamoto` templates). Instead it has the previous-generation CAF/Grease import (`sync_snap.sh` v1, `qcom-caf.sh`, `qcom-grease.sh`, `qcom-hy11.sh`, `qcom-ref.sh`, `qcom-ref-tag.sh`).
>
> **[§9 Qualcomm import](#9-qualcomm-import-jobs) is therefore written from the PPT stage diagrams and the session walkthroughs, not from code.** It is accurate as a description of *what happens*; it does not give you line references. [§17.2](#172-the-previous-generation-import-scripts-in-this-checkout) maps the old scripts for historical context — several ideas carried forward unchanged.

---

## Table of contents

1. [What CodeSync is](#1-what-codesync-is)
2. [Architecture](#2-architecture)
3. [Environments, nodes and storage](#3-environments-nodes-and-storage)
4. [The `code-sync` repository](#4-the-code-sync-repository)
5. [Change management: how you ship a change](#5-change-management-how-you-ship-a-change)
6. [The job catalogue](#6-the-job-catalogue)
7. [Mirror sync jobs](#7-mirror-sync-jobs)
8. [Sync Git jobs](#8-sync-git-jobs)
9. [Sync Manifest and Sync Manifest+Gits jobs](#9-sync-manifest-and-sync-manifestgits-jobs)
10. [Qualcomm import jobs](#10-qualcomm-import-jobs)
11. [Miscellaneous jobs](#11-miscellaneous-jobs)
12. [Runbook: performing a Qualcomm import](#12-runbook-performing-a-qualcomm-import)
13. [Runbook: verification](#13-runbook-verification)
14. [Runbook: failure handling and troubleshooting](#14-runbook-failure-handling-and-troubleshooting)
15. [Runbook: recurring change requests](#15-runbook-recurring-change-requests)
16. [Open items and unanswered questions](#16-open-items-and-unanswered-questions)
17. [Appendices](#17-appendices)

---

## 1. What CodeSync is

📊🎙 CodeSync is **a collection of shell scripts plus Jenkins Job Builder (JJB) job definitions that automate mirroring source code between locations** — AOSP, Qualcomm, Gerrit and Sony's internal review servers.

The business purpose: Sony's development teams build against Sony's own internally gated Gerrit servers, not against upstream. Something has to continuously pull code *in* from the four external upstreams and push it into `review.ptc.sony.co.jp`. That something is CodeSync.

🎙 The four upstream sources:

| Source | What comes from it |
|---|---|
| `android.googlesource.com` (AOSP) | Public Android platform |
| `partner-android.googlesource.com` | Google pre-access / partner code, mainline (AML) releases, FS releases |
| `chipcode.qti.qualcomm.com` (Chipcode) | Qualcomm proprietary release content |
| `git.codelinaro.org` (CodeLinaro / CLO) | Qualcomm open-source release content |

Everything lands in `review.ptc.sony.co.jp`. A separate Gerrit, `review-plus.ptc.sony.co.jp`, hosts the tooling itself (including the `code-sync` repo).

---

## 2. Architecture

📊 Slide 4 of the deck is the one-picture summary. In text:

```
  Google                          CodeSync (Jenkins)                   Targets
  ─────────                       ──────────────────                   ────────
  AOSP ──────── Mirror Sync ────►  ┌──────────────┐
                                   │ Local Mirror │  AOSP / Chipcode
  partner-android ─────────────►   │  (git repos) │
                                   └──────┬───────┘
                                          │ referenced by
                                          ▼
  Qualcomm                          ┌───────────┐   Google pre-access code sync
  ─────────                         │  Jenkins  │ ──────────────────────────►  review.ptc.sony.co.jp
  Chipcode ──── Mirror Sync ────►   │           │   Mainline release code sync
                                    │           │ ──────────────────────────►
  git.codelinaro ───────────────►   └─────▲─────┘   Qualcomm release source code
                                          │       ──────────────────────────►
                                          │ Ansible + YAML/SH
                                    review-plus.ptc.sony.co.jp
```

Three things to take from it:

1. **Two data paths from every upstream.** One path feeds the *local mirror*; the other is the *actual sync job* which pushes to `review.ptc.sony.co.jp`. The sync jobs consult the mirror to go faster — they don't sync *from* the mirror as their source of truth.
2. **`review-plus` is the control plane.** The `code-sync` repo (YAML job definitions + shell scripts) lives there, and Ansible + JJB deploy from it into the Jenkins instances.
3. **Jenkins is the only executor.** There is no cron on the boxes, no manual push path in normal operation.

### 2.1 Why the local mirror exists

🎙 This came up as the first question in Session 1 and is worth restating clearly, because it is not obvious.

The mirror is **not** the sync source. It is a `--reference` for `repo init`. Sony syncs from the upstreams *daily*; a full `repo sync` of a partner-android release branch or a Qualcomm tree straight from the internet is prohibitively slow and consumes a lot of disk in every job workspace. By pointing `repo init --reference=<mirror>` at a locally-held object store, each job only fetches the delta.

🎙 Concretely:
- Sync jobs have **both a time and a space constraint** without the mirror.
- Import jobs have **a time constraint** — they will still work without the mirror, they just take much longer. (This is exactly what bit the team on the standalone-QSSI import described in [§14.3](#143-worked-example-the-standalone-qssi-delay).)

---

## 3. Environments, nodes and storage

### 3.1 The two environments

📊 Slide 3:

| | **Prod** | **Stage** |
|---|---|---|
| Jenkins URL | `https://codesync.ptc.sony.co.jp/` | `https://codesync.ptc-stage.sony.co.jp/` |
| Gerrit | `https://review-plus.ptc.sony.co.jp` | `https://review-plus.ptc.sony.co.jp` |
| Repo | `code-sync` | `code-sync` |
| Branch | `master` | `stage` |

🎙 Note: the checkout in this folder — and the `prepare-code-sync` JJB macro in it — clone branch **`scps`** (✅ `jenkins-jobs/macros.yaml:7`). That is the older branch name. Treat `master`/`stage` from the deck as current.

### 3.2 Node topology

🎙 History matters here because job names still carry the scars:

- CodeSync originally ran on **SCPS** with **multiple Jenkins nodes** — hence job-name suffixes like `_codesync06`, `_codesync07`, `_AOSP_MIRROR`, `_CHIPCODE_MIRROR`.
- It was then migrated to the **Cloud J2** environment. Now each environment is **one large EC2 instance with a single Jenkins node**:
  - Prod node: `prod-code-sync`
  - Stage node: `stage-code-sync`
- **10 executors** on that node. No capacity problems so far because the instance is large, and job schedules were spread out deliberately to avoid pile-ups.
- Prod and stage are **entirely separate EC2 instances with separate EBS volumes**. Nothing is shared between them.
- Every job pins its node explicitly.

> 🎙 **Gotcha found live during Session 1:** some jobs still carry old node names (e.g. a job labelled as being on the chipcode mirror node that shouldn't be). The presenter flagged these as stale and agreed they can be corrected. When you see a job whose node suffix doesn't match `prod-code-sync`/`stage-code-sync`, check whether it is one of these leftovers before assuming it's intentional.

### 3.3 Storage layout

Two views of the same thing — the deck gives you the values that appear in job parameters, the session gives you the on-disk layout.

📊 **MIRROR_ROOT values used in jobs:**

| Value | Used by |
|---|---|
| `/mnt/efs/gitmirror` | AOSP, Chipcode, partner-android, CodeLinaro mirrors |
| `/home/code-sync/workspace/mirror` | `review` and `review-plus` mirrors (codesync06/07) |

🎙 **On-instance layout (post cloud migration):** two EBS volumes per instance.

| Volume | Contents |
|---|---|
| **EBS1** | Job workspaces, plus the **internal** git mirrors: `review` and `review-plus` |
| **EBS2** | The **external** git mirrors: `android.googlesource.com` (AOSP), `chipcode`, `codelinaro`, `partner-android` |

🎙 The mnemonic the presenter used: *anything you would call a remote source lives under the git-mirror path on EBS2; the review-server mirrors live on EBS1 alongside the workspaces.*

❓ The mapping between the `/mnt/efs/...` parameter values and the EBS1/EBS2 mount points was not stated explicitly. Confirm on the box (`df -h`, `ls /mnt/efs/gitmirror`) before relying on either.

### 3.4 Access

🎙 Access is via SSH with a PEM key, plus a VNC server used for local verification syncs.

> ❗ **There is no document for this.** Session 1 closed with an action item to write one: how to SSH into prod/stage, how to reach the workspaces, and how to request/connect to VNC. Commands were previously shared "in bits and pieces" by Samrat. **This is still outstanding** — see [§16](#16-open-items-and-unanswered-questions).

---

## 4. The `code-sync` repository

✅ Verified against the checkout.

### 4.1 Layout

```
code-sync/
├── README.rst                  What it is; how to bootstrap the deploy job
├── config.sh                   Common env setup, sourced by every *.sh
├── git.sh                      Sync a single git  (Sync Git jobs)
├── git-jenkins.sh              Variant of the above
├── ohd.sh                      Sync a manifest + its gits (Sync Manifest jobs)
├── ensure-projects-exist.sh    Create missing projects on Gerrit before push
├── join_manifests.sh           Merge two repo manifests, de-conflicting remotes
├── sync_snap.sh                Qualcomm tree download (v1, CAF/Grease era)
├── sync_snap_linaro.sh         Ditto, CodeLinaro variant
├── qcom-caf.sh                 ─┐
├── qcom-caf-private.sh          │
├── qcom-grease.sh               │ Previous-generation import stages
├── qcom-hy11.sh                 │ (see §17.2)
├── qcom-ref.sh                  │
├── qcom-ref-tag.sh              │
├── qcom-ref-patched.sh          │
├── qcom-ref-tag-patched.sh      │
├── qcom-extract-patches.sh     ─┘
├── jenkins-jobs/               JJB definitions — templates, macros, per-instance projects
├── ansible/                    Provisioning for Jenkins master, nodes, mirrors, web servers
├── proxy/                      connect.c + ssh/socks wrappers for the SoMC proxy
└── configurator/               Submodule: jenkins-jobs-configurator
```

### 4.2 `config.sh` — sourced by every script

✅ `config.sh`:

```bash
GERRIT_FETCH_URL   default git://review.ptc.sony.co.jp
GERRIT_PUSH_URL    default = GERRIT_FETCH_URL
HY11_SUFFIX        = "-$HY11_CHIPSET" if HY11_CHIPSET set
CPU_NO             = nproc, used as -j for repo forall
CODE_SYNC_DIR      = absolute path of the script dir
COMMON_REPO_INIT_ARGS = "--repo-branch stable --no-repo-verify"
                        + "--reference=$REPO_MIRROR" if REPO_MIRROR set   ← the mirror hook
```

It also validates that every variable named in `$required_vars` is set, and defines `find_repo_manifest()`, which resolves `.repo/manifest.xml` through its `<include>` to the real manifest file. Both of those are used throughout.

**The single most important line for understanding the whole system** is `COMMON_REPO_INIT_ARGS` picking up `--reference=$REPO_MIRROR`. That is where the local mirror gets wired into every `repo init`.

### 4.3 `jenkins-jobs/` structure

✅

```
jenkins-jobs/
├── Makefile                        make update / test / delete, driven by JENKINS_URL
├── macros.yaml                     Reusable builders (prepare-code-sync, sync-git, gitconfig…)
├── template-sync-defaults.yaml     `sync-defaults` — node, logrotate, recipients
├── template-sync.yaml              sync_git_*, sync_manifest_* job templates
├── template-mirroring.yaml         update_mirror_*, update_mirror_manifest_*, update_bin_mirror_*
├── template-qcom.yaml              sync_qcom* (previous generation)
├── template-notification.yaml
├── codesync.ajdc.sony.co.jp/       ← per-instance job definitions
│   ├── project-mirrors.yaml
│   ├── project-partner.yaml
│   ├── project-qcom.yaml
│   ├── project-deploy-jenkins-jobs.yaml
│   └── project-test-jenkins-jobs.yaml
└── android-ci-cm.swtools.sonymobile.net/
    ├── aosp.yaml, korg.yaml, qcom.yaml
```

**The pattern to internalise:** `template-*.yaml` defines *how a job works* (parameters, builders, shell). `<instance>/project-*.yaml` defines *which jobs exist* and with what values. Adding a new sync target is almost always an edit to a `project-*.yaml` only.

✅ `Makefile` copies `template-*.yaml` + `macros.yaml` plus the `project-*.yaml` files matching the target `JENKINS_URL` host into `out/`, then JJB acts on that directory. `YAML_PREFIX` defaults to `project-`.

### 4.4 Reusable builders (`macros.yaml`)

✅

| Macro | What it does |
|---|---|
| `prepare-code-sync` | `rm -rf code-sync && git clone -b scps --single-branch git://review-plus.ptc.sony.co.jp/code-sync.git`, then `make -C code-sync/proxy` |
| `sync-git` | `prepare-code-sync`, then `code-sync/git.sh $SOURCE_URL $TARGET_URL $REFSPEC $PUSH_ARGS` |
| `prepare-gitconfig-oss` | Sets `user.name jp21771`, `user.email jp21771@sony.com`, http/https proxy; unsets the `insteadOf` rewrite for `android.googlesource.com`; unsets `REPO_MIRROR_LOCATION` |
| `prepare-gitconfig-caf` / `-grease` | Legacy `insteadOf` rewrites pointing CAF/Grease URLs at the local mirrors |
| `archive-resultdir` | Archives `result-dir/**/*` |

🎙 Note on credentials: the jobs used to read a `.netrc` file straight off the server. After the Cloud J2 migration, **credentials live in Jenkins** and are injected via a wrapper. All jobs authenticate as **Watanabe-san's account** (`jp21771`) rather than a per-user account.

---

## 5. Change management: how you ship a change

🎙 Session 2 covers this in detail. This is the process Sony mandates; follow it exactly.

```
  1. Write patch on `stage` branch, push to review-plus
              │
  2. Automatic +1 from the code-sync test Jenkins job   (YAML syntax / JJB validation)
              │
  3. Deploy the *unmerged* patch to Stage Jenkins        (deploy job, GERRIT_REFSPEC)
              │
  4. Verify on Stage; attach verification results to the ticket
              │
  5. +1 from internal team member (owner / Anupam)
              │
  6. +1 from Ashun-san
              │
  7. Sony review → merge to `stage`
              │
  8. Cherry-pick to `master` (prod)
```

### 5.1 The deploy job

✅ `project-deploy-jenkins-jobs.yaml` defines `code_sync_deploy_jenkins_jobs`:
- Triggers: nightly (`H H * * *`) **and** a Gerrit `ref-updated` trigger on project `code-sync`, branch `scps`, file path `jenkins-jobs/**`.
- Optional `GERRIT_REFSPEC` parameter — "check out this refspec of code-sync before deploying, e.g. `refs/changes/61/314061/1`".
- Body: reset to `$GERRIT_NEWREV`, fetch and check out the refspec, `git submodule init/update`, then `make -C jenkins-jobs clean deployment-env`, `make update`, then reset back and run `make test` and `make delete`.

🎙 Important operational nuances:

- **Prod deploys are trigger-only.** The `GERRIT_REFSPEC` "build with parameters" path was deliberately removed from the prod deploy template — Sony asked that prod deployment happen only via the Gerrit trigger. An older job retaining the parameter is kept **on stage** as a manual backup for verification. Don't use the manual path in prod.
- **Stage is a shared, serialised resource.** Deploying an unmerged patch to stage replaces what's there. If two people are testing unmerged changes simultaneously they will clobber each other. Coordinate. (Once the jobs are deployed and running this matters less.)
- **Stage does not push.** 🎙 Stage sync jobs are either disabled or run in dry-run mode, so a stage run proves *the job was created correctly*, not *the sync works*. That distinction drives the next rule.

### 5.2 What you must verify where

| Change type | Verification required |
|---|---|
| Adding/removing a job (template entry only) | Confirm the job is created correctly on Stage. Then proceed to review. You do **not** have to wait for a successful sync on stage — new-branch sync problems can be worked out in prod. |
| **Any `.sh` script change** | **Must** be tested on Stage. Share the verification results in the ticket, get the internal +1, then go for Sony review. Non-negotiable. |

---

## 6. The job catalogue

📊 Slide 3 — five categories:

| Category | Purpose | Template |
|---|---|---|
| **Qualcomm Import jobs** | Import a full Qualcomm Android release from Chipcode + CodeLinaro | `template-qcom-*.yaml` |
| **Mirror Sync jobs** | Build and maintain the local git mirrors | `template-mirroring.yaml` |
| **Sync Git jobs** | Mirror one specific git from Google → review server | `template-sync.yaml` |
| **Sync Manifest jobs** / **Sync Manifest & Gits jobs** | Mirror a whole manifest branch and its projects | `template-sync.yaml` |
| **Misc jobs** | Housekeeping — stale repos, garbage files, combined manifests, deploy/test | `template-mirroring.yaml`, `project-mirrors.yaml` |

Order of dependency: **mirrors first** (everything else references them), then sync/import.

---

## 7. Mirror sync jobs

📊 *Purpose: create and maintain a local mirror/copy of remote source-code repositories (AOSP, Grease, Chipcode) to make builds fast and consistent.*

**Template:** `template-mirroring.yaml`

### 7.1 Parameters

📊

| Parameter | Meaning |
|---|---|
| `SOURCE_URL` | Manifest URL to init from |
| `MIRROR_ROOT` | Where the mirror lives on disk |
| `BRANCH` | Manifest branch |
| `MANIFEST` | `default.xml` or `external.xml` |
| `REPO_SYNC_ARGS` | e.g. `-j24`, `-j4 -f`, `-j10 -t MAGIC-MIRROR` |
| `EXCLUDED_PROJECTS` | Whitespace-separated project names to skip |

### 7.2 What the job does

📊 Slide 14, ✅ confirmed against `template-mirroring.yaml:31-64`:

1. `cd $MIRROR_ROOT/<name>`
2. **Init.** ✅ The job checks whether the mirror already exists *and is a mirror*:
   ```bash
   if [ -e .repo/manifests.git -a "$(git --git-dir .repo/manifests.git config --local repo.mirror)" = "true" ] ; then
     repo init -u $SOURCE_URL -b $BRANCH -m $MANIFEST --groups=all --no-repo-verify
   else
     rm -rf .repo
     repo init -u $SOURCE_URL -b $BRANCH -m $MANIFEST --groups=all --no-repo-verify --mirror
   fi
   ```
   🎙 This is the "first-time vs subsequent sync" distinction the presenter highlighted — **the only difference is `--mirror`**. First time (or if the existing `.repo` isn't a mirror) it wipes and re-inits with `--mirror`; afterwards it re-inits without it.
3. **Excluded projects.** If `EXCLUDED_PROJECTS` is set, write `.repo/local_manifests/local_manifest.xml` containing one `<remove-project name="..."/>` per entry. Otherwise **delete** any existing `local_manifest.xml`. ✅ (Same pattern appears in `ohd.sh:49-58`.)
4. `repo sync $REPO_SYNC_ARGS`
5. ✅ `find . -name "*.git" -type d -exec touch {}/git-daemon-export-ok \;` — marks every mirrored repo as servable over `git://`.
6. 📊 Cleanup: delete temporary files older than one day.

### 7.3 The mirror jobs

📊 Slides 12–13:

| Job | Source URL | MIRROR_ROOT | Branch | Manifest | Sync args |
|---|---|---|---|---|---|
| `Update Mirror android.googlesource.com on AOSP_MIRROR` | `https://android.googlesource.com/mirror/manifest` | `/mnt/efs/gitmirror` | `main` | `default.xml` | `-j24` |
| `Update Mirror chipcode.qti.qualcomm.com on CHIPCODE_MIRROR` | `git://review.ptc.sony.co.jp/mirror/manifest` | `/mnt/efs/gitmirror` | `chipcode` | `external.xml` | `-j4 -f` |
| `Update Mirror partner-android.googlesource.com on AOSP_MIRROR` | `git://review.ptc.sony.co.jp/mirror/manifest` | `/mnt/efs/gitmirror` | `partner-google` | `default.xml` | `-j12` |
| `Update Mirror review-plus.ptc.sony.co.jp on codesync07` | `git://review.ptc.sony.co.jp/mirror/manifest` | `/home/code-sync/workspace/mirror` | `review-plus` | `default.xml` | `-j12` |
| `Update Mirror review.ptc.sony.co.jp on codesync06` | `git://review.ptc.sony.co.jp/mirror/manifest` | `/home/code-sync/workspace/mirror` | `master` | `default.xml` | `-j10 -t MAGIC-MIRROR` |
| `Update Mirror review.ptc.sony.co.jp on codesync07` | `git://review.ptc.sony.co.jp/mirror/manifest` | `/home/code-sync/workspace/mirror` | `master` | `default.xml` | `-j10 -t MAGIC-MIRROR` |

**Read the second column carefully.** Only the AOSP mirror inits from Google directly. Every other mirror inits from **Sony's own `mirror/manifest` git**, on a branch named after the upstream (`chipcode`, `partner-google`, `review-plus`, `master`). That indirection is the key to the whole mirror system — see §7.5.

### 7.4 The CodeLinaro exception

📊 Slide 15:

- **Job:** `Update Mirror Simple git.codelinaro.org on CHIPCODE_MIRROR`
- **Params:** `MIRROR_NAME: git.codelinaro.org`, `MIRROR_ROOT: /mnt/efs/gitmirror`, `REPO_SYNC_ARGS: -j12`
- **Flow:** cd to mirror path → `repo sync` → cleanup temp files >1 day old
- **📊 Note verbatim from the deck: "Here repo initialization will be handling manually."**

🎙 The presenter confirmed this and flagged it as unexplained: *"we don't do repo init from the job side. Actually, they do the repo init manually. We still don't know the reason why they do the repo init manually only for the codelinaro side."* Neither the current owner nor Yamanouchi-san knows why; the practice was inherited.

> ❓ **Open item.** If the CodeLinaro mirror ever needs rebuilding you will have to `repo init` it by hand, and nobody currently knows the exact incantation used. Get this documented before you need it.

### 7.5 Updating `mirror/manifest` — the routine you will actually do

🎙 This is the most common mirror-side task and it is a **code review flow, not a job trigger**.

When Qualcomm publishes a new platform or a release introduces new gits, the mirror won't pick them up because the mirror's project list comes from Sony's `mirror/manifest` git, not from upstream.

```
New platform / new gits appear upstream (e.g. a new Yamamoto release)
        │
1.  Edit the mirror manifest XML on the matching branch:
        chipcode / codelinaro  → branch `chipcode` (a.k.a. volatile-CLO), file chipcode.xml / external.xml
        Add <project> entries for the new gits.
        (🎙 A tooling script exists to generate these entries — see ❓ below.)
        │
2.  Upload as a patch for review on the mirror-manifest branch
        │
3.  Reviewed and merged
        │
4.  Run the corresponding mirror sync job → new gits are mirrored
```

> ❓ The presenter said "*we have tools, script for that. Based on that script, we will update this XML — I will give you the reference on it*" but the reference was never shown on-screen in the recorded sessions. **Ask for the script and the reference tickets.**

### 7.6 Combined mirror manifest jobs

📊 Slides 27–28. **Template:** `template-mirroring.yaml`. **Parameter:** `USE_LOCAL_SCRIPTS`.

Some upstreams need *many* branches mirrored. Rather than one mirror job per branch, a **combined mirror manifest** job merges several manifests/branches into a single XML at runtime, and the mirror job then syncs against that.

**Job 1 — `update_combined_mirror_manifest_partner-android.googlesource.com`** combines:
- `https://partner-android.googlesource.com/platform/manifest`
  branches: `t-aml-prebuilt-release`, `t-go-aml-prebuilt-release`, `u-aml-prebuilt-release`, `v-aml-prebuilt-release`, `b-aml-prebuilt-release`
- `https://partner-android.googlesource.com/platform/vendor/pdk/generic/fs/manifest`
  branches: `u-qpr1-fs-release`, `24Q3-fs-release`, `24Q4-fs-release`, `25Q1-fs-release`, `25Q2-fs-release`, `25Q3-fs-release`, `25Q4-fs-release`

**Job 2 — `update_combined_mirror_manifest_review-plus.ptc.sony.co.jp`** combines:
- `git://review-plus.ptc.sony.co.jp/S-Link-Spica/kernelmanifest`
  branches: `sa525m-le1.0-kernel-ref`, `sa525m-le3.0-kernel-ref`, `volatile-test0-sa525m-le1.0-kernel-ref`, `volatile-test0-sa525m-le3.0-kernel-ref`
- `git://review-plus.ptc.sony.co.jp/S-Link-Spica/targetmanifest`
  branches: `sa525m-le1.0-vendor-ref`, `sa525m-le3.0-vendor-ref`, `volatile-test0-sa525m-le1.0-vendor-ref`, `volatile-test0-sa525m-le3.0-vendor-ref`

🎙 Two facts that matter:

1. **The combined XML is runtime-only.** It is *not* committed anywhere. It is generated during the job run, used, and discarded. Job 1 then triggers the `partner-android` mirror job as a downstream.
2. **⚠️ It is a second place to edit when release branches change.** When a release branch is added or retired (e.g. "25Q1/25Q2 no longer required"), you must:
   - remove/add the **sync job** for that branch, **and**
   - remove/add the branch in the **combined mirror manifest job**.

   Forgetting the second one leaves the mirror carrying dead branches; forgetting the first leaves a sync job with no mirror backing.

> ❓ **Is the `review-plus` / S-Link-Spica job still needed?** 🎙 The presenter did not know what the Spica (LE1/LE3) content is used for, said no imports had happened on LE1/LE3 recently, and agreed it should be questioned with Sony. Session 1 action item: check the job's recent builds for actual new content, then ask whether it can be stopped.

### 7.7 `update_mirror_manifest_*` — the auto-generated manifest job

✅ Also in `template-mirroring.yaml:66-125`, distinct from the combined-manifest job. It rebuilds `mirror/manifest` from a *listing of the remote server*:

- `type: cgit` → scrape the index URL for project names
- `type: gerrit-ssh` → `ssh <host> -p 29418 gerrit ls-projects`

then writes both `default.xml` (internal fetch URL) and `external.xml` (external fetch URL) with one `<project>` per name, clones `mirror/manifest` on the matching branch, commits, and pushes to **both** `refs/for/<branch>` (for review) and `refs/heads/<branch>` (directly).

**This is why `default.xml` vs `external.xml` matters:** same project list, different `fetch=` — internal points at the local mirror host, external at the real upstream. That's the choice being made when a job sets `MANIFEST: external.xml`.

---

## 8. Sync Git jobs

📊 *These jobs sync remote gits from Google to the review server.*

**Template:** `template-sync.yaml` (job template `sync_git_{name}-{repo-name}`)
**Script:** `git.sh` ✅

### 8.1 Parameters

📊

| Parameter | Typical value |
|---|---|
| `SOURCE_URL` | `https://partner-android.googlesource.com/<git>` |
| `TARGET_URL` | `git://review.ptc.sony.co.jp/<git>` |
| `REFSPEC` | `refs/heads/*:refs/heads/ohd/*` |
| `PUSH_ARGS` | `-f --tags` (varies per job) |

Note the refspec convention: upstream `refs/heads/*` lands under **`refs/heads/ohd/*`** on the Sony side. `ohd` is the remote/namespace name used throughout for Google-sourced content. Some jobs instead use `refs/tags/*:refs/tags/*` (✅ all the `partner_modules/*Prebuilt` jobs in `project-partner.yaml`).

### 8.2 What the job does

📊 Slides 16–17, ✅ confirmed against `git.sh`:

1. Download the source git to the local Jenkins node
2. Compare the SHA-1 of source and target
3. If the source has extra commits, push them to the target

✅ `git.sh` in detail:

```bash
NAME=$(basename $source .git).git
SHA1SUM_NAME=$(basename $source .git)-ref-sha1sum

mkdir -p $NAME ; cd $NAME
git init --bare .
git remote remove origin (if present)
git remote add origin --tags --mirror=fetch $source
cd ..

touch $SHA1SUM_NAME
REF_STATUS=$(cat $SHA1SUM_NAME)          # SHA1 recorded at end of last run
cd $NAME
for r in ${refspec//,/ } ; do
  lhs=${r%%:*}
  git fetch origin +$lhs:$lhs            # fetch each refspec's LHS
done

NEW_REF_STATUS=$(git show-ref | sha1sum)
[ "$NEW_REF_STATUS" == "$REF_STATUS" ] && PUSH=0

if [ $PUSH == 1 ]; then
  git remote add somc $target (if absent)
  for r in $refspec ; do git push $git_args somc $r ; done
  git show-ref | sha1sum > ../$SHA1SUM_NAME
fi
```

**The change-detection mechanism:** a checksum of the *entire* `git show-ref` output is stored in a sidecar file (`<git>-ref-sha1sum`) next to the bare repo. If the checksum after fetching equals the stored one, nothing changed and the push is skipped entirely. 🎙 The presenter walked through exactly this in Session 2 and it's worth knowing, because a stale or deleted sidecar file causes an unnecessary full push, and a *wrongly-persisted* one causes a silently skipped push.

Also ✅ in `git.sh`: `USE_SYSTEM_GIT_CONFIG=false` sets `GIT_CONFIG_NOSYSTEM=1`. The proxy wrapper logic (`$proxy/ssh-connect`, HTTP_PROXY) is present but **commented out** — 🎙 because proxy is now configured at the server level, not per job.

### 8.3 The shared persistent directory

🎙 This is the one real subtlety in Sync Git jobs, and it took a while to explain in Session 2.

Two job-level flags are injected:

| Flag | Meaning |
|---|---|
| `USE_SYSTEM_GIT_CONFIG` | Whether to honour the system gitconfig (usually `false`) |
| `USE_GIT_SYNC_PERSISTENT_DIRECTORY` | **`true` for Sync Git jobs**, false elsewhere |

When the persistent-directory flag is true, the gits are **not** fetched into the job's own workspace. They go into a **shared directory** (`sync_git_persistent_data` or similar under the common workspace) used by all Sync Git jobs.

**Why:** several of the partner-android gits being synced are **shared across different manifests**. Rather than each job maintaining its own copy of the same objects, they all fetch into one common directory.

🎙 Caveats the presenter was explicit about:
- This is **the** structural difference between Sync Git jobs and the other sync jobs. All other jobs fetch into their own workspace and push from there.
- Nobody on the current team has verified *which* gits are actually shared, or *which* manifests share them. The use case was described to them during migration and accepted; it was never audited. ❓
- The requesting team / rationale (BUT? kernel team?) is unknown. ❓

🎙 `git.sh` also **updates the `alternates` file** after pushing: jobs that use a mirror have the mirror path in `objects/info/alternates`, and since the content is now pushed to the review server the alternates reference is updated accordingly.

### 8.4 The Sync Git jobs

📊 Slides 18–19:

| Job | Source | Target | Refspec | Push args |
|---|---|---|---|---|
| `sync_git_partner-platform-vendor-partner_gms` | `…/platform/vendor/partner_gms` | `…/platform/vendor/partner_gms` | `refs/heads/*:refs/heads/ohd/*` | `-f --tags` |
| `sync_git_partner-platform-system-libfmq` | `…/platform/system/libfmq` | `…/platform/system/libfmq` | `refs/heads/*:refs/heads/ohd/*` | `-f` |
| `sync_git_partner-device-google-wahoo` | `…/device/google/wahoo` | `…/device/google/wahoo` | `refs/heads/*:refs/heads/ohd/*` | |
| `sync_git_partner-widevine` | `…/platform/vendor/widevine` | `…/platform/vendor/widevine` | `refs/heads/*:refs/heads/ohd/*` | |
| `sync_git_partner-platform-vendor-google_parntners-qcom-chre` | `…/platform/vendor/google_partners/qcom-chre` | `…/platform/vendor/google/qcom-chre` | `refs/heads/*:refs/heads/ohd/*` | |

(Source prefix `https://partner-android.googlesource.com`, target prefix `git://review.ptc.sony.co.jp`. Note the job name typo `parntners` and the source/target path mismatch on the chre job — both are as-shipped.)

🎙 There are also `sync_git_kernel_aosp*` jobs sourced from AOSP rather than partner-android; same template, same script.

✅ The checkout additionally shows a large family of `platform/vendor/partner_modules/*Prebuilt` and `platform/prebuilts/module_sdk/*` jobs using `refs/tags/*:refs/tags/*` on a `H H/6 * * *` schedule.

### 8.5 Maintenance profile

🎙 Sync Git is the **lowest-maintenance category**:
- No script changes have ever been requested for `git.sh`.
- Requests are limited to: *start syncing a new git* / *stop syncing an existing git*.
- Failures are almost always transient (network, disk space).

**To add a new git** — see the checklist in [§15.1](#151-request-start-syncing-a-new-git).

---

## 9. Sync Manifest and Sync Manifest+Gits jobs

📊 Two closely-related categories sharing `template-sync.yaml`. The script behind both is ✅ `ohd.sh`.

| Category | What it syncs |
|---|---|
| **Sync Manifest jobs** | Downloads the latest manifest for a branch, syncs all gits in it, pushes/merges changes to `review.ptc.sony.co.jp`, and **branches out gits that aren't branched yet** |
| **Sync Manifest & Gits jobs** | Same, plus: for each git in `static_manifest.xml`, fetch **all tags** and push them |

🎙 Third-category framing from Session 2: *"one kind of job syncs the entire git [Sync Git], another syncs only the particular manifest [Sync Manifest], and we have jobs which sync both manifest and the gits."*

### 9.1 Parameters

📊 Slides 20 & 23:

| Parameter | Sync Manifest & Gits | Sync Manifest |
|---|---|---|
| `MANIFEST` | `platform/manifest` | varies (see job list) |
| `BRANCH` | per job | per job |
| `TAG` | `android-7.1.1_r4` (used when `BRANCH=tag`) | same |
| `REMOTE` | `ohd` | `ohd` |
| `SKIP_PUSH` | `False` | — |
| `SKIP_SYNC` | `False` | — |
| `SOURCE_GERRIT` | `https://partner-android.googlesource.com` | same |
| `REPO_INIT_ARGS` | *(blank)* | e.g. `--repo-rev=rel/v2.51 --no-current-branch` |
| `REPO_FORALL_ARGS` | `-j20` | `-j20 -v` |
| `PUSH_MODE` | `all` | `single` or `all` |
| `GIT_PUSH_ARGS` | `--force -o skip-validation` | per job |
| `EXCLUDED_PROJECTS` | *(blank)* | *(blank)* |
| `SECURITY_PATCH_IMPORT` | — | present on Sync Manifest jobs |

### 9.2 `ohd.sh` — the actual logic

✅ This is the most intricate script in the checkout. Structure:

**Phase 1 — sync the upstream into `ohd/`**
```bash
repo init -u $SOURCE_GERRIT/$manifest -b $branch --groups=all $REPO_INIT_ARGS \
          [--reference=$AOSP_MIRROR] --no-repo-verify --mirror
# EXCLUDED_PROJECTS → .repo/local_manifests/local_manifest.xml with <remove-project>
repo sync -d -j16
```

**Phase 2 — decide what to compare against**
```bash
if [ -e ../ref/.repo/project.list -a "$PUSH_MODE" = "single" ] ; then
   check_url=file://$(readlink -f ../ref)   # compare against last run's local ref tree — fast
   check_prefix=refs/remotes/origin
else
   check_url=git://review.ptc.sony.co.jp    # compare against the live server
   check_prefix=refs/heads
fi
```
This is a performance optimisation: if the previous run left a synced `ref/` tree and we're in `single` mode, compare locally rather than doing thousands of `git ls-remote` calls.

**Phase 3 — ensure target projects exist**
```bash
$CODE_SYNC_DIR/ensure-projects-exist.sh admin/meta/android-standard
```

**Phase 4 — push, by mode.** Three `PUSH_MODE` values, and they behave very differently:

| Mode | Behaviour |
|---|---|
| `single` | For each project: fetch, then push `HEAD` → `refs/heads/$remote/$branch` **only if** `git ls-remote` shows the target doesn't already have that revision |
| `all` | For each project: find **all local branches containing `$REPO_RREV`**, push each one → `refs/heads/$remote/<br>`. For the manifest project, additionally include `builds/$branch/*` branches |
| `tag` | Push branches *and* tags. For `platform/manifest`, push `refs/heads/$branch` and `refs/tags/$branch`. For everything else: push each containing branch, and if there are none, push `$REPO_RREV^{}` to `refs/heads/semc/$remote/$branch-cache`; also push the raw `$REPO_RREV` if the server doesn't have it |

**Phase 5 — update the manifest branch**
```bash
cd .repo/manifests
git remote add semc $GERRIT_PUSH_URL/$manifest
git push $GIT_PUSH_ARGS semc origin/$branch:refs/heads/$remote/$branch
# non-tag mode: also create refs/heads/semc/$remote/$branch and wait for replication
```

**Phase 6 — build the internal `ref/` tree** (non-tag modes). This is where the manifest is *adapted for internal use*:
```bash
repo init -u git://review.ptc.sony.co.jp/$manifest -b semc/$remote/$branch
cd .repo/manifests
git merge -s recursive -X theirs origin/$remote/$branch
# rewrite default.xml:
#   revision=  → $remote/$branch      (single) or prefix with $remote/   (all)
#   name=      → "origin"
#   remote=    → "origin"
#   review=    → https://review.ptc.sony.co.jp
#   clone-depth= → removed
git commit -a -m "Adapted revision for internal use"      # or --amend if merge produced a commit
cp default.xml new.xml
repo init -b semc/$remote/$branch -m new.xml --groups=all
repo sync -d -j9 -c  ||  { rm -rf * .repo/projects .repo/project-objects ; repo sync -d -j9 -c ; }
git push semc $sha1:refs/heads/semc/$remote/$branch
sleep 30 ; git fetch --all
repo init … && repo sync -d -j9 -c
```
The `sed` block is the heart of it: **it retargets the upstream manifest at Sony's Gerrit**, pinning revisions to the `ohd/<branch>` refs that Phase 4 just pushed. The retry-after-`rm -rf` pattern appears throughout — repo syncs here are expected to fail occasionally and are simply retried from clean.

**Phase 7 — emit results**
```bash
repo manifest -r -o $workdir/static_manifest.xml
echo $sha1 > $workdir/manifest_revision
```
`static_manifest.xml` (fully-pinned revisions) is the job's key artifact.

**Phase 8 — optional bringup rebase** (only if a 4th arg is passed): init the bringup branch, `repo start`, `git reset --hard`, `git rebase m/semc/$remote/$branch`, push. Not used by the standard jobs.

✅ Back in `template-sync.yaml`, the job wrapper around `ohd.sh`:
- Copies the **previous run's** `static_manifest.xml` via `copyartifact` into `.previous/`
- After the run, diffs old vs new: identical → build description `NONEW`; different → description = the SW label from `semcsystem/getswlabelname.py --branch $branch`
- For PDK manifests the branch label gets a suffix parsed out of the manifest commit message
- Archives `result-dir/**/*`, sets the build description, triggers `build_{remote}_{branch}` downstream, emails on completion

### 9.3 `ensure-projects-exist.sh`

✅ Called before every push. It:
1. `ssh -p 29418 <user>@review.ptc.sony.co.jp gerrit ls-projects` → `project-existing.list`
2. `repo forall -c 'echo $REPO_PROJECT'` → `project.list`
3. **Normalises names** by stripping: `.git`, `revision-history/`, `clo/la/`
4. For any project not already present: `gerrit create-project <proj> --parent admin/meta/android-standard`

Step 3 is significant for imports: `clo/la/` and `revision-history/` prefixes come off the upstream Qualcomm project names, meaning the Sony-side project name is the *stripped* form. Keep that in mind when hunting for a project on the review server.

🎙 Consequence worth knowing: **new gits appearing in an upstream release are created on the review server automatically.** You do not need to request them. (The *exception* is gitified techpack artifacts — see [§10.8](#108-gitification-and-the-two-run-techpack-procedure).)

### 9.4 `join_manifests.sh`

✅ Merges two `repo` manifests into one, using `xmlstarlet`:
1. `remove_defaults()` — pushes `<default remote=…>` / `<default revision=…>` values down onto every element that lacks them, then deletes the `<default>` node. (Necessary because two manifests' defaults will conflict.)
2. Detects remote-name collisions between the two manifests and renames them `<name>1` / `<name>2`.
3. Emits `<manifest>` with all non-project elements from both, then all projects from both.

🎙 This is the script referred to in Session 5 as "the joint manifest script" used at the `ref-manifest` import stage to merge the many `.repo/local_manifests/*.xml` files (one per techpack artifact: audio, BT/FM, display, …) into a single combined XML.

### 9.5 Sync Manifest & Gits jobs

📊 Slides 21–22. Manifest `platform/manifest`, source `https://partner-android.googlesource.com`, target `git://review.ptc.sony.co.jp/`, push mode `all`.

| Job | Branch |
|---|---|
| `sync_manifest_and_gits_ohd_t-aml-prebuilt-release` | `t-aml-prebuilt-release` |
| `sync_manifest_and_gits_ohd_t-go-aml-prebuilt-release` | `t-go-aml-prebuilt-release` |
| `sync_manifest_and_gits_ohd_u-aml-prebuilt-release` | `u-aml-prebuilt-release` |
| `sync_manifest_and_gits_ohd_v-aml-prebuilt-release` | `v-aml-prebuilt-release` |
| `sync_manifest_and_gits_ohd_b-aml-prebuilt-release` | `b-aml-prebuilt-release` |

(AML = Android Mainline. These are the mainline prebuilt release branches.)

### 9.6 Sync Manifest jobs

📊 Slides 25–26:

| Job | Branch | Push mode | Manifest | Repo init args |
|---|---|---|---|---|
| `sync_manifest_ohd_security-aosp-udc-release` | `security-aosp-udc-release` | `single` | `platform/manifest` | |
| `sync_manifest_ohd_security-aosp-24Q3-release` | `security-aosp-24Q3-release` | `single` | `platform/manifest` | |
| `sync_manifest_ohd_24Q4-fs-release` | `24Q4-fs-release` | `all` | `platform/vendor/pdk/generic/fs/manifest` | `--repo-rev=rel/v2.51 --no-current-branch` |
| `sync_manifest_ohd_25Q2-fs-release` | `25Q2-fs-release` | `all` | `platform/vendor/pdk/generic/fs/manifest` | `--repo-rev=rel/v2.51 --no-current-branch` |
| `sync_manifest_ohd_25Q3-fs-release` | `25Q3-fs-release` | `all` | `platform/vendor/pdk/generic/fs/manifest` | `--repo-rev=rel/v2.51 --no-current-branch` |
| `sync_manifest_ohd_25Q4-fs-release` | `25Q4-fs-release` * | `all` | `platform/vendor/pdk/generic/fs/manifest` | `--repo-rev=rel/v2.51 --no-current-branch` |
| `sync_manifest_ohd_security-aosp-udc-staging` | `security-aosp-udc-staging` | `single` | `platform/vendor/pdk/generic/fs/manifest` | |
| `sync_manifest_ohd_security-aosp-24Q3-staging` | `security-aosp-24Q3-staging` | `single` | `platform/vendor/pdk/generic/fs/manifest` | |
| `sync_manifest_ohd_security-aosp-25Q2-staging` | `security-aosp-25Q2-staging` | `single` | `platform/vendor/pdk/generic/fs/manifest` | |

\* 📊 Slide 26 lists the `25Q4` job with branch `25Q3-fs-release`. That is almost certainly a copy-paste error in the deck — **verify the real branch in Jenkins before trusting it.** ❓

**Pattern:** `security-*` branches use `PUSH_MODE: single`; `*-fs-release` (pre-access "FS release") branches use `PUSH_MODE: all` and pin the repo tool version.

🎙 Three branch families were named in Session 2 as the thing to understand: **FS release branches** (pre-access code), **security branches**, and **AML (Android mainline) release branches** — three job families, differing in how the source is downloaded and how it is pushed.

---

## 10. Qualcomm import jobs

> **Source note:** this section is built from 📊 the PPT (job matrix, parameter list, and the two SmartArt stage diagrams on slides 8–9) and 🎙 sessions 3–5. **The current import scripts are not in this checkout** — see the warning at the top. Descriptions of what each stage does are reliable; exact file/function names are not.

📊 *Imports a Qualcomm Android release from ChipCode and CodeLinaro. Since Qualcomm software is released for each product tier, each SoC year and each Android version, we have different jobs to support these combinations.*

### 10.1 The release taxonomy

Four axes determine which job you run:

| Axis | Examples |
|---|---|
| **SoC** | SM8750, SM8650, SM8550 |
| **Qcom distro** | `2024-spf-1-0`, `2023-spf-2-0`, `2023-spf-1-0`, `2022-spf-2-0-1`, `2022-spf-2-0`, `2022-spf-1-0` |
| **Sony project (codename)** | V Shimanto, V Asahi, U Asahi, V Yodo, U Yodo, T Yodo |
| **Component** | Kernel, QSSI13/14/15, Vendor Techpack |

📊 Job naming convention: `Import_Qcom_<distro>_<component>_<project>`

### 10.2 Import job matrix

📊 Slide 5 — the authoritative list:

| Qcom distro | Sony project | Kernel | QSSI15 | QSSI14 | QSSI13 | Vendor Techpack |
|---|---|---|---|---|---|---|
| `2024-spf-1-0` | V Shimanto | `Import_Qcom_2024-spf-1-0_Kernel_V-Shimanto` | `…_QSSI15_V-Shimanto` | — | — | `…_Vendor_techpack_V-Shimanto` |
| `2023-spf-2-0` | V Asahi | `…_Kernel_V-Asahi` | `…_QSSI15_V-Asahi` | `…_QSSI14_V-Asahi` | — | `…_Vendor_techpack_V-Asahi` |
| `2023-spf-1-0` | U Asahi | `…_Kernel_U-Asahi` | — | `…_QSSI14_U-Asahi` | — | `…_Vendor_techpack_U-Asahi` |
| `2022-spf-2-0-1` | V Yodo | `…_Kernel_V-Yodo` | `…_QSSI15_V-Yodo` | `…_QSSI14_V-Yodo` | `…_QSSI13_U-Yodo` | `…_Vendor_techpack_V-Yodo` |
| `2022-spf-2-0` | U Yodo | `…_Kernel_U-Yodo` | — | `…_QSSI14_U-Yodo` | `…_QSSI13_U-Yodo` | `…_Vendor_techpack_U-Yodo` |
| `2022-spf-1-0` | T Yodo | `…_Kernel_T-Yodo` | — | — | `…_QSSI13_T-Yodo` | `…_Vendor_techpack_T-Yodo` |

Read across a row and you have the full set of jobs for one release. Note that **QSSI is shared across Android versions** — this is what causes the volatile-branch situation in §10.9.

🎙 The sessions discuss more recent codenames (Yamamoto = A17, Takeuchi, Shingo/Chikugo = A16, Yuko, Shimanto, LE/LB). These are **not** in the deck's matrix, and the transcript mangles them badly. **Use Jenkins for the current job list; use the deck only for the shape of the naming convention.** ❓

🎙 Additionally there is a **standalone QSSI** job family (e.g. QSSI17 standalone), separate from the per-product QSSI jobs — see [§10.10](#1010-standalone-qssi).

### 10.3 Components and target manifests

📊 Slide 6 diagram:

| Component | Contents | Manifest repo in Sony |
|---|---|---|
| **Kernel** | | `platform/kernelmanifest` |
| **QSSI** | | `platform/qssimanifest` |
| **Vendor Techpack** | Audio, CV, Graphics, Sensors, Video, Camera, Display, HEXLP, Vendor, XR | `platform/targetmanifest` |

The Vendor Techpack is a bundle of ten sub-artifacts. **That structure is what makes techpack imports a two-run procedure** — see §10.8.

### 10.4 Job parameters

📊 Slide 7:

| Parameter | Purpose (🎙 from the walkthrough) |
|---|---|
| `AU_TAG` | The Qualcomm AU tag to import. **Mandatory.** Taken from the release note. |
| `AU_TAG_INTERNAL` | Test tag, used with a volatile branch for testing. Convention: `test_01`, `test_02`… appended to the AU tag. Optional. |
| `RELEASE_NUMBER` | Full release number from the release note / email |
| `REF_BRANCH` | Sony-internal reference branch. Confirmed with Sony for each new job; defaulted per job. |
| `SENSOR_TAG` | ─┐ |
| `XR_TAG` | │ Additional techpack tags. **Mandatory on older platforms** (up to Shimanto); |
| `HEXLP_TAG` | │ **no longer used** on recent platforms — made optional and excluded. |
| `GRAPHICS_TAG` | │ |
| `WLAN_TAG` | │ |
| `BFTM_TAG` | ─┘ |
| `SYNC_SCRIPT` | Choice: where `sync_snap_v2.sh` comes from — **distro git** (normal), grease utilities (legacy, unused), or **local** (from the job's local workspace) |
| `SKIP_STAGES_BEFORE` | Resume from a named stage. **Requires `CLEANUP_WORKING_DIR` unchecked.** |
| `STOP_BUILD_AT_STAGE` | Halt after a named stage — used for the techpack first run |
| `CLEANUP_WORKING_DIR` | Wipe the workspace before starting. Checked = fresh run. |
| `PSEUDO_MIRROR_TREE` | Build a mirror tree inside the job workspace and reference it → much faster download |
| `GIT_PUSH_ARGS` | Extra push args; mostly used for dry-run |
| `SYNC_SNAP_OPTS` | Extra options to `sync_snap_v2.sh` (e.g. `-j1` for huge gits). **Never used so far.** |
| `PRESYNC_COMMANDS` | Commands to run before sync. **Never used so far.** |
| `TEMP_PROXY` | Legacy — server now has proxy configured. Unused. |
| `VERBOSE_QCOM_SYNC` | Sets `GIT_TRACE=1` etc. for verbose logs |
| `USE_LOCAL_SCRIPTS` | Overlay script changes from a local server directory onto the cloned `code-sync`. Used for on-box debugging; the team deploys a patch to stage instead. |

> 🎙 **`SKIP_STAGES_BEFORE` + `CLEANUP_WORKING_DIR` is the trap.** If you set a skip stage but leave cleanup checked, the workspace gets wiped and the skipped stages' output is gone. There is an internal validation that warns you, but **it warns — it does not stop you.** Always uncheck cleanup when skipping.

### 10.5 Project- and template-level variables

🎙 Beyond the job parameters, each import job is configured by variables in `project-qcom-<product>.yaml` (per-instance) and `template-qcom-<product>.yaml` (shared defaults). Template values are overridden by project values where needed.

| Variable | Notes |
|---|---|
| `distro` | e.g. `2025-spf-1-0`. Matches the release note. |
| `distro_full_name` | **Generated**, not typed — see §10.6 |
| `tree_type` | `kernel`, `LA_QSSI`, `LA_vendor_techpack`, `vendor_techpack`, … Comes from the release note. |
| `tree_type_name` | Job-side label (e.g. `16`, `kernel`) |
| `target_project` | The Sony product |
| `ref_branch` | Default ref branch per component. **Confirmed with Sony per new job.** |
| `manifest_branch` | Chipcode manifest branch, includes the customer ID |
| `hy11_suffix` | `-kernel` for kernel; product codename for vendor techpack; `-QSSI` for QSSI |
| `caf_remote_suffix` | **`private` while the OSS manifest is private. Must be REMOVED when the release moves to public.** |
| `oss_manifest` | Manifest git URL. `CLO/LA/…` = **public** (no auth). `CLO private` = **private** (auth needed). |
| `path_to_sync_script_dir` | Path *inside the downloaded chipcode tree* where `sync_snap_v2.sh` lives, e.g. `LA.<ver>/…/LA.QSSI.16.2/…`. Version-dependent. ❓ derivation not shown |
| `chipcode_server` | Host from the Qualcomm site, e.g. `qpm.qualcomm.com/home2`. Overridable per-project when a release gives a different download URL. |
| `chipcode_customer_id` | **`1055`** — Sony's Qualcomm customer ID. ❓ Nobody knows what it maps to on Qualcomm's side. |
| `common_oss_url` | The CodeLinaro URL. Constant. |
| `workspace` | Per-**component** (not per-product) — see §10.7 |
| `gerrit_user` | `JP21771` |
| `build_node` | `prod-code-sync` / `stage-code-sync` |
| `image_type`, `prop_opt` | Defaults from the release note. `prop_opt` is "check both". |

### 10.6 `distro_full_name` generation

🎙 A small piece of logic that trips people up. The job takes a short distro like `2025-spf-1-0` and builds the full Qualcomm distro name:

```
split distro on "-"  →  [0]=2025  [1]=spf  [2]=1-0

if [0] starts with "20" AND [1] == "spf":
      → "Snapdragon Premium <distro> AMSS Standard OEM"
elif  (HLOS dev case — used only for standalone QSSI):
      → HLOS-dev variant
else:
      → "Snapdragon High Mid AMSS Standard OEM"
```

So the three families are **Snapdragon Premium High**, **Snapdragon High Mid**, and (one case) **HLOS dev**. If you pass a distro like `high-mid`, it falls to the `else` branch and produces the High Mid name.

**Why you care:** the distro name is what you match against on the Qualcomm site and in release emails. `AMSS Standard OEM` is the suffix that distinguishes real releases from test-device releases. See §12.1.

### 10.7 Workspace layout

🎙 Inside the job workspace:

```
<workspace>/
├── code-sync/                  cloned from review-plus
├── grease_utilities/           sparse-checkout landing zone for sync_snap_v2.sh (+ snap_release.xml)
├── <component>_st/             ← REMOTE: the Qualcomm tree downloaded from Chipcode/CLO
│     kernel_st  |  qssi_st  |  vendor_st  |  vendor_techpack_st
└── ref_st/                     ← INTERNAL: the Sony review-server ref-branch tree
```

**Two trees, and everything in the import is a movement between them.** `<component>_st` is what Qualcomm gave you; `ref_st` is what Sony has. The first five stages populate and push the former; the last five build and push the latter.

🎙 The mapping from `tree_type` to directory is a conditional in the prepare script. Two wrinkles:

1. **The workspace is per-component, shared across products.** All QSSI imports (any product) use `qssi_st`. All kernel imports use `kernel_st`. So a QSSI-17 import for product A and a QSSI-17 import for product B **use the same directory**.
   → 🎙 **A lock file guards this.** At the start of an import a lock file is written containing the running job's name, and held until all import scripts complete. A second import for the same component checks the lock, finds another job's name in it, and refuses to run with a message naming the job that holds it.
2. **Vendor techpack has two directories** — `vendor_st` and `vendor_techpack_st` — because the `tree_type` name changed between platform generations (`LA_vendor_techpack_<product>` on older, `vendor_techpack` on newer). Rather than extend the existing `if` with another `||`, a separate branch was added.
   🎙 The presenter was explicit that this is **cosmetic, not functional**: "it has no particular effect on it… we could keep this condition here and use a common workspace for vendor also, that is not a problem." Workspaces are cleaned per run, so there is no overwrite risk. **But you must know which product uses which directory when you go to verify the download.** ❓ Confirm the current mapping in the live job config.

### 10.8 The import stages

📊 Slides 8–9 (SmartArt). This is the definitive stage list and description — quoted:

#### Remote side (slide 8)

| # | Stage | What it does |
|---|---|---|
| 1 | **`prepare_utilities`** | Fetch the Qualcomm download script `sync_snap_v2.sh` from **distro git** or **grease utilities** |
| 2 | **`syncsnap`** | Using `sync_snap_v2` download the whole tree. **Set mirror location.** Check if the pseudo mirror is enabled — if so, create directories and symlinks of the entire repo mirror tree in the current workspace |
| 3 | **`syncsnap-notdefault`** | By default the sync-snap script does not download repositories in the `notdefault` group (default `repo` behaviour). At this stage **tweak the repo config files and sync the `notdefault`-group repositories** |
| 4 | **`syncsnap-list`** | Create the list of repositories downloaded so far along with mirror usage. **Generate the combined manifest** using `repo manifest` |
| 5 | **`syncsnap-push`** | **Create any new projects** in our review server. **Push each project defined in the manifest** to the review server |

#### Reference side (slide 9)

| # | Stage | What it does |
|---|---|---|
| 6 | **`hy11`** | During `sync_snap_v2.sh` the prebuilt directories are downloaded to a specific directory. Save the whole directory into our review server by **making a commit in a dedicated git repository** |
| 7 | **`ref-manifest`** | Combine the local manifests (`.repo/local_manifests/*.xml`) into `$AU_TAG.xml`. **Create our own version of the combined manifest.** Add gitified directories to it. Push the manifest to our manifest git at path `grease/$AU_TAG.xml`. The manifest points to the tag as default revision |
| 8 | **`ref-repo-init` / `ref-repo-sync`** | `repo init` and `repo sync` — downloads the whole software **from our review server** |
| 9 | **`ref-push`** | For each git repository defined in the manifest, **pin `refs/heads/$REF_BRANCH` to the defined revision** |
| 10 | **`ref-tag`** | Generate `default.xml` and **update the tags for every imported project**. The tag name is `$AU_TAG` |

🎙 Session detail worth adding to each:

**Stage 1 (`prepare_utilities`)** — The download is a **git sparse checkout**: a helper (`git_clone_sparse`) takes the distro remote URL + release number + a fetch path (the `path_to_sync_script_dir`) + the mirror reference, and checks out *only* `sync_snap_v2.sh` rather than the whole tree. It is then copied into the job workspace. On the newest platform generation, `snap_release.xml` is fetched the same way. If `SYNC_SCRIPT=local`, the file is copied from a local server directory instead.

**Stage 2 (`syncsnap`)** — the actual download. Notes:
- Per-component `if/else` blocks, because each component has a different URL path. 🎙 The presenter observed these have become highly repetitive: *"the same thing is repeating for all the ones, so this might need some refactoring."*
- `shallow_clone` is passed as **`false`** so the full history/files come down, and a later `unshallow` stage exists as well. 🎙 The team noticed this looks contradictory and could not explain it. The presenter's account: shallow-clone `true` was tried, some files went missing, so it was set to `false`. ❓ **Still an open question** ("I will confirm why we do the unshallow again").
- **`PSEUDO_MIRROR_TREE`**: when enabled, the job builds a mirror directory *inside the workspace* and symlinks the whole repo-mirror tree into it, then references that. Verification: check `git_start.html` (generated by the job) — if `repo_mirror_location` points at the EBS mirror path, pseudo-mirror is **off**; if it points at `/home/code-sync/<workspace>/mirror/…`, it is **on**.
- 🎙 One product generation has an extra block for downloading proprietary content that isn't otherwise available; inherited, unchanged, not applicable to the newest platform.

**Stage 3 (`syncsnap-notdefault`)** — the manifest XML is edited to replace/neutralise the `notdefault` group so those projects can be fetched, then `repo sync` runs for them.

**Stage 4 (`syncsnap-list`)** — produces `gits.txt` (the project list) and an HTML rendering of it for convenience.

**Stage 5 (`syncsnap-push`)** — pushes with `HEAD`, comparing upstreams. 🎙 Two important behaviours:
- **Remote filtering.** The manifest declares several remotes. The push logic filters projects by remote name pattern. Historically: `CAF`, `Grease`, `CLO/LA`. Newer releases introduced many more prefixed remotes (`audio`, `BT`, `FM`, … each with a `CLO private` style suffix) plus a **`propagation-history` / `revision-history`** remote. The filter patterns had to be generalised (match on `CLO` + pattern rather than exact `CLO private`, plus a `grease [A-Z]` pattern) to cover both generations.
  > ⚠️ **Nobody tells you when remotes change.** 🎙 *"we have to check it manually — check the manifest XML and see what new remotes are available."* Add this to your per-release checks.
- **Project-name rewrites before push.** See §10.11.

**Stage 6 (`hy11`)** — gitifies and pushes the prebuilt directories and techpack artifacts. See §10.9.

**Stage 7 (`ref-manifest`)** — the local manifests (one per techpack artifact — audio has audio's projects, BT/FM has theirs, etc.) are combined via the join-manifests script into one XML. Then the manifest is rewritten for internal use: the upstream remotes (CodeLinaro, Qualcomm) get a `review.ptc.sony.co.jp` remote added, naming conventions are applied, CAF-family branches get their symlinks added. If no default remote exists the job exits (this has never happened). The AU-tag XML is placed under `grease/`.

**Stage 9 (`ref-push`)** — `AU_TAG_INTERNAL` is honoured here: if you supplied a test tag, that is what gets written; otherwise the real `AU_TAG`.

**Stage 10 (`ref-tag`)** — the tagging is done by `tag-official-release.py` from `semctools/cm_tools` (✅ this is still visible in the old `qcom-ref-tag.sh`). It checks each project: if the tag already exists remotely it skips, otherwise it applies it.
> 🎙 **The tag counters are your verification signal.** A clean run reports all projects `tag OK`, zero `tag exists`, zero `failed`. If the job is interrupted mid-tagging you get e.g. 900 OK / 100 failed. On the re-run from `ref-tag`, you should see ~900 `tag exists` and the remaining 100 `tag OK`, with **zero failures**. Watch those three counters.

### 10.9 Gitification and the two-run techpack procedure

🎙 This is the single most error-prone part of the import, and the reason vendor-techpack imports are run twice.

**The problem.** Qualcomm ships the Vendor Techpack artifacts (audio, camera, display, video, sensors, CV, graphics, HEXLP, XR, vendor) and the `prebuilt_HY11` content as **plain directories, not git repositories** — with one exception, `display/LE`, which arrives already gitified. Different Sony teams consume different artifacts individually, so each must become its own git on the review server. CodeSync **manually gitifies** them (`git init`, add, commit, push) during the `hy11` stage.

**The risk.** If a file is silently dropped between download and gitification, a team gets an incomplete repo and nobody notices.

**The safeguard — a checksum bracket around gitification:**

```
   Stage 2 (syncsnap), immediately after download
        │  walk techpack_artifacts/ and prebuilt_HY11/
        │  write a symlink/manifest file: <checksum> <path> <project> <size>   per file
        ▼
   Stage 6 (hy11): gitify + push
        │
        ▼
   Stage 9 (ref-push), BEFORE pushing
        │  regenerate the same checksum file from the resulting .git content
        │  compare
        ├── match    → proceed with ref push
        └── mismatch → ABORT the job
```

🎙 *"If all the files' checksums match, it means no alteration was there and none of the files were missed in gitification. If there is any missing file, the job will be aborted."*

**The two-run procedure:**

| | Run 1 | Run 2 |
|---|---|---|
| `STOP_BUILD_AT_STAGE` | `syncsnap-notdefault` | *(blank)* |
| `SKIP_STAGES_BEFORE` | *(blank)* | *(blank)* |
| `CLEANUP_WORKING_DIR` | ✅ checked | ✅ checked |
| Purpose | Download, then **stop and inspect the artifacts** | Full fresh run to completion |

**Run 1 — what you inspect.** Go to the techpack artifacts path in the workspace and list what's there. Expected: **only `display/LE` is already a git**; everything else is a plain directory. Record this in the ticket: *"artifacts present: <list>; only display LE is a git; no new techpack artifacts."*

> ⚠️ **The point of Run 1 is to catch a NEW artifact.** If Qualcomm adds an artifact that isn't in the script's techpack-artifacts list, it will not be gitified and not be pushed. If you find one:
> 1. Add it to the artifacts list in the script (a code change → full stage/review process)
> 2. **Ensure the corresponding repository exists on the review server.** Ordinary new gits are auto-created by `ensure-projects-exist.sh`, but **manually-gitified artifacts are not** — this one you must confirm.

**Run 2 — policy change, note this.** 🎙 The procedure **used to be**: uncheck `CLEANUP_WORKING_DIR`, set `SKIP_STAGES_BEFORE=syncsnap-notdefault`, and resume from where Run 1 stopped. **This was changed** (agreed with Sony) to a completely fresh run from scratch, to avoid issues carried over from the partial workspace. It takes longer; that was accepted. **Use the fresh-run form.**

**Run 2 verification.** Confirm every techpack artifact is now gitified, and confirm they appear under the *gitified artifacts* path in the ref-branch manifest. Note that `display/LE` will **not** be under that path — it came from Qualcomm already gitified and lives at its own upstream path (`platform/…/qcom-proprietary/…`). The manually-gitified ones are the ones under the gitified-artifacts directory. Compare against the previous release's manifest to confirm the path.

### 10.10 The volatile branch case

🎙 QSSI is shared across Android versions, and its ref branch moves forward with the highest imported AU tag. Sometimes a release arrives whose QSSI tag is **behind** what the ref branch already has.

**Example given:** ref branch is at release 80. A new product release requires QSSI release 72. You cannot import 72 on top of 80.

**Procedure:**
1. Branch out from the **previously imported tag below the target** (e.g. release 68)
2. Create a **volatile branch** from it
3. Import onto the volatile branch — **still pushing the exact real AU tag** (not a test tag). So every project ends up correctly tagged; only the branch differs.
4. **In the import completion email, state explicitly that a volatile branch was used and why** (ref branch already at a later tag). Consuming teams integrate from that volatile branch.

🎙 Official builds keep pointing at the QSSI ref branch. The ref branch itself carries only the `default.xml` with the latest tags — projects are pushed directly to individual gits, so the volatile branch does not fragment anything.

**Volatile branches are also used for testing**, paired with `AU_TAG_INTERNAL` (a `test_NN_<AU_TAG>` tag), on stage.

### 10.11 Project-name rewrites at push time

🎙 Before pushing, the script rewrites certain project names. You must **verify these landed correctly** after every import.

| Rewrite | Reason |
|---|---|
| `platform/external/dtc` → **`…dtc-kernel`** (suffix `-kernel`) | The DTC project exists in **both** kernel and QSSI trees with **different content**. Sony asked for them to be distinguishable, so the kernel one gets a `-kernel` suffix. |
| **cuttlefish** project → suffixed similarly | Same collision, reported by the HQ team on a recent import: *"we have two gits with the same name, please create the new one with any suffix to identify it."* |
| Strip `_group` / `_repo` suffixes on some QSSI projects | Upstream had e.g. `build_group` → Sony side becomes `build/blueprint`, `build/release`, `build/soong`. Similarly `trade federation` variants. |

🎙 Important nuances:
- The `_group` stripping is becoming obsolete — **Qualcomm has removed the group suffix upstream on recent releases**, so newer imports arrive already as `build/…`. The `_repo` variant is still in transition.
- **`repo` itself must NOT be truncated.** There's an explicit exclusion so that a project genuinely named `…_repo` is not mangled. Verify this survives.
- The rewrites are per-project lines in the script — adding another is a one-line change plus the full review process.

**Where to verify:** `project_list.xml` inside the job workspace (pre-push), and `default.xml` on the ref branch (post-push). Then open the project on the review server and confirm the tag landed.

### 10.12 Standalone QSSI

🎙 Separate from the per-product QSSI jobs there is a **standalone QSSI** import job (e.g. QSSI17 standalone).

| | Product-bundled QSSI | Standalone QSSI |
|---|---|---|
| Distro | `Snapdragon Premium <year> … AMSS Standard OEM` | `LA.QSSI.<ver>` |
| Manifest git | product manifest | different |
| Normally triggered by | CodeSync team | 🎙 the other team ("Lund"?) |
| Ref branch | same QSSI ref branch | **same QSSI ref branch** |

Both import into the **same** QSSI ref branch. So when checking whether you're up to date on QSSI you must check **both** release streams.

🎙 **This caused a real incident** — see [§14.3](#143-worked-example-the-standalone-qssi-delay).

---

## 11. Miscellaneous jobs

### 11.1 Delete garbage files in EFS mirror

📊 Slide 29. Template: `template-mirroring.yaml`.
Deletes temporary files created by git commands under `/mnt/efs/gitmirror`, matching a pattern defined in the job, **last modified more than one day ago**.

### 11.2 Delete stale repository in mirror

📊 Slides 30–32. Template: `project-mirrors.yaml`.

Removes projects from the mirror manifest that have had no change within a given period.

**Parameters:** `MISSING_SINCE`, `DRY_RUN`, `USE_LOCAL_SCRIPTS`

**Flow** (📊 slide 32 diagram):
```
clone mirror manifest from git://review.ptc.sony.co.jp
        ↓
STALE_TIME defined from the MISSING_SINCE job parameter
        ↓
For each git project in the mirror manifest:
   clone it, compare its latest commit against STALE_TIME
   no change since STALE_TIME → the repository directory is deleted
        ↓
applied on codesync07 and AOSP_MIRROR
```
📊 It also **reports untracked files** for each project whose last-updated time is less than the stale time.

**Jobs:**
- `delete_stale_repository_mirror_review-plus.ptc.sony.co.jp_codesync07` — deletes from the REVIEW-PLUS mirror
- `delete_stale_repository_mirror_partner-android.googlesource.com_AOSP_MIRROR` — deletes from AOSP_MIRROR

> ⚠️ **Use `DRY_RUN` first.** This job deletes mirror content.

### 11.3 `list_manifest_tags`

🎙 Not in the deck, but operationally central. It lists, per component, the current tag on each of three sides:

| Side | Meaning |
|---|---|
| **CodeLinaro** | Tag available on CLO |
| **Chipcode** | Tag available on Chipcode |
| **Sony** | Tag currently on the Sony review-server ref branch |

**The rule: only proceed with an import when the new tag is present on BOTH CodeLinaro and Chipcode.** If one is still on the old tag, wait — importing from a half-published release will fail or import incomplete content.

**Exception:** 🎙 **kernel has no Chipcode entry** — Qualcomm never added kernel support there. For kernel, confirm on CodeLinaro only. ❓ Reason unknown.

### 11.4 Deploy and test jobs

- `code_sync_deploy_jenkins_jobs` — §5.1
- `code_sync_test_jenkins_jobs` (`project-test-jenkins-jobs.yaml`) — 🎙 gives the automatic +1 on a `code-sync` patch by validating YAML/JJB syntax
- 🎙 An email-notification job exists for informing consuming teams of a completed import; ❓ the presenter was going to check whether it is still compatible and share the link.

---

## 12. Runbook: performing a Qualcomm import

🎙 Session 3 opens with this checklist; sessions 4–5 fill in the verification. The team maintains a shared checklist sheet — **get access to it, this section is a reconstruction, not a replacement.**

### 12.1 Step 1 — Detect the release

**Source A: the release email.** Qualcomm sends release notifications.

> ⚠️ **You will receive many notifications for distros you must ignore** — test devices, other tiers, HLOS variants. Filter on:
> - The **distro must be one of ours** (get the list of Sony distros from the team)
> - The suffix must be **`AMSS Standard OEM`**
>
> Then note the **release number**.

**Source B: the Qualcomm site (`chipcode` / QPM).** Log in → the left pane lists distros → pick the product's distro → the release list appears, newest first, with release dates. Use this to confirm, and to catch releases when no email arrives (which does happen).

**Release notes:** previously on the web; **now only via the QPM3 desktop application**, which must be installed locally. 🎙 In practice notes arrive from Anupam-san or the MPE team; otherwise fetch from the Qualcomm page.

> ❓ **Account access.** At the time of the recorded sessions the incoming team did **not** have Qualcomm/chipcode accounts. All jobs run as **Watanabe-san's account**; individual accounts exist for manual checks. **Get accounts created — this blocks step 1 entirely.**

### 12.2 Step 2 — Get the tags

Three independent sources; cross-check at least two.

**Source A — the release note.** Find the **"Android build information"** table. Confirm:
- the release number matches
- the distro matches
- **the chipset matches your product** (release notes may list several chipsets)

The table lists all tags. You normally need: **vendor**, **kernel**, and **QSSI** tags. On older platforms, one or two techpack tags too.

**Source B — the `list_manifest_tags` job.** Run it and read off CodeLinaro / Chipcode / Sony per component. Proceed only when CLO and Chipcode agree on the new tag (kernel: CLO only).

**Source C — the Qualcomm site.** Recent releases publish the `repo init` / clone commands directly, with the tag names in them. If not published, match the **last three digits of the release number** against the tag suffix (e.g. release …177 → tag …177).

**Then:** confirm the parameter set internally (post to the team channel, get it peer-reviewed) before triggering.

### 12.3 Step 3 — Pre-import local sync

🎙 On the **VNC server** (faster than the code-sync box for this), for the target ref branch:

```bash
repo init -u <ref manifest> -b <REF_BRANCH>
repo sync
```

This gives you the **before** state — the tags currently on the ref branch. You will re-sync after the import to prove the tags moved.

### 12.4 Step 4 — Trigger the jobs

Jobs for different components **can run in parallel**. Trigger each of Kernel / QSSI / Vendor Techpack for the release.

Standard parameters:
- `AU_TAG` = the AU tag from step 2 (**mandatory even on platforms where `snap_release.xml` contains it** — deliberately kept mandatory to catch mismatches)
- `RELEASE_NUMBER` = full release number
- `REF_BRANCH` = default, unless a volatile branch is needed (§10.10)
- `PSEUDO_MIRROR_TREE` = **enabled** (unless a public/private path change makes the mirror unusable — see §15.3)
- `CLEANUP_WORKING_DIR` = checked
- `SKIP_STAGES_BEFORE` / `STOP_BUILD_AT_STAGE` = blank
- Techpack: **use the two-run procedure** (§10.9)

### 12.5 Step 5 — Post-import verification

Full detail in [§13](#13-runbook-verification). Summary:
1. `repo sync -c` on the VNC tree; confirm the new tags are checked out
2. Run the SHA-1 diff check (remote vs local)
3. Component-specific checks (kernel DTC/cuttlefish, QSSI name rewrites, techpack gitification)
4. Attach all outputs to the Jira ticket

### 12.6 Step 6 — Communicate

- Send the import-completion email
- **If a volatile branch was used, say so explicitly and explain why**
- 🎙 Notification practice differs per product — one product uses direct integration with the consuming team, another uses email. Confirm the current convention.

---

## 13. Runbook: verification

🎙 This section is the part the outgoing owner agreed with Watanabe-san as the required verification set. Do all of it.

### 13.1 Tag verification (all import jobs)

**The problem:** you want to prove the Sony ref branch now matches the Qualcomm remote. You can't just compare manifests — the download produces *many* manifest files, and the combined one only exists inside the job workspace.

**The method:**

```
   In the JOB WORKSPACE (code-sync server):
      the job has already produced the combined manifest
      extract remote SHA-1s from <component>_st  →  remote_hashes.txt
                                (qssi_st / kernel_st / vendor_st)

   On the VNC SERVER:
      repo sync the ref branch (before and after import)
      extract local SHA-1s      →  local_tags.txt

   Diff the two.
```

**Expected result:**
- **Vendor techpack jobs:** the *only* differences should be the **techpack artifacts** — they legitimately differ because Sony gitified them manually and Qualcomm's side has them as directories.
- **Kernel and QSSI jobs:** **no differences at all.**

Any other project appearing in the diff is a real problem.

> ❓ **Unresolved mechanics.** Getting `remote_hashes.txt` from the code-sync server to the VNC server for the diff was an open struggle in Session 5. The presenter's approach: open the file on the code-sync server, copy the contents, create a file with the same name on the VNC server, paste, diff there. The team found VNC's clipboard couldn't handle a file that large. The presenter said *"I'll confirm whether I copied from VNC to here or here to VNC"* — **this was never resolved.** Find a proper transfer method (scp/rsync between the boxes, or generate both files on the same host).
>
> 🎙 Note also **why** the job workspace is used rather than doing everything on VNC: the static/combined manifest only exists in the workspace, and VNC lacks the disk space to sync the full tree.

### 13.2 Kernel-specific checks

- `platform/external/dtc` → confirm the **`-kernel` suffix** was applied on the review server
- **cuttlefish** project → confirm its suffix was applied
- Confirm in `project_list.xml` (job workspace) and `default.xml` (ref branch), then open the project and check the tag in the log

### 13.3 QSSI-specific checks

- Confirm `_group` / `_repo` suffix handling:
  - `build_group` → `build/blueprint`, `build/release`, `build/soong` etc.
  - trade-federation projects handled per the current rule
  - **projects genuinely named `…_repo` must NOT be truncated**
- Compare `project_list.xml` (workspace, upstream naming) against `default.xml` (ref branch, Sony naming)
- Open a rewritten project on the review server → branches → logs → confirm the new tag

### 13.4 Vendor techpack checks

- **Run 1:** list the artifacts; confirm only `display/LE` is already a git; confirm **no new unhandled artifact**. Record in the ticket.
- **Run 2:** confirm **all** techpack artifacts are gitified; confirm they appear under the *gitified artifacts* path in the ref manifest; attach the project list to the ticket.
- The checksum bracket (§10.9) does this automatically too — but the job aborting is your safety net, not your evidence. Record the manual confirmation.

### 13.5 Tag-counter check

From the `ref-tag` stage log: **`tag OK` + `tag exists` should account for every project, with `failed` = 0.** On a resumed run, the previously-tagged projects show as `tag exists`.

### 13.6 Spot-check on the review server

Pick a project (e.g. `kernel/common`):
1. Find its **upstream branch** from the manifest
2. On the review server, view that upstream branch's log → confirm the latest tag
3. View **Sony's ref branch** for the same project → confirm the same tag
Both should match.

---

## 14. Runbook: failure handling and troubleshooting

### 14.1 Import job failures

**The recovery pattern:**

```
1. Identify the STAGE at which the job failed  (report this — it's the first thing anyone will ask)
2. Re-trigger with:
       SKIP_STAGES_BEFORE  = <the failed stage>
       CLEANUP_WORKING_DIR = UNCHECKED     ← critical
3. The job resumes from that stage using the existing workspace
```

**Exception — failures in `syncsnap`.** 🎙 If the failure is during the download stage, prefer a **full clean re-run** (cleanup checked) rather than resuming. A partially-downloaded tree is not worth trusting.

**Most failures are transient network errors.** 🎙 Signatures to look for in the log:
- `unable to fully sync the tree` / `downloading network changes failed`
- `index invalid packet`, `invalid pack out`, socket errors
→ These mean network, not code. Re-trigger.

**Should you debug on stage?** 🎙 No, not for network failures — prod will hit them too and re-triggering in prod is the fix. Use stage when you suspect a **script problem** and want to debug, or to test a change with a volatile branch + test tag.

### 14.2 Mirror / fetch failures

🎙 Chipcode and CodeLinaro mirror jobs fail relatively often because the gits are huge and the sync is network-bound. **Fetch errors there are expected and classified as transient.**

**Triage rule:**

| Pattern | Meaning | Action |
|---|---|---|
| A **different** git fails each time | Network | Transient — subsequent build usually passes |
| The **same** git fails repeatedly | Possibly removed/renamed upstream | Investigate (below) |

**Investigating a persistently failing git:**
1. `git ls-remote <the exact source URL from the failing command line>` — is it reachable at all? The failing job log gives you the URL to use.
2. Add verbose tracing: `GIT_TRACE=1`, `GIT_TRACE2=1`, `repo -v`, and re-run `repo init` + `repo sync` **for that project only** in a test workspace under code-sync. Look for HTTP 503s or other specifics.
3. Log in to the Qualcomm/CodeLinaro account and check whether the repository still exists.
4. Only then raise a ticket to Sony (Onishi-san / Yuko-san) with the logs, asking whether the git is obsolete and can be removed from the manifest.

> 🎙 **Do the troubleshooting before escalating.** The presenter was explicit that steps 1–3 are expected before reporting to Sony.

### 14.3 Worked example: the standalone QSSI delay

🎙 A real incident from Session 4, useful because it chains three of the gotchas in this document.

**What happened:**
1. A standalone QSSI release (89) was published but the team that normally imports it **didn't**. The CodeSync team only found it by checking the standalone distro's release list separately from the product distro's.
2. Meanwhile the OSS manifest path for that release had **moved from public to private**. Someone changed the job configuration **manually in Jenkins** to point at the new manifest path.
3. But the **internal mirror path in the script** was still the old (public) one. So with `PSEUDO_MIRROR_TREE` enabled, the mirror reference wouldn't resolve and the job would fail.
4. Workaround: run **without** the pseudo mirror. That made the job dramatically slower; it got interrupted once and had to be re-triggered.

**Three lessons:**
- **Check both release streams for QSSI** (product distro *and* standalone `LA.QSSI.<ver>`), and compare against the last-imported release number to spot gaps.
- **A public→private path move is a two-place change** — the project YAML **and** the mirror path in the script. Changing only one leaves the mirror broken. See §15.3.
- **Manual job-config edits in Jenkins are outside the review process** and will be reverted by the next deploy. Fix it properly via a patch.

---

## 15. Runbook: recurring change requests

### 15.1 Request: start syncing a new git

🎙 The complete flow (as done for the most recent addition, a "quick share" git):

```
1. Sony provides the source URL for the git to sync
2. ▶ CHECK: does the target repository already exist on review.ptc.sony.co.jp?
       (git ls-remote, or check Gerrit)
   ├── Yes → continue
   └── No  → ask Sony to raise a repository-creation request.
             Sony raises it (SOMC CM); it is approved by the
             relevant functional area. WAIT for creation.
             ⚠️ CodeSync does NOT raise this request.
3. Add the job entry in the project YAML (sync_git template)
4. Patch → stage → verify job created → review → merge → cherry-pick to prod
5. Trigger and confirm the first sync
```

> 🎙 **This ordering was learned the hard way** — the job was created first, the target git turned out not to exist, and the request had to be raised afterwards, delaying things.
>
> 🎙 **A checklist for this does not exist yet.** Session 2 action item: create one. Consider this the draft.

### 15.2 Request: stop syncing a git / retire a release branch

Remember the **two places**:
1. Remove the sync job from the project YAML
2. **Remove the branch from the combined mirror manifest job** (§7.6) if it is one of the combined branches

### 15.3 A release moves from public to private (or back)

🎙 Qualcomm moves manifest paths between public (`CLO/LA/…`, no auth) and private (`CLO private`, auth required) — **with no notification**. You discover it by reading each release note.

**How to detect it:**
- Compare the current release note's `sync_snap_v2.sh` invocation parameters against the previous release's — the chipcode path / CodeLinaro path parameters will differ
- Or: `git ls-remote` the manifest git URL; failure without auth means private
- 🎙 On the newest platform generation the paths moved into `snap_release.xml`, so check there instead

**What to change — THREE places:**

| # | Where | What |
|---|---|---|
| 1 | Project YAML | `oss_manifest` / manifest path → the new public or private URL |
| 2 | Project YAML | `caf_remote_suffix` → set to `private`, or **removed** when moving to public |
| 3 | **Import script** | The **mirror path** in the per-component `syncsnap` block |

> ⚠️ **Missing #3 is the failure mode from §14.3.** The job appears configured correctly but `PSEUDO_MIRROR_TREE` silently points at a path that no longer exists. 🎙 In the script, previously-migrated components have the old path commented out and the new one active — follow that pattern.

### 15.4 A new techpack artifact appears

See §10.9. Summary: detect it in Run 1 → add it to the artifacts list in the script (full review process) → **confirm the repository exists on the review server** → re-run.

### 15.5 New remotes appear in the manifest

🎙 Nobody notifies you. Per release, diff the manifest XML's `<remote>` list against the previous release. If a new remote prefix appears, the push filter patterns in `syncsnap-push` need extending (§10.8, stage 5) or those projects will silently not be pushed.

### 15.6 A new import job for a new platform / component

🎙 Most of the parameters have defaults; you supply the release-specific ones:

1. Get from **Sony**: the `ref_branch` (and confirmation of the project naming convention). Confirm the ref branch already exists.
2. Get from the **release note**: distro, tree type, OSS manifest path (public/private), `prop_opt`, image type, and any new `sync_snap_v2.sh` options
3. Get from the **downloaded chipcode tree**: `path_to_sync_script_dir` (where `sync_snap_v2.sh` sits)
4. Copy an existing project-YAML block for the same component, change the above
5. Patch → stage (verify the job is created) → review → merge → cherry-pick to prod

> ⚠️ 🎙 **Check every release note for new `sync_snap_v2.sh` parameters.** If Qualcomm adds an option, it must be added to the script's invocation or the download will be wrong. This is a standing per-release check.

---

## 16. Open items and unanswered questions

### 16.1 Owed by the outgoing owner (promised during the sessions, verify delivery)

| # | Item | Session |
|---|---|---|
| 1 | Reference tickets for **mirror** issues and mirror-manifest updates | 1 |
| 2 | Reference tickets for **Sync Git** jobs (if any exist) | 2 |
| 3 | The **script/reference for updating the mirror manifest** for chipcode & CodeLinaro | 1 |
| 4 | Reference ticket for the **gitification content check** | 4 |
| 5 | Reference ticket for the **newest-platform import adaptation** (the initial patch) | 4 |
| 6 | Reference ticket for the **tagging script update** | 5 |
| 7 | Ticket for the **cuttlefish** project-name handling | 4 |
| 8 | Sample **release notes** for study | 3 |
| 9 | A **document for server access**: SSH commands, workspace locations, VNC request & connection | 1 |
| 10 | Confirm `path_to_sync_script_dir` derivation by showing it in a downloaded chipcode tree | 3,4 |
| 11 | Confirm **why `unshallow` runs** when `shallow_clone=false` | 4,5 |
| 12 | Confirm the **`remote_hashes.txt` copy direction** for the SHA-1 diff | 5 |
| 13 | Locate/verify the **import notification email job** | 3 |
| 14 | Example logs of a **resumed (skip-stages) import** | 5 |
| 15 | Explain the **chipset selection** for the newest platform (why the release note still points at the older chipset) | 3 |

### 16.2 Genuinely unknown — nobody currently knows

| # | Question |
|---|---|
| 1 | **Why is `repo init` done manually for the CodeLinaro mirror?** Not known by the current owner or Yamanouchi-san; inherited practice. **If that mirror needs rebuilding, the procedure is undocumented.** |
| 2 | **Why does Chipcode not publish kernel tags?** Kernel is verified against CodeLinaro only. |
| 3 | **What does Qualcomm customer ID `1055` correspond to?** Used everywhere; meaning unknown. |
| 4 | **Which gits are actually shared** in the Sync Git persistent directory, and **which manifests share them**? Never audited. |
| 5 | **Which team requested** the shared-directory arrangement, and why? |
| 6 | **Is the S-Link-Spica / review-plus mirror + combined manifest still needed?** No recent LE1/LE3 imports; consumers unknown. Should be raised with Sony. |
| 7 | Is the separate `vendor_st` vs `vendor_techpack_st` split needed at all, or purely cosmetic? (Presenter believed cosmetic.) |

### 16.3 Things this document could not verify

- All of [§10](#10-qualcomm-import-jobs) — the current import scripts are not in this checkout
- The 25Q4 sync-manifest job's actual branch (deck says `25Q3-fs-release`, likely a typo)
- The mapping between `/mnt/efs/...` parameter values and the EBS1/EBS2 mounts
- The current product codenames (transcript ASR is unreliable; deck matrix is a generation behind)
- Exact stage script filenames (`prepare.sh`, `stage_skipper.sh`, `import.sh` are the names heard in audio)

### 16.4 Agreed next actions from the KT

🎙 From the close of Session 5: **the next import is to be performed by the incoming engineers** — one import each — **following the complete checklist end to end**, with the outgoing owner available for questions. That is the acceptance test for this handover.

Also outstanding as team actions:
- Create a **checklist for new-git requests** (§15.1 is a draft)
- Add to the import checklist: the standalone-QSSI check, the public/private mirror-path change, the kernel DTC/cuttlefish verification, the techpack artifact verification, and the tag SHA-1 diff
- Get **Qualcomm/chipcode accounts** created for the incoming team

---

## 17. Appendices

### 17.1 Glossary

| Term | Meaning |
|---|---|
| **AML** | Android Mainline — the `*-aml-prebuilt-release` branches |
| **AU tag** | Qualcomm's release tag (`AU_LINUX_…`), the unit of an import |
| **CAF** | Code Aurora Forum — Qualcomm's former open-source host, superseded by CodeLinaro |
| **Chipcode** | `chipcode.qti.qualcomm.com` — Qualcomm's proprietary release distribution |
| **CLO** | CodeLinaro (`git.codelinaro.org`) — Qualcomm's open-source host |
| **Distro** | Qualcomm's release line, e.g. `Snapdragon Premium 2025 SPF1 AMSS Standard OEM` |
| **FS release** | Pre-access code released via `platform/vendor/pdk/generic/fs/manifest` |
| **Gitification** | Converting a plain directory shipped by Qualcomm into a git repo and pushing it |
| **Grease** | Legacy Qualcomm proprietary distribution channel, largely superseded by Chipcode |
| **HY11 / prebuilt-hy11** | The prebuilt-content git; also the name of the import stage that creates it |
| **`ohd`** | The remote/namespace used for Google-sourced content (`refs/heads/ohd/*`) |
| **Pseudo mirror** | A mirror tree built inside the job workspace (symlinks to the real mirror) for faster download |
| **QSSI** | Qualcomm Single System Image — the system-side tree, shared across Android versions |
| **`ref_st` / ref branch** | Sony's internal reference tree/branch on `review.ptc.sony.co.jp` |
| **`review` / `review-plus`** | Sony's Gerrit servers — content vs tooling |
| **SCPS** | The environment CodeSync originally ran on; survives as the deck title and the old branch name |
| **Techpack** | The Vendor Techpack bundle (audio, camera, display, …) |
| **Tree type** | Which Qualcomm tree is being imported (`kernel`, `LA_QSSI`, `LA_vendor_techpack`, …) |
| **Volatile branch** | Temporary branch used when the ref branch is ahead of the incoming release, or for testing |

### 17.2 The previous-generation import scripts in this checkout

✅ Not the current implementation, but several concepts carried forward directly. Useful for reading the old `sync_qcom*` jobs and for understanding where the current design came from.

| Script | Role | Concept that survives |
|---|---|---|
| `sync_snap.sh` | Qualcomm's own tree-download script (v1). Handles QSSI tree / vendor tree / single tree × Grease / Chipcode. Header comments document the matrix of where OSS vs proprietary content lives. | Superseded by `sync_snap_v2.sh` (fetched from distro git rather than living in the repo) |
| `qcom-caf.sh` | `repo init` from the CAF mirror with `caf_$AU_VERSION.xml`; strips 40-char pinned revisions and `clone-depth`; syncs; then pushes each branch containing `$REPO_LREV` to Sony. Has a **force-push backup path**: before force-pushing a non-ancestor, back the old ref up to `<br>-obsolete-<date>`. | → `syncsnap` + `syncsnap-push` |
| `qcom-grease.sh` | Grease-side equivalent | Grease path now largely unused |
| `qcom-hy11.sh` | Downloads `prebuilt_CDR005_$AU_VERSION.tar.gz`, extracts, **`git init` in the prebuilt dir, commit, push** to `platform/vendor/qcom-proprietary/prebuilt-hy11${HY11_SUFFIX}` | → the `hy11` stage. **This is the ancestor of gitification.** |
| `qcom-ref.sh` | Runs `join_manifests.sh` over the CAF and Grease manifests → `$AU_VERSION.xml`; rewrites `fetch=`, remotes, upstreams; injects the prebuilt-hy11 project; `repo init`/`sync` on the ref branch; `repo forall … git push …:refs/heads/$REF_BRANCH`; commits the combined manifest to `grease/$AU_VERSION.xml` | → `ref-manifest`, `ref-repo-init/sync`, `ref-push`. **The `grease/$AU_TAG.xml` manifest path in the current design comes from here.** |
| `qcom-ref-tag.sh` | Clones `semctools/cm_tools`; `static_manifest.py` → `.repo/static.xml`; **`tag-official-release.py`** applies `$AU_VERSION`; pushes tags; rewrites `default.xml` to point at `refs/tags/$AU_VERSION`; tags the manifest git | → `ref-tag`. **`tag-official-release.py` is still the tagging tool.** |
| `qcom-extract-patches.sh`, `qcom-ref-patched.sh`, `qcom-ref-tag-patched.sh` | The "private CAF + patches" variant | Not used currently |
| `qcom-ref-tag-patched.sh` | ditto | |

✅ `template-qcom.yaml` shows the old orchestration — and one detail worth copying forward: `qcom-ref.sh` is wrapped in a **10-attempt retry loop with 30s sleeps**, because Gerrit replication lag makes the ref stage flaky. The current design's `sleep 30; git fetch --all` in `ohd.sh` is the same instinct.

### 17.3 Parameter quick reference

**Mirror jobs:** `SOURCE_URL`, `MIRROR_ROOT`, `BRANCH`, `MANIFEST`, `REPO_SYNC_ARGS`, `EXCLUDED_PROJECTS`
**Sync Git jobs:** `SOURCE_URL`, `TARGET_URL`, `REFSPEC`, `PUSH_ARGS` (+ injected `USE_SYSTEM_GIT_CONFIG`, `USE_GIT_SYNC_PERSISTENT_DIRECTORY`)
**Sync Manifest jobs:** `MANIFEST`, `BRANCH`, `TAG`, `REMOTE`, `SKIP_PUSH`, `SKIP_SYNC`, `SOURCE_GERRIT`, `REPO_INIT_ARGS`, `REPO_FORALL_ARGS`, `PUSH_MODE`, `GIT_PUSH_ARGS`, `EXCLUDED_PROJECTS`, `SECURITY_PATCH_IMPORT`
**Import jobs:** see §10.4
**Stale-repo job:** `MISSING_SINCE`, `DRY_RUN`, `USE_LOCAL_SCRIPTS`

### 17.4 People referenced in the sessions

Kept as they appear in the material (see the transcript warning — spellings are ASR output and may be imprecise).

| Name | Context in the sessions |
|---|---|
| **Watanabe-san** (Yasuhiro Watanabe, `jp21771`) | Account used by all CodeSync jobs; raises repository-creation requests; sets the verification requirements |
| **Yamanouchi-san** | Previous owner; source of inherited practices; authored local script adaptations for the newest platform |
| **Anupam-san** | Internal reviewer (+1); supplies release notes |
| **Ashun-san** | Required +1 before Sony review |
| **Onishi-san / Yuko-san** | Sony contacts for escalating unreachable/obsolete gits |
| **Christian-san** | Raised a recent repository-creation request |
| **Samrat** | Previously shared server-access commands informally |
| **Karthik, Suman** | Team members named during the sessions |
| **BUT team / MPE team / HQ team** | Consuming teams; BUT syncs chipcode on Monster PC; HQ reported the cuttlefish name collision |

### 17.5 Source material inventory

| File | Contents |
|---|---|
| `CodeSync_Jobs_ptc.pptx` | 33 slides. Job matrices (5, 12–13, 18–19, 22, 25–26), parameter lists (7, 10, 20, 23, 30), architecture diagram (4), component/manifest diagram (6), **import stage SmartArt (8–9)**, mirror flow (11), sync-manifest flow (24), stale-repo flow (32) |
| `session_transcriptions/clean/CodeSync KT - Session01.vtt` | Overview, architecture, mirror sync jobs, mirror rationale, node/storage layout, mirror troubleshooting |
| `…Session 02.vtt` | Change-management process (stage→prod), Sync Git jobs, `git.sh` walkthrough, persistent directory |
| `…Session 03.vtt` | Import: release detection, tag sourcing, project/template variables, `distro_full_name`, workspace layout, lock file, stage list |
| `…Session 04.vtt` | Import stages 1–5 in detail, pseudo mirror, gitification + checksum, two-run techpack procedure, name rewrites, standalone QSSI incident |
| `…Session 05.vtt` | Import stages 6–10, ref-side manifest handling, tagging & counters, full verification procedure, failure recovery |
| `session_transcriptions/anonymize_vtt.py` | The anonymisation tool used on the transcripts |
| `code-sync/` | Older repo snapshot — see the warning at the top |

---

*End of document.*
