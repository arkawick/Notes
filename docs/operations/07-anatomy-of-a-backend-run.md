# 07 — Anatomy of a backend run

[03](03-jenkins-jobs.md) is the reference for the JJB YAML: the files, the
defaults, the macros, the triggers, how the jobs are deployed. This document is
about what actually happens **when one of those jobs fires** — the sequence on
the build slave, where every environment variable comes from, the two divergent
execution paths, and how to read a failure back to a stage.

---

## 1. There is no cron, no daemon, no queue

It is worth being blunt about what CMWEB's backend *is not*, because every
intuition from a normal service is wrong here:

- **Not cron.** No crontab exists on any host. The schedule lives in Jenkins,
  generated from `timed:` lines in the job YAML.
- **Not a worker.** Celery is eager everywhere; there is no broker and no
  consumer (see [CLAUDE.md](../../CLAUDE.md) and
  [04 §Celery](04-ansible-playbooks.md)). Nothing is queued and picked up.
- **Not an RPC to the web tier.** The web servers are never involved. They do
  not know a job ran.
- **Not a long-lived process.** Nothing stays resident between runs.

What it *is*: **a second, complete installation of CMWEB, built from scratch on
a throwaway build slave, pointed at the same production database the web tier
reads.**

```
   ┌─────────────────────────┐          ┌──────────────────────────────┐
   │  Web tier (AMI)         │          │  Jenkins slave CMWEB_SLAVE_22│
   │  /srv/www/<host>/site   │          │  $WORKSPACE/site             │
   │  Apache + mod_wsgi      │          │  ./manage.py index_labels    │
   │  settings_deployed.py   │          │  settings_management.py      │
   │  built by Ansible/AMI   │          │  built by repo sync + make   │
   └───────────┬─────────────┘          └───────────────┬──────────────┘
               │                                        │
               │        both write/read the same        │
               └──────────────►  RDS  ◄─────────────────┘
                        cmweb.….ap-northeast-1.rds.amazonaws.com
```

Two installations, built by two entirely different mechanisms, from two
independently-moving copies of `cloudj2`, sharing one database. That single
fact explains most of the operational behaviour below.

### The workspace *is* the deployment root

This is the detail that makes the whole thing click. `settings.py` derives every
path relatively:

```python
GLOBALS['PATH_PROJECT']    = dirname(abspath(__file__))   # …/site/cmweb
GLOBALS['PATH_SITE']       = dirname(PATH_PROJECT)        # …/site
GLOBALS['PATH_ROOT']       = dirname(PATH_SITE)           # …/
GLOBALS['PATH_REPOSITORY'] = join(PATH_ROOT, 'repository')
GLOBALS['PATH_LABEL_CACHE']= join(PATH_ROOT, 'cache')
```

On a web server `PATH_ROOT` is `/srv/www/cmweb.ptc.sony.co.jp/`. **On a Jenkins
slave it is `$WORKSPACE`.** So when `cmweb-mount-efs` does

```bash
ln -s /mnt/nfs/repo-mirror_20/ ${WORKSPACE}/repository
```

it is not a convenience — it is satisfying `PATH_REPOSITORY` exactly. Django
needs no configuration to find the git mirrors; the job just reproduces the
deployed directory layout inside the workspace and the relative paths land on
their feet.

---

## 2. One build, start to finish

Take `index_labels`, the hourly build importer. The timer fires at a
hash-determined minute between 08:00 and 20:00.

