# 04 — Ansible playbooks

`cmweb-scripts/ansible/` builds a CMWEB web server: one playbook, three plays
(prod / stage / test), **11 roles**, 56 files, and an encrypted vault.

For Ansible taught from first principles, see
[learning/08](../learning/08-ansible-and-apache.md). This document is the
operational reference — every role, every variable source, the idempotence
patterns in use, and the bugs currently in the tree.

---

## 1. The model: this is an AMI build, not a deploy

Ansible never reaches out to a fleet of servers. It runs **on the machine being
baked**, configuring itself, and the result is captured as an AMI.

```
EC2 Image Builder pipeline  (cloudformation/ec2imagebuilder/)
  ├─ 1. setup-proxy          apt proxy, or nothing can download
  ├─ 2. get-tools            awscli, jq, ansible
  ├─ 3. setup-password       vault password from Secrets Manager -> ~/.vault (0400)
  ├─ 4. get-scripts          SSH key, git config, clone cmweb-scripts @ cloudj2, submodules
  ├─ 5. provision-web  ───►  export HOME=/root
  │                          cd ~/cmweb-scripts/ansible
  │                          ACCOUNT_ID=`curl -s http://169.254.169.254/latest/meta-data/…`
  │                          if   659398199407 -> ENV=prod
  │                          elif 009896685360 -> ENV=stage
  │                          elif 100267242497 -> ENV=test
  │                          ansible-playbook --vault-password-file ~/.vault \
  │                                           -c local -i hosts/$ENV web-servers.yml
  └─ 6. teardown-password    rm ~/.vault
                                   │
                                   ▼
                         AMI: cmweb-web  (tagged System=cmweb)
```

Three consequences that explain otherwise-baffling details:

**Every inventory is `localhost`:**

```ini
# hosts/prod              # hosts/stage             # hosts/test
[production_web_servers]  [stage_web_servers]       [test_web_servers]
localhost prod=1          localhost stage=1         localhost test=1
```

**The environment is discovered, not passed.** The playbook asks the instance
metadata service which AWS account it is in. There is no `-e env=prod`.

**Secrets never reach the image.** The vault password is fetched in component 3,
used in component 5, deleted in component 6 — all before the snapshot.

> Running a *playbook* is therefore not how you ship a change to production. You
> rebuild the AMI and replace instances. Running `ansible-playbook` by hand on a
> live host is a debugging action, not a deploy.

---

## 2. Layout

```
cmweb-scripts/ansible/
├── ansible.cfg              3 settings
├── README                   how to run, vault conventions, lint
├── ssh_config               CMWEB_ON_AWS host entry
├── web-servers.yml          the playbook: 3 plays
├── hosts/                   3 inventories, each one `localhost`
│   ├── prod  ├── stage  └── test
├── group_vars/              plain variables
│   ├── all     shared, non-secret
│   ├── web     target_account, home
│   └── prod / stage / test
├── encrypted_vars/          ansible-vault
│   ├── common.yml
│   └── access-prod.yml / access-stage.yml / access-test.yml
└── roles/                   11 roles
    ├── environment       ├── sonyca          ├── certificate
    ├── package           ├── cmweb-account   ├── cmweb-node
    ├── apache-server     ├── cloudwatch-agent
    ├── efs               ├── cronjob         └── c1ws
```

`ansible.cfg`:

```ini
[defaults]
host_key_checking = False       # cloning from Gerrit without a known_hosts prompt
retry_files_enabled = False     # no *.retry littering the repo
interpreter_python=/usr/bin/python3
```

---

## 3. The playbook

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

Three near-identical plays. **Role order is dependency order**, and each step
genuinely blocks the next:

```
environment      proxy in /etc/environment        ── nothing reaches the internet without it
   ▼
sonyca           Sony CA certificates             ── nothing can TLS-verify internal hosts
   ▼
certificate      apt keyring + swerepo.list       ── the internal apt repo becomes usable
   ▼
package          base packages (python3, git…)
   ▼
cmweb-account    the cmweb user, SSH key, sudo    ── needed to clone as cmweb
   ▼
cmweb-node       repo sync, secure.py, make static
   ▼
apache-server    Apache, mod_wsgi, the vhost
   ▼
