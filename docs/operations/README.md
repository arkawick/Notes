# Operations — commands, indexing, Jenkins, Ansible, Apache

Reference documentation for how CMWEB actually *runs* in production: the 62
management commands, the indexing pipeline they drive, the 47 Jenkins jobs that
schedule them, the Ansible that builds the servers, and the Apache config that
fronts the whole thing.

Where the [learning track](../learning/README.md) teaches Django concepts, these
seven documents are operational reference — catalogues, mappings and flows you
look things up in.

| # | Document | Covers |
| --- | --- | --- |
| 01 | [Management commands](01-management-commands.md) | All 62 commands across 13 apps, `explorer`'s 20 in depth, argument conventions, house rules |
| 02 | [The indexing flow](02-indexing-flow.md) | End to end: C2D → `index_labels` → `index_label` → components → commits → sublabels, plus the incompleteness model |
| 03 | [Jenkins jobs (JJB)](03-jenkins-jobs.md) | The job templates, macros, builders, how `COMMANDS` reaches `manage.py`, deployment of the jobs themselves |
| 04 | [Ansible playbooks](04-ansible-playbooks.md) | `web-servers.yml`, all 11 roles, variables, vault, the AMI build path |
| 05 | [Apache configuration](05-apache-config.md) | The vhost directive by directive, mod_wsgi tuning, the LDAP gate, troubleshooting |
| 06 | [The `cmweb-scripts` repository](06-cmweb-scripts-repo.md) | The whole repo: CloudFormation and the AMI pipeline, the Packer-built Jenkins agent, `bin/` mirroring scripts, `etc/` rules, the three AWS accounts |
| 07 | [Anatomy of a backend run](07-anatomy-of-a-backend-run.md) | What happens when a job fires: the build timeline, variable provenance, the two execution paths, the build-triggered chain, reading a failure |

---

## The one table to remember

**A Jenkins job is a management command plus a schedule.** Nearly every job's
`COMMANDS` parameter is a semicolon-separated list of `manage.py` subcommands,
executed by the shared `cmweb-run-commands` builder.

```
jobs_on_cloud/index_labels.yaml          cmweb-app/explorer/management/commands/index_labels.py
  COMMANDS: "index_labels --days=0.5"  ───────────►  class Command(BaseCommand)
  triggers: timed "H 8-20 * * *"                      def handle(self, *args, **options)
```

### Scheduled jobs → commands

Times are Jenkins cron. `H` = hash-spread within the period, so load is
staggered across jobs rather than all firing on the minute.

| Schedule | Job | Runs |
| --- | --- | --- |
| `H * * * *` (hourly) | `mirror_gits` | *(no manage.py — `repo sync --mirror`)* |
| `H * * * *` | `sync_projects_from_gerrit` | `sync_projects_from_gerrit` |
| `H * * * *` | `sync_rebase_records` | `sync_rebase_records --jobs=1 --force-status` ; `index_topic_changes --jobs=1` ; `index_target_label --jobs=1` |
| `H * * * *` | `update_cherries` | `update_cherries` |
| `H/30 * * * *` | `index_delta_labels` | `index_delta_labels` |
| `H */2 * * *` | `update_search_index` | `opensearch document …` *(different builder)* |
| `H */12 * * *` | `update_fix_delivered_jiml` | `update_fix_delivered --days $DAYS --projects $PROJECTS` |
| `H */12 * * *` | `update_fix_delivered_jimx` | same, different projects |
| **`H 8-20 * * *`** | **`index_labels`** | `index_labels --add-branch --days=0.5` |
| **`H 8-20 * * *`** | **`index_latest`** | `index_latest --max-latest-interval=30 --exclusion-threshold=365 --jobs=4` |
| `H 8-20 * * *` | `index_pp_apps` | `index_pp_apps --jobs 1` |
| `H 0 * * *` | `index_latest_more` | `index_latest` |
| `H 0 * * *` | `update_requests` | `update_branch_requests` ; `update_repository_requests` |
| `H 0 * * *` | `update_fix_delivered_jimodm18` | `update_fix_delivered …` |
| `H 1 * * *` | `detect_branchpoints` | `detect_branchpoints` |
| `H 1 * * *` | `sync_commits_more` | `sync_commits --lines --no-review` |
| `H 2 * * *` | `index_labels_more` | `index_labels --days 4 --branch open-devices` ; `index_labels --days 4` |
| `H 4 * * *` | `clean_old_entries_in_db` | `archive_activity` ; `delete_old_zeitgeist_entries` |
| `H 4 * * *` | `sync_projects_from_git` | `sync_projects` |
| `H 4 * * *` | `update_swprojects` | `update_swprojects` |
| `H 8 * * *` | `find_incomplete_labels` | `find_incomplete_labels` |
| `H 8 * * *` | `index_boot_labels` | `index_boot_labels --days=$INDEXING_DAYS --manifest=$MANIFEST` |
| `H 12 * * 6` (Sat) | `sync_tags_jira` | `sync_tags_jira` |
| `H 13 * * 7` (Sun) | `update_cherries_more` | `deactivate_old_cherrypick_policies --days 500` ; `update_cherries --full` |
| `H H 1 * *` (monthly) | `deactivate_users` | `deactivate_users` |
| `H H 1 * *` | `remove_empty_groups` | `remove_empty_groups` |
| `0 20 * * *` | `disable_indexing_jobs` | *(Jenkins REST API)* |
| `0 20 * * *` | `disable_verification_jobs` | *(Jenkins REST API)* |