| # | Stage | What happens | Workspace after |
| --- | --- | --- | --- |
| 0 | **Jenkins** | `workspace-cleanup` wrapper empties the workspace. Credentials are bound into the environment. `defaults.yaml` injects the proxy vars and `SCRIPT_BRANCH`/`APP_BRANCH`. 480-min timeout starts. | *(empty)* |
| 1 | `cmweb-setup-env` | Splits `$JOB_NAME` on `/` to get `FOLDER_NAME`, builds `FOLDER_URL`, writes and injects `.env.prop`. | `.env.prop` |
| 2 | `cmweb-setup-git` | `somc-setup-review -f -p ptc -i $SSH_USERNAME`; copies `$SSH_KEY_FILE` to `~/.ssh/id_ed25519` at 0400; deletes `~/.netrc`. | *(same)* |
| 3 | `cmweb-mount-efs` | `sudo mount -t efs fs-a18f0c81:/ /mnt/nfs` (prod), symlinks `repo-mirror_20` → `$WORKSPACE/repository`, then `ls -la` it. | `repository -> /mnt/nfs/…` |
| 4 | `cmweb-prepare-site` | `repo init -u …/cmweb-manifest -m $CMWEB_MANIFEST -b cloudj2`, `repo sync -d -c -j4`. Applies `GERRIT_DOWNLOAD_LIST` via `repo download` if set. | `.repo/`, `site/`, `site/apps/` |
| 5 | `cmweb-generate-settings` | Branches on `$JENKINS_URL` to pick prod/stage hosts. Writes `site/cmweb/secure.py` and `site/cmweb/settings_management.py`. | + two generated files |
| 6 | `cmweb-run-commands` | `export DJANGO_SETTINGS_MODULE=cmweb.settings_management`; `make install VIRTUALENV_DIR=../.virtualenv NO_APT_INSTALL=1`; activate. | `.virtualenv/` |
| 7 | *(same builder)* | Splits `$COMMANDS` on `;`, runs `./manage.py <line> -v3 --traceback` for each, appending failures to `failed_commands`. | `site/failed_commands` |
| 8 | *(same builder)* | `cat failed_commands`; `exit $(wc -l < failed_commands)`. | — |
| 9 | **Jenkins** | On non-zero exit, emails `somc-sw-cmweb@sony.com` with subject prefix `[Prod][Backend]`. Build retained 365 days. | discarded |

Final layout at step 7, which is the deployed layout with `$WORKSPACE` standing
in for `/srv/www/<host>/`:

```
$WORKSPACE/
├── .repo/                    repo tool metadata
├── .virtualenv/              built fresh by `make install`, every run
├── repository -> /mnt/nfs/repo-mirror_20/     ← PATH_REPOSITORY
└── site/                     ← PATH_SITE   (cmweb-project)
    ├── cmweb/
    │   ├── settings.py           from git
    │   ├── settings_prod.py      from git
    │   ├── secure.py             GENERATED at step 5
    │   └── settings_management.py GENERATED at step 5  ← DJANGO_SETTINGS_MODULE
    ├── apps/                 ← APPS_DIR    (cmweb-app)
    ├── manage.py
    └── failed_commands       written at step 7
```

Some jobs prepend one extra shell builder before step 1, which curls
`submitDescription` to stamp the parameters into the build description —
`index_latest`, `sync_commits` and `run_commands` do this, so the build history
shows what each run was actually asked to do rather than just a number.

### `COMMANDS` is the whole interface

```bash
echo $COMMANDS | tr ";" "\n" | while read line; do
  ./manage.py $line -v3 --traceback || { echo "$line" >> failed_commands ; }
done
exit `wc -l < failed_commands`
```

Five properties fall out of those four lines:

1. **Semicolon-separated** — one job can run a sequence.
2. **Unquoted `$COMMANDS`** — the shell word-splits it, which is why
   `COMMANDS` can reference other build parameters (`--days=$INDEXING_DAYS`)
   and why an argument containing spaces cannot be passed safely.
3. **Always `-v3 --traceback`** — the console log is the only diagnostic
   channel, so it is maximally verbose by default.
4. **Failures do not abort** — later commands still run.
5. **Exit code = number of failed commands**, and they are named in the log
   under `---- failed_commands:`.

---

## 3. Where each variable comes from

Nothing about the run is configured in one place. Tracing a value back matters
when a job behaves differently from what the YAML appears to say.