cloudwatch-agent / efs / cronjob / c1ws           ── monitoring and storage
```

`apache-server` also declares `meta/main.yml: dependencies: [sonyca]`, so the CA
role is guaranteed even if someone reorders the playbook.

### Where the environments differ

| | prod | stage | test |
| --- | --- | --- | --- |
| Roles | all 11 | all 11 | **omits `efs` and `cronjob`** |
| `hostname` | `cmweb.ptc.sony.co.jp` | `cmweb.ptc-stage.sony.co.jp` | `cmweb.ptc-test.sony.co.jp` |
| `manifest` | `release` | `default` | `default` |
| `nfs_volume` | `10.26.14.9:/` | `10.26.41.95:/` | `dummy_nfs:/` |
| `django_environment` | `prod` | `stage` | `test` |
| `opensearch_host` | real VPC endpoint | real VPC endpoint | `localhost` (dummy) |

The test omissions are real behaviour, not tidying: **no EFS means no git
mirror**, so git-backed pages and all indexing are inoperative there; **no
cronjob means no `/server-status` scraping**, so there are no CloudWatch
scoreboard metrics for test.

---

## 4. The roles

### 4.1 `environment` (2 tasks)

```yaml
- name: Update /etc/environment
  ansible.builtin.template: { src: environment, dest: /etc/environment, mode: "0644" }

- name: Update needrestart conf to restart automatically
  ansible.builtin.template:
    src: 50-autorestart.conf
    dest: /etc/needrestart/conf.d/50-autorestart.conf
```

The environment file:

```
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"

https_proxy=http://proxy-sen.noc.sony.co.jp:10080
http_proxy=http://proxy-sen.noc.sony.co.jp:10080
no_proxy=169.254.169.254,localhost,127.0.0.0/8,::1,10.0.0.0/8,.ptc.sony.co.jp,.amazonaws.com,amazonaws.com
```

**`169.254.169.254` in `no_proxy` is load-bearing.** That is the EC2 instance
metadata service; routing it through the corporate proxy would break the
account-id detection that selects the environment, the IAM instance-profile
credentials, and everything that depends on them.

```
$nrconf{restart} = 'a';
```

sets needrestart to restart services automatically rather than prompting —
essential for an unattended `apt upgrade` on Ubuntu 22, which otherwise hangs
on an interactive dialog.

### 4.2 `sonyca` (5 tasks)

Installs three CA certificates and runs `update-ca-certificates`:

```
/usr/local/share/ca-certificates/extra/Sony_Root_CA2.crt
/usr/local/share/ca-certificates/extra/Sony_Intranet_CA2.crt
/usr/local/share/ca-certificates/extra/Sony_B2B_CA2.crt
```

The certificate bodies come from `group_vars/all`, referencing the vault:

```yaml
sony_b2b_ca2_cer: "{{ vault_sony_b2b_ca2_cer}}"
sony_root_ca2_cer: "{{ vault_sony_root_ca2_cer }}"
sony_intranet_ca2_cer: "{{ vault_sony_intranet_ca2_cer }}"
```

> These are public CA certificates, not secrets — vaulting them is belt and
> braces rather than necessity.

This role also matters for a reason not visible here: `update-ca-certificates`
is what turns the **server** certificate into `/etc/ssl/certs/cmweb.pem`, which
the Apache vhost references. See [05 §4](05-apache-config.md).

### 4.3 `certificate` (7 tasks)

Wires up the internal Artifactory apt repository, then installs two certificate
packages from it.

```yaml
- name: Get credentials to access buildrepo
  block:
    - name: Fetch credentials
      ansible.builtin.uri:
        url: https://api.ptc.sony.co.jp/buildrepo/mc-k3f9b2q1
        return_content: true
        body_format: json
      register: certificate_credentials
    - name: Get username
      ansible.builtin.set_fact:
        certificate_buildrepo_username: "{{ (certificate_credentials.content | from_json).globaltools.username }}"
      no_log: true
    - name: Get password
      ansible.builtin.set_fact:
        certificate_buildrepo_password: "{{ (certificate_credentials.content | from_json).globaltools.password }}"
      no_log: true
```

**Credentials are fetched at runtime from an internal endpoint** rather than
stored in the vault, and `no_log: true` keeps them out of the Ansible output.
The URL path (`mc-k3f9b2q1`) is effectively the shared secret.

```yaml
- name: Install key for buildrepo
  ansible.builtin.get_url:
    url: https://ptcrepo.jfrog.io/artifactory/globaltools/keys/swerepo_saas_public.gpg
    dest: /etc/apt/keyrings/swerepo.gpg
    validate_certs: false        # <-- note
