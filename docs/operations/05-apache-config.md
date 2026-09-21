# 05 — Apache configuration

The deployed vhost lives at `/etc/apache2/sites-available/000-cmweb.conf`,
rendered by Ansible from
`cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2` and
symlinked into `sites-enabled/`.

Apache is not a thin reverse proxy here. It **authenticates every request
against LDAP before Django sees it**, serves all static content, rewrites legacy
URLs, terminates TLS, and owns the 240 worker slots the application runs in.
A meaningful amount of CMWEB's behaviour is in this one file.

---

## 1. What Apache does that Django does not

| Concern | Handled by | Why there |
| --- | --- | --- |
| TLS termination | Apache | Python TLS termination is slower and harder to configure correctly |
| Authentication | **Apache** (LDAP basic auth) | Predates Django's LDAP backends here; also protects endpoints Django never sees |
| Static files | Apache | `/static/` never enters Python — no GIL, no worker slot |
| Legacy URL redirects | Apache `RewriteRule` | Keeps dead URL shapes out of the Django URLconf |
| Process management | mod_wsgi daemon mode | Restart, recycle, drop privileges |
| Access logging with timings | Apache `%D` | Django has no equivalent for free |
| Authorization (`view_all_pages`) | Django middleware | Needs the database |
| Page caching | Django middleware | Needs to vary on the logged-in user |

The split matters because **a request can be rejected before Python starts**.
A 401 has no Django log line, no traceback, and no page-cache entry.

---

## 2. Request path

```
client ──► Apache :443
             │
             ├─ 1. SSL handshake            SSLEngine, SSLCertificateFile
             ├─ 2. Translate name           Alias /static/  ──► filesystem, DONE
             ├─ 3. URL rewriting            RewriteRule     ──► 302 to browser, DONE
             ├─ 4. AuthN                    <Location "/">  ──► LDAP bind
             │       └─ fail ──► 401 ──► ErrorDocument ──► /register, DONE
             ├─ 5. AuthZ                    Require valid-user / Require all granted
             ├─ 6. Fixups                   Header Set, ExpiresActive
             └─ 7. Handler                  WSGIScriptAlias / ──► site/cmweb/wsgi.py
                                                  │
                                                  ▼
                                            Django, with REMOTE_USER already set
                                                  │
                                            (see chapter 09 of the learning track
                                             for the middleware chain from here)
```

Steps 2–6 are Apache's standard request phases. Knowing which phase a directive
belongs to explains most ordering surprises — `Alias` resolves before the WSGI
handler is consulted, which is why `/static/` wins over `WSGIScriptAlias /`.

---

## 3. The rendered vhost

For production, `hostname = cmweb.ptc.sony.co.jp`, `hostname_short = cmweb`,
`cmweb_write_group = somc-sw-cmweb`, `system_account = jp21602`. Substituting,
the file on disk reads:

```apache
ExtendedStatus On
LimitRequestBody 10048576

ServerName cmweb.ptc.sony.co.jp
<VirtualHost *:443>
    SSLEngine On
    SSLCertificateFile /etc/ssl/certs/cmweb.pem
    SSLCertificateKeyFile /etc/ssl/private/cmweb.key

    ServerAdmin somc-sw-cmweb@sony.com
    ServerAlias cmweb

    LimitRequestFieldSize 32760
    TimeOut 250

    DocumentRoot /srv/www/cmweb.ptc.sony.co.jp/htdocs/
    <Directory />
        Options FollowSymLinks
        AllowOverride All
    </Directory>

    LogFormat "%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D" cmweb_access
    LogLevel warn
    ErrorLog /var/log/apache2/cmweb.ptc.sony.co.jp_error.log
    SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
    CustomLog /var/log/apache2/cmweb.ptc.sony.co.jp_access.log cmweb_access env=!forwarded

    Alias /static/ /srv/www/cmweb.ptc.sony.co.jp/htdocs/static/

    RewriteEngine on
    RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
    RewriteRule ^/labels/(.*)/projects/(.*)$ /labels/$1/repositories/$3 [R,N]
    RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ /labels/$1/\+$2/$3 [R,N]
    RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]

    WSGIDaemonProcess cmweb user=cmweb group=cmweb processes=16 threads=15 \
        maximum-requests=2000 display-name=%{GROUP} \
        python-path=/srv/www/cmweb.ptc.sony.co.jp/site \
        python-home=/srv/www/cmweb.ptc.sony.co.jp/ENV/
    WSGIProcessGroup cmweb
    WSGIScriptAlias / /srv/www/cmweb.ptc.sony.co.jp/site/cmweb/wsgi.py

    ExpiresActive On
    <Location "/">
        AuthName "User/Password"
        AuthType Basic
        AuthBasicProvider ldap
        AuthLDAPURL  "ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName"
        AuthLDAPBindDN "CN=jp21602,OU=Users,OU=JPUsers,DC=jp,DC=sony,DC=com"
        AuthLDAPBindPassword "<vault_system_password>"
        Require valid-user
        ErrorDocument 401 "<html><meta http-equiv=\"refresh\" content=\"0;url=/register\"></html>"
    </Location>
    <LocationMatch "^/rpc/?$">          Require all granted  </LocationMatch>
    <LocationMatch "^/register$">       Require all granted  </LocationMatch>
    <LocationMatch "^/access-denied$">  Require all granted  </LocationMatch>
    <LocationMatch "^/.*favicon.ico$">  Require all granted  </LocationMatch>
    <LocationMatch "^/backend/tasks/.*/status$">
        Header Set Pragma "no-cache"
        Header Set Expires "Thu, 1 Jan 1970 00:00:00 GMT"
        Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
        Header Unset ETag
        FileETag None
    </LocationMatch>
    <LocationMatch "^/backend/tasks/apply/.*$">
        ... identical ...
    </LocationMatch>
    <Directory /srv/www/cmweb.ptc.sony.co.jp>
        Options Indexes FollowSymLinks MultiViews
        Require all granted
    </Directory>
</VirtualHost>
```