| Variable | Set by | Notes |
| --- | --- | --- |
| `COMMANDS` | job YAML `parameters:`, overridable in the UI | the payload |
| `INDEXING_DAYS`, `MAX_INTERVAL`, … | job YAML `parameters:` | expanded inside `COMMANDS` by the shell |
| `SCRIPT_BRANCH`, `APP_BRANCH` | `defaults.yaml` inject | both `cloudj2` |
| `http_proxy`, `https_proxy`, `no_proxy` | `defaults.yaml` inject | `no_proxy=ptc.sony.co.jp,amazonaws.com` |
| `DB_USERNAME`, `DB_PASSWORD` | credentials-binding `db_account` | → `secure.py` |
| `SERVICE_USERNAME`, `SERVICE_PASSWORD` | credentials-binding `system_account_password` | → `AUTH_DEFAULT_SERVICE_*` |
| `OPENSEARCH_AUTH_*` | credentials-binding `opensearch_credentials` | → `secure.py` |
| `JENKINS_USER`, `JENKINS_TOKEN` | credentials-binding `jenkins_api_token` | used for REST calls back into Jenkins |
| `SSH_KEY_FILE`, `SSH_USERNAME` | credentials-binding `ssh_private_key` | installed by `cmweb-setup-git` |
| `ANSIBLE_VAULT_PASS` | credentials-binding `ansible_vault_pass` | only the Ansible jobs use it |
| `FOLDER_NAME`, `FOLDER_URL` | `cmweb-setup-env` → `.env.prop` | derived from `$JOB_NAME` |
| `JENKINS_URL` | Jenkins | **selects prod vs stage** |
| `AWS_ENV` | the slave, *not* this repo | **selects which EFS is mounted** |
| `REPO_MIRROR`, `REPO_MANIFEST`, `REPO_BRANCH` | the slave, *not* this repo | only `bin/*.sh` read these; nothing in `cmweb-scripts` assigns them |
| `DB_HOST`, `CACHE_HOST`, `OPENSEARCH_HOST`, `CM_WEB_ENVIRONMENT` | `cmweb-generate-settings`, by `$JENKINS_URL` | hard-coded hostnames |

Two of those are worth dwelling on, because they are the job's entire notion of
"which environment am I":

**`$JENKINS_URL`** — a literal string comparison decides whether the run writes
production or stage database credentials. Anything unrecognised prints
`run this script on cloud Jenkins` and exits 1.

**`$AWS_ENV`** — a *different* variable, from a *different* source, decides
which EFS gets mounted. Nothing checks that the two agree. They are kept
consistent by the slave being in the right account, not by any assertion.

---

## 4. Two execution paths, and how they drifted

The steps in §2 exist twice in `cmweb-scripts`, in two places that must be
edited together and are not linked by anything:

| | `jobs_on_cloud/macros.yaml` | `bin/run_commands.sh` |
| --- | --- | --- |
| Used by | **~20 scheduled jobs** + `run_commands`, `migrate_db` | **`index_jenkins_job` only** |
| Form | six JJB `builder:` macros | one 120-line bash script |
| Git mirror | `cmweb-mount-efs` — mounts EFS, symlinks `repo-mirror_20` | `repo_sync_projects.sh`, retried by literal repetition `A \|\| A \|\| A` |
| `repository` symlink | always created | `[ ! -e repository ] && ln -s $REPO_MIRROR repository` |
| `rm -rf var` | no | yes |
| `settings_management.py` | module docstring + `EMAIL_SUBJECT_PREFIX` | same, **plus `CELERY_TASK_ALWAYS_EAGER = True`** |
| Failure summary | `cat failed_commands` before exiting | exits without printing them |
| Braces | must be doubled (`${{JENKINS_URL}}`) — JJB templating | plain `${JENKINS_URL}` |

