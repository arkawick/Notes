# Infrastructure and operations

`cmweb-scripts` is not part of the Django application — it contains no Python that CMWEB imports. It is
the repository that provisions the AWS environment, deploys the application onto it, keeps the git
mirrors the indexer reads up to date, and defines the ~50 Jenkins jobs that populate the database.

```
cmweb-scripts/
├── ansible/          server provisioning and application deployment
├── jobs_on_cloud/    Jenkins Job Builder definitions
├── cloudformation/   AWS stacks (image builder, IAM, VPC security groups)
├── agent/            Packer/Ansible for the Jenkins agent AMI
├── bin/              git mirroring scripts and the mirror-creator jar
├── etc/              mirror rules and Python requirements
└── configurator/     git submodule: jenkins-jobs-configurator (shared Makefile)
```

`configurator` is a **submodule** (`git://review-plus.ptc.sony.co.jp/jenkins-jobs-configurator`) and
supplies the Makefile that `jobs_on_cloud/Makefile` includes. Clone with `--recursive`, or run
`git submodule init && git submodule update`, otherwise the job targets fail with a missing include.

## Deployed topology

Everything runs in AWS `ap-northeast-1`, in three environments — prod, stage and test — each with its
own hostname, RDS instance, ElastiCache cluster and OpenSearch domain.

```
                    ┌──────────────┐
   users ──HTTPS──▶ │ Apache +     │      Postgres (RDS)
                    │ mod_wsgi     │ ───▶ memcached (ElastiCache)  ← sessions + cache
                    │ LDAP auth    │      OpenSearch (managed)
                    └──────┬───────┘
                           │
                    /mnt/nfs (EFS)  ──  repo-mirror : bare git mirrors
                           ▲
                    ┌──────┴───────┐
                    │ Jenkins      │  indexing jobs, mirroring, deployment
                    │ agents       │
                    └──────────────┘
```

The web servers and the Jenkins agents share the git mirror over EFS: the `mirror_gits` job writes it,
the web application and the indexing jobs read it.

| | Production |
| --- | --- |
| Hostname | `cmweb.ptc.sony.co.jp` |
| Database | `cmweb.cm8tmtafyb32.ap-northeast-1.rds.amazonaws.com:5432/cmweb` |
| Cache | `cmweb.myfjt0.cfg.apne1.cache.amazonaws.com:11211` |
| OpenSearch | `vpc-cmweb-prod-…aos.ap-northeast-1.on.aws` |
| Jenkins | `https://ci-tools.ptc.sony.co.jp/job/cmweb/` |

Stage mirrors this with its own endpoints and `ci-tools.ptc-stage.sony.co.jp`. Test has no EFS mount
and no scheduled jobs.

## Ansible

`ansible/web-servers.yml` is the single playbook; it defines one play per environment with the same
role list.

```bash
cd ansible
# put the vault password in ../.vault first
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod  web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/test  web-servers.yml
```

It runs with `-c local` against `localhost` — this is a machine configuring itself, invoked during
image build or on the instance, not a push from a control node.

| Role | What it does |
| --- | --- |
| `environment` | Locale, ulimits, unattended-restart configuration |
| `sonyca` | Installs the Sony Root / Intranet / B2B CA certificates |
| `certificate` | Sony package repository certificates |
| `package` | Base OS packages (per Ubuntu release: bionic / focal / jammy) |
| `cmweb-account` | The `cmweb` service account, its SSH keys and sudo rules |
| `cmweb-node` | **Deploys the application** — see below |
| `apache-server` | The vhost, SSL certificate and mod_wsgi configuration |
| `cloudwatch-agent` | Log and metric shipping |
| `efs` | Mounts the EFS volume at `/mnt/nfs` (not on test) |
| `cronjob` | `/srv/cron/apache_status_logging.py`, run every 5 minutes |
| `c1ws` | Trend Micro Cloud One workload security agent |

### What `cmweb-node` does

This is the deployment itself:

1. Raises the open-file ulimits for the `cmweb` user (16 WSGI processes × 15 threads need them).
2. Creates `/srv/www/<hostname>/` and `repo init -u …/cmweb-manifest -m <release|default>.xml -b cloudj2`
   followed by `repo sync`, producing `site/` and `site/apps/`.
3. Renders `site/cmweb/secure.py` from `templates/django/secure.py.j2` with the database, cache, LDAP,
   OpenSearch and service-account credentials pulled from the vault.
4. Symlinks `site/cmweb/settings_deployed.py` → `settings_<env>.py`.
5. Symlinks `static/media` → `/mnt/nfs/media` and `repository` → `/mnt/nfs/cmweb/repo-mirror`.
6. Runs `make static` with `DJANGO_SETTINGS_MODULE=cmweb.settings_deployed`, which installs the
   virtualenv into `ENV/` and compresses the assets.