**There is no `*:80` vhost.** Plain HTTP is not served at all — the default
vhost is explicitly removed by Ansible (`Disable default Apache config`), so
there is no HTTP→HTTPS redirect. A user typing `http://cmweb…` gets a connection
failure, not a redirect.

---

## 4. Directive by directive

### Global preamble

```apache
ExtendedStatus On
LimitRequestBody 10048576
ServerName cmweb.ptc.sony.co.jp
```

- **`ExtendedStatus On`** enables per-request detail on `/server-status`, which
  the cron job scrapes every five minutes (section 9). It costs a small amount
  of bookkeeping per request; it is on deliberately.
- **`LimitRequestBody 10048576`** caps request bodies at ~9.6 MiB. Note this is
  outside the `<VirtualHost>` block, so it applies server-wide.
- **`ServerName` is outside the vhost too**, which sets the global server name
  and suppresses Apache's startup warning about determining the FQDN.

### TLS

```apache
SSLEngine On
SSLCertificateFile /etc/ssl/certs/cmweb.pem
SSLCertificateKeyFile /etc/ssl/private/cmweb.key
```

The key path matches an Ansible task directly. **The certificate path does
not**, and the indirection is worth knowing:

```
vault_cmweb_crt
   └─ templates/ssl/cmweb.crt  ({{ cmweb_crt }})
        └─ /usr/local/share/ca-certificates/extra/cmweb.crt     <- installed as a CA cert
             └─ update-ca-certificates
                  └─ /etc/ssl/certs/cmweb.pem                   <- symlink Apache reads
```

The **server** certificate is installed into the system **CA** directory, and
`update-ca-certificates` is what produces the `.pem` the vhost references — it
scans `/usr/local/share/ca-certificates/**/*.crt` and emits
`/etc/ssl/certs/<name>.pem`.

> **Consequence:** if `update-ca-certificates` does not run, `/etc/ssl/certs/cmweb.pem`
> does not exist and **Apache will not start** with
> `SSLCertificateFile: file does not exist or is empty`. The task that runs it
> is in the `apache-server` role and is also where one of the known rough edges
> lives (section 10).

The key is written at mode 0644 — world-readable for a private key. Defensible
only because the host is single-purpose and access-controlled; it is not what
you would write today.

Separately, the `sonyca` role installs the Sony Root, Intranet and B2B CAs into
the same directory so the host trusts internal services, and `cmweb-node`
additionally injects all three into **certifi's bundle inside the virtualenv** —
because `requests` uses certifi, not the system store.

### Limits and timeouts

```apache
LimitRequestFieldSize 32760
TimeOut 250
```

**`LimitRequestFieldSize 32760`** raises the per-header limit from Apache's
default 8190. CMWEB URLs genuinely get long — a label commit URL can carry a
manifest prefix, a slash-encoded branch name, a `+`-section, a filter and a
format suffix:

```
/builds/platform/systemmanifest/55.0.A.0.477/+allcommits/all-including-merges/csv
```

and the `Referer` header then carries that whole URL on the next request.

**`TimeOut 250`** — over four minutes. Necessary because some label pages do
real work, and because eager Celery means anything a view `.delay()`s runs
inside the request (see section 8).

### Logging