### Event-triggered and manual jobs

| Trigger | Job | Runs |
| --- | --- | --- |
| Gerrit ref-updated on `cmweb-scripts/jobs_on_cloud/**` | `deploy_jenkins_jobs` | `jenkins-jobs update` — deploys all jobs including itself |
| Gerrit | `index_amssmanifest` | `update_manifestbranches` ; `index_static_manifest …` |
| Gerrit | `index_aosp` | `update_manifestbranches` ; `index_latest --branch-heads …` |
| Upstream build | `index_jenkins_job`, `post_build_trigger_cmweb_index` | `index_jenkins_job …` ; `index_latest …` |
| Gerrit patchset | `verify_cmweb_changes`, `verify_jenkins_jobs`, `verify_ansible_playbook` | CI verification |
| Manual | **`run_commands`** | **anything** — the general escape hatch |
| Manual | `migrate_db` | `migrate` |
| Manual | `add_users_manually` | `add_users --filter …` |
| Manual | `create_bulk_schedules` | `create_bulk_schedules --file …` |
| Manual | `create_cmweb_testdata` | regenerates `testdata.json` |
| Manual | `release_manifest`, `snapshot_manifest` | manifest pinning |

### Downstream chains

Two jobs trigger others on completion:

```
index_latest           ──► sync_commits, sync_issues
deploy_jenkins_jobs    ──► disable_indexing_jobs, disable_verification_jobs
```

Both use `threshold: FAILURE`, which in Jenkins is the *most permissive*
threshold — the downstream job runs even if the upstream one failed.

---

## Coverage: 32 of 62 commands have a job

The other 30 are not dead code. They fall into three groups:

**Called by another command, never scheduled directly** — `index_label`,
`index_label_commits`, `index_sublabels`, `index_decoupled`,
`index_boot_packages`, `index_repository`. These are invoked via
`call_command()` from within the indexing chain (see
[02](02-indexing-flow.md)).

**Ad-hoc / operator tools, run through `run_commands`** —
`fixup_manifestcomponents`, `fix_bad_tags`, `update_include_exclude_rules`,
`delete_cache_key`, `setup_auth`, `reconfigure_users`, `import_rebases`,
`resave_issue_trend`, `sync_labels`, `sync_labels_jira`, `index_testdata`.

**Apparently unscheduled and worth questioning** — `index_zeitgeist`,
`index_zeitgeist_reviewplus`, `index_issue_trend` (historian),
`index_caf_release`, `index_releases`, `reindex_fixed_crs_xls` (vendorsync),
`update_aod_to_cod` (aod), `branch_request_digest`, `cherry_tag_digest`,
`dump_awstats_userinfo`, `generate_cherrypick_yamls`,
`index_boot_packages_revision`. Some of these populate pages that are visibly
stale; if a feature looks frozen in time, check whether its indexer still runs.
`threading_example` (base) is a code sample.

Full per-command detail in [01](01-management-commands.md).

---

## The three views in Jenkins

`jobs_on_cloud/view.yaml` groups jobs in the UI:

| View | Contents |
| --- | --- |
| `backend` | explicit job list |
| `indexing` | regex `index_.*\|snapshot_.*\|sync_.*\|update_.*` |
| `verification` | regex `verify_.*` |

The `indexing` view is what `disable_indexing_jobs` enumerates via the Jenkins
REST API when it switches the stage environment off overnight.

---

## Where things live

```
cmweb-app/<app>/management/commands/*.py    the 62 commands
cmweb-app/explorer/management/indexing.py   the shared indexing engine (639 lines)
cmweb-app/explorer/management/c2d.py        C2D metadata field names and parsing

cmweb-scripts/jobs_on_cloud/*.yaml          the 47 job templates
cmweb-scripts/jobs_on_cloud/macros.yaml     shared builders and parameters
cmweb-scripts/jobs_on_cloud/defaults.yaml   node, credentials, proxy, logrotate
cmweb-scripts/bin/run_commands.sh           standalone twin of the builders; used by index_jenkins_job only

cmweb-scripts/ansible/web-servers.yml       the playbook
cmweb-scripts/ansible/roles/                11 roles
cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2
```

## Related

- [docs/learning/06-settings-and-management-commands.md](../learning/06-settings-and-management-commands.md) — how to *write* a command
- [docs/learning/08-ansible-and-apache.md](../learning/08-ansible-and-apache.md) — Ansible and Apache taught from first principles
- [docs/infrastructure.md](../infrastructure.md) — AWS topology
- [docs/02-management-commands.md](../02-management-commands.md) — the earlier deep-dive