7. Injects the Sony CA certificates into the virtualenv's `certifi/cacert.pem`, so `requests` can talk
   to internal HTTPS services.
8. Installs a logrotate configuration for `var/log`.

### Secrets

Secrets live in `ansible/encrypted_vars/*.yml`, encrypted with `ansible-vault`. The convention, which
the repository's own README insists on: **variables inside the vault are named `vault_*`, and roles
never reference them directly** — `group_vars/*` maps `vault_ssh_private_key` → `ssh_private_key` and
roles use the unprefixed name. Roles therefore do not need to know what is secret, and developers can
grep for variable names without decrypting anything.

```bash
ansible-vault edit encrypted_vars/access-prod.yml

# See plaintext diffs for vaulted files
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"

# Lint
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml
```

`.vault`, `.key` and `.vault_password` are gitignored. The vault password is documented on the internal
Confluence ("Service accounts and passwords").

## Apache

`roles/apache-server/templates/apache/cmweb.conf.j2` is worth reading before debugging any
authentication or URL problem. It:

- terminates TLS and runs 16 WSGI processes × 15 threads with `maximum-requests=2000`
- points `python-path` at `site/` and `python-home` at `ENV/`
- enforces **LDAP basic auth for the whole site** against `ldaps://LDAP.jp.sony.com:3269`, with
  `Require all granted` exceptions for `/rpc/`, `/register`, `/access-denied` and the favicon; a 401 is
  rewritten into a redirect to `/register`
- rewrites legacy URL shapes onto current ones (`/projects/x.git` → `/repositories/x`,
  `/labels/<l>/commits/…` → `/labels/<l>/+commits/…`, `/tags/schedule/…` → `/schedule/branches/…`)
- disables caching on `/backend/tasks/*/status` and `/backend/tasks/apply/*` so task polling works

Django's own `PermissionCheckMiddleware` is a *second* gate behind this one; opening a URL to anonymous
users needs changes in both.

## Jenkins jobs

`jobs_on_cloud/` holds Jenkins Job Builder YAML. Jobs live in the `cmweb` folder on
`ci-tools.ptc.sony.co.jp` (prod) and `ci-tools.ptc-stage.sony.co.jp` (stage).

### Structure

| File | Role |
| --- | --- |
| `defaults.yaml` | Global defaults: agent label `CMWEB_SLAVE_22`, branches (`cloudj2`), proxy settings, credential bindings, 480-minute timeout, failure mail to `somc-sw-cmweb@sony.com` |
| `macros.yaml` | The reusable builders every job composes from |
| `generic_project.yaml` | Generated list of all job templates — regenerate with `make update-project` |
| `view.yaml`, `template_*.yaml` | Views and parameterised templates, excluded from the generated project |

The builder macros are the interesting part, because every indexing job is the same five steps:

| Macro | What it does |
| --- | --- |
| `cmweb-setup-env` | Derives folder name/URL from `$JOB_NAME` and injects them |
| `cmweb-setup-git` | Installs the SSH key from Jenkins credentials for Gerrit access |
| `cmweb-mount-efs` | Mounts the environment's EFS volume and symlinks `repository` into the workspace |
| `cmweb-prepare-site` | `repo init`/`repo sync` of `cmweb-manifest`, then applies any `GERRIT_DOWNLOAD_LIST` patches |
| `cmweb-generate-settings` | Writes `cmweb/secure.py` and a `cmweb/settings_management.py` from the Jenkins credential bindings, choosing prod or stage endpoints from `$JENKINS_URL` |
| `cmweb-run-commands` | `make install NO_APT_INSTALL=1`, then runs each `;`-separated entry of `$COMMANDS` as `./manage.py <cmd> -v3 --traceback`, collecting failures and exiting with the failure count |

So most job definitions are just a `COMMANDS` default plus a `triggers: timed:` schedule, and a job can
be re-run by hand with different commands through the `run_commands` job.

### Deploying job changes

```bash
cd jobs_on_cloud
make update-project     # regenerate generic_project.yaml after adding/removing a job
make update             # push to Jenkins (target comes from ../configurator/Makefile)
```

In practice this is done by the **`deploy_jenkins_jobs`** job, which updates every job including
itself; a bootstrap job is needed only for a brand-new Jenkins instance. Job changes are verified by
`verify_jenkins_jobs` on patchset upload.

### Scheduled jobs

Times are Jenkins cron with `H` hashing. Non-scheduled jobs are triggered manually or by other jobs.

