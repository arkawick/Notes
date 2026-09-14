# 05 — Apache configuration

The deployed vhost lives at `/etc/apache2/sites-available/000-cmweb.conf`,
rendered by Ansible from
`cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2`.

Apache is not just a reverse proxy here. It **authenticates every request
against LDAP before Django sees it**, serves all static content, rewrites legacy
URLs, and manages the 240 worker slots the application runs in.

---

## 1. Request path

```
client ──► Apache :443
             │
             ├─ SSL termination
             ├─ Alias /static/            ──► filesystem, never enters Python
             ├─ RewriteRule               ──► legacy URL redirects (302 to the browser)
             ├─ <Location "/">            ──► LDAP basic auth, Require valid-user
             │     └─ 401 ──► ErrorDocument ──► redirect to /register
             ├─ <LocationMatch>           ──► four anonymous exceptions
             └─ WSGIScriptAlias /         ──► site/cmweb/wsgi.py
                                                 │
                                                 └─ Django (REMOTE_USER already set)
```

---

## 2. The vhost, directive by directive

### Preamble

```apache
ExtendedStatus On
LimitRequestBody 10048576

ServerName {{ hostname }}
<VirtualHost *:443>
```

`ExtendedStatus On` powers `/server-status`, which the cron job scrapes every
five minutes (section 6). `LimitRequestBody` caps uploads at ~10 MB.

### TLS

```apache
    SSLEngine On
    SSLCertificateFile /etc/ssl/certs/cmweb.pem
    SSLCertificateKeyFile /etc/ssl/private/cmweb.key

    ServerAdmin {{ cmweb_write_group }}@sony.com
    ServerAlias {{ hostname_short }}
```

The key is installed by a separate Ansible task from `vault_cmweb_key`, mode
0644 at `/etc/ssl/private/cmweb.key`.

### Limits

```apache
    LimitRequestFieldSize 32760
    TimeOut 250
```

- **32760-byte header limit.** CMWEB URLs get long — encoded branch names,
  optional manifest prefixes, `+`-sections, filters and format suffixes all
  stack up. The default 8190 is not enough.
- **250-second timeout.** Over four minutes, because some label pages do real
  work (and because eager Celery means "background" tasks run in the request).

### Logging

```apache
    LogFormat {% raw %}"%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D"{% endraw %} {{ hostname_short }}_access
    LogLevel warn
    ErrorLog /var/log/apache2/{{ hostname }}_error.log
    SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
    CustomLog /var/log/apache2/{{ hostname }}_access.log {{ hostname_short }}_access env=!forwarded
```

| Token | Meaning |
| --- | --- |
| `%I` / `%O` | Bytes received / sent, including headers |
| `%D` | **Request duration in microseconds** |
| `%>s` | Final status after internal redirects |

**`%D` is your first stop for "which page is slow".** Sort the access log by the
last field.

`SetEnvIf X-Forwarded-For … forwarded` + `env=!forwarded` means **proxied
requests are not logged**. Health checks and traffic arriving through a proxy
are excluded so the log reflects real user activity — but be aware of it before
concluding "nobody used that page".

`{% raw %}` is required because Apache's log format contains `%{Referer}i`; the
`{{ hostname_short }}` outside the raw block is still substituted.

### Static files

```apache
    DocumentRoot /srv/www/{{ hostname }}/htdocs/
    <Directory />
        Options FollowSymLinks
        AllowOverride All
    </Directory>

    Alias /static/ /srv/www/{{ hostname }}/htdocs/static/
```

`htdocs/static` is a symlink to `../static`, which is where `make static`
(collectstatic + django-compressor offline) writes. **Ordering matters:**
`Alias /static/` precedes `WSGIScriptAlias /`, so static files win.

### Legacy URL rewrites

```apache
    RewriteEngine on
    RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
    RewriteRule ^/labels/(.*)/projects/(.*)$ /labels/$1/repositories/$3 [R,N]
    RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ /labels/$1/\+$2/$3 [R,N]
    RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]
```

`[R]` = external redirect (browser sees 302 and a new URL). `[N]` = restart the
rewrite loop.

The third rule inserts the `+` section prefix, keeping pre-`+` bookmarks alive.

> **If a URL "changes by itself" in the address bar, look here first, not at the
> Django URLconf.** Note the second rule references `$3` while only capturing
> two groups — a latent bug that has evidently never mattered in practice.

### mod_wsgi

```apache
    WSGIDaemonProcess {{ hostname_short }} user=cmweb group=cmweb \
        processes=16 threads=15 maximum-requests=2000 \
        display-name=%{GROUP} \
        python-path=/srv/www/{{ hostname }}/site \
        python-home=/srv/www/{{ hostname }}/ENV/
    WSGIProcessGroup {{ hostname_short }}
    WSGIScriptAlias / /srv/www/{{ hostname }}/site/cmweb/wsgi.py
```