```

`validate_certs: false` appears here **and** on the `Get certificate` task — TLS
verification disabled while fetching the very packages that establish trust. A
chicken-and-egg workaround; worth knowing it is there.

`templates/swerepo.list`:

```
deb [signed-by=/etc/apt/keyrings/swerepo.gpg] https://ptcrepo.jfrog.io/artifactory/swerepo jammy main
deb [signed-by=/etc/apt/keyrings/swerepo.gpg] https://ptcrepo.jfrog.io/artifactory/swerepo jammy jammy-updates main
deb [signed-by=/etc/apt/keyrings/swerepo.gpg] https://ptcrepo.jfrog.io/artifactory/swerepo jammy devpack
```

**The release is hardcoded to `jammy`**, despite `package/vars/` supporting
bionic, focal and jammy and the recipes building both Ubuntu 20 and 22. On a
focal build this points at the wrong suite.

```yaml
certificate_base_url: https://ptcrepo.jfrog.io/artifactory/globaltools/certs/packages
certificate_packages:
  - ptc-certificate.deb
  - sonypki-certificate.deb
```

### 4.4 `package` (3 tasks)

```yaml
- name: Include package file
  ansible.builtin.include_vars:
    file: "vars/{{ ansible_distribution_release }}.yml"

- name: Apt update/upgrade
  ansible.builtin.apt: { update_cache: true, upgrade: true }

- name: Install packages
  ansible.builtin.apt:
    name: "{{ package_debs }}"
    state: present
    install_recommends: false
    update_cache: false
```

`vars/bionic.yml`, `focal.yml`, `jammy.yml` — currently **identical**:

```yaml
package_debs:
  - python3, python3-dev, python3-venv, libssl-dev
  - curl, git, xz-utils
  - ca-certificates, ptc-certificate, sonypki-certificate
```

The indirection exists so a future release can differ without touching tasks.
`install_recommends: false` keeps the image lean.

> **`upgrade: true` makes AMI builds non-reproducible.** The same commit built a
> week apart produces a different package set. Combined with
> `ParentImage: x.x.x` in the Image Builder recipe, there is no pinned input at
> all.

### 4.5 `cmweb-account` (12 tasks)

Creates the service account everything else runs as.

```yaml
- name: Create sg
  ansible.builtin.group: { name: "{{ cmweb_write_group }}", gid: 1111 }

- name: Create cmweb group
  ansible.builtin.group: { name: cmweb, system: true, gid: 2222 }

- name: Create cmweb user
  ansible.builtin.user:
    name: cmweb
    home: /home/cmweb
    shell: /bin/bash
    system: true
    uid: 2222
```

**UIDs and GIDs are pinned** (1111, 2222). That matters because the EFS git
mirror is shared across hosts — file ownership must agree between a web server,
a Jenkins slave and a freshly baked AMI, and NFS carries numeric ids.

SSH key for Gerrit, from the vault:

```yaml
- name: Create SSH private key for Gerrit
  ansible.builtin.template:
    src: ssh/private_key.j2          # {{ ssh_private_key }}
    dest: /home/cmweb/.ssh/id_ed25519
    mode: "0600"
```

```yaml
- name: Create initial authorized_keys
  ansible.builtin.copy:
    src: /home/cmweb/.ssh/id_ed25519.pub
    dest: /home/cmweb/.ssh/authorized_keys
    force: false                     # never overwrite an existing file
    remote_src: true                 # src is on the target, not the controller
```

`force: false` means the key is seeded once and later additions survive.

#### The sudoers files

```yaml
- name: Allow cmweb to sudo
  ansible.builtin.template:
    src: "sudo/{{ item }}"
    dest: "/etc/sudoers.d/{{ item }}"
    mode: "0440"
    validate: 'visudo -cf %s'        # <-- validate before installing
  with_items: [ 20-owner, 40-cmweb, 50-pypi ]