| Job | Schedule | Purpose |
| --- | --- | --- |
| `mirror_gits` | hourly | `repo sync --mirror` of the EFS git mirror using the magic-mirror tag |
| `sync_projects_from_gerrit` | hourly | Repository list from Gerrit |
| `index_labels` | hourly, 08–20 | Import builds from C2D |
| `index_latest` | hourly, 08–20 | Index the newest build per branch |
| `index_pp_apps` | hourly, 08–20 | Product package apps |
| `index_delta_labels` | every 30 min | Materialise delta builds requested in the UI |
| `update_cherries` | hourly | Cherry-pick automation |
| `sync_rebase_records` | hourly | Rebase tracking |
| `update_search_index` | every 2 h | OpenSearch reindex |
| `update_fix_delivered_jimx` / `_jiml` | every 12 h | JIRA fix-delivered flags |
| `index_labels_more`, `sync_commits_more`, `detect_branchpoints` | nightly ~01–02 | Deeper backfill |
| `index_latest_more`, `update_requests`, `update_fix_delivered_jimodm18` | nightly ~00 | |
| `clean_old_entries_in_db`, `sync_projects_from_git`, `update_swprojects` | nightly ~04 | Housekeeping |
| `index_boot_labels`, `find_incomplete_labels` | daily ~08 | Boot packages; indexing health report |
| `disable_indexing_jobs`, `disable_verification_jobs` | 20:00 daily | Quiet window — indexing stops overnight |
| `update_cherries_more` | weekly (Sun) | |
| `sync_tags_jira` | weekly (Sat) | |
| `deactivate_users`, `remove_empty_groups` | monthly | LDAP hygiene |
| `snapshot_*` | weekly | Manifest snapshots from `template_snapshot_manifest.yaml` |

`disable_indexing_jobs` at 20:00 is why the hourly indexing jobs are scoped to `H 8-20` — the
indexers deliberately stand down overnight.

### Verification jobs

| Job | Trigger |
| --- | --- |
| `verify_cmweb_changes` | Patchset on `cmweb-app` or `cmweb-project`; runs `make` (clean, kwalitee, test) and votes Verified |
| `verify_ansible_playbook` | Patchset on `cmweb-scripts` ansible changes |
| `verify_jenkins_jobs` | Patchset on `cmweb-scripts` job definitions |

`post_build_trigger_cmweb_index` lets external build systems poke CMWEB to index a build as soon as it
finishes, rather than waiting for the next scheduled run.

## Git mirroring

The indexer reads bare git repositories from disk rather than fetching from Gerrit, so the mirror is a
hard dependency of everything.

- `bin/mirror_repo.sh` drives `mirror-creator.jar` against `review.ptc.sony.co.jp`. Note two details:
  it asks **CMWEB's own `/rpc` endpoint** for the mirror manifest (which is why Apache grants `/rpc/`
  anonymous access), and it passes `--fetch-notes` so `refs/notes/review` comes across — that ref is
  where commit approvers and verifiers are parsed from.
- `etc/mirror-repo-rules.txt` and `mirror-repo-rules-prio.txt` are the project name patterns that
  decide what gets mirrored, and in what priority order.
- `bin/repo_sync_projects.sh` and `bin/run_commands.sh` are the wrappers the jobs call.
- Failed mirror creations are recorded in `.mirror-update-logs/mirror_creation_stats.csv` and deleted
  on the next run so they are retried.

## CloudFormation and the agent AMI

`cloudformation/` holds the stacks, deployed by uploading to S3 and creating a stack or change set:

```bash
cd cloudformation
./upload_all.sh
./create-stack.sh       PATH/TO/ROOT_TEMPLATE.yaml   # first time
./create-change-set.sh  PATH/TO/ROOT_TEMPLATE.yaml   # subsequent updates, then execute in the console
./validate-template.sh  PATH/TO/TEMPLATE.yaml
```

- `ec2imagebuilder/` — an EC2 Image Builder pipeline that bakes the web AMI: components fetch
  `cmweb-scripts`, fetch tools, provision the web tier by running the Ansible playbook, and handle
  proxy and password setup/teardown around the build.
- `iam/` — instance profiles for the web servers, the Jenkins agents and the image builder.
- `vpc/` — security groups for RDS, ElastiCache and the test environment.

`agent/` is the Jenkins agent image: `agent.yml` applies the `packages` role, with per-release variable
files (`bionic.yml`, `focal.yml`) and pinned Python requirements in `resources/python/3.8/`. The
`.pkrvars.hcl` files are the Packer variable sets for the Ubuntu 18.04 and 20.04 agent images.