The `secure.py` heredoc and the `$JENKINS_URL` host table are **duplicated
verbatim** between them. An RDS endpoint change, a new credential, a new
`secure.py` key — each needs editing in both, plus in `ansible/group_vars/<env>`
for the web tier. Nothing enforces agreement; see
[06 §The three-place problem](06-cmweb-scripts-repo.md).

> The extra `CELERY_TASK_ALWAYS_EAGER = True` in the script is harmless — base
> `settings.py` already sets it and nothing overrides it. It is useful only as
> evidence that eager mode is the intended production configuration rather than
> an oversight.

---

## 5. The build-triggered path

Everything above is time-triggered. One chain is not: when a platform build
finishes, it pushes itself into CMWEB.

```
 Platform build job (another Jenkins entirely)
   │  archives result-dir/buildid.txt, sets build description to the label name
   ▼
 post_build_trigger_cmweb_index          node: CMWEB_RECEPTION_22, concurrent: true
   │  auth-token: treefrog3   ← remote trigger, no login
   │  • if SEMC_BUILD_ID absent: sleep 90, curl $HUDSON_INPUT_URL/artifact/result-dir/buildid.txt
   │  • validates BRANCH, MANIFEST, JENKINS_PARENT_JOB_URL are present
   │  • rejects a JENKINS_PARENT_JOB_URL containing "/view/"
   │  • MIRROR_UPDATE_USING_MANIFEST = (MANIFEST != platform/systemmanifest)
   │  • writes properties.txt
   ▼  trigger-builds, block: true, property-file: properties.txt
 index_jenkins_job                        concurrent: true, auth-token set
   │  cmweb-setup-env → cmweb-setup-git → cmweb-checkout-scripts → cmweb-mount-efs
   │  bin/parameter_validation.sh          ← cross-checks BRANCH/MANIFEST against the parent URL
   │  [ -z "$WAIT" ] || sleep $WAIT
   │  inject REPO_MIRROR_UPDATE_FIRST, REPO_SKIP_CHECKOUT=true, GERRIT_SERVER, …
   ▼  bin/run_commands.sh
 COMMANDS = index_jenkins_job $JENKINS_PARENT_JOB_URL --branch $BRANCH
              --manifest $MANIFEST --days $DAYS
          ;  index_latest --branch $MANIFEST:$BRANCH --jobs 1
```

Three things here that exist nowhere else in the job set:

**`bin/parameter_validation.sh` is a guard against indexing the wrong branch.**
It asserts that the parent job's URL and the `BRANCH`/`MANIFEST` parameters
describe the same thing — a `systemmanifest` build must come from a URL
containing `system`, the URL must contain `${BRANCH}_`, and so on. It
deliberately skips the check for CMWEB's own sync jobs and for ODM branches
(`$BRANCH =~ odm`), whose offbuild jobs are named differently. Without it, a
mis-parameterised trigger would silently attach one branch's build to another.

**`REPO_MIRROR_UPDATE_FIRST` can make the job update the mirror.** When the
manifest is not `platform/systemmanifest`, `repo_sync_projects.sh` runs
`repo init --mirror` + `repo sync` against `$REPO_MIRROR` *before* indexing, so
the commits the new build references exist locally. With `REPO_SKIP_CHECKOUT`
also injected as `true`, the script stops there and never makes a working
checkout.

**`REPO_MIRROR` / `REPO_MANIFEST` / `REPO_BRANCH` are not set by this
repository.** `repo_sync_projects.sh` needs all three, and the inject block in
`index_jenkins_job.yaml` supplies `BRANCH` and `MANIFEST` — different names.
They therefore come from the slave's own environment, or the script takes its
`else` branch and prints `Not syncing projects:` with the three empty values.
If mirror updates appear not to be happening for build-triggered indexing, that
log line is the thing to look for.

> `index_jenkins_job.yaml` also writes `echo "CMWEB_INSTANCE=stage" > extra.prop`
> and injects it. Nothing in `cmweb-scripts`, `cmweb-project` or `cmweb-app`
> reads `CMWEB_INSTANCE`, and the value is hard-coded to `stage` even in
> production. It appears to be dead.