```

`validate:` is the right pattern and worth copying: Ansible renders to a temp
file, runs `visudo -cf` on it, and only installs if it parses. A malformed
sudoers file can lock everyone out of root; this makes that impossible.

The contents are less reassuring. `40-cmweb`:

```
%somc-sw-cmweb ALL=(root) NOPASSWD: ALL
cmweb ALL=NOPASSWD: ALL
cmweb ALL=(cmweb) NOPASSWD: ALL
```

**Unrestricted passwordless root** for the `cmweb` user and for every member of
the `somc-sw-cmweb` group. Since Apache's WSGI daemon runs as `cmweb`, any
code-execution bug in the application is a direct path to root. A tighter
`Cmnd_Alias` limited to what the roles actually need (`update-ca-certificates`,
`mount`, `apt-get`) would close that.

`20-owner` is a ~50-line legacy **workstation** sudoers file — `nvidia-settings`,
`wireshark`, `jockey-gtk`, `vmware-modconfig`, `citrix_install.sh`,
`alsa force-reload`. None of it is meaningful on a headless web server. It is
copied from a desktop image and should be dropped.

#### Gerrit setup

```yaml
# as somc-setup-review just append settings to ~/.gitconfig
- name: Move ~/.gitconfig
  ansible.builtin.shell:
    cmd: mv ~/.gitconfig ~/.gitconfig$(date --iso-8601=minute)
    removes: ~/.gitconfig
  become_user: cmweb

- name: Execute somc-setup-review
  ansible.builtin.command:
    cmd: "somc-setup-review -i {{ system_account }} -p jp -f"
  become_user: cmweb
```

`somc-setup-review` **appends** rather than replaces, so a re-run would double
the config. The `Move` task sidesteps that by timestamping the old file aside,
guarded by `removes:` so it is a no-op when there is nothing to move.

### 4.6 `cmweb-node` (21 tasks) — the application

The biggest role. In order:

**File descriptor limits:**

```yaml
- ansible.builtin.lineinfile:
    dest: /etc/security/limits.conf
    line: 'cmweb hard nofile 64000'
- ansible.builtin.lineinfile:
    dest: /etc/security/limits.conf
    line: 'cmweb soft nofile 33333'
```

**Directories** — `/srv/www`, `/srv/www/<host>` at mode `02775` (setgid, so new
files inherit the `somc-sw-cmweb` group).

**Packages:** `repo`, `make`, `default-jre`, `somc-virtualenv3`. `default-jre`
is there for django-compressor's YUI minifier jar.

**The code:**

```yaml
- name: Initialise CMWEB manifest
  ansible.builtin.command:
    cmd: "repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m {{ manifest }}.xml -b cloudj2"
    creates: "/srv/www/{{ hostname }}/.repo/manifest.xml"
  become_user: cmweb

- name: Fetch CMWEB code
  ansible.builtin.command:
    cmd: repo sync -c -d
    chdir: "/srv/www/{{ hostname }}"
  become_user: cmweb
  changed_when: false
```

The `git://` URL works over authenticated SSH because the `get-scripts` Image
Builder component installed a `url.insteadOf` rewrite in root's `.gitconfig`.

**Settings — the two tasks that matter most:**

```yaml
- name: Create secure.py
  ansible.builtin.template:
    src: django/secure.py.j2
    dest: "/srv/www/{{ hostname }}/site/cmweb/secure.py"
    mode: "0640"
    owner: cmweb
    group: "{{ cmweb_write_group | lower }}"

- name: Link Django settings file
  ansible.builtin.file:
    path: "/srv/www/{{ hostname }}/site/cmweb/settings_deployed.py"
    src: "settings_{{ django_environment }}.py"
    state: link
```

`secure.py.j2` in full — twelve lines that close the loop with
[learning/06](../learning/06-settings-and-management-commands.md):

```
DATABASES__DEFAULT__HOST = '{{ django_db_host }}'
DATABASES__DEFAULT__PORT = '{{ django_db_port }}'
DATABASES__DEFAULT__NAME = '{{ django_db_name }}'
DATABASES__DEFAULT__PASSWORD = '{{ django_db_password }}'
CACHES__DEFAULT__HOST = '{{ django_cache_host }}'
CACHES__DEFAULT__PORT = '{{ django_cache_port }}'
AUTH_DEFAULT_SERVICE_USERNAME = '{{ system_account }}'
AUTH_DEFAULT_SERVICE_PASSWORD = '{{ system_password }}'
LDAP_SERVER = '{{ ldap_server }}'
OPENSEARCH_HOST = '{{ opensearch_host }}'
OPENSEARCH_AUTH_USERNAME = '{{ opensearch_username }}'
OPENSEARCH_AUTH_PASSWORD = '{{ opensearch_password }}'
```

Mode `0640` because it holds the database and LDAP service passwords.

