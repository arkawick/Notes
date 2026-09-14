# 04 — Ansible playbooks

`cmweb-scripts/ansible/` builds a CMWEB web server. One playbook, three plays
(prod/stage/test), **11 roles**, and a vault.

For Ansible taught from first principles, see
[learning/08](../learning/08-ansible-and-apache.md). This document is the
operational reference: every role, every variable source, and the full deploy
path.

---

## 1. The crucial context: this is an AMI build, not a deploy to a server

Ansible never reaches out to a fleet. It runs **on the machine being baked**,
configuring itself, and the result is captured as an AMI.

```
EC2 Image Builder
  └─ component `provision-web`
       export HOME=/root
       cd ~/cmweb-scripts/ansible
       ACCOUNT_ID=`curl -s http://169.254.169.254/latest/meta-data/identity-credentials/ec2/info/ | jq -r ".AccountId"`
       if   [ "659398199407" = "${ACCOUNT_ID}" ]; then ENV="prod"
       elif [ "009896685360" = "${ACCOUNT_ID}" ]; then ENV="stage"
       elif [ "100267242497" = "${ACCOUNT_ID}" ]; then ENV="test"
       fi
       ansible-playbook --vault-password-file ~/.vault -c local -i hosts/$ENV web-servers.yml
  └─ result baked into an AMI (Ubuntu 20 / 22)
```

Source: `cmweb-scripts/cloudformation/ec2imagebuilder/builder-cmweb-component-provision-web.yaml`.

This explains two things that otherwise look wrong:

**Every inventory is `localhost`:**

```ini
# hosts/prod
[production_web_servers]
localhost prod=1
```

**The environment is discovered, not passed.** The playbook asks the instance
metadata service which AWS account it is in, and maps the account id to
prod/stage/test. There is no `-e env=prod`.

---

## 2. The playbook

`web-servers.yml` — three plays, identical except for variables and two roles:

```yaml
- name: Production web servers
  hosts: production_web_servers
  become: true
  roles:
    - environment
    - sonyca
    - certificate
    - package
    - cmweb-account
    - cmweb-node
    - apache-server
    - cloudwatch-agent
    - efs
    - cronjob
    - c1ws
  vars_files:
    - group_vars/web
    - group_vars/prod
    - encrypted_vars/common.yml
    - encrypted_vars/access-prod.yml
```

**Role order is dependency order** — OS environment, then CA certificates, then
the apt repo and packages, then the `cmweb` user, then the code, then Apache,
then monitoring.

`test` omits **`efs`** and **`cronjob`**. That is a real functional difference:
the test environment has no shared git mirror (`nfs_volume: dummy_nfs:/`) and no
Apache status logging.

---

## 3. The 11 roles

| Role | Tasks | What it does |
| --- | --- | --- |
| `environment` | 2 | `/etc/environment`, needrestart auto-restart config |
| `sonyca` | 5 | Installs Sony Root / Intranet / B2B CA certs, `update-ca-certificates` |
| `certificate` | 7 | apt keyring + `swerepo.list` for the internal package repo; fetches and installs the host certificate |
| `package` | 3 | apt upgrade, then the base package list |
| `cmweb-account` | 12 | The `cmweb` user and group, SSH key for Gerrit, sudo, `somc-gitconfig`, `somc-setup-review` |
| `cmweb-node` | 21 | **The application** — `repo sync`, `secure.py`, `settings_deployed` symlink, `make static`, directories, logrotate, CA certs into certifi |
| `apache-server` | 17 | Apache, mod_wsgi, the vhost, module symlinks, SSL, start |
| `cloudwatch-agent` | 7 | collectd + the CloudWatch agent and its config |
| `efs` | 3 | `nfs-common`, mounts the EFS volume at `/mnt/nfs` |
| `cronjob` | 7 | pip3, `/srv/cron`, `apache_status_logging.py`, the crontab |
| `c1ws` | — | Cloud One Workload Security agent (`install_c1ws_agent.sh`) |

### `package` — distribution-aware

```yaml
- name: Include package file
  ansible.builtin.include_vars:
    file: "vars/{{ ansible_distribution_release }}.yml"
```

`vars/bionic.yml`, `focal.yml`, `jammy.yml` — currently identical:

```yaml
package_debs:
  - python3, python3-dev, python3-venv, libssl-dev
  - curl, git, xz-utils
  - ca-certificates, ptc-certificate, sonypki-certificate
```

The indirection exists so a future Ubuntu release can differ without touching
the tasks. Note `upgrade: true` on the apt task — the AMI build takes whatever
the archive has that day, so two AMIs built a week apart are not identical.

### `efs` — the git mirror mount

```yaml
- name: Mount volume
  ansible.posix.mount:
    name: /mnt/nfs
    src: "{{ nfs_volume }}"
    fstype: nfs4
    opts: "nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=60,retrans=2,noresvport"
    state: mounted