```apache
LogFormat "%h %l %u %t \"%r\" %>s %I %O \"%{Referer}i\" \"%{User-Agent}i\" %D" cmweb_access
LogLevel warn
ErrorLog /var/log/apache2/cmweb.ptc.sony.co.jp_error.log
SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
CustomLog /var/log/apache2/cmweb.ptc.sony.co.jp_access.log cmweb_access env=!forwarded
```

Field by field:

| Pos | Token | Meaning |
| --- | --- | --- |
| 1 | `%h` | Remote host |
| 2 | `%l` | identd (always `-`) |
| 3 | `%u` | **Authenticated username** — populated by the LDAP auth, so the log says *who* |
| 4 | `%t` | Timestamp |
| 5 | `\"%r\"` | Request line |
| 6 | `%>s` | Final status after internal redirects |
| 7 | `%I` | Bytes received including headers |
| 8 | `%O` | Bytes sent including headers |
| 9 | `\"%{Referer}i\"` | Referer |
| 10 | `\"%{User-Agent}i\"` | User agent |
| 11 | **`%D`** | **Request duration in microseconds** |

Because auth happens in Apache, `%u` is reliable on *every* line — including
requests that never reached Django.

**The proxy exclusion is easy to miss:**

```apache
SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
CustomLog ... env=!forwarded
```

Any request carrying an `X-Forwarded-For` that looks like a dotted address sets
the `forwarded` variable, and `env=!forwarded` then **excludes it from the
access log entirely**. Health checks and proxied traffic are silently absent.

> Before concluding "nobody uses that page", check whether the traffic you are
> looking for arrives through a proxy.

### Static files

```apache
DocumentRoot /srv/www/cmweb.ptc.sony.co.jp/htdocs/
Alias /static/ /srv/www/cmweb.ptc.sony.co.jp/htdocs/static/
```

`htdocs/static` is a symlink to `../static`, where `make static`
(`collectstatic` + django-compressor offline) writes.

```
/srv/www/<host>/
├── htdocs/
│   └── static -> ../static        (symlink; needs Options FollowSymLinks)
└── static/
    ├── css/ js/ images/ external/
    └── compressed/
        └── manifest.json          -> feeds STATIC_MD5 -> X-PJAX-Version
```

Two consequences:

- **Static files never enter Python.** No worker slot, no GIL contention.
- **A deploy that skips `make static` serves stale assets**, and because
  `compressed/manifest.json` is unchanged, `X-PJAX-Version` is unchanged too, so
  clients are not forced to reload.

### The `<Directory>` blocks

```apache
<Directory />
    Options FollowSymLinks
    AllowOverride All
</Directory>
```

`AllowOverride All` from `/` means Apache will look for `.htaccess` in **every
directory component of every path it serves**. That is a per-request stat cost
and an override surface nobody appears to use. `AllowOverride None` would be
faster and tighter.

```apache
<Directory /srv/www/cmweb.ptc.sony.co.jp>
    Options Indexes FollowSymLinks MultiViews
    Require all granted
</Directory>
```

`Indexes` enables **directory listing** for that tree — so a URL mapping to a
directory with no index file returns a generated listing. `Require all granted`
here is filesystem-level authorization; URL-level auth still comes from the
`<Location "/">` block, which is evaluated for the request URI. The two are not
in conflict, but the combination is broader than it needs to be.

### Legacy URL rewrites

```apache
RewriteEngine on
RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
RewriteRule ^/labels/(.*)/projects/(.*)$ /labels/$1/repositories/$3 [R,N]
RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ /labels/$1/\+$2/$3 [R,N]
RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]
```

| Flag | Meaning |
| --- | --- |
| `[R]` | External redirect — browser receives 302 and a new URL |
| `[N]` | Restart the rewrite ruleset from the top with the new URI |

The third rule is the historically important one: it inserts the `+` section
prefix, so bookmarks from before that convention still work.

Two observations:

- **Rule 2 references `$3` but only captures two groups.** `$3` expands to
  empty, so `/labels/X/projects/Y` becomes `/labels/X/repositories/` — the tail
  is dropped. A latent bug that evidently has not mattered.
- `[N]` re-runs the ruleset; combined with `[R]` the browser round-trips
  anyway, so `[N]` is mostly redundant here.

> **If a URL appears to change by itself in the address bar, this block is the
> cause — not the Django URLconf.** A `[R]` redirect is visible as a 302 in the
> access log.

### mod_wsgi

```apache
WSGIDaemonProcess cmweb user=cmweb group=cmweb \
    processes=16 threads=15 maximum-requests=2000 \
    display-name=%{GROUP} \
    python-path=/srv/www/cmweb.ptc.sony.co.jp/site \
    python-home=/srv/www/cmweb.ptc.sony.co.jp/ENV/
WSGIProcessGroup cmweb
WSGIScriptAlias / /srv/www/cmweb.ptc.sony.co.jp/site/cmweb/wsgi.py
```