**The git mirror link** — this is `settings.GLOBALS['PATH_REPOSITORY']`:

```yaml
- name: Link repo-mirror in NFS
  ansible.builtin.file:
    path: "/srv/www/{{ hostname }}/repository"
    src: /mnt/nfs/cmweb/repo-mirror
    state: link
    force: true
```

**Static assets:** `make static` with `DJANGO_SETTINGS_MODULE=cmweb.settings_deployed`,
with a nicely precise change test:

```yaml
  changed_when: "r.stdout and 'make: Nothing to be done for' not in r.stdout"
```

**Log rotation:**

```
/srv/www/{{ hostname }}/var/log/*.json {
  rotate 8   weekly   compress   delaycompress   missingok   notifempty
}
```

**The last three tasks — the certifi injection**, easily the least obvious thing
in the role:

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
# ... and the same for Sony Root CA and Sony Intranet CA
```

**`requests` uses certifi's bundle, not the system CA store.** Installing the
CAs with `update-ca-certificates` (the `sonyca` role) is not enough for Python —
every JIRA, Gerrit, C2D and M+ call would fail TLS verification. The Python
version is discovered at runtime to build the `site-packages` path, and
`blockinfile`'s `marker:` makes the insertion idempotent.

> **If `requests` starts failing certificate verification against an internal
> host after a virtualenv rebuild, these three tasks are what did not run.**

### 4.7 `apache-server` (17 tasks)

Covered directive-by-directive in [05](05-apache-config.md). The two patterns
worth repeating here:

```yaml
- name: Freeze manifest
  ansible.builtin.command: { cmd: repo manifest -r }
  register: static_manifest
  changed_when: false

- name: Check code change
  ansible.builtin.copy:
    content: '{{ static_manifest.stdout }}'
    dest: "/srv/www/{{ hostname }}/static-manifest-wsgi.xml"
  notify: Restart WSGI
```

`repo manifest -r` prints the exact revision of every repository in the
checkout. Writing it with `copy` turns **Ansible's own idempotence into a
content hash**: unchanged content → task reports `ok` → handler not notified.
The application reloads only when code actually changed. The same trick is
applied to `static/compressed/manifest.json`.

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

mod_wsgi daemon mode watches the script's mtime; `touch` is the whole reload.

### 4.8 `cloudwatch-agent` (7 tasks)

collectd, then the CloudWatch agent `.deb` downloaded straight from S3, then
config and start. The config template ships **three log streams**:

| File | CloudWatch log group |
| --- | --- |
| `/var/log/apache2/{{ hostname }}_access.log` | `cmweb/apache/accesslog` |
| `/srv/www/{{ hostname }}/var/log/wsgi.json` | `cmweb/apache/wsgi` |
| `/srv/cron/logs/apache_status.log` | `cmweb/apache/server-status` |

all with `"retention_in_days": -1` — **never expire**.

Metrics: collectd aggregation at 60s, plus `disk used_percent` and
`mem_used_percent`, dimensioned by `InstanceId`, `InstanceType`, `ImageId` and
`AutoScalingGroupName`.

> The third stream is the Apache scoreboard scraper from the `cronjob` role —
> and the `cronjob` role is **omitted on test**, so that log group is empty
> there.

### 4.9 `efs` (3 tasks)

```yaml
- name: Mount volume
  ansible.posix.mount:
    name: /mnt/nfs
    src: "{{ nfs_volume }}"
    fstype: nfs4
    opts: "nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=60,retrans=2,noresvport"
    state: mounted
```

| Option | Effect |
| --- | --- |
| `nfsvers=4.1` | Required for EFS |
| `rsize`/`wsize=1048576` | 1 MiB transfers — AWS's recommended values |
| **`hard`** | **A hung server blocks readers indefinitely rather than returning errors** |
| `timeo=60,retrans=2` | 6s timeout, 2 retries before reporting a server as unresponsive |
| `noresvport` | Survives reconnects without needing a privileged source port |

`state: mounted` both mounts now and writes `/etc/fstab`, so it survives reboot.

**The `hard` option is the operationally significant one.** An EFS problem
manifests as pages that hang until Apache's 250-second `TimeOut`, filling worker
slots — not as 500s.

### 4.10 `cronjob` (7 tasks)

Installs `python3-pip`, then one pip package, with the proxy supplied inline:

```yaml
- name: Install pip libraries
  ansible.builtin.pip:
    name: [ python-json-logger ]
    executable: pip3
  environment:
    http_proxy: http://proxy-sen.noc.sony.co.jp:10080
    https_proxy: http://proxy-sen.noc.sony.co.jp:10080