```

`nfs_volume` is `10.26.14.9:/` in prod, `dummy_nfs:/` in test — which is why the
test play omits this role entirely. `hard` mount semantics mean a hung EFS
blocks readers indefinitely rather than returning errors: an EFS problem shows
up as hanging page loads, not 500s.

### `cmweb-node` — how the application gets onto the box

The 21 tasks, in narrative order:

```yaml
- name: Set hard/soft limit to number of open files for cmweb
  ansible.builtin.lineinfile:
    dest: /etc/security/limits.conf
    line: 'cmweb hard nofile {{ pam_limits_nofile_hard }}'    # 64000 / 33333
```

```yaml
- name: Initialise CMWEB manifest
  ansible.builtin.command:
    cmd: "repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m {{ manifest }}.xml -b cloudj2"
    creates: "/srv/www/{{ hostname }}/.repo/manifest.xml"
  become_user: cmweb

- name: Fetch CMWEB code
  ansible.builtin.command:
    cmd: repo sync -c -d
  changed_when: false
```

`creates:` is how a `command` task is made idempotent — skip if that path
exists. `manifest` is `release` in prod, `default` in test.

```yaml
- name: Create secure.py
  ansible.builtin.template:
    src: django/secure.py.j2
    dest: "/srv/www/{{ hostname }}/site/cmweb/secure.py"
    mode: "0640"
    owner: cmweb

- name: Link Django settings file
  ansible.builtin.file:
    path: "/srv/www/{{ hostname }}/site/cmweb/settings_deployed.py"
    src: "settings_{{ django_environment }}.py"
    state: link
```

**These two tasks are the whole settings story.** `secure.py` is generated from
the vault at mode 0640 (it holds the DB and LDAP service passwords);
`settings_deployed.py` is a symlink chosen by `django_environment`.

```yaml
- name: Link repo-mirror in NFS
  ansible.builtin.file:
    path: "/srv/www/{{ hostname }}/repository"
    src: /mnt/nfs/cmweb/repo-mirror
    state: link
    force: true
```

This is `settings.GLOBALS['PATH_REPOSITORY']` — the bare git mirrors that
`Project.git_path()` and dulwich read.

The last three tasks are subtle and worth knowing about:

```yaml
- name: Get Python version
  ansible.builtin.shell:
    cmd: |
      set -o pipefail
      version=`python3 --version`
      echo ${version%.*} | cut -d" " -f2
  register: pyver
  changed_when: false

- name: Add Sony B2B CA
  ansible.builtin.blockinfile:
    path: "/srv/www/{{ hostname }}/ENV/lib/python{{ pyver.stdout }}/site-packages/certifi/cacert.pem"
    insertbefore: BOF
    marker: "# Sony B2B CA"
    block: "{{ sony_b2b_ca2_cer }}"
```

**The three Sony CAs are injected into `certifi`'s bundle inside the
virtualenv.** `requests` (and therefore every JIRA, Gerrit and C2D call) uses
certifi's bundle, not the system store, so installing the CAs with
`update-ca-certificates` is not enough. The Python version is discovered at
runtime to build the site-packages path.

> If `requests` starts failing TLS verification against an internal host after
> a virtualenv rebuild, this is the task that did not run.

### `cronjob` — the only cron on the box

The crontab, once the comment header is stripped, is a single line:

```cron
*/5 * * * * /srv/cron/apache_status_logging.py
```

That is all. **Everything else scheduled runs in Jenkins, not cron.** The
config it reads is rendered from the vault:

```json
{
    "HOSTNAME": "{{ hostname }}",
    "SERVICE_USER": "{{ system_account }}",
    "SERVICE_PASS": "{{ system_password }}"
}
```

### `apache-server`

Covered directive-by-directive in [05](05-apache-config.md). The three tasks
worth repeating here are the change-detection pair and the reload mechanism:

```yaml
- name: Freeze manifest
  ansible.builtin.command:
    cmd: repo manifest -r
  register: static_manifest
  changed_when: false

- name: Check code change
  ansible.builtin.copy:
    content: '{{ static_manifest.stdout }}'
    dest: "/srv/www/{{ hostname }}/static-manifest-wsgi.xml"
  notify: Restart WSGI
