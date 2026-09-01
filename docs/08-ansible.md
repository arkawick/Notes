# 8. Ansible and the deployment scripts

*How a bare server becomes a CMWEB server. The `cmweb-scripts` repository.*

---

## Part A — The concept

### What Ansible is

A configuration-management tool. You describe the **desired state** of a machine
in YAML, and Ansible makes it so — installing packages, writing files, starting
services.

The key property is **idempotence**: running a playbook twice is the same as
running it once. Tasks check current state and act only if needed. That is why
they read as descriptions rather than commands:

```yaml
- name: Install packages
  ansible.builtin.apt:
    name: apache2
    state: present     # "make sure it is installed", not "install it"
```

### The vocabulary

| Term | Meaning |
| --- | --- |
| **Task** | One unit of work — install a package, write a file |
| **Module** | The thing a task calls (`apt`, `file`, `template`, `service`) |
| **Role** | A reusable bundle of tasks, templates and variables |
| **Play** | Maps a set of roles onto a set of hosts |
| **Playbook** | A file containing one or more plays |
| **Inventory** | The list of hosts, in groups |
| **Handler** | A task that runs only when *notified* by a changed task |
| **Vault** | Encrypted variable files |

### Templates

Ansible renders files through Jinja2, so config can vary per environment:

```apache
ServerName {{ hostname }}
```

with `hostname` coming from a variable file. `{{ }}` inserts a value; `{% %}`
does logic.

### Handlers

A handler runs at the end of the play, and only if something notified it:

```yaml
tasks:
  - name: Install Apache virtualhost config
    ansible.builtin.template:
      src: apache/cmweb.conf.j2
      dest: /etc/apache2/sites-available/000-cmweb.conf
    notify: Reload Apache      # only if the file actually changed

handlers:
  - name: Reload Apache
    ansible.builtin.service:
      name: apache2
      state: reloaded
```

Handlers run **once**, at the end, no matter how many tasks notified them —
which is exactly what you want for a service restart.

### Variable precedence

Ansible has many places to put variables. CMWEB uses:

```
group_vars/all      → every host
group_vars/web      → web servers
group_vars/prod     → production only
encrypted_vars/*    → secrets (vault-encrypted)
```

More specific wins.

---

## Part B — CMWEB's layout

```
cmweb-scripts/
├── ansible/
│   ├── web-servers.yml        ← the only playbook
│   ├── ansible.cfg
│   ├── hosts/{prod,stage,test}
│   ├── group_vars/{all,web,prod,stage,test}
│   ├── encrypted_vars/*.yml   ← vault
│   └── roles/                 ← 11 roles
├── jobs_on_cloud/             ← Jenkins jobs (see infrastructure.md)
├── cloudformation/            ← AWS stacks
├── agent/                     ← Jenkins agent AMI (Packer)
├── bin/                       ← git mirroring
└── configurator/              ← git SUBMODULE
```

> `configurator` is a **submodule**. Clone with `--recursive`, or run
> `git submodule init && git submodule update`. `jobs_on_cloud/Makefile` does
> `include ../configurator/Makefile`, so the job targets fail without it.

### The playbook

`web-servers.yml` has three plays — prod, stage, test — with the same role list
against different inventories:

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

Test omits `efs` and `cronjob`; that is the only structural difference.

### Running it

```bash
cd ansible
# vault password must be in ../.vault first
ansible-playbook --vault-password-file ../.vault -c local -i hosts/test  web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod  web-servers.yml
```

Note **`-c local`** and the inventories:

```ini
[production_web_servers]
localhost prod=1
```

`-c local` means "do not SSH anywhere, act on this machine". So this is **a
machine configuring itself** — run during AMI build or on the instance — not a
push from a control node. That is why `become: true` is set at the play level
and why the roles freely use `sudo`.

---

## Part C — The roles

| # | Role | Responsibility |
| --- | --- | --- |
| 1 | `environment` | `/etc/environment`; sets needrestart to `'a'` (auto-restart services, no prompts) |
| 2 | `sonyca` | Sony Root / Intranet / B2B CA certificates |
| 3 | `certificate` | Sony package-repository certificates |
| 4 | `package` | Base OS packages, per Ubuntu release |
| 5 | `cmweb-account` | The `cmweb` user, SSH keys, sudo rules |
| 6 | `cmweb-node` | **The application deploy** |
| 7 | `apache-server` | vhost, modules, SSL, static compression |
| 8 | `cloudwatch-agent` | Log and metric shipping |
| 9 | `efs` | Mounts EFS at `/mnt/nfs` (not on test) |
| 10 | `cronjob` | `apache_status_logging.py` every 5 minutes |
| 11 | `c1ws` | Trend Micro workload security agent |

