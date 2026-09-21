# 03 — Jenkins jobs and JJB templates

`cmweb-scripts/jobs_on_cloud/` holds **47 job templates** defined as
[Jenkins Job Builder](https://docs.openstack.org/infra/jenkins-job-builder/)
YAML. JJB compiles YAML into Jenkins job configuration and pushes it over the
REST API — the jobs are code, reviewed in Gerrit like everything else.

| Environment | Jenkins |
| --- | --- |
| Production | `https://ci-tools.ptc.sony.co.jp/job/cmweb/` |
| Stage | `https://ci-tools.ptc-stage.sony.co.jp/job/cmweb/` |
| Test | none |

---

## 1. File layout

```
jobs_on_cloud/
├── README                    conventions and Jenkins URLs
├── Makefile                  regenerates generic_project.yaml
├── defaults.yaml             node, credentials, proxy, logrotate, email — applied to every job
├── macros.yaml               shared parameters and builders
├── view.yaml                 the three Jenkins views
├── generic_project.yaml      GENERATED — the list of job names to instantiate
├── template_snapshot_manifest.yaml
└── <verb>_<something>.yaml   one file per job
```

The README states the naming rule: **`verb_something.yaml`**, and mandates that
keys appear in the same order as the tabs in the Jenkins Configure GUI:

```yaml
- job-template:
    (defaults:)
# General
    name:
    description:
    parameters:
    (logrotate:)  (concurrent:)  (node:)
# Source Code Management
    scm:
# Build Triggers
    (auth-token:)  triggers:
# Build Environment
    (wrappers:)
# Build
    builders:
# Post-build Actions
    (publishers:)
```

Parenthesised sections can be omitted because `defaults.yaml` supplies them.

### `generic_project.yaml` is generated

```make
update-project:
	@echo "- project:" >> $(PROJ_FILE)
	@echo "    name: generic" >> $(PROJ_FILE)
	@echo "    jobs:" >> $(PROJ_FILE)
	@jobs=`grep -h -e "^    name:"  $(TEMPLATE_FILES) | awk '{print $$2}'` && \
		for job in $$jobs; do echo "      - $$job" >> $(PROJ_FILE); done
```

JJB needs a `project` stanza listing which templates to instantiate. Rather than
maintain it by hand, `make update-project` greps every template's `name:` and
regenerates the list. `EXCLUDE_FILES` keeps `defaults`, `macros`, `view`,
`index_static_manifest`, `snapshot_manifest` and `template_*` out of it.

---

## 2. `defaults.yaml` — what every job inherits

```yaml
- defaults:
    name: global
    folder-name: 'cmweb'
    script-branch: 'cloudj2'
    app-branch: 'cloudj2'
    logrotate:
      daysToKeep: 365
    node: 'CMWEB_SLAVE_22'
```

| Setting | Effect |
| --- | --- |
| `node: CMWEB_SLAVE_22` | All jobs run on the Ubuntu 22.04 slave label |
| `logrotate: 365` | A year of build history — long enough to correlate a data problem with the run that caused it |
| `script-branch` / `app-branch` | `cloudj2` — the branch everything is built from |

**Injected environment** — including the corporate proxy, which every job needs
to reach anything outside `*.ptc.sony.co.jp`:

```yaml
    properties:
      - inject:
          properties-content: |
            SCRIPT_BRANCH={script-branch}
            APP_BRANCH={app-branch}
            http_proxy=http://proxy-sen.noc.sony.co.jp:10080
            https_proxy=http://proxy-sen.noc.sony.co.jp:10080
            no_proxy=ptc.sony.co.jp,amazonaws.com
```

**Wrappers** — workspace cleanup, an 8-hour timeout, and six credential
bindings:

```yaml
    wrappers:
      - workspace-cleanup
      - timeout:
          timeout: 480
      - credentials-binding:
          - ssh-user-private-key:
              credential-id: ssh_private_key
              key-file-variable: SSH_KEY_FILE
              username-variable: SSH_USERNAME
          - username-password-separated:
              credential-id: system_account_password      -> SERVICE_USERNAME / SERVICE_PASSWORD
          - username-password-separated:
              credential-id: jenkins_api_token            -> JENKINS_USER / JENKINS_TOKEN
          - username-password-separated:
              credential-id: db_account                   -> DB_USERNAME / DB_PASSWORD
          - username-password-separated:
              credential-id: opensearch_credentials        -> OPENSEARCH_AUTH_USERNAME / _PASSWORD
          - text:
              credential-id: ansible_vault_pass            -> ANSIBLE_VAULT_PASS
```

Every secret the pipeline needs arrives as an environment variable from the
Jenkins credential store. **No secret is in the YAML**, which is what lets these
files live in a reviewable git repository.

`workspace-cleanup` matters for correctness, not just disk: each job starts from
an empty workspace and does a full `repo sync`, so a job can never be
contaminated by a previous run.

Finally, every job emails `somc-sw-cmweb@sony.com` on failure.

---

## 3. `macros.yaml` — the shared building blocks

### Parameters

| Macro | Gives the job |
| --- | --- |
| `cmweb-parameter-gerrit-download-list` | `GERRIT_DOWNLOAD_LIST` — apply un-merged patches before running, e.g. `"cmweb-project 233738/5, cmweb-app 243932/5"` |
| `cmweb-parameter-gerrit-refspec` | `GERRIT_REFSPEC` — same, for `cmweb-scripts` |
| `cmweb-parameter-manifest` | `CMWEB_MANIFEST` — `default.xml` or `release.xml` |

`GERRIT_DOWNLOAD_LIST` is the thing to know about: **you can run any indexing
job against an unmerged change**, which is how indexing fixes get tested against
real production data before merge.

### Builders — the standard six-step pipeline

Almost every job is these, in order:

```yaml
    builders:
      - cmweb-setup-env
      - cmweb-setup-git
      - cmweb-mount-efs
      - cmweb-prepare-site
      - cmweb-generate-settings
      - cmweb-run-commands
```

| Builder | Does |
| --- | --- |
| `cmweb-setup-env` | Derives `FOLDER_NAME` / `FOLDER_URL` from `JOB_NAME`, injects them |
| `cmweb-setup-git` | `somc-setup-review`, installs the SSH key from `$SSH_KEY_FILE` at 0400, removes any `.netrc` |
| `cmweb-mount-efs` | `sudo mount -t efs fs-a18f0c81:/ /mnt/nfs` (prod) or `fs-a265d682` (stage); symlinks `repo-mirror_20` to `$WORKSPACE/repository` |
| `cmweb-prepare-site` | `repo init -u …/cmweb-manifest -m $CMWEB_MANIFEST -b cloudj2` then `repo sync -d -c -j4`; applies `GERRIT_DOWNLOAD_LIST` via `repo download` |
| `cmweb-generate-settings` | Writes `cmweb/secure.py` and `cmweb/settings_management.py` (below) |
| `cmweb-run-commands` | Runs the commands (below) |

Note `cmweb-mount-efs` ends with `ls -la ${WORKSPACE}/repository/` — a
deliberate fail-fast, so a job dies immediately if the mirror is not mounted
rather than indexing an empty repository.

### `cmweb-generate-settings` — environment by Jenkins URL

```bash
if [ "https://ci-tools.ptc.sony.co.jp/" = "${JENKINS_URL}" ]; then
  DB_HOST="cmweb.cm8tmtafyb32.ap-northeast-1.rds.amazonaws.com"
  OPENSEARCH_HOST="https://vpc-cmweb-prod-...aos.ap-northeast-1.on.aws"
  CACHE_HOST="cmweb.myfjt0.cfg.apne1.cache.amazonaws.com"
  CM_WEB_ENVIRONMENT="prod"
elif [ "https://ci-tools.ptc-stage.sony.co.jp/" = "${JENKINS_URL}" ]; then
  ... stage hosts ...
else
  echo "run this script on cloud Jenkins"
  exit 1
fi
```

The job identifies its environment **from the Jenkins URL it is running on** —
the same trick Ansible plays with the AWS account id. It then writes
`cmweb/secure.py` from the credential-bound environment variables, and:

```bash
echo "\"\"\"Support for Jenkins environment settings.\"\"\"
from __future__ import absolute_import
from .settings_$CM_WEB_ENVIRONMENT import *
EMAIL_SUBJECT_PREFIX = '[Prod][Backend] '
" > cmweb/settings_management.py
```

So backend runs use **`cmweb.settings_management`**, a fourth settings module
alongside `settings_prod` / `settings_deployed` / `settings_wsgi`, differing
only in the email subject prefix — so an error email tells you immediately
whether it came from the web tier or a batch job.

### `cmweb-run-commands` — where `COMMANDS` becomes `manage.py`

**This is the mechanism the whole mapping rests on:**

```bash
[ -z "$COMMANDS" ] && exit 0

cd site

export DJANGO_SETTINGS_MODULE=cmweb.settings_management
export PYTHONIOENCODING=utf_8
export PYTHONUNBUFFERED=1
make install VIRTUALENV_DIR=../.virtualenv NO_APT_INSTALL=1
. ../.virtualenv/bin/activate

rm -f failed_commands
touch failed_commands
echo $COMMANDS | tr ";" "\n" | while read line; do
  echo "---- Executing $line"
  ./manage.py $line -v3 --traceback || { echo "$line" >> failed_commands ; }
done
echo "---- failed_commands: "
cat failed_commands
exit `wc -l < failed_commands`
```

Five things to take from this:

1. **`COMMANDS` is split on `;`** — one Jenkins job can run several management
   commands in sequence.
2. **Every command gets `-v3 --traceback`** — maximum verbosity and a full
   traceback on failure, because the build log is the only diagnostic.
3. **A failing command does not abort the run.** It is appended to
   `failed_commands` and the loop continues.
4. **The exit code is the number of failed commands.** A build that fails "with
   status 2" failed exactly two of its commands — and the log names them.
5. **`PYTHONUNBUFFERED=1`** so the Jenkins console updates live rather than in
   4 KB bursts.

> The `while read` loop runs in a subshell because of the pipe, so
> `failed_commands` is written to disk rather than accumulated in a variable.
> That is deliberate and is why the file is `rm`'d and `touch`ed first.

### `cmweb-run-opensearch-commands` — the one exception

`update_search_index` uses a different builder, because it drives Django's
`opensearch` subcommand rather than a CMWEB command:

```bash
prev_date=$(date -d '-1 day' '+%Y-%m-%d')
echo $COMMAND_ARGS | tr ";" "\n" | while read line; do
  if [[ "${line}" =~ -ipost || "${line}" =~ -iproject || "${line}" =~ -imanifest_branch ]]; then
    ./manage.py opensearch document --force $line index
    ./manage.py opensearch document --force $line update
  else
    ./manage.py opensearch document --force ${line}${prev_date} index
    ./manage.py opensearch document --force ${line}${prev_date} update
  fi
done
```

`COMMAND_ARGS` defaults to:

```
-icommit -fcommit_date__gte=;-ilabel -fdate_created__gte=;-iissue -fdate_modified__gte=;-iprofile -fdate_modified__gte=;-ipost;-iproject;-imanifest_branch
```

Note the trailing `=` on the filters: the builder **appends yesterday's date**,
so commits/labels/issues/profiles are reindexed incrementally, while small
document types (`post`, `project`, `manifest_branch`) are reindexed whole.

This exists because `OPENSEARCH_DSL_AUTOSYNC = False` — the search index is
**not** updated on save. It is refreshed by this job every two hours. Search
results are therefore up to two hours stale by design.

---

## 4. A job template, annotated

`index_labels.yaml` in full:

```yaml
- job-template:

# General
    name: index_labels
    description: |
      Imports builds from C2D.
    parameters:
      - string:
          name: COMMANDS
          default: "index_labels --add-branch --days=$INDEXING_DAYS"
      - string:
          name: INDEXING_DAYS
          default: "0.5"
          description: Number of days to index.
      - cmweb-parameter-gerrit-download-list
      - cmweb-parameter-manifest

# Build Triggers
    triggers:
      - timed: "H 8-20 * * *"

# Build
    builders:
      - cmweb-setup-env
      - cmweb-setup-git
      - cmweb-mount-efs
      - cmweb-prepare-site
      - cmweb-generate-settings
      - cmweb-run-commands
```

Note `COMMANDS` **references another parameter** (`$INDEXING_DAYS`). The value
is expanded by the shell in `cmweb-run-commands`, so an operator can re-run the
job with a wider window by changing one number in the Jenkins UI without editing
the command string.

### Cron syntax: `H` is not a typo

`H 8-20 * * *` means "once per hour between 08:00 and 20:00, at a
hash-determined minute". Jenkins derives the minute from the job name, so jobs
spread deterministically across the hour instead of all firing at :00.
`H H 1 * *` is monthly at a hashed hour and minute. `H/30` is twice an hour.

---

## 5. Triggers other than time

### Gerrit

`deploy_jenkins_jobs` fires whenever `jobs_on_cloud/**` changes on the
`cloudj2` branch:

```yaml
    triggers:
      - gerrit:
          trigger-on:
            - ref-updated-event
          projects:
            - project-compare-type: 'PLAIN'
              project-pattern: 'cmweb-scripts'
              branches:
                - branch-compare-type: 'PLAIN'
                  branch-pattern: '{script-branch}'
              file-paths:
                - compare-type: ANT
                  pattern: jobs_on_cloud/**
          server-name: review-plus
```

`index_amssmanifest` and `index_aosp` are similarly Gerrit-triggered, using
`$GERRIT_REFNAME` / `$GERRIT_PROJECT` to index exactly the branch that changed.

### Downstream triggers

```yaml
    publishers:
      - trigger:
          project: sync_commits, sync_issues
          threshold: FAILURE
```

on `index_latest`, and

```yaml
      - trigger:
          project: disable_indexing_jobs, disable_verification_jobs
          threshold: FAILURE
```

on `deploy_jenkins_jobs`.

> **`threshold: FAILURE` means "always".** In Jenkins, the threshold is the
> *worst* result that still triggers the downstream job, and FAILURE is the
> worst there is. This reads like "only on failure" and means the opposite.

---

## 6. Deploying the jobs themselves

`deploy_jenkins_jobs` is the bootstrap-and-update job. It updates **all** jobs
including itself.

```bash
cd .cmweb-scripts/
. .virtualenv/bin/activate
INI="etc/secure.cmweb.ini"
jenkins-jobs --conf ${INI} ${IGN} ${LVL} update jobs_on_cloud/
```

with `cmweb-prepare-jjb` having written the config from the credential-bound
Jenkins API token:

```bash
echo "
[jenkins]
user=${JENKINS_USER}
password=${JENKINS_TOKEN}
url=${JENKINS_URL}job/cmweb
query_plugins_info=False
" > ${INI}
```

Parameters: `FORCE_UPDATE` (default true) adds `--ignore-cache`; `VERBOSE`
adds `-l DEBUG`.

**To add a scheduled command, you need two changes in two repositories:**

1. the command in `cmweb-app/<app>/management/commands/`
2. a job YAML in `cmweb-scripts/jobs_on_cloud/`

Merging the second triggers `deploy_jenkins_jobs` automatically.

---

## 7. The self-disabling stage environment

`disable_indexing_jobs` runs at 20:00 and does something clever:

```bash
if [ "https://ci-tools.ptc.sony.co.jp/" = "${{JENKINS_URL}}" ]; then
  urls=${{JOB_URL}}                        # in PROD: disable ITSELF
else
  urls=`curl -u "${{JENKINS_USER}}:${{JENKINS_TOKEN}}" \
        ${{FOLDER_URL}}view/indexing/api/json | jq -r '.jobs[].url'`
fi

for url in $urls ; do
  curl -X POST -u "${{JENKINS_USER}}:${{JENKINS_TOKEN}}" ${{url}}disable
done
```

One job definition, opposite behaviour per environment: **in stage it disables
every job in the `indexing` view; in production it disables only itself.** So
the stage environment stops indexing overnight (saving cost and load on shared
services), and the identical job shipped to production neuters itself on first
run.

This is why the `indexing` view's regex matters — it defines the set:

```yaml
- view:
    name: indexing
    view-type: list
    regex: index_.*|snapshot_.*|sync_.*|update_.*
```

`disable_verification_jobs` does the same for `verify_.*`.

> If stage indexing has silently stopped, check whether anyone re-enabled the
> jobs after 20:00.

Note the doubled braces (`${{JENKINS_URL}}`) in these shell blocks — JJB
interpolates `{…}` as its own template variables, so a literal brace must be
escaped by doubling. A single-brace `${JENKINS_URL}` inside a job-template
shell block is a JJB error, not a shell one.

---

## 8. `bin/run_commands.sh` — the standalone twin

`cmweb-scripts/bin/run_commands.sh` does the same job as the
`cmweb-generate-settings` + `cmweb-run-commands` builders, as one script. **It
is not what the scheduled jobs use** — they call the macros above. Exactly one
job still executes the script: `index_jenkins_job`. The two have drifted; see
[07 §4](07-anatomy-of-a-backend-run.md#4-two-execution-paths-and-how-they-drifted)
for the differences.

```bash
[ -z "$COMMANDS" ] && exit 0
# ... pick hosts by JENKINS_URL ...
$(dirname $0)/repo_sync_projects.sh || \
  $(dirname $0)/repo_sync_projects.sh || \
    $(dirname $0)/repo_sync_projects.sh
repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m $CMWEB_MANIFEST -b cloudj2
repo sync -d -c -j4
[ ! -e repository ] && ln -s $REPO_MIRROR repository
# ... write secure.py and settings_management.py ...
```

Two details unique to this script:

- **`repo_sync_projects.sh` is retried three times** by literal repetition —
  `A || A || A`. Crude, but the mirror sync is the flakiest step.
- **It re-asserts eager Celery explicitly:**

```bash
echo "...
CELERY_TASK_ALWAYS_EAGER = True
" > cmweb/settings_management.py
```

That line is one of the pieces of evidence that eager mode is the real
production configuration and not a development convenience — there is no broker
and no worker anywhere.

---

## 9. Reading a failed build

1. **Exit code = number of failed commands.** Look for `---- failed_commands:`
   near the end of the console log; it lists them by name.
2. **Each command ran with `--traceback`**, so the Python traceback is in the
   log above that.
3. **Check which builder failed.** Each prints a banner —
   `++++++++++ mount efs ++++++++++`, `++++++++++ prepare site ++++++++++`. A
   failure before `++++++++++ run commands ++++++++++` is infrastructure
   (mirror not mounted, `repo sync` failed, proxy), not application code.
4. **`make install` runs on every build.** A dependency change that breaks
   installation breaks every job at once.
5. **Timeout is 480 minutes.** A job killed at exactly 8 hours hit the wrapper,
   not an application error.
6. An email went to `somc-sw-cmweb@sony.com` with a subject prefixed
   `[Prod][Backend]` or `[Stage][Backend]`.

### Re-running one command by hand

Use the **`run_commands`** job. `COMMANDS` takes the same semicolon-separated
string:

```
index_label --label-name 55.0.A.0.477 --manifest platform/systemmanifest --branch p-kumano
```

It also posts your command string as the build description, so the build history
shows what each manual run actually did:

```bash
curl -u ${{JENKINS_USER}}:${{JENKINS_TOKEN}} "${{BUILD_URL}}submitDescription" -d "description=$COMMANDS"
```

To test an unmerged fix, set `GERRIT_DOWNLOAD_LIST` to
`cmweb-app 243932/5` and the job will `repo download` that patchset before
running.