| Option | Meaning |
| --- | --- |
| `WSGIDaemonProcess` | Daemon mode — the app runs in its own process group, not Apache's workers |
| `user=cmweb group=cmweb` | Drops privileges |
| `processes=16 threads=15` | **240 concurrent request slots** |
| `maximum-requests=2000` | Recycle each process after 2000 requests — blunt but effective against slow leaks |
| `display-name=%{GROUP}` | Processes show as `(wsgi:cmweb)` in `ps` |
| `python-path` | Puts `cmweb-project` on `sys.path` so `import cmweb` works |
| `python-home` | The virtualenv |

**Capacity arithmetic worth internalising.** 240 slots, and Celery is eager — so
a task that takes 30 seconds occupies one slot for 30 seconds. There is no queue
absorbing it.

**Reload:** mod_wsgi in daemon mode watches the script file's mtime, so the
Ansible handler is `touch …/cmweb/wsgi.py`. No restart, no dropped connections.

### Authentication — the outer gate

```apache
    ExpiresActive On
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

- Port **3269** is LDAPS against the Active Directory Global Catalog.
- `sAMAccountName` is the login attribute.
- The bind DN is the service account (`jp21602`) with its vault password.
- `ErrorDocument 401` bounces unknown users to `/register` instead of leaving
  the browser in a credential-prompt loop.

Apache passes the authenticated username to Django as `REMOTE_USER`, which
`django.contrib.auth.middleware.RemoteUserMiddleware` converts into a logged-in
user via `users.auth.RemoteLDAPBackend`.

### The four anonymous paths

```apache
    <LocationMatch "^/rpc/?$">          Require all granted  </LocationMatch>
    <LocationMatch "^/register$">       Require all granted  </LocationMatch>
    <LocationMatch "^/access-denied$">  Require all granted  </LocationMatch>
    <LocationMatch "^/.*favicon.ico$">  Require all granted  </LocationMatch>
```

**Exactly four.** Everything else requires LDAP.

### Cache-busting for task polling

```apache
    <LocationMatch "^/backend/tasks/.*/status$">
        Header Set Pragma "no-cache"
        Header Set Expires "Thu, 1 Jan 1970 00:00:00 GMT"
        Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
        Header Unset ETag
        FileETag None
    </LocationMatch>
    <LocationMatch "^/backend/tasks/apply/.*$">
        ... same ...
    </LocationMatch>
```

Production wraps Django in a 10-minute page cache
(`UpdateCacheMiddleware` / `FetchFromCacheMiddleware` in `settings_prod.py`). A
task-status endpoint returning a 10-minute-old answer would be useless, so these
two paths force revalidation.

---

## 3. The two gates

The site is gated **twice**, and both must be opened to expose an endpoint.

| Gate | Where | Mechanism |
| --- | --- | --- |
| 1 | Apache | `Require valid-user` + LDAP, with four `Require all granted` exceptions |
| 2 | Django | `cmweb.middleware.PermissionCheckMiddleware` on `users.view_all_pages`, with `NO_AUTH_URLS` / `EXEMPT_URLS` |

```python
NO_AUTH_URLS = ['.+/trigger-config/?$', '.+/xml(/all)?/?$',
                'builds/(.+/)?rss/?$', 'projects/.+/rss/?$',
                'activity/rss/?$', 'rpc/?$', 'api/(?!a/).*$',
                'register$', 'access-denied$']
EXEMPT_URLS = ['accounts/', 'request/']
```

### Adding a public endpoint = three edits in three repositories

| # | Edit | Repository |
| --- | --- | --- |
| 1 | The URLconf | `cmweb-app` |
| 2 | `NO_AUTH_URLS` in `cmweb/middleware.py` | `cmweb-project` |
| 3 | A `LocationMatch` + `Require all granted` in `cmweb.conf.j2` | `cmweb-scripts` |

| Symptom | Missing |
| --- | --- |
| 401 basic-auth prompt | 3 |
| Redirect to `/access-denied` | 2 |
| 404 | 1 |

### The delegated-trust hazard

```python
auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
```

`PermissionCheckMiddleware` base64-decodes the `Authorization` header and
**trusts the username without checking the password**. This is safe *only*
because Apache has already bound that username against LDAP. The safety lives
entirely in `cmweb.conf.j2`, in a different repository.

**Never put this application behind anything that does not authenticate.**

---

## 4. Modules

Enabled explicitly by the Ansible role (this is `a2enmod` done with symlinks):

**`.conf` + `.load`:** `status`, `wsgi`, `proxy`, `proxy_balancer`,
`cache_disk`, `ssl`

**`.load` only:** `rewrite`, `auth_basic`, `expires`, `cache`, `headers`,
`ldap`, `authnz_ldap`, `vhost_alias`, `slotmem_shm`, `socache_shmcb`

Cross-check against the vhost:

| Directive | Needs |
| --- | --- |
| `RewriteRule` | `rewrite` |
| `AuthLDAPURL`, `AuthBasicProvider ldap` | `ldap` + `authnz_ldap` + `auth_basic` |
| `Header Set` / `Header Unset` | `headers` |
| `ExpiresActive` | `expires` |
| `WSGIDaemonProcess` | `wsgi` |
| `SSLEngine` | `ssl` + `socache_shmcb` |
| `ExtendedStatus` / `/server-status` | `status` |

**If a directive in the vhost has no matching module, Apache refuses to start.**
That is the most common cause of a failed AMI build after a vhost edit.

`proxy`, `proxy_balancer`, `cache`, `cache_disk`, `slotmem_shm` and
`vhost_alias` are enabled but unused by the current vhost — leftovers from an
earlier topology.

---

## 5. The Ansible tasks that produce all this

```yaml
- name: Install packages           # apache2, apache2-bin, apache2-utils, libapache2-mod-wsgi-py3
- name: Increase max open files    # patches /usr/sbin/apache2ctl ULIMIT_MAX_FILES -> 33333
- name: Static file compression    # make static, as cmweb, DJANGO_SETTINGS_MODULE=cmweb.settings_deployed
- name: Freeze manifest            # repo manifest -r
- name: Check code change          # writes it; notify: Restart WSGI
- name: Create htdocs directory
- name: Link static dir            # htdocs/static -> ../static
- name: Install Apache virtualhost config   # the template; notify: Reload Apache
- name: Enable Apache modules (.conf)       # notify: Reload Apache
- name: Enable Apache modules (.load)       # notify: Reload Apache
- name: Enable Apache vhost                 # sites-enabled symlink
- name: Disable default Apache config       # removes 000-default.conf
- name: Put SSL Certificate Key File
- name: Put SSL Certificate File
- name: Update CA crt
- name: Check compressed static changes     # compressed/manifest.json; notify: Reload Apache
- name: Enable and start Apache
```

Handlers run **once** at the end of the play regardless of how many tasks
notified them:

```yaml
- name: Reload Apache
  ansible.builtin.service: { name: apache2, state: reloaded }

- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

The ulimit patch is needed because 16 processes × 15 threads against a large git
mirror opens a lot of file descriptors; without it Apache hits
"Too many open files".

---

## 6. Monitoring

The only cron job on the box scrapes Apache's own status page:

```cron
*/5 * * * * /srv/cron/apache_status_logging.py
```

```python
"""
Fetch https://cmweb.ptc.sony.co.jp/server-status and store it to log file.
This script is called from cron job on a regular basis.
Log file is uploaded to aws cloudwatch logs.
"""
```

It decodes the Apache scoreboard into named states — `WaitingForConnection`,
`ReadingRequest`, `SendingReply`, `KeepAlive`, `DNSLookup`, `ClosingConnection`,
`Logging`, `GracefullyFinishing`, `IdleCleanupOfWorker`,
`OpenSlotWithNoCurrentProcess` — and writes JSON lines picked up by the
CloudWatch agent.

**This is the metric for "are we running out of worker slots".** A rising
`SendingReply` count with few open slots means requests are queueing.

Log rotation (`cmweb-node` role):

```
/srv/www/{{ hostname }}/var/log/*.json {
  rotate 8
  weekly
  compress
  delaycompress
  missingok
  notifempty
}
```

---

## 7. Troubleshooting

| Symptom | Cause |
| --- | --- |
| **Apache will not start after a vhost edit** | A directive whose module is not in the enable lists. `apache2ctl configtest` |
| **401 on a new endpoint** | No `LocationMatch` / `Require all granted` block |
| **Redirect to `/access-denied`** | Missing from `NO_AUTH_URLS` (Django gate) |
| **Everyone logged out at once** | The memcached cache was flushed — sessions live there |
| **Traceback shown in production** | Expected. `cmweb/wsgi.py` wraps Django in Paste `ErrorMiddleware` with `debug: True`, regardless of `DEBUG = False` |
| **Stale page content for up to 10 minutes** | The `UpdateCacheMiddleware` / `FetchFromCacheMiddleware` page cache |
| **Old assets served after a deploy** | `make static` did not re-run, so `compressed/manifest.json` and therefore `STATIC_MD5` / `X-PJAX-Version` are unchanged |
| **"Too many open files"** | The `apache2ctl` ulimit patch did not apply |
| **Requests hang rather than erroring** | EFS is `hard`-mounted; a stuck NFS blocks readers indefinitely |
| **A URL redirects unexpectedly** | The `RewriteRule` block, not the URLconf |
| **New code not live after a deploy** | `repo manifest -r` output was unchanged, so `Restart WSGI` never fired. Touch `wsgi.py` manually |
| **Which page is slow?** | `%D` — the last field of the access log |

### Useful commands on a web server

```bash
apache2ctl configtest                 # validate config before reloading
apache2ctl -M                         # list loaded modules
systemctl reload apache2              # re-read config, keep connections
touch /srv/www/<host>/site/cmweb/wsgi.py     # reload the application only

tail -f /var/log/apache2/<host>_error.log
tail -f /var/log/apache2/<host>_access.log
sort -t' ' -k11 -rn <host>_access.log | head   # slowest requests by %D
```

### Previewing a vhost change safely

```bash
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage \
                 web-servers.yml --check --diff
```

`--check --diff` shows exactly what would be written to
`/etc/apache2/sites-available/000-cmweb.conf` without writing it.