Order matters: CAs before packages (the package repo is HTTPS), the account
before the deploy that runs as it, the deploy before Apache which serves it.

### `package` — per-release variables

```
roles/package/vars/bionic.yml   # Ubuntu 18.04
roles/package/vars/focal.yml    # Ubuntu 20.04
roles/package/vars/jammy.yml    # Ubuntu 22.04
```

Mirrors the split in `cmweb-project/etc/requirements-20.txt` vs `-22.txt`.

### `cmweb-account` — fixed ids

```yaml
- name: Create sg
  ansible.builtin.group:
    name: "{{ cmweb_write_group }}"
    gid: 1111

- name: Create cmweb user
  ansible.builtin.user:
    name: cmweb
    uid: 2222
```

Hardcoded uid/gid, because files live on **shared EFS** — the numeric ids must
match across every instance or permissions break.

### `cmweb-node` — the deploy itself

The most important role. In order:

1. **Raise `nofile` ulimits** — 16 processes × 15 threads need the descriptors.
2. **Fetch the code**:
   ```yaml
   - name: Initialise CMWEB manifest
     ansible.builtin.command:
       cmd: "repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m {{ manifest }}.xml -b cloudj2"
       creates: "/srv/www/{{ hostname }}/.repo/manifest.xml"
   - name: Fetch CMWEB code
     ansible.builtin.command:
       cmd: repo sync -c -d
   ```
   This produces `site/` and `site/apps/` — the layout Django expects. Prod uses
   `release.xml` (pinned); other environments use `default.xml` (floating).
   `creates:` makes the first task idempotent.
3. **Render `secure.py`** from a Jinja2 template with vault values:
   ```
   DATABASES__DEFAULT__HOST = '{{ django_db_host }}'
   AUTH_DEFAULT_SERVICE_PASSWORD = '{{ system_password }}'
   OPENSEARCH_HOST = '{{ opensearch_host }}'
   ```
   This is the only place those credentials touch disk.
4. **Symlink the settings**: `settings_deployed.py` → `settings_<env>.py`.
5. **Symlink shared storage**: `static/media` → `/mnt/nfs/media`,
   `repository` → `/mnt/nfs/cmweb/repo-mirror`.
6. **`make static`** with `DJANGO_SETTINGS_MODULE=cmweb.settings_deployed` —
   builds the virtualenv into `ENV/` and compresses assets.
7. **Inject Sony CAs into the virtualenv's `certifi` bundle**:
   ```yaml
   - name: Add Sony B2B CA
     ansible.builtin.blockinfile:
       path: "/srv/www/{{ hostname }}/ENV/lib/python{{ pyver.stdout }}/site-packages/certifi/cacert.pem"
       insertbefore: BOF
       marker: "# Sony B2B CA"
       block: "{{ sony_b2b_ca2_cer }}"
   ```
   Without this, `requests` cannot reach internal HTTPS services. The Python
   version is discovered at runtime by a shell task.

   > **Fragile by nature**: it edits a file *inside* an installed package.
   > Reinstalling or upgrading `certifi` silently undoes it. Note this is
   > separate from the *system* CA bundle at
   > `/etc/ssl/certs/ca-certificates.crt` that `GerritRESTClientMixin`
   > hardcodes — two bundles, both needed, used by different code.
8. **Logrotate config** for `var/log`.

Note what is **absent**: no `migrate`. Schema changes run through the
`migrate_db` Jenkins job instead — see [06-migrations.md](06-migrations.md).

### `apache-server`

Covered in [07-apache-deployment.md](07-apache-deployment.md). It declares a
dependency:

```yaml
# roles/apache-server/meta/main.yml
dependencies:
  - { role: sonyca }
```

so the CAs are guaranteed present before SSL is configured, regardless of play
order.

---

## Part D — Vault and the secret convention

Secrets live in `encrypted_vars/`, `ansible-vault`-encrypted. The repo's own
README states the rule:

> Start with `vault_` in `encrypted_vars/*` and refer no vault variables through
> `group_vars/*`.

So the vault contains:

```yaml
vault_django_db_password: "…"
vault_ssh_private_key: "…"
```

and `group_vars/` maps them:

```yaml
django_db_password: "{{ vault_django_db_password }}"
ssh_private_key: "{{ vault_ssh_private_key }}"
```

Roles only ever reference the unprefixed name. Two benefits, both stated in the
README:

- Roles do not need to know whether a value is secret.
- Developers can grep for variable names without decrypting anything.

### Working with the vault

```bash
ansible-vault edit encrypted_vars/access-prod.yml

# see plaintext diffs for vaulted files in git
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"
git config --unset diff.ansible-vault.textconv     # when done

# lint
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml
# expected: Passed: 0 failure(s), 0 warning(s) on 19 files
```