### Downstream triggers

```
index_latest         ──► sync_commits, sync_issues
deploy_jenkins_jobs  ──► disable_indexing_jobs, disable_verification_jobs
```

This is why `sync_commits` and `sync_issues` have no `timed:` trigger of their
own — they are not unscheduled, they are chained. Both use
`threshold: FAILURE`, which in Jenkins means the *worst* result that still
triggers, i.e. **always**, including after the upstream job failed.

---

## 6. Reading a failure back to a stage

Every builder opens with a banner, which makes the console log self-indexing:

```
++++++++++ setup env ++++++++++
++++++++++ setup git ++++++++++
++++++++++ mount efs ++++++++++
++++++++++ prepare site ++++++++++
++++++++++ generate settings ++++++++++
++++++++++ run commands ++++++++++
```

**Anything that fails before `run commands` is infrastructure, not application
code.**

| Last banner seen | Likely cause |
| --- | --- |
| *(none)* | Slave offline, or `workspace-cleanup` could not clear the workspace |
| `setup git` | `somc-setup-review` failed, or the `ssh_private_key` credential is missing/rotated |
| `mount efs` | EFS not reachable, or `$AWS_ENV` is neither `prod` nor `stage` so no mount happened and the closing `ls -la repository/` failed |
| `prepare site` | Gerrit unreachable, `repo sync` conflict, or a bad `GERRIT_DOWNLOAD_LIST` patchset reference |
| `generate settings` | `$JENKINS_URL` unrecognised — `run this script on cloud Jenkins`, exit 1 |
| `run commands`, exit before any `---- Executing` | `make install` failed — a dependency change breaks **every job at once** |
| `run commands`, exit *n* | *n* management commands failed; they are listed under `---- failed_commands:` and their tracebacks are above |
| killed at 8h | the `timeout: 480` wrapper, not an application error |

Because `make install` runs on every build against `cloudj2` HEAD, a broken
`etc/requirements-22.txt` presents as the entire backend going dark
simultaneously, with no application traceback anywhere.

---

## 7. Consequences to keep in mind

- **A backend failure is invisible on the site.** No 500, no error page. The
  job emails `somc-sw-cmweb@sony.com` and the data quietly stops advancing.
  Users report it as "the build list is stale", not as an outage.
- **The two installations drift.** The web tier is an AMI baked at some point;
  the jobs are `cloudj2` HEAD at the moment they run. Code that indexes and
  code that renders can be different versions of the same repository.
- **Migrations are unordered with respect to both.** `migrate_db` is a manually
  triggered job and the deploy does not run migrations, so a schema change is
  two independent human actions against a database two installations are using.
- **Any operator can run any command against production.** `run_commands` takes
  a free-text `COMMANDS` and an optional unmerged patchset via
  `GERRIT_DOWNLOAD_LIST`. That is intentional — it is how indexing fixes get
  validated against real data — but it is also unaudited beyond the build
  description and the 365-day log retention.
- **Concurrency is mostly unmanaged.** Only `index_jenkins_job` and
  `post_build_trigger_cmweb_index` set `concurrent: true`; the rest rely on
  Jenkins' default of one build at a time per job. Nothing coordinates
  *between* jobs, so two different jobs can index overlapping data at once.

---

## Related

- [03 — Jenkins jobs and JJB templates](03-jenkins-jobs.md) — the YAML: files, defaults, macros, triggers, deploying the jobs
- [01 — Management commands](01-management-commands.md) — the 62 commands themselves
- [02 — The indexing flow](02-indexing-flow.md) — what `index_labels` does once it starts
- [06 — The `cmweb-scripts` repository](06-cmweb-scripts-repo.md) — the AMI pipeline, `bin/` scripts, the three-place configuration problem
- [docs/how-the-site-works.md](../how-the-site-works.md) — the web-request side of the same system