#### Daemon mode vs embedded mode

mod_wsgi can run the application **inside** Apache's own worker processes
(embedded) or in a **separate process group it manages** (daemon). CMWEB uses
daemon mode, which is the right choice and buys four things:

1. **Privilege separation** — `user=cmweb group=cmweb`, so the application
   never runs as Apache's user.
2. **Independent reload** — touching the script file recycles only the
   application, not Apache.
3. **Isolation** — a wedged Python process does not consume an Apache worker.
4. **Its own interpreter lifetime** — imports happen once per daemon process.

#### The process model

```
16 processes × 15 threads = 240 concurrent request slots
```

Each of the 16 processes is a separate OS process with its own Python
interpreter and its own GIL. Within a process, the 15 threads are real threads
contending for that one GIL — so **CPU-bound work does not scale past 1 core
per process**, but I/O-bound work (database, git, HTTP to Gerrit/JIRA) overlaps
fine, which is what CMWEB actually does.

Memory is the trade: 16 interpreters each holding Django, the ORM, dulwich and
the rest. `maximum-requests=2000` recycles a process after 2000 requests, which
bounds slow leaks — at the cost of re-importing everything on the next request
that lands there (the first request after a recycle is noticeably slower).

| Option | Effect |
| --- | --- |
| `python-path=.../site` | Prepends `cmweb-project` to `sys.path`, so `import cmweb` works |
| `python-home=.../ENV/` | The virtualenv — equivalent to activating it |
| `display-name=%{GROUP}` | Processes appear as `(wsgi:cmweb)` in `ps`, not as `apache2` |
| `WSGIProcessGroup cmweb` | Routes this vhost's requests to that daemon group |

> `python-path` is **not** where `cmweb-app` gets onto the path. That happens
> inside `settings.py` (`sys.path.append(APPS_DIR)`), which is why `cmweb-app`
> must be checked out at `site/apps/`.

#### The WSGI entry point

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings_wsgi")
application = get_wsgi_application()
...
conf = {'debug': True, 'show_exceptions_in_wsgi_errors': True}
application = ErrorMiddleware(application, global_conf=conf)
```

Two things follow:

1. **Web requests use `cmweb.settings_wsgi`**, not the `cmweb.settings` that
   `manage.py` defaults to. The chain is
   `settings_wsgi` → `settings_deployed` (symlink) → `settings_prod` →
   `settings` → `secure.py`.
2. **Unhandled exceptions render a full Paste traceback in production**,
   regardless of Django's `DEBUG = False`. For an internal, LDAP-gated tool this
   is a deliberate trade — it makes debugging trivial. On anything public it
   would be a serious information leak.

#### Reload semantics

mod_wsgi in daemon mode monitors the mtime of the script named by
`WSGIScriptAlias`. When it changes, the daemon processes are shut down
gracefully (in-flight requests complete) and restarted on the next request.

```bash
touch /srv/www/cmweb.ptc.sony.co.jp/site/cmweb/wsgi.py
```

That is the entire deploy step. The Ansible handler does exactly this, and only
when `repo manifest -r` output changed.

`systemctl reload apache2` is a *different* operation — it re-reads Apache's
configuration. Editing the vhost needs the reload; changing Python code needs
the touch.

### Authentication — gate 1

```apache
<Location "/">
    AuthName "User/Password"
    AuthType Basic
    AuthBasicProvider ldap
    AuthLDAPURL  "ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName"
    AuthLDAPBindDN "CN=jp21602,OU=Users,OU=JPUsers,DC=jp,DC=sony,DC=com"
    AuthLDAPBindPassword "<vault>"
    Require valid-user
    ErrorDocument 401 "<html><meta http-equiv=\"refresh\" content=\"0;url=/register\"></html>"
</Location>
```

Decoding the `AuthLDAPURL`:

```
ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName
└─┬──┘ └────────┬────────┘ └┬┘ └─────┬─────┘ └──────┬─────┘
 TLS        host          port    search base   attribute to match