```

`repo manifest -r` prints the exact revision of every repository. Writing it
with `copy` means Ansible's own idempotence acts as a content hash: unchanged
content → task reports `ok` → handler not notified. **The application reloads
only when the code actually changed.**

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

mod_wsgi in daemon mode watches the script's mtime. `touch` is the reload — no
service restart, no dropped connections.

---

## 4. Variables

### Three layers

```
group_vars/all      shared, non-secret       system_account, ldap_server, ports, ulimits
group_vars/web      target_account, home
group_vars/<env>    per-environment          hostname, db host, cache host, opensearch, manifest
encrypted_vars/*    vault-encrypted          vault_* names only
```

`group_vars/all`:

```yaml
system_account: jp21602            # managed by https://idm.jp.sony.com/IDM_Web/
cmweb_write_group: somc-sw-cmweb

# The first label of the logs_hostname FQDN, i.e. the part before the first dot.
hostname_short: '{{ hostname | regex_replace("\..*$", "") }}'

# Defined in encrypted_vars/common.yml
system_password: "{{ vault_system_password }}"
django_db_password: "{{ vault_django_db_password }}"

django_cache_port: 11211
django_db_port: 5432
django_db_name: cmweb

pam_limits_nofile_soft: 33333
pam_limits_nofile_hard: 64000

ldap_server: LDAP.jp.sony.com
```

### Per-environment differences

| Variable | prod | stage | test |
| --- | --- | --- | --- |
| `hostname` | `cmweb.ptc.sony.co.jp` | `cmweb.ptc-stage…` | `cmweb.ptc-test…` |
| `manifest` | `release` | — | `default` |
| `django_environment` | `prod` | `stage` | `test` |
| `nfs_volume` | `10.26.14.9:/` | — | `dummy_nfs:/` |
| `opensearch_host` | real VPC endpoint | real | `localhost` (dummy) |

`hostname_short` is derived once and then names the Apache config file, the
WSGI process group, the log format and the logrotate config. Change `hostname`
and all five follow.

### The vault convention

From the `README`:

> Start with "vault_" in encrypted_vars/* and refer no vault variables through
> group_vars/*. The reasons are:
> - Files in roles/* don't want to know whether variables are vault or not
> - Developers cannot search variables in encrypted_vars/ until they decrypt them

So roles say `system_password`; `group_vars/all` maps that to
`vault_system_password`; only `encrypted_vars/common.yml` holds the value. You
can grep `group_vars/` to learn every secret's *name* without being able to read
one.

```bash
ansible-vault edit encrypted_vars/common.yml
ansible-vault view encrypted_vars/access-prod.yml
```

Password is in Confluence (`Service accounts and passwords`). To see plaintext
in `git diff`:

```bash
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"
```

---

## 5. Running and checking

```bash
ansible-playbook --vault-password-file ../.vault -c local -i hosts/test  web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod  web-servers.yml
```

| Flag | Use |
| --- | --- |
| `--check --diff` | Preview: report changes and show the before/after of every template. **The safe way to review a `cmweb.conf.j2` edit.** |
| `--list-tasks` | What would run |
| `--start-at-task="name"` | Resume after a failure |
| `--tags` / `--skip-tags` | Subset |
| `-vvv` | Verbose |
| `--syntax-check` | Parse only |

### Linting

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml
```

Expected clean result, per the README:

> Passed: 0 failure(s), 0 warning(s) on 19 files. Last profile that met the
> validation criteria was 'production'.

Enforced in CI by the `verify_ansible_playbook` Jenkins job.

`ansible.cfg`:

```ini
[defaults]
host_key_checking = False
retry_files_enabled = False
interpreter_python=/usr/bin/python3
```

---

## 6. What the deploy does NOT do

Two absences that surprise people, both deliberate:

**No migrations.** There is no `manage.py migrate` in any role. Schema changes
go through the separate `migrate_db` Jenkins job, whose description says
*"Migrate DB asynchronously against creating AMI"*. **Shipping a schema change
is two operations, not one**, and they can happen in either order — so a
migration must be compatible with both the old and new application code
transiently.

**No Celery worker.** No role installs or starts one, and no broker URL exists
in the Ansible-rendered `secure.py`. Combined with
`CELERY_TASK_ALWAYS_EAGER = True` in the base settings and re-asserted in
`bin/run_commands.sh`, this is the evidence that every `.delay()` runs inline in
the calling thread.

---

## 7. Known rough edges

Real issues in the current roles. None is breaking anything today; all are worth
understanding before copying the pattern.

**`Restart WSGI` references an unregistered variable:**

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
  changed_when: result.rc == 0
```

`result` is never registered in this handler. The condition is not evaluating
what it appears to.

**`Update CA crt` sudoes inside an already-`become: true` play:**

```yaml
- name: Update CA crt
  ansible.builtin.command:
    cmd: sudo update-ca-certificates
  register: result
  changed_when: result.rc == 0
```

The `sudo` is redundant, and `changed_when: result.rc == 0` means "report
changed whenever it succeeds" — so this task always shows as changed, defeating
the point of idempotence reporting. The same pattern appears in the
`apache-server` role.

**`apt upgrade: true` in the `package` role** makes AMI builds
non-reproducible: the same commit built on two different days can produce
different package sets.