`.vault`, `.key` and `.vault_password` are gitignored. The password is on the
internal Confluence page "Service accounts and passwords".

---

## Part E — Environment configuration

`group_vars/all` — shared:

```yaml
system_account: jp21602
cmweb_write_group: somc-sw-cmweb
django_cache_port: 11211
django_db_port: 5432
django_db_name: cmweb
pam_limits_nofile_soft: 33333
pam_limits_nofile_hard: 64000
ldap_server: LDAP.jp.sony.com
```

`group_vars/prod`:

```yaml
nfs_volume: 10.26.14.9:/
hostname: cmweb.ptc.sony.co.jp
manifest: release
django_environment: prod
django_db_host: 'cmweb.cm8tmtafyb32.ap-northeast-1.rds.amazonaws.com'
django_cache_host: 'cmweb.myfjt0.cfg.apne1.cache.amazonaws.com'
opensearch_host: 'https://vpc-cmweb-prod-….aos.ap-northeast-1.on.aws'
```

Note the derived variable in `group_vars/all`:

```yaml
hostname_short: '{{ hostname | regex_replace("\..*$", "") }}'
```

`cmweb.ptc.sony.co.jp` → `cmweb`, used for the WSGI process group and config
filenames.

> **Duplication worth knowing about.** These same endpoints are **repeated** in
> `jobs_on_cloud/macros.yaml`, where the `cmweb-generate-settings` macro selects
> them by inspecting `$JENKINS_URL`. Changing an RDS, cache or OpenSearch
> endpoint means editing **both** `ansible/group_vars/<env>` **and**
> `jobs_on_cloud/macros.yaml`. Nothing enforces that they agree.

---

## Part F — The rest of `cmweb-scripts`

### CloudFormation

```bash
cd cloudformation
./upload_all.sh                                  # push templates to S3
./create-stack.sh      PATH/TO/ROOT_TEMPLATE.yaml   # first time
./create-change-set.sh PATH/TO/ROOT_TEMPLATE.yaml   # updates, then execute in console
./validate-template.sh PATH/TO/TEMPLATE.yaml
```

- `ec2imagebuilder/` — the pipeline that bakes the web AMI. Its components fetch
  `cmweb-scripts`, fetch tools, and **run the Ansible playbook** — which is how
  `-c local` makes sense.
- `iam/` — instance profiles for web servers, Jenkins agents, image builder.
- `vpc/` — security groups for RDS, ElastiCache, test.

### Git mirroring

`bin/mirror_repo.sh` maintains the bare git mirrors the indexer reads:

```bash
manifest_server=https://${SERVICE_USERNAME}:${SERVICE_PASSWORD}@cmweb.ptc.sony.co.jp/rpc
python $here/manifest.py $manifest_server $magic_mirror_tag
...
java -jar $here/mirror-creator.jar --fetch-notes ...
```

Two details:

- It asks **CMWEB's own `/rpc` endpoint** for the mirror manifest — served by
  `explorer/__init__.py`. The app and its data pipeline are circular, which is
  why the Apache vhost grants `/rpc/` anonymous access.
- **`--fetch-notes`** brings across `refs/notes/review`, which `repo sync` does
  not fetch by default. That ref is where commit approvers and verifiers come
  from; without it commits index with empty review metadata.

`etc/mirror-repo-rules.txt` and `-prio.txt` decide which projects get mirrored.

### The Jenkins agent AMI

`agent/` — Packer plus Ansible for the build agents. `agent.yml` applies a
`packages` role with per-release vars; `.pkrvars.hcl` files are the Packer
variable sets for Ubuntu 18.04 and 20.04.

---

## Part G — Making a change

Changes to `cmweb-scripts` go through Gerrit like application code, and are
verified by the `verify_ansible_playbook` and `verify_jenkins_jobs` Jenkins jobs.

```bash
repo start my-change .
# edit
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml            # must pass clean
repo upload .
```

```
[ ] ansible-lint passes (0 failures on 19 files)
[ ] new secrets are vault_-prefixed and mapped through group_vars
[ ] file/template changes notify the right handler
[ ] tasks are idempotent (creates:, state:, changed_when:)
[ ] endpoint changes applied to jobs_on_cloud/macros.yaml too
[ ] tested on test before stage before prod
```

### Debugging

```bash
ansible-playbook ... --check          # dry run
ansible-playbook ... --diff           # show file changes
ansible-playbook ... -vvv             # verbose
ansible-playbook ... --start-at-task="Install packages"
ansible-playbook ... --tags apache    # if tags are defined
```

`--check` is imperfect here: several tasks are `command`/`shell`, which Ansible
cannot dry-run meaningfully.

---

That is the last of the eight. Back to the [index](internals.md).