```

- **Port 3269** is LDAPS against the Active Directory **Global Catalog** (rather
  than 636 for normal LDAPS). The GC allows searching across the whole forest
  from one endpoint, at the cost of only replicating a subset of attributes —
  fine here, since only `sAMAccountName` is needed.
- **The bind DN is the service account** (`jp21602`), used to search for the
  user before binding as them.
- `Require valid-user` — any successful LDAP bind is accepted. There is **no
  group restriction at the Apache layer**; that is Django's job (gate 2).

The `ErrorDocument 401` is a small but real usability decision: instead of the
browser's endless credential prompt, an unknown user is bounced to `/register`.

After a successful bind, Apache sets `REMOTE_USER` in the WSGI environ, and
`django.contrib.auth.middleware.RemoteUserMiddleware` turns it into a Django
user via `users.auth.RemoteLDAPBackend`.

### The four anonymous paths

```apache
<LocationMatch "^/rpc/?$">          Require all granted  </LocationMatch>
<LocationMatch "^/register$">       Require all granted  </LocationMatch>
<LocationMatch "^/access-denied$">  Require all granted  </LocationMatch>
<LocationMatch "^/.*favicon.ico$">  Require all granted  </LocationMatch>
```

**Exactly four**, and each has a reason:

| Path | Why anonymous |
| --- | --- |
| `/rpc/` | `cmweb-scripts/bin/manifest.py` calls this XML-RPC endpoint to fetch the magic-mirror manifest — see [06 §5.3](06-cmweb-scripts-repo.md) |
| `/register` | The landing page for users with no account, reached from the 401 handler |
| `/access-denied` | Where Django's permission gate redirects |
| `favicon.ico` | Browsers request it before/outside an authenticated context |

`/rpc/` is the interesting one: **the mirroring script asks the website which
repositories to mirror**, so the website must answer it without credentials.

### Cache-busting for task polling

```apache
<LocationMatch "^/backend/tasks/.*/status$">
    Header Set Pragma "no-cache"
    Header Set Expires "Thu, 1 Jan 1970 00:00:00 GMT"
    Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
    Header Unset ETag
    FileETag None
</LocationMatch>
<LocationMatch "^/backend/tasks/apply/.*$">  ... identical ...  </LocationMatch>
```

Production wraps Django in a 10-minute page cache
(`UpdateCacheMiddleware` / `FetchFromCacheMiddleware`, `CACHE_MIDDLEWARE_SECONDS = 10 * 60`).
A task-status endpoint returning a 10-minute-old answer would make the UI's
progress polling useless — `cmweb.ajaxtask.js` would poll a frozen response
forever. These blocks belt-and-brace it at four levels: `Pragma`, `Expires` in
the past, `Cache-Control`, and ETag removal.

### `ExpiresActive On` with no rules

```apache
ExpiresActive On
```

There is no `ExpiresDefault` or `ExpiresByType` anywhere in the vhost, so
mod_expires is enabled but adds no headers. Effectively a no-op — presumably
left from an earlier configuration. Static assets therefore get no far-future
`Expires`; cache-busting relies entirely on django-compressor's hashed
filenames.

---

## 5. The two gates

The site is gated **twice**, and both must be opened to expose an endpoint.

| Gate | Layer | Mechanism | Fails with |
| --- | --- | --- | --- |
| 1 | Apache | `Require valid-user` + LDAP; four `Require all granted` exceptions | **401** |
| 2 | Django | `PermissionCheckMiddleware` on `users.view_all_pages`; `NO_AUTH_URLS` / `EXEMPT_URLS` | **302 → `/access-denied`** |

```python
EXEMPT_URLS = ['accounts/', 'request/']

NO_AUTH_URLS = ['.+/trigger-config/?$', '.+/xml(/all)?/?$',
                'builds/(.+/)?rss/?$', 'projects/.+/rss/?$',
                'activity/rss/?$', 'rpc/?$', 'api/(?!a/).*$',
                'register$', 'access-denied$']
```

Note `NO_AUTH_URLS` is **broader** than the Apache allow-list — it includes RSS
feeds, XML endpoints and `api/` (but not `api/a/`). Those paths pass Django's
gate but are still stopped by Apache's. **The effective anonymous surface is the
intersection: four paths.**

### Adding a public endpoint = three edits in three repositories

| # | Edit | Repository |
| --- | --- | --- |
| 1 | The URLconf | `cmweb-app` |
| 2 | `NO_AUTH_URLS` in `cmweb/middleware.py` | `cmweb-project` |
| 3 | `LocationMatch` + `Require all granted` in `cmweb.conf.j2` | `cmweb-scripts` |

| Symptom | Missing step |
| --- | --- |
| Basic-auth prompt / 401 | 3 |
| Redirect to `/access-denied` | 2 |
| 404 | 1 |

Because the three live in three repositories with separate review cycles, they
will not land simultaneously. **Ship 3 first** — opening the Apache gate on a
path that does not exist yet is harmless; the reverse leaves a broken endpoint.

### The delegated-trust hazard

```python
auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
```

`PermissionCheckMiddleware` base64-decodes the `Authorization` header and
**trusts the username without verifying the password**.

This is safe *only* because Apache has already bound that exact username
against LDAP. The safety property lives entirely in `cmweb.conf.j2`, in a
different repository, with nothing in the Python code asserting it.

**Never put this application behind anything that does not authenticate** — a
plain reverse proxy, a local `runserver`, or a test harness all make it
trivially impersonable by sending your own `Authorization` header.

---

## 6. Modules

Enabled explicitly by Ansible with symlinks (the manual equivalent of
`a2enmod`):

**`.conf` + `.load`:** `status`, `wsgi`, `proxy`, `proxy_balancer`,
`cache_disk`, `ssl`

**`.load` only:** `rewrite`, `auth_basic`, `expires`, `cache`, `headers`,
`ldap`, `authnz_ldap`, `vhost_alias`, `slotmem_shm`, `socache_shmcb`

| Module | Required by | Used? |
| --- | --- | --- |
| `ssl` + `socache_shmcb` | `SSLEngine`, session cache | ✅ |
| `wsgi` | `WSGIDaemonProcess`, `WSGIScriptAlias` | ✅ |
| `rewrite` | `RewriteRule` | ✅ |
| `auth_basic` | `AuthType Basic` | ✅ |
| `ldap` + `authnz_ldap` | `AuthBasicProvider ldap`, `AuthLDAPURL` | ✅ |
| `headers` | `Header Set` / `Header Unset` | ✅ |
| `status` | `ExtendedStatus`, `/server-status` | ✅ |
| `expires` | `ExpiresActive` | ⚠️ enabled, no rules |
| `proxy`, `proxy_balancer`, `cache`, `cache_disk`, `slotmem_shm`, `vhost_alias` | — | ❌ unused |

**If a directive in the vhost has no matching module, Apache refuses to start.**
That is the most common cause of a failed AMI build after a vhost edit — and
because the failure happens inside Image Builder, you see it as a failed
pipeline, not as an Apache error.

The six unused modules are leftovers from an earlier topology. They cost a
little memory and a little attack surface; removing them would be safe but
nobody has.

---

## 7. What Ansible does to produce this

```yaml
- name: Install packages                    # apache2, apache2-bin, apache2-utils, libapache2-mod-wsgi-py3
- name: Increase max open files             # patches /usr/sbin/apache2ctl ULIMIT_MAX_FILES -> 33333
- name: Static file compression             # make static as cmweb, DJANGO_SETTINGS_MODULE=cmweb.settings_deployed
- name: Freeze manifest                     # repo manifest -r    -> register static_manifest
- name: Check code change                   # write it            -> notify: Restart WSGI
- name: Create htdocs directory
- name: Link static dir                     # htdocs/static -> ../static
- name: Install Apache virtualhost config   # the template        -> notify: Reload Apache
- name: Enable Apache modules (.conf)       #                     -> notify: Reload Apache
- name: Enable Apache modules (.load)       #                     -> notify: Reload Apache
- name: Enable Apache vhost                 # sites-enabled symlink
- name: Disable default Apache config       # removes 000-default.conf
- name: Put SSL Certificate Key File        # -> /etc/ssl/private/cmweb.key
- name: Put SSL Certificate File            # -> /usr/local/share/ca-certificates/extra/cmweb.crt
- name: Update CA crt                       # -> creates /etc/ssl/certs/cmweb.pem
- name: Check compressed static changes     # compressed/manifest.json -> notify: Reload Apache
- name: Enable and start Apache
```

The **ulimit patch** matters: 16 processes × 15 threads reading a large git
mirror opens a lot of descriptors, and without it Apache hits "Too many open
files" under load.

```yaml
- name: Increase max open files to avoid "Too many open files" error
  ansible.builtin.replace:
    dest: /usr/sbin/apache2ctl
    regexp: 'ULIMIT_MAX_FILES="\$\{APACHE_ULIMIT_MAX_FILES:-ulimit -n \d+\}"'
    replace: 'ULIMIT_MAX_FILES="${APACHE_ULIMIT_MAX_FILES:-ulimit -n 33333}"'
    backup: true
```

Handlers run **once** at the end of the play no matter how many tasks notified
them:

```yaml
- name: Reload Apache
  ansible.builtin.service: { name: apache2, state: reloaded }

- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

---

## 8. Capacity and performance

### The arithmetic

```
16 processes × 15 threads         =  240 concurrent request slots
TimeOut 250s                      =  worst case a slot is held 4m10s
maximum-requests 2000             =  a process recycles roughly every 2000 requests
```

### Where the slots actually go

Three things consume them in ways that are not obvious:

1. **Eager Celery.** `CELERY_TASK_ALWAYS_EAGER = True` with no broker and no
   worker anywhere, so every `.delay()` runs *inline in the request thread*. A
   30-second "background" task holds a slot for 30 seconds. There is no queue
   absorbing it.
2. **Git reads.** `Project.git_path()` reads bare repositories over an EFS
   mount. EFS is mounted `hard`, so **a hung EFS blocks readers indefinitely
   rather than erroring** — slots fill and the site hangs rather than 500s.
3. **External calls.** Gerrit, JIRA and M+ calls made during a request hold a
   slot for the round trip.

### What the page cache does and does not absorb

`settings_prod.py` wraps the middleware stack:

```python
MIDDLEWARE = \
    ['django.middleware.cache.UpdateCacheMiddleware'] + \
    ['django.middleware.gzip.GZipMiddleware'] + \
    list(MIDDLEWARE) + \
    ['django.middleware.cache.FetchFromCacheMiddleware']
```

A cache hit is served by `FetchFromCacheMiddleware` **after** the full request
middleware chain has run — including `PermissionCheckMiddleware`. So a cached
page still costs a worker slot, a session lookup in memcached and an LDAP-backed
user object; it saves the view, the ORM and the template.

It does **not** happen at all in Apache. Apache's `cache`/`cache_disk` modules
are loaded but unconfigured.

### Sessions and the cache share a backend

```python
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
```

Both live in the same memcached. **Flushing the cache to clear stale pages logs
every user out.** Use `manage.py delete_cache_key --key …` to drop a single key
instead.

---

## 9. Monitoring

### `/server-status` and the scoreboard

`ExtendedStatus On` plus mod_status exposes the scoreboard. The only cron job on
the machine scrapes it:

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

It decodes the single-character scoreboard into named states and emits JSON
lines (via `python-json-logger` and a `RotatingFileHandler`) that the CloudWatch
agent ships:

| Char | State | Meaning |
| --- | --- | --- |
| `_` | `WaitingForConnection` | Idle, ready |
| `S` | `StartingUp` | |
| `R` | `ReadingRequest` | |
| `W` | `SendingReply` | **Actively serving — includes time in Django** |
| `K` | `KeepAlive` | |
| `D` | `DNSLookup` | |
| `C` | `ClosingConnection` | |
| `L` | `Logging` | |
| `G` | `GracefullyFinishing` | Recycling after `maximum-requests` |
| `I` | `IdleCleanupOfWorker` | |
| `.` | `OpenSlotWithNoCurrentProcess` | Unused capacity |

**This is the metric for "are we running out of worker slots".** Rising `W` with
few `_` and `.` means requests are queueing. Rising `G` means processes are
recycling — expected at a steady rate given `maximum-requests=2000`, but a spike
suggests memory pressure.

The config it reads is rendered from the vault:

```json
{
    "HOSTNAME": "{{ hostname }}",
    "SERVICE_USER": "{{ system_account }}",
    "SERVICE_PASS": "{{ system_password }}"
}
```

It authenticates as the service account — because `/server-status` sits behind
the same LDAP gate as everything else.

### Log rotation

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

Eight weeks of the application's JSON logs. Apache's own
`/var/log/apache2/*.log` are rotated by the distribution's default config, not
this one.

---

## 10. Security posture

Worth stating plainly, because the configuration makes deliberate trades that
would be wrong on a public site.

**Enforced:**

- TLS only; no `*:80` vhost at all
- LDAP authentication on every path except four
- `Require valid-user` before any Python executes
- Privilege separation (`user=cmweb`), `secure.py` at mode 0640
- `CSRF_TRUSTED_ORIGINS = ['https://cmweb.ptc.sony.co.jp']`

**Deliberately absent:**

| Missing | Effect |
| --- | --- |
| `SECURE_SSL_REDIRECT`, HSTS | No `*:80` vhost exists, so there is nothing to redirect — but also no HSTS header |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Not set; only mitigated by there being no HTTP listener |
| `XFrameOptionsMiddleware` | Commented out in `settings.py` — no clickjacking protection |
| `ALLOWED_HOSTS` | `['*']` in production |
| Group restriction at Apache | Any valid Sony LDAP user reaches Django; authorization is Django's `view_all_pages` |
| Paste traceback suppression | Full tracebacks rendered in production |
| Private key permissions | `/etc/ssl/private/cmweb.key` at 0644 |

None of these is exploitable given the LDAP gate and the internal network. All
of them are things to fix before this application is ever exposed more widely,
and all of them are reasons the delegated-trust hazard in section 5 matters.

---

## 11. Troubleshooting

| Symptom | Cause | First check |
| --- | --- | --- |
| **Apache will not start after a vhost edit** | Directive whose module is not enabled | `apache2ctl configtest` |
| **Apache will not start, SSL error** | `/etc/ssl/certs/cmweb.pem` missing — `update-ca-certificates` did not run | `ls -l /etc/ssl/certs/cmweb.pem` |
| **401 on a new endpoint** | No `LocationMatch` / `Require all granted` | The vhost |
| **Redirect to `/access-denied`** | Missing from `NO_AUTH_URLS` (Django gate) | `cmweb/middleware.py` |
| **404** | Not in the URLconf | `cmweb-app/<app>/urls.py` |
| **Everyone logged out at once** | memcached flushed — sessions live there | Who ran a cache flush |
| **Traceback shown in production** | Expected: Paste `ErrorMiddleware` with `debug: True` | `cmweb/wsgi.py` |
| **Content stale up to 10 minutes** | Django page cache | `CACHE_MIDDLEWARE_SECONDS` |
| **Old CSS/JS after a deploy** | `make static` did not re-run; `STATIC_MD5` unchanged | `static/compressed/manifest.json` mtime |
| **New code not live after a deploy** | `repo manifest -r` unchanged, so `Restart WSGI` never fired | `touch site/cmweb/wsgi.py` |
| **"Too many open files"** | `apache2ctl` ulimit patch missing | `grep ULIMIT_MAX_FILES /usr/sbin/apache2ctl` |
| **Requests hang instead of erroring** | EFS `hard` mount stuck | `mount \| grep nfs`, `df` |
| **Site slow, no errors** | Worker slots exhausted | `/server-status`, scoreboard `W` vs `_` |
| **URL redirects unexpectedly** | `RewriteRule` block | 302s in the access log |
| **A page is missing from the logs entirely** | `X-Forwarded-For` exclusion | `SetEnvIf` line |
| **First request after idle is slow** | Process recycled at `maximum-requests`, re-importing Django | Scoreboard `G` count |

### Commands on a web server

```bash
apache2ctl configtest                  # validate before reloading — ALWAYS do this first
apache2ctl -M                          # list loaded modules
apache2ctl -S                          # vhost/ServerName summary
systemctl reload apache2               # re-read config, keep connections
touch /srv/www/<host>/site/cmweb/wsgi.py    # reload the application only

tail -f /var/log/apache2/<host>_error.log
tail -f /var/log/apache2/<host>_access.log

ps aux | grep 'wsgi:cmweb'             # the 16 daemon processes
ls -l /etc/ssl/certs/cmweb.pem         # the symlink update-ca-certificates made
```

### Log analysis recipes

`%D` is the last field, in microseconds:

```bash
# slowest 20 requests
awk '{print $NF, $0}' <host>_access.log | sort -rn | head -20

# requests over 10 seconds
awk '$NF > 10000000' <host>_access.log

# mean duration by URL path (field 7 is the URI in "%r")
awk '{print $7, $NF}' <host>_access.log \
  | awk '{s[$1]+=$2; n[$1]++} END {for (u in s) printf "%12.0f  %6d  %s\n", s[u]/n[u], n[u], u}' \
  | sort -rn | head -20

# who is hitting the site (%u is field 3)
awk '{print $3}' <host>_access.log | sort | uniq -c | sort -rn | head

# status code distribution
awk '{print $9}' <host>_access.log | sort | uniq -c | sort -rn
```

---

## 12. Changing the vhost safely

1. **Edit the template**, never the deployed file —
   `ansible/roles/apache-server/templates/apache/cmweb.conf.j2`. Anything you
   change on a server is lost at the next AMI build.
2. **Mind the Jinja2 braces.** Apache's `%{Referer}i` is close enough to Jinja2
   syntax to be a trap; the `LogFormat` line is wrapped in `{% raw %}…{% endraw %}`
   for that reason. Any new literal `{{` or `{%` needs the same treatment.
3. **Check the module.** If you add a directive, confirm its module is in the
   `Enable Apache modules` lists — otherwise Apache will not start and the AMI
   build fails.
4. **Preview the render:**

```bash
ansible-playbook --vault-password-file ../.vault -c local -i hosts/stage \
                 web-servers.yml --check --diff
```

`--check --diff` shows exactly what would be written to
`/etc/apache2/sites-available/000-cmweb.conf` without writing it.

5. **Validate on a stage host** before prod: `apache2ctl configtest`.
6. **Remember the reload split** — a vhost change needs `Reload Apache`; a code
   change needs `Restart WSGI`. They are different handlers and different
   triggers.

### Known rough edges

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
  changed_when: result.rc == 0          # <- `result` is never registered here
```

```yaml
- name: Update CA crt
  ansible.builtin.command:
    cmd: sudo update-ca-certificates    # <- redundant sudo; play is already become: true
  register: result
  changed_when: result.rc == 0          # <- always "changed" when it succeeds
```

Neither breaks anything today. The second is the task the TLS certificate
depends on (section 4), so it is worth understanding before anyone "tidies" it
away.