```

The comment above it — `# need proxy only for pip` — is the tell: the proxy is
in `/etc/environment`, but Ansible tasks do not read a login shell's
environment, so it has to be re-supplied here.

Then `/srv/cron/{config.json, apache_status_logging.py}` and the crontab at
`/var/spool/cron/crontabs/cmweb` (mode 0600, as cron requires).

The crontab, stripped of its inherited comment header, is **one line**:

```cron
*/5 * * * * /srv/cron/apache_status_logging.py
```

**That is the only cron on a CMWEB web server.** Everything else scheduled runs
in Jenkins ([03](03-jenkins-jobs.md)).

`config.json.j2` gives the script the credentials to authenticate to
`/server-status`, which sits behind the same LDAP gate as everything else:

```json
{
    "HOSTNAME": "{{ hostname }}",
    "SERVICE_USER": "{{ system_account }}",
    "SERVICE_PASS": "{{ system_password }}"
}
```

### 4.11 `c1ws` (3 tasks)

Trend Micro Cloud One Workload Security agent — the endpoint-security product.

```yaml
- name: Check whether c1ws is already installed or not
  ansible.builtin.stat: { path: "/opt/ds_agent/" }
  register: c1ws_installed

- name: Put install script ...
  when: not c1ws_installed          # <-- BUG, see below

- name: Install Trend Micro C1WS
  ansible.builtin.command: { cmd: "~/install_c1ws_agent.sh" }
  when: not c1ws_installed          # <-- same
```

Note this role's file is `tasks/main.yaml` (not `.yml`). Ansible accepts both.

Two problems, detailed in section 8.

---

## 5. Variables

### The three layers

