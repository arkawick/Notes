# JJB Validation Failure — `offbuild_test_jenkins_jobs` #9849: undefined template variable `csm-source`

**Job:** `offbuild_test_jenkins_jobs`
**Build:** `#9849`
**Node:** `EC2 (AWSJ2) ci-cm_CM_UTIL_FIXED` (`i-0d1c29ffb596dc6b2`), label `CM_UTIL_FIXED`
**Trigger:** Gerrit patchset-created — [change 3253939](https://review.ptc.sony.co.jp/c/semctools/offbuild/+/3253939), **patchset 5** (`refs/changes/39/3253939/5`)
**Repo under test:** `semctools/offbuild`, branch `master`
**Base revision at checkout:** `03393bd92011e78c6e0dfd30b121246ed199d86f` — *"Change build schedule for a16-elbe2-offbuild"*
**Result:** `FAILURE`

> **One-line summary:** Patchset 5 of change 3253939 adds `CSM_SOURCE={csm-source}` to a
> Jenkins Job Builder template but never defines `csm-source`, so JJB aborts with
> `KeyError: 'csm-source'` while rendering `isobuild_superlabel_android`.
> **Fix: add `csm-source` to the `isobuild-defaults` block in `template-isobuild.yaml`.**

---

## 1. Executive summary

`offbuild_test_jenkins_jobs` is a **gating job**: it fires on every patchset touching
`jenkins-jobs/**` in `semctools/offbuild` and runs `jenkins-jobs test` over the YAML to
prove the job definitions still render. It is not a build job — nothing is compiled or
deployed. A failure here means *the proposed change would produce invalid Jenkins job
configuration*.

Patchset 5 introduces a new environment variable into the `inject` block of the isobuild
Android superlabel template:

```
CSM_SOURCE={csm-source}
```

JJB resolves `{...}` placeholders against a merged parameter dictionary assembled from the
`defaults` block, the `job-group`, and the project file. **`csm-source` is not defined in
any of them**, so the lookup raises `KeyError` and JJB exits non-zero.

This is a self-contained defect in the patchset. It is **not** an infrastructure problem,
and it is unrelated to the Ubuntu 24 / SBE migration issues tracked separately.

---

## 2. The error

From `#9849.txt`:

```
3978  ERROR:root:Problem formatting with args:
3990  ERROR:root:Failure formatting template '{name-prefix}isobuild_superlabel_android', ...
3991  Traceback (most recent call last):
4008  KeyError: 'csm-source'
4012  Traceback (most recent call last):
4036      raise JenkinsJobsException(desc)
4037  jenkins_jobs.errors.JenkinsJobsException: csm-source parameter missing to format
        SYSTEM_COMPONENT=android
        DEBIANREPO_URL={debianrepo-url}
        GERRIT_USER={gerrit-user}
        JOB_PROPFILE=_propfile
        USE_CODE_SYNC_MGR={use-code-sync-mgr}
        CSM_SOURCE={csm-source}          <-- unresolvable
4225  make: *** [../configurator/Makefile:38: test] Error 1
      Build step 'Execute shell' marked build as failure
      Finished: FAILURE
```

The `make` error on line 4225 is only the wrapper reporting JJB's exit status. The
actionable message is line 4037.

**Failing template:** `{name-prefix}isobuild_superlabel_android`

**Scope of failure — exactly one variable.** A grep over the complete 4232-line log
returns a single distinct `KeyError`:

```
$ grep -ao "KeyError: '[^']*'" '#9849.txt' | sort -u
KeyError: 'csm-source'
```

---

## 3. Where the failure occurred in the job

The builder (`config.xml`) runs two `cm_tools` scripts:

```sh
cm_tools/hudson-scripts/test-jenkins-jobs.sh
cm_tools/hudson-scripts/exclude-mlc-branch.sh
```

`test-jenkins-jobs.sh` iterates over the changes in the patchset. For each it runs
`run_test_on_patch()`, which checks out the patch, runs `make -C jenkins-jobs`, then checks
out `HEAD~1` and diffs the generated XML so a reviewer can see what the change alters.

`make` delegates to the `jenkins-jobs-configurator` submodule
(`.gitmodules` → `git://review-plus.ptc.sony.co.jp/jenkins-jobs-configurator`, mounted at
`configurator/`), whose `Makefile:38` defines the `test` target that shells out to
`jenkins-jobs test`.

The relevant sequence in the log:

| Line | Event |
|---|---|
| 3821 | `make clean-out -C jenkins-jobs` — previous iteration cleaned up |
| 3824 | `git fetch origin refs/changes/39/3253939/5` |
| 3827 | `* branch refs/changes/39/3253939/5 -> FETCH_HEAD` |
| 3828, 3854 | `git checkout FETCH_HEAD` |
| 3857 | `make -C jenkins-jobs` |
| 3978–4037 | **JJB fails rendering the template** |
| 4225 | `make: *** [../configurator/Makefile:38: test] Error 1` |

Earlier iterations (lines 82, 410, 1317, 1455, 1949, 3070) completed successfully. **The
failure occurs while the patchset itself is checked out**, which confirms the defect is in
the proposed change and not in the base revision.

---

## 4. Root cause

### 4.1 What the patchset changes

Current `master` — `template-isobuild-superlabel-android.yaml:72-77` — has **five** lines
in the inject block:

```yaml
      - inject:
          keep-system-variables: true
          keep-build-variables: true
          override-build-parameters: true
          properties-content: |
            SYSTEM_COMPONENT=android
            DEBIANREPO_URL={debianrepo-url}
            GERRIT_USER={gerrit-user}
            JOB_PROPFILE=_propfile
            USE_CODE_SYNC_MGR={use-code-sync-mgr}
```

The paramdict dumped in the error (log line 3990) shows **six**, with `CSM_SOURCE={csm-source}`
appended. That line is what patchset 5 adds.

### 4.2 Why it fails

JJB substitutes `{name}` placeholders from a parameter dictionary merged, in precedence
order, from:

1. the `defaults:` block named by the template (`isobuild-defaults`),
2. the `job-group` entry,
3. the project file (`ci*/project-isobuild.yaml`).

A placeholder with no matching key is a hard error, not a warning and not an empty string.

**`csm-source` is defined nowhere in the tree.** A recursive grep across
`offbuild/jenkins-jobs/` returns zero hits for either `csm-source` or `CSM_SOURCE` on
master. Every sibling placeholder on those same lines resolves cleanly:

| Placeholder | Defined in | Line |
|---|---|---|
| `{debianrepo-url}` | `template-isobuild.yaml` (`isobuild-defaults`) | ~57 |
| `{gerrit-user}` | `template-isobuild.yaml` (`isobuild-defaults`) | ~55 |
| `{use-code-sync-mgr}` | `template-isobuild.yaml` (`isobuild-defaults`) | 76 |
| **`{csm-source}`** | **nowhere** | **—** |

The paramdict in the log confirms this directly — it carries `use-code-sync-mgr`,
`code-sync-mgr-version` and `sbe-image-repo`, but no `csm-source`.

### 4.3 Which project instance tripped it

The failing paramdict shows `netrcconfig: 'cm-account-netrc-credentials-odm'` and
`use-code-sync-mgr: 'true'`, identifying the ODM project
(`ci-cm-odm.ptc.sony.co.jp/project-isobuild.yaml`).

This is incidental — JJB aborts on the first template it cannot render. **Every** project
instantiating this template is equally affected, because the missing key is absent from the
shared defaults rather than from one project file.

---

## 5. Fix

Add the variable to the `isobuild-defaults` block in `template-isobuild.yaml`. The block
header is at lines 36–37 (`- defaults:` / `name: 'isobuild-defaults'`); the new entry
belongs with its siblings after line 77:

```diff
     use-code-sync-mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: ''
     sbe-image-repo: 'aws'
     expose-supported-pps-only: 'true'
```

Every isobuild template declares `defaults: 'isobuild-defaults'`, so this single line
covers all of them.

### 5.1 Land it in the same patchset

Amend change 3253939 and upload patchset 6 rather than filing a separate change. The
template line and its default must merge together — separating them leaves master broken in
whichever order they land.

---

## 6. Open questions for the change author

Two things the failing test cannot answer:

**Is `''` the correct default value?** An empty string is the safe, behaviour-preserving
choice: it makes `CSM_SOURCE` render as empty for jobs that do not use Code Sync Manager,
which is consistent with `use-code-sync-mgr` defaulting to `'false'`. But if `csm-source` is
meant to carry a real value (a repository URL, a branch, a version), projects that set
`use-code-sync-mgr: 'true'` will likely need a per-project override in their
`project-isobuild.yaml`. **Making the test pass does not prove the runtime value is right.**

**Were other templates changed in the same patchset?** JJB aborts on the first failure, so a
second missing definition elsewhere in the patch would not appear in this log. In
particular, if `CSM_SOURCE={csm-source}` was also added to any `template-offbuild-*` file,
note that `template-offbuild.yaml` carries **two** separate defaults blocks
(`code-sync-mgr-version` appears at both line 113 and line 163) — both would need the same
addition.

---

## 7. Verification before re-uploading

Run the same check the gating job runs, from `offbuild/jenkins-jobs`:

```sh
# 1. every use of the variable should have a matching definition
grep -rn "CSM_SOURCE\|csm-source" .

# 2. render all YAML (this is what Makefile:38 invokes)
make test
```

Expected: the grep shows the template use **and** a definition in every defaults block that
feeds it; `make test` exits 0.

The gating job re-runs automatically on patchset upload, and a green result posts
`Verified +1` back to change 3253939.

---

## 8. Assessment

| | |
|---|---|
| **Severity** | Low — gating job caught it before merge; no production job affected |
| **Blast radius if merged** | All `isobuild_superlabel_*` jobs would fail to generate |
| **Fix size** | One line |
| **Risk of fix** | Minimal — adds a default, changes no existing behaviour |
| **Related to Ubuntu 24 / SBE migration** | No — unrelated defect |

The gating job did exactly its job here. No infrastructure action is required; this closes
when patchset 6 passes and merges.






```sh
I'll analyze it. Let me find the folder.

  Read 1 file, ran 4 shell commands

Found the error. Let me pin down the exact YAML — you have the offbuild repo locally.

  Ran 11 shell commands

Confirmed — exactly one undefined variable.

The error

#9849.txt lines 4008 / 4037:

KeyError: 'csm-source'
jenkins_jobs.errors.JenkinsJobsException: csm-source parameter missing to format
SYSTEM_COMPONENT=android
DEBIANREPO_URL={debianrepo-url}
GERRIT_USER={gerrit-user}
JOB_PROPFILE=_propfile
USE_CODE_SYNC_MGR={use-code-sync-mgr}
CSM_SOURCE={csm-source}          ← this line

Failing template: {name-prefix}isobuild_superlabel_android. make: *** [../configurator/Makefile:38: test] Error 1 is just the wrapper reporting JJB's non-zero exit.

Root cause

This job is Gerrit-triggered on jenkins-jobs/** patchset-created, so it's validating a proposed change, not master. The patchset adds CSM_SOURCE={csm-source} to the inject properties-content in template-isobuild-superlabel-android.yaml — but never defines csm-source.

Current master (your local checkout) has five lines there, template-isobuild-superlabel-android.yaml:72-77:

          properties-content: |
            SYSTEM_COMPONENT=android
            DEBIANREPO_URL={debianrepo-url}
            GERRIT_USER={gerrit-user}
            JOB_PROPFILE=_propfile
            USE_CODE_SYNC_MGR={use-code-sync-mgr}

I grepped the whole jenkins-jobs tree: csm-source / CSM_SOURCE appears nowhere. Every other {...} on those lines resolves — debianrepo-url, gerrit-user, use-code-sync-mgr are all in the isobuild-defaults block. JJB builds a merged paramdict from defaults + job-group + project vars and substitutes {name} against it; a key that isn't there is a hard KeyError.

The dump in the log confirms it: the paramdict contains use-code-sync-mgr, code-sync-mgr-version, sbe-image-repo — and no csm-source.

Fix

Add the default alongside its siblings in template-isobuild.yaml. The isobuild-defaults block starts at line 36; the variable belongs after line 77:

     use-code-sync-mgr: 'false'
     code-sync-mgr-version: '1.9.0'
+    csm-source: ''
     sbe-image-repo: 'aws'
     expose-supported-pps-only: 'true'

Every isobuild template declares defaults: 'isobuild-defaults', so one line covers all of them, including the ODM project that actually tripped the error (its params show netrcconfig: cm-account-netrc-credentials-odm, use-code-sync-mgr: 'true').

This belongs in the same patchset — amend and re-upload rather than filing a separate change, since the template line and its default have to land together or master breaks.

Two things to check before you push

Is '' the right default? It's the safe, behaviour-preserving choice: jobs with use-code-sync-mgr: 'false' get CSM_SOURCE= set but empty, and nothing reads it. But whoever wrote the patch may intend a real default (a URL or branch), and projects that genuinely use CSM probably need a per-project value in their project-isobuild.yaml. The empty default makes the test pass; it doesn't tell you the runtime value is correct.

Did the patch touch other templates? I can only see the one that failed — JJB aborts on the first error, so a second missing definition elsewhere wouldn't appear in this log. If CSM_SOURCE={csm-source} was also added to any template-offbuild-* file, those use a different defaults block: template-offbuild.yaml has code-sync-mgr-version at both line 113 and line 163, so it carries two defaults blocks and both would need the same addition.

Quick way to catch all of it in one pass before re-uploading — run the same check the job runs, from offbuild/jenkins-jobs:

grep -rn "CSM_SOURCE\|csm-source" .
make test          # ../configurator/Makefile:38

The grep should show the template use and a matching definition in every defaults block that feeds it.


grep -rn "CSM_SOURCE\|csm-source" .
make test          # ../configurator/Makefile:38

The grep should show the template use and a matching definition in every defaults block that feeds it.
```