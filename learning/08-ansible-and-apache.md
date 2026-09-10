# 08 — Ansible templates and Apache configuration

> **Goal:** be able to read `cmweb-scripts/ansible/` end to end — playbook,
> inventory, roles, variables, vault, handlers, Jinja2 templates — and explain
> exactly what the generated Apache vhost does to a request before Django ever
> sees it.

This is the chapter for the "Basic Tools" topic. It is infrastructure, not
Django, and it uses a different mental model: **describe the desired state, let
the tool converge to it.**

---

# Part A — Apache and mod_wsgi

## 1. Why there is a web server in front of Django at all

`manage.py runserver` is a development tool. It is single-purpose, unhardened,
and explicitly not for production. In front of Django you want something that:

- terminates TLS
- serves static files without touching Python
- authenticates users (here: against LDAP)
- manages a pool of worker processes
- rewrites legacy URLs
- writes access logs

CMWEB uses **Apache 2 + mod_wsgi**.

## 2. WSGI in one paragraph

WSGI (PEP 3333) is the contract between a web server and a Python web
application. The application is a callable taking `(environ, start_response)`;
`environ` is a dict of CGI-style variables, `start_response` is a callback for
status and headers, and the return value is an iterable of byte strings.

Django provides that callable via `get_wsgi_application()`. Apache's mod_wsgi
imports the file named by `WSGIScriptAlias` and looks for a module-level name
`application`.

`cmweb-project/cmweb/wsgi.py`:

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings_wsgi")
application = get_wsgi_application()
...
conf = {'debug': True, 'show_exceptions_in_wsgi_errors': True}
application = ErrorMiddleware(application, global_conf=conf)
```

Two things worth flagging:

1. `DJANGO_SETTINGS_MODULE` is set **here**, to `cmweb.settings_wsgi` — not to
   the same module `manage.py` uses. This is why a command-line `manage.py`
   run and a web request can see different settings.
2. The Django application is wrapped in Paste's `ErrorMiddleware` with
   `debug: True`, so **unhandled exceptions render a full traceback in
   production regardless of Django's `DEBUG = False`.** That is a deliberate
   choice for an internal tool behind LDAP; it would be a serious information
   leak on a public site.

## 3. The generated vhost, line by line

The file that reaches the server is
`/etc/apache2/sites-available/000-cmweb.conf`, rendered from
`cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2`.
Walk it in order.

### Global preamble

```apache
ExtendedStatus On
LimitRequestBody 10048576

ServerName {{ hostname }}
<VirtualHost *:443>
```

`LimitRequestBody` caps uploads at ~10 MB. `{{ hostname }}` is a Jinja2
variable — Part B explains where it comes from.

### TLS

```apache
    SSLEngine On
    SSLCertificateFile /etc/ssl/certs/cmweb.pem
    SSLCertificateKeyFile /etc/ssl/private/cmweb.key
```

The key is installed by a separate Ansible task from an encrypted vault value.

### Limits and logging

```apache
    LimitRequestFieldSize 32760
    TimeOut 250

    LogFormat {% raw %}"%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D"{% endraw %} {{ hostname_short }}_access
    LogLevel warn
    ErrorLog /var/log/apache2/{{ hostname }}_error.log
    SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
    CustomLog /var/log/apache2/{{ hostname }}_access.log {{ hostname_short }}_access env=!forwarded
```

- `LimitRequestFieldSize 32760` — CMWEB URLs get long (encoded branch names,
  filters, format suffixes).
- `TimeOut 250` — over four minutes, because some label pages do real work.
- `%D` at the end of `LogFormat` is request duration in microseconds. That is
  your first stop for "which page is slow".
- `SetEnvIf X-Forwarded-For ... forwarded` + `env=!forwarded` means requests
  arriving through a proxy are **not** written to the access log — otherwise
  health checks and proxied traffic would drown it.

### Static files

```apache
    DocumentRoot /srv/www/{{ hostname }}/htdocs/
    Alias /static/ /srv/www/{{ hostname }}/htdocs/static/
```

`/static/` is served directly by Apache. It never enters Python. `htdocs/static`
is a symlink to `../static`, which is where `make static` writes the
`collectstatic` + django-compressor output.

### Legacy URL rewrites

```apache
    RewriteEngine on
    RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
    RewriteRule ^/labels/(.*)/projects/(.*)$ /labels/$1/repositories/$3 [R,N]
    RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ /labels/$1/\+$2/$3 [R,N]
    RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]
```

Old bookmarks kept alive at the HTTP layer instead of in the URLconf. The third
rule is the one that inserts the `+` section prefix described in chapter 04 —
so URLs from before that convention still work.

Flags: `[R]` = external redirect (the browser sees a 302 and a new URL),
`[N]` = restart the rewrite loop.

> If you are debugging a URL that "changes by itself" in the address bar, this
> block is the first place to look — not the Django URLconf.

### The WSGI daemon

```apache
    WSGIDaemonProcess {{ hostname_short }} user=cmweb group=cmweb \
        processes=16 threads=15 maximum-requests=2000 \
        display-name=%{GROUP} \
        python-path=/srv/www/{{ hostname }}/site \
        python-home=/srv/www/{{ hostname }}/ENV/
    WSGIProcessGroup {{ hostname_short }}
    WSGIScriptAlias / /srv/www/{{ hostname }}/site/cmweb/wsgi.py
```

| Directive / option | Meaning |
| --- | --- |
| `WSGIDaemonProcess` | Run the app in a separate process group, not in Apache's own workers (daemon mode) |
| `user=cmweb group=cmweb` | Drops privileges |
| `processes=16 threads=15` | **240 concurrent request slots** |
| `maximum-requests=2000` | Recycle each process after 2000 requests — a blunt but effective defence against slow memory leaks |
| `python-path=.../site` | Puts `cmweb-project` on `sys.path` so `import cmweb` works |
| `python-home=.../ENV/` | The virtualenv |
| `WSGIScriptAlias /` | Everything not matched earlier goes to Django |

**Ordering matters:** `Alias /static/` appears before `WSGIScriptAlias /`, so
static files win.

**Concurrency consequence.** 16 processes x 15 threads with an in-process
(eager) Celery means a slow "background" task occupies one of 240 slots for its
whole duration. This is the operational cost of `CELERY_TASK_ALWAYS_EAGER`
(chapter 06).

**Reload mechanism.** mod_wsgi in daemon mode watches the script file's mtime.
The Ansible handler is therefore:

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

`touch` is the deploy. No service restart, no dropped connections.

### Authentication — gate 1

```apache
    <Location "/">
        AuthName "User/Password"
        AuthType Basic
        AuthBasicProvider ldap
        AuthLDAPURL  "ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName"
        AuthLDAPBindDN "CN={{ system_account }},OU=Users,OU=JPUsers,DC=jp,DC=sony,DC=com"
        AuthLDAPBindPassword "{{ system_password }}"
        Require valid-user
        ErrorDocument 401 "<html><meta http-equiv=\"refresh\" content=\"0;url=/register\"></html>"
    </Location>
```

Every request under `/` must present valid LDAP credentials **before Django is
invoked**. Port 3269 is LDAPS against the Global Catalog; `sAMAccountName` is
the login attribute.

The `ErrorDocument 401` is a nice touch: instead of an endless browser
credential prompt, an unknown user gets bounced to `/register`.

Apache then passes the authenticated username to Django as `REMOTE_USER`, which
`django.contrib.auth.middleware.RemoteUserMiddleware` turns into a logged-in
user via `users.auth.RemoteLDAPBackend`.

### The anonymous allow-list

```apache
    <LocationMatch "^/rpc/?$">
        Require all granted
    </LocationMatch>
    <LocationMatch "^/register$">
        Require all granted
    </LocationMatch>
    <LocationMatch "^/access-denied$">
        Require all granted
    </LocationMatch>
    <LocationMatch "^/.*favicon.ico$">
        Require all granted
    </LocationMatch>
```

**Exactly four** anonymous paths. Everything else requires LDAP.

This is gate 1 of the two described in chapter 04. Gate 2 is
`PermissionCheckMiddleware` with its `NO_AUTH_URLS` list. **Both must be opened
to expose an endpoint**, and they are in different repositories:

| To expose a new public endpoint | Edit |
| --- | --- |
| 1. Route it | `cmweb-app/<app>/urls.py` |
| 2. Let it past the Django gate | `NO_AUTH_URLS` in `cmweb-project/cmweb/middleware.py` |
| 3. Let it past the Apache gate | a `LocationMatch` + `Require all granted` in `cmweb.conf.j2` |

| Symptom | Missing step |
| --- | --- |
| 401 basic-auth prompt | 3 |
| Redirect to `/access-denied` | 2 |
| 404 | 1 |

### Cache-busting for task polling

```apache
    <LocationMatch "^/backend/tasks/.*/status$">
        Header Set Pragma "no-cache"
        Header Set Expires "Thu, 1 Jan 1970 00:00:00 GMT"
        Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
        Header Unset ETag
        FileETag None
    </LocationMatch>
```

Production wraps Django in a 10-minute page cache (chapter 06). A task-status
endpoint that returned a 10-minute-old answer would be useless, so these two
`LocationMatch` blocks force revalidation.

---

# Part B — Ansible

## 4. The model

Ansible is **agentless** (it works over SSH, or locally) and **declarative-ish**:
you describe desired state as a list of tasks, each of which is expected to be
**idempotent** — running it twice changes nothing the second time.

Core vocabulary:

| Term | Is |
| --- | --- |
| **Inventory** | The list of hosts, in groups |
| **Playbook** | A YAML file mapping host groups to roles/tasks |
| **Play** | One `hosts:` block inside a playbook |
| **Role** | A reusable directory of tasks/templates/handlers/vars |
| **Task** | One invocation of a module |
| **Module** | The unit of work (`apt`, `file`, `template`, `service`, ...) |
| **Handler** | A task that runs only if notified, and only once at the end |
| **Variable** | Values from `group_vars`, `host_vars`, inventory, vault, facts |
| **Fact** | Auto-discovered host information (`ansible_facts`) |
| **Vault** | AES-encrypted variable files |

## 5. CMWEB's layout

```
cmweb-scripts/ansible/
├── ansible.cfg
├── README
├── web-servers.yml          <- the playbook
├── hosts/                   <- inventories: prod, stage, test
│   ├── prod
│   ├── stage
│   └── test
├── group_vars/              <- plain variables
│   ├── all
│   ├── web
│   ├── prod
│   ├── stage
│   └── test
├── encrypted_vars/          <- ansible-vault encrypted secrets
│   ├── common.yml
│   ├── access-prod.yml
│   ├── access-stage.yml
│   └── access-test.yml
├── ssh_config
└── roles/
    ├── apache-server/
    ├── c1ws/
    ├── certificate/
    ├── cloudwatch-agent/
    ├── cmweb-account/
    ├── cmweb-node/
    ├── cronjob/
    ├── efs/
    ├── environment/
    ├── package/
    └── sonyca/
```

### The inventory is a single localhost

```ini
# hosts/prod
[production_web_servers]
localhost prod=1
```

All three inventories name `localhost`. **The machine configures itself.** The
playbook is always run with `-c local` (the local connection plugin), never
over SSH to a fleet. Section 9 explains why.

### The playbook

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

Three near-identical plays, one per environment. **Roles run in listed order**,
and the order encodes dependencies: OS environment, then certificates, then
packages, then the `cmweb` user, then the code (`cmweb-node`), then Apache.

`test` omits `efs` and `cronjob` — a real difference between environments,
visible right in the playbook.

### Role anatomy

```
roles/apache-server/
├── tasks/main.yml         the work
├── handlers/main.yml      Reload Apache / Restart WSGI
├── meta/main.yml          dependencies
└── templates/
    ├── apache/cmweb.conf.j2
    └── ssl/cmweb.crt, cmweb.key
```

Ansible finds these by convention. `templates/` is the search root for the
`template` module, which is why `src: apache/cmweb.conf.j2` is a relative path.

`meta/main.yml`:

```yaml
dependencies:
  - { role: sonyca }
```

`sonyca` is guaranteed to have run before `apache-server`, even if someone
reorders the playbook.

## 6. Variables and precedence

Three layers, by design:

```
group_vars/all      ->  shared, non-secret        (system_account, ldap_server, ports)
group_vars/<env>    ->  per-environment           (hostname, db host, opensearch host)
encrypted_vars/*    ->  secrets, vault-encrypted  (vault_* names only)
```

`group_vars/all`:

```yaml
system_account: jp21602
cmweb_write_group: somc-sw-cmweb

# The first label of the logs_hostname FQDN,
# i.e. the part before the first dot.
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

Two things to notice.

**A. Variables are computed from other variables.**

```yaml
hostname_short: '{{ hostname | regex_replace("\..*$", "") }}'
```

`hostname` is defined per environment (`cmweb.ptc.sony.co.jp`); `hostname_short`
is derived (`cmweb`), and it is what names the Apache config file, the log
format, and the WSGI process group. Define once, derive everywhere.

**B. The vault-indirection convention.** From the role's point of view the
variable is `system_password`. That name is defined in the *plain* file as a
reference to `vault_system_password`, which lives in the *encrypted* file.

The `README` states the rule and the reasoning:

> Start with "vault_" in encrypted_vars/* and refer no vault variables through
> group_vars/*. The reasons are:
> - Files in roles/* don't want to know whether variables are vault or not
> - Developers cannot search variables in encrypted_vars/ until they decrypt them

So roles never mention `vault_*`, and you can grep `group_vars/` to discover
every secret's *name* without being able to read its *value*. This is the
Ansible-recommended pattern and it is worth copying.

`group_vars/prod`:

```yaml
nfs_volume: 10.26.14.9:/
hostname: cmweb.ptc.sony.co.jp
manifest: release

django_environment: prod
django_db_host: 'cmweb.cm8tmtafyb32.ap-northeast-1.rds.amazonaws.com'
django_cache_host: 'cmweb.myfjt0.cfg.apne1.cache.amazonaws.com'

opensearch_host: 'https://vpc-cmweb-prod-...aos.ap-northeast-1.on.aws'
opensearch_username: '{{ vault_opensearch_username }}'
opensearch_password: '{{ vault_opensearch_password }}'
```

`manifest: release` vs `manifest: default` in test is the `repo` manifest file
selected at checkout — prod pins a release manifest, test tracks the default.

### Working with the vault

```bash
ansible-vault edit encrypted_vars/common.yml
ansible-vault view encrypted_vars/access-prod.yml
ansible-vault encrypt somefile.yml
```

The README also documents making vaulted files diffable:

```bash
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"
```

## 7. Jinja2 in Ansible

Same language as chapter 05, different renderer and different job.

Jinja2 appears in three places:

1. **`.j2` template files**, rendered by the `template` module.
2. **Inline in YAML**, anywhere `{{ }}` appears in a task or a var.
3. **`when:` conditions**, which are Jinja2 expressions *without* the braces.

### `secure.py.j2` — generating Python from Jinja2

`roles/cmweb-node/templates/django/secure.py.j2`, in full:

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

**This closes the loop with chapter 06.** `cmweb/secure.py` is not a file
anybody edits — it is twelve lines of Python generated from Ansible variables,
half of which come out of the vault. The task that renders it:

```yaml
- name: Create secure.py
  ansible.builtin.template:
    src: django/secure.py.j2
    dest: "/srv/www/{{ hostname }}/site/cmweb/secure.py"
    mode: "0640"
    owner: cmweb
    group: "{{ cmweb_write_group | lower }}"
```

Note `mode: "0640"` — the file contains a database password and an LDAP service
password, so it is not world-readable.

### `{% raw %}` — when the output language also uses braces

```
LogFormat {% raw %}"%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D"{% endraw %} {{ hostname_short }}_access
```

Apache's log format uses `%{Referer}i`. Jinja2 does not treat `%{...}` as
special — but the pattern is close enough to be a trap, and any future edit that
introduces a real `{{` or `{%` would break silently. `{% raw %}` makes the
intent explicit: *emit this verbatim*. Note the `{{ hostname_short }}` is
outside the raw block, so it is still substituted.

**This is the number one Jinja2-in-Ansible gotcha:** when generating a config
language that itself uses braces (Apache, nginx, systemd, Prometheus, another
Jinja2 template), wrap the literal parts in `{% raw %}`.

### Filters you will meet

```
{{ hostname | regex_replace("\..*$", "") }}
{{ cmweb_write_group | lower }}
{{ some_var | default('fallback') }}
{{ a_list | join(',') }}
{{ path | basename }}
```

The `| lower` on every `group:` line exists because the group name is
`somc-sw-cmweb` in one place and might arrive capitalised from IDM; normalising
at use time is cheaper than trusting the source.

## 8. Reading `apache-server/tasks/main.yml`

The whole role, in narrative order:

```yaml
- name: Install packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
    update_cache: true
    cache_valid_time: 3600
  with_items:
    - apache2
    - apache2-bin
    - apache2-utils
    - libapache2-mod-wsgi-py3
```

`state: present` not `state: latest` — reproducible builds, no surprise
upgrades. `cache_valid_time: 3600` avoids an `apt-get update` on every run.

```yaml
- name: Increase max open files to avoid "Too many open files" error
  ansible.builtin.replace:
    dest: /usr/sbin/apache2ctl
    regexp: 'ULIMIT_MAX_FILES="\$\{APACHE_ULIMIT_MAX_FILES:-ulimit -n \d+\}"'
    replace: 'ULIMIT_MAX_FILES="${APACHE_ULIMIT_MAX_FILES:-ulimit -n {{ pam_limits_nofile_soft }}}"'
    backup: true
```

Patching a distribution script in place. Note it is a *regex replace*, so it is
idempotent — after the first run the pattern no longer matches its own output
in a way that would double-apply. `backup: true` keeps the original.

```yaml
- name: Static file compression
  ansible.builtin.command:
    cmd: make static
    chdir: "/srv/www/{{ hostname }}/site"
  environment:
    DJANGO_SETTINGS_MODULE: cmweb.settings_deployed
  become: true
  become_user: cmweb
  changed_when: false
```

The deploy runs `make static` (collectstatic + offline compression) as the
`cmweb` user with the deployed settings module. `changed_when: false` tells
Ansible "never report this as a change" — it always runs, so reporting it would
make every run look dirty.

```yaml
- name: Freeze manifest
  ansible.builtin.command:
    cmd: repo manifest -r
    chdir: "/srv/www/{{ hostname }}"
  become: true
  become_user: cmweb
  register: static_manifest
  changed_when: false

- name: Check code change
  ansible.builtin.copy:
    content: '{{ static_manifest.stdout }}'
    dest: "/srv/www/{{ hostname }}/static-manifest-wsgi.xml"
    owner: cmweb
    group: "{{ cmweb_write_group | lower }}"
    mode: "0644"
  notify: Restart WSGI
```

**This pair is the cleverest thing in the role.** `repo manifest -r` prints the
exact revision of every git repository in the checkout. That output is written
to a file. The `copy` module is idempotent: if the file content is unchanged,
the task reports `ok` and **the handler is not notified**. If any repository
moved, the content differs, the task reports `changed`, and `Restart WSGI`
fires.

In other words: **the app reloads only when the code actually changed** — using
Ansible's own change detection as a content hash. No version file to bump, no
manual restart step.

```yaml
- name: Install Apache virtualhost config
  ansible.builtin.template:
    src: apache/cmweb.conf.j2
    dest: "/etc/apache2/sites-available/000-{{ hostname_short }}.conf"
    group: "{{ cmweb_write_group | lower }}"
    mode: "0644"
  notify: Reload Apache
```

Same idempotence: the vhost is only rewritten when the rendered output differs,
and only then does Apache reload.

```yaml
- name: Enable Apache modules (.load)
  ansible.builtin.file:
    path: "/etc/apache2/mods-enabled/{{ item }}.load"
    src: "../mods-available/{{ item }}.load"
    state: link
  with_items:
    - rewrite
    - status
    - auth_basic
    - wsgi
    - expires
    - proxy
    - proxy_balancer
    - cache
    - headers
    - ldap
    - authnz_ldap
    - vhost_alias
    - cache_disk
    - slotmem_shm
    - ssl
    - socache_shmcb
  notify: Reload Apache
```

This is `a2enmod` done explicitly with symlinks. Cross-check the list against
the vhost: `ldap` + `authnz_ldap` for the auth block, `rewrite` for the
`RewriteRule`s, `headers` for the cache-busting `Header Set`, `expires` for
`ExpiresActive`, `wsgi` for the daemon. **If a directive in the vhost has no
matching module here, Apache refuses to start.**

```yaml
- name: Check compressed static changes
  ansible.builtin.copy:
    src: "/srv/www/{{ hostname }}/static/compressed/manifest.json"
    dest: "/srv/www/{{ hostname }}/compressed-static.json"
    ...
  notify: Reload Apache
```

The same change-detection trick applied to the compressor manifest — the hash
that feeds `STATIC_MD5` and therefore `X-PJAX-Version` (chapter 05).

### Handlers

```yaml
- name: Reload Apache
  ansible.builtin.service:
    name: apache2
    state: reloaded

- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

Handlers run **once**, at the end of the play, no matter how many tasks
notified them. That is why ten `notify: Reload Apache` tasks produce one reload.

## 9. The whole deploy path

Put the pieces together. **The web tier is an AMI, not a server you install
onto.**

```
1. EC2 Image Builder starts a build from an Ubuntu 20/22 base image
2. The `provision-web` component runs:
       ACCOUNT_ID=`curl -s http://169.254.169.254/latest/meta-data/.../info/ | jq -r ".AccountId"`
       if   [ "659398199407" = "$ACCOUNT_ID" ]; then ENV="prod"
       elif [ "009896685360" = "$ACCOUNT_ID" ]; then ENV="stage"
       elif [ "100267242497" = "$ACCOUNT_ID" ]; then ENV="test"
       fi
       ansible-playbook --vault-password-file ~/.vault -c local -i hosts/$ENV web-servers.yml
3. Ansible (locally, on the build instance):
       - repo init + repo sync the code to /srv/www/<hostname>/site
       - render cmweb/secure.py from the vault
       - symlink settings_deployed.py -> settings_<env>.py
       - make static
       - install the Apache vhost, enable modules, start Apache
4. The result is baked into an AMI
5. Instances launched from that AMI already have everything
```

That is `cloudformation/ec2imagebuilder/builder-cmweb-component-provision-web.yaml`
and `roles/cmweb-node/tasks/main.yml`.

**Now the inventory makes sense.** Every inventory is `localhost` because
Ansible never reaches out to a fleet — it runs *on the machine being baked*, and
picks its environment by asking the instance metadata service which AWS account
it is in.

### `cmweb-node` — how the code arrives

```yaml
- name: Initialise CMWEB manifest
  ansible.builtin.command:
    cmd: "repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m {{ manifest }}.xml -b cloudj2"
    creates: "/srv/www/{{ hostname }}/.repo/manifest.xml"
    chdir: "/srv/www/{{ hostname }}"
  become: true
  become_user: cmweb

- name: Fetch CMWEB code
  ansible.builtin.command:
    cmd: repo sync -c -d
    chdir: "/srv/www/{{ hostname }}"
  become: true
  become_user: cmweb
  changed_when: false
```

`creates:` is how you make a `command` task idempotent — skip it if that path
already exists.

```yaml
- name: Link Django settings file
  ansible.builtin.file:
    path: "/srv/www/{{ hostname }}/site/cmweb/settings_deployed.py"
    src: "settings_{{ django_environment }}.py"
    state: link
```

**This is where `settings_deployed.py` comes from** — one symlink, driven by
`django_environment` from `group_vars/<env>`. Chapter 06's diagram, made real.

### And what is NOT here

There is no `manage.py migrate` in any role. Migrations are the separate
`migrate_db` Jenkins job (chapter 07). **Shipping a schema change is two
operations, not one.**

There is also no Celery worker installed or started by any role — the other
half of the evidence for chapter 06's claim that eager mode is not a
development convenience but the actual production configuration.

## 10. Running it

From the `README`:

```bash
ansible-playbook --vault-password-file ../.vault -c local -i hosts/test  web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage web-servers.yml
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod  web-servers.yml
```

Useful flags while developing a role:

| Flag | Does |
| --- | --- |
| `--check` | Dry run — report changes, make none |
| `--diff` | Show the actual before/after of every templated file |
| `--tags` / `--skip-tags` | Run a subset |
| `--start-at-task="name"` | Resume from a task |
| `-vvv` | Verbose |
| `--syntax-check` | Parse only |
| `--list-tasks` | Show what would run |

`--check --diff` together is the safe way to preview a template change: you see
exactly what would be written to `/etc/apache2/sites-available/...` without
writing it.

### Linting

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml
```

The README records the expected clean result:

> Passed: 0 failure(s), 0 warning(s) on 19 files. Last profile that met the
> validation criteria was 'production'.

There is also a `verify_ansible_playbook` Jenkins job, so this is checked in CI.

`ansible.cfg`:

```ini
[defaults]
host_key_checking = False
retry_files_enabled = False
interpreter_python=/usr/bin/python3
```

## 11. Known rough edges in this role

Two things you would fix if you were tidying it, both real:

**A. The `Restart WSGI` handler has a broken `changed_when`.**

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
  changed_when: result.rc == 0
```

`result` is never registered in this handler — it refers to a variable defined
by an unrelated task elsewhere. It happens to work, but the condition is not
evaluating what it appears to.

**B. `Update CA crt` shells out to `sudo` inside an already-`become: true`
play.**

```yaml
- name: Update CA crt
  ansible.builtin.command:
    cmd: sudo update-ca-certificates
  register: result
  changed_when: result.rc == 0
```

The `sudo` is redundant (the play is `become: true`), and `changed_when:
result.rc == 0` means "report changed whenever it succeeds" — so this task
always shows as changed, which is exactly what idempotence reporting is
supposed to avoid.

Neither is breaking anything today. Both are the kind of thing worth
understanding before you copy the pattern into a new role.

---

## 12. Try it

You cannot run this playbook here — it needs the vault password, the Sony
package index, and AWS. But you can read it properly.

**A. Trace one variable end to end.** Find every place `hostname` is used:

```powershell
Select-String -Path ..\cmweb-scripts\ansible -Pattern "hostname" -Recurse |
    Select-Object Filename, LineNumber, Line
```

Start at `group_vars/prod` (`hostname: cmweb.ptc.sony.co.jp`), then
`group_vars/all` (`hostname_short` derived from it), then find all four uses in
`cmweb.conf.j2` and all the path uses in `tasks/main.yml`.

**B. Render the template by hand.** Take `cmweb.conf.j2`, substitute
`hostname = cmweb.ptc.sony.co.jp`, `hostname_short = cmweb`,
`cmweb_write_group = somc-sw-cmweb`, `system_account = jp21602`, and write out
the resulting `.conf`. Compare your output against section 3.

**C. Cross-check modules against directives.** For every directive in
`cmweb.conf.j2` that needs a module (`RewriteRule`, `AuthLDAPURL`, `Header
Set`, `ExpiresActive`, `WSGIDaemonProcess`, `SSLEngine`), find the matching
entry in the `Enable Apache modules` task lists. Is anything enabled that the
vhost never uses?

**D. Find every Jinja2 template in the repository:**

```powershell
Get-ChildItem -Path ..\cmweb-scripts -Filter *.j2 -Recurse | Select-Object FullName
```

**E. Practise Jinja2 locally.** It is installed in the local venv (Ansible is
not, but Jinja2 comes with plenty of packages):

```python
from jinja2 import Template
t = Template("ServerName {{ hostname }}\nAlias /static/ /srv/www/{{ hostname }}/htdocs/static/")
print(t.render(hostname="cmweb.ptc.sony.co.jp"))

t = Template("{% raw %}%{Referer}i{% endraw %} on {{ h }}")
print(t.render(h="cmweb"))
```

**F. Write a role skeleton** in a scratch directory:

```
myrole/
├── tasks/main.yml
├── handlers/main.yml
├── templates/thing.conf.j2
└── defaults/main.yml
```

with one `template` task that notifies one handler. Run
`ansible-playbook --check --diff` if you have Ansible on a Linux box.

---

## 13. Check yourself

1. What is the WSGI contract, and which file in CMWEB provides the callable?
2. Which settings module does a web request use, and which does `manage.py`
   use? Why are they different?
3. Production runs with `DEBUG = False` but still shows tracebacks. Why?
4. How many concurrent requests can one CMWEB web server handle, and from which
   directive?
5. What does `maximum-requests=2000` defend against?
6. How does a deploy reload the application without restarting Apache?
7. Name the four anonymous paths in the vhost. What are the three edits needed
   to add a fifth, and in which repositories do they live?
8. You get a 401 on a new endpoint. Which of the two gates did you miss? What
   about a redirect to `/access-denied`?
9. Why is every Ansible inventory `localhost`?
10. How does the playbook know whether it is building prod, stage or test?
11. Explain the `Freeze manifest` / `Check code change` task pair. What is
    Ansible's idempotence being used as?
12. Why do roles reference `system_password` rather than `vault_system_password`
    directly? Give both reasons from the README.
13. Why does `cmweb.conf.j2` need `{% raw %}`, and what is still substituted
    inside that line?
14. What creates `cmweb/secure.py`, and what mode is it written with? Why that
    mode?
15. What creates `settings_deployed.py`?
16. Name two things the deploy does **not** do that you might expect it to.