```
group_vars/all      shared, non-secret     system_account, ldap_server, ports, ulimits, CA certs
group_vars/web      target_account, home
group_vars/<env>    per-environment        hostname, db/cache/opensearch hosts, manifest, nfs
encrypted_vars/*    vault                  vault_* names ONLY
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

### Derived variables

```yaml
hostname_short: '{{ hostname | regex_replace("\..*$", "") }}'
```

`hostname` is per-environment; `hostname_short` is computed from it and then
names **five** things: the Apache config filename, the vhost `ServerAlias`, the
`LogFormat` nickname, the WSGI daemon process group, and the logrotate config
name. Change `hostname` and all five follow.

### The vault-indirection convention

From the `README`:

> Start with "vault_" in encrypted_vars/* and refer no vault variables through
> group_vars/*. The reasons are:
> - Files in roles/* don't want to know whether variables are vault or not
> - Developers cannot search variables in encrypted_vars/ until they decrypt them

```
roles/*          say   system_password
group_vars/all   maps  system_password: "{{ vault_system_password }}"
encrypted_vars/  holds vault_system_password: <ciphertext>
```

So you can grep `group_vars/` to discover every secret's **name** without being
able to read one, and roles stay ignorant of what is secret.

Working with it:

```bash
ansible-vault edit encrypted_vars/common.yml
ansible-vault view encrypted_vars/access-prod.yml
ansible-vault encrypt somefile.yml
```

The password is in Confluence (*Service accounts and passwords*). To read
plaintext in `git diff`:

```bash
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"
```

`.gitattributes` supplies the other half:

```
ansible/encrypted_vars/* diff=ansible-vault merge=binary
```

`merge=binary` stops git line-merging ciphertext into an unopenable file.
**Vault conflicts must be resolved by decrypting both sides**, never by hand.

### What lives in each vault file

| File | Holds |
| --- | --- |
| `common.yml` | `vault_system_password`, `vault_django_db_password`, the three Sony CA certs |
| `access-<env>.yml` | `vault_ssh_private_key` / `_public_key`, `vault_cmweb_key` / `_crt`, `vault_opensearch_username` / `_password` |

---

## 6. Idempotence patterns in use

This repository is a decent catalogue of the standard techniques. Worth
recognising each:

| Pattern | Example | Effect |
| --- | --- | --- |
| `creates:` | `repo init … creates: .repo/manifest.xml` | Skip if the path exists |
| `removes:` | `mv ~/.gitconfig … removes: ~/.gitconfig` | Run only if the path exists |
| `changed_when: false` | `repo sync`, `make static` probe | Never report changed — for commands that always run |
| `changed_when: <expr>` | `"r.stdout and 'Nothing to be done' not in r.stdout"` | Parse output to decide |
| `copy: content:` as a hash | `Check code change` | Use content comparison as change detection, then `notify` |
| `force: false` | `authorized_keys` | Seed once, never overwrite |
| `validate:` | `visudo -cf %s` | Verify before installing — prevents lockout |
| `blockinfile` + `marker:` | certifi CAs | Insert once, update in place |
| `lineinfile` | `limits.conf` | Ensure one line exists |
| `state: link` | `settings_deployed.py` | Declarative symlink |
| `state: mounted` | EFS | Mount **and** fstab |
| `regex_replace` in vars | `hostname_short` | Derive, do not duplicate |

### Handlers

```yaml
- name: Reload Apache
  ansible.builtin.service: { name: apache2, state: reloaded }

- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

Handlers run **once**, at the end of the play, no matter how many tasks notified
them — which is why ten `notify: Reload Apache` tasks produce one reload. They
also run **only if something changed**, which is the entire point of the
change-detection patterns above.

---

## 7. Running and checking

```bash
ansible-playbook --vault-password-file ../.vault -c local -i hosts/test  web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod  web-servers.yml
```

| Flag | Use |
| --- | --- |
| `--check --diff` | Preview: report changes, show before/after of every template. **The safe way to review a template edit.** |
| `--list-tasks` | What would run, in order |
| `--start-at-task="name"` | Resume after a failure |
| `--tags` / `--skip-tags` | Subset (no tags are currently defined) |
| `--step` | Confirm each task interactively |
| `-vvv` | Verbose, including the rendered module args |
| `--syntax-check` | Parse only |

> `--check` is **not fully reliable here.** Several roles use `command`/`shell`,
> which are skipped in check mode, so later tasks that depend on their
> `register`ed output can report misleadingly. Treat `--check --diff` as a
> template preview, not a full dry run.

### Linting

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml
```

The README records the expected clean result:

> Passed: 0 failure(s), 0 warning(s) on 19 files. Last profile that met the
> validation criteria was 'production'.

Enforced in CI by the `verify_ansible_playbook` Jenkins job.

---

## 8. Bugs and rough edges currently in the tree

Real issues found by reading. None is breaking production today; all are worth
knowing before copying a pattern.

### 8.1 The `c1ws` role never installs anything

```yaml
- ansible.builtin.stat: { path: "/opt/ds_agent/" }
  register: c1ws_installed

- name: Put install script ...
  when: not c1ws_installed
```

`stat` registers a **dict**, which is always truthy, so `not c1ws_installed` is
always `false` and **both subsequent tasks are always skipped**. The agent is
never installed by this role.

The correct condition is:

```yaml
  when: not c1ws_installed.stat.exists
```

This is the most consequential of the bugs here — an endpoint-security agent
that silently never deploys. (It may well be installed by another mechanism;
worth confirming before "fixing" it.)

### 8.2 Activation credentials committed in plaintext

`roles/c1ws/templates/install_c1ws_agent.sh` hardcodes the Trend Micro
**tenant ID, activation token and policy id** as literal strings in a file
committed to git, while every other secret in this repository goes through
`ansible-vault`. They belong in `encrypted_vars/common.yml` like the rest.

### 8.3 `changed_when` referencing an unregistered variable

Four tasks across three roles do this:

```yaml
- name: Restart WSGI                       # apache-server/handlers
  ansible.builtin.command: { cmd: "touch …/wsgi.py" }
  changed_when: result.rc == 0             # `result` never registered here

- name: Install cloudwatch agent           # cloudwatch-agent
  ansible.builtin.command: { cmd: "dpkg -i -E ~/amazon-cloudwatch-agent.deb" }
  changed_when: result.rc == 0             # same

- name: Apply cloudwatch agent config      # cloudwatch-agent
  changed_when: result.rc == 0             # same

- name: Execute somc-setup-review          # cmweb-account
  changed_when: result.rc == 0             # `result` here leaks from the previous task
```

Each reads whatever `result` was last registered by some other task. The
reported status is meaningless; the tasks themselves still run.

### 8.4 Always-changed tasks

```yaml
- name: Update CA crt
  ansible.builtin.command: { cmd: sudo update-ca-certificates }
  register: result
  changed_when: result.rc == 0
```

"Report changed whenever it succeeds" — so every run shows as changed, defeating
the purpose of idempotence reporting. The `sudo` is also redundant inside a
`become: true` play.

**This is the task that creates `/etc/ssl/certs/cmweb.pem`**, which Apache's
`SSLCertificateFile` points at. Understand it before tidying it.

### 8.5 Hardcoded `jammy` in `swerepo.list`

Three `deb` lines pin `jammy` while the Image Builder recipes build both Ubuntu
20 (focal) and 22 (jammy), and `package/vars/` carries bionic/focal/jammy
variants. A focal build gets the wrong suite.

### 8.6 Non-reproducible builds

`apt upgrade: true` in the `package` and `certificate` roles, plus
`ParentImage: …/x.x.x` in the recipe, plus `latest` in the CloudWatch agent URL.
No input is pinned.

### 8.7 `validate_certs: false`

Twice in the `certificate` role, while fetching the packages that establish
trust. Chicken-and-egg, but it means a MITM during the AMI build could install
arbitrary certificate packages.

### 8.8 Over-broad sudo

`cmweb ALL=NOPASSWD: ALL` plus `%somc-sw-cmweb ALL=(root) NOPASSWD: ALL`, with
the WSGI daemon running as `cmweb`. And `20-owner` is a desktop-workstation
sudoers file that has no business on a server.

---

## 9. What the deploy does **not** do

Two deliberate absences that surprise people.

**No migrations.** There is no `manage.py migrate` in any role. Schema changes
go through the separate `migrate_db` Jenkins job, whose description reads
*"Migrate DB asynchronously against creating AMI"*. **Shipping a schema change
is two operations, not one**, and they can land in either order — so a migration
must be transiently compatible with both the old and the new application code.
See [07 of the learning track](../learning/07-migrations-and-database.md).

**No Celery worker.** No role installs or starts one, and no broker URL appears
in the Ansible-rendered `secure.py`. Together with
`CELERY_TASK_ALWAYS_EAGER = True` in the base settings and its re-assertion in
`bin/run_commands.sh`, this is the evidence that eager mode is the real
production configuration, not a development convenience.

---

## 10. Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Playbook fails at the first apt task | Proxy not set — the `environment` role did not run, or `/etc/environment` is not being read |
| TLS failures fetching internal URLs | `sonyca` did not run |
| `requests` TLS failures *from Django only* | The certifi blockinfile tasks in `cmweb-node` did not run (virtualenv rebuilt?) |
| Apache will not start, SSL error | `/etc/ssl/certs/cmweb.pem` missing — `Update CA crt` did not run |
| Apache will not start after a vhost edit | A directive whose module is not in the enable lists |
| `repo sync` fails | SSH key from the vault, or the `url.insteadOf` rewrite from the Image Builder component |
| `make static` fails | `default-jre` missing (YUI minifier) |
| New code not live after a rebuild | `repo manifest -r` unchanged, so `Restart WSGI` never fired |
| EFS not mounted / pages hang | `efs` role, or the `hard` mount is stuck |
| No CloudWatch scoreboard metrics on test | Expected — test omits `cronjob` |
| Everything reports "changed" every run | Section 8.4 — cosmetic |
| An unattended `apt upgrade` hangs | needrestart prompting; `50-autorestart.conf` did not apply |

### Reading the run

```bash
ansible-playbook … --list-tasks          # what will run
ansible-playbook … --check --diff        # preview templates
ansible-playbook … --start-at-task="Install Apache virtualhost config"
ansible-playbook … -vvv                  # rendered module args
```

On a running host, the artefacts each role leaves:

```bash
cat /etc/environment                            # environment
ls /usr/local/share/ca-certificates/extra/      # sonyca
cat /etc/apt/sources.list.d/swerepo.list        # certificate
id cmweb; cat /etc/sudoers.d/40-cmweb           # cmweb-account
ls -l /srv/www/<host>/site/cmweb/secure.py      # cmweb-node (expect 0640)
ls -l /srv/www/<host>/site/cmweb/settings_deployed.py   # symlink target
ls -l /srv/www/<host>/repository                # -> /mnt/nfs/cmweb/repo-mirror
apache2ctl -S                                   # apache-server
mount | grep nfs                                # efs
crontab -u cmweb -l                             # cronjob
ls /opt/ds_agent/                               # c1ws (probably absent — §8.1)
```
