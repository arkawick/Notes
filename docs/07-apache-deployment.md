# 7. Deploying under Apache

*How Django actually runs in production, and how CMWEB's vhost is put together.*

---

## Part A — The concept

### `runserver` is not a production server

`./manage.py runserver` is single-threaded, unoptimised, and explicitly not for
production. Real deployment needs a proper web server.

### WSGI

**WSGI** is the Python standard interface between a web server and a Python web
application. The application side is one callable:

```python
def application(environ, start_response):
    ...
```

`environ` is a dict of request data; `start_response` is a callback for status
and headers. Every Python web framework exposes one, which is why any WSGI
server can run any WSGI framework.

Django generates it for you:

```python
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

> **Note this is a factory.** `get_wsgi_application()` *returns* the callable —
> the module-level name `application` must hold the **result**, not the function.
> Pointing a server at the factory produces
> `get_wsgi_application() takes 0 positional arguments but 2 were given` on
> every request. (This bit the `local-cmweb` setup, which is why
> `config/wsgi_local.py` exists as a separate module.)

### mod_wsgi

`mod_wsgi` is the Apache module that hosts WSGI applications. It has two modes:

- **Embedded** — runs inside Apache's own worker processes.
- **Daemon** — runs in separate processes Apache talks to. Preferred: you
  control process and thread counts, and you can reload the app without
  restarting Apache.

CMWEB uses daemon mode.

---

## Part B — The settings chain

CMWEB's is four levels deep, and getting lost in it is common:

```
cmweb/wsgi.py
  └─ sets DJANGO_SETTINGS_MODULE = cmweb.settings_wsgi
       │
       └─ settings_wsgi.py
            │   IS_WSGI = True
            │   LOGGING['root']['level'] = 'ERROR'
            └─ from .settings_deployed import *
                 │
                 └─ settings_deployed.py  ← a SYMLINK, created by Ansible
                      └─ settings_prod.py  (or _stage / _test)
                           └─ from .settings import *
                                └─ from .secure import *   (generated, gitignored)
```

Why each layer exists:

| Layer | Purpose |
| --- | --- |
| `settings.py` | Base: everything common, plus `GLOBALS` |
| `secure.py` | Credentials and host names. **Never committed** — rendered by Ansible |
| `settings_prod/stage/test.py` | Per-environment: database, cache, hostnames, LDAP on/off |
| `settings_deployed.py` | A symlink to whichever of those applies. Lets Celery and cron reference one stable name |
| `settings_wsgi.py` | Sets `IS_WSGI = True` so the logging config can split WSGI logs (`wsgi.json`) from management-command logs (`django.json`) |

Note `settings_wsgi.py` imports **without** a try/except:

```python
# This has to exist, no error handling
from .settings_deployed import *
```

If the symlink is missing, the site fails loudly at startup — which is correct.

---

## Part C — `wsgi.py` is not the Django default

`cmweb-project/cmweb/wsgi.py` wraps the application:

```python
import paste
from paste.exceptions.errormiddleware import ErrorMiddleware, Supplement
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings_wsgi")
application = get_wsgi_application()

# ... CatchingIter class, ~90 lines of Python 3 generator handling ...

conf = {'debug': True, 'show_exceptions_in_wsgi_errors': True}
paste.exceptions.errormiddleware.ErrorMiddleware.make_catching_iter = \
    make_catching_iter
application = ErrorMiddleware(application, global_conf=conf)
```

It wraps Django in Paste's `ErrorMiddleware` and monkey-patches
`make_catching_iter` to handle Python 3 generators (the shipped version was
Python 2 only).

**The practical effect**: unhandled exceptions render a **Paste traceback page**,
not Django's 500 page — and `debug: True` here is independent of Django's
`DEBUG = False` in `settings_prod`. Detailed tracebacks are visible in
production. Worth knowing both when debugging and when thinking about what the
site exposes.

---

## Part D — The vhost

`cmweb-scripts/ansible/roles/apache-server/templates/apache/cmweb.conf.j2`, a
Jinja2 template Ansible renders per environment.

### The WSGI block

```apache
WSGIDaemonProcess {{ hostname_short }} user=cmweb group=cmweb \
    processes=16 threads=15 maximum-requests=2000 \
    display-name=%{GROUP} \
    python-path=/srv/www/{{ hostname }}/site \
    python-home=/srv/www/{{ hostname }}/ENV/
WSGIProcessGroup {{ hostname_short }}
WSGIScriptAlias / /srv/www/{{ hostname }}/site/cmweb/wsgi.py
```

| Directive | Meaning |
| --- | --- |
| `processes=16 threads=15` | 240 concurrent request slots |
| `maximum-requests=2000` | Recycle each process after 2000 requests — papers over slow memory growth |
| `python-path=…/site` | Puts `cmweb-project` on `sys.path`; combined with the `sys.path.append` in settings, this is what makes `cmweb-app` importable |
| `python-home=…/ENV/` | The virtualenv |
| `display-name=%{GROUP}` | Processes show a readable name in `ps` |

### Authentication

```apache
<Location "/">
    AuthType Basic
    AuthBasicProvider ldap
    AuthLDAPURL "ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName"
    AuthLDAPBindDN "CN={{ system_account }},OU=Users,OU=JPUsers,DC=jp,DC=sony,DC=com"
    AuthLDAPBindPassword "{{ system_password }}"
    Require valid-user
    ErrorDocument 401 "<html><meta http-equiv=\"refresh\" content=\"0;url=/register\"></html>"
</Location>
```

**Apache authenticates the entire site against LDAP before Django sees the
request.** The authenticated username is passed on, and Django's
`RemoteUserMiddleware` turns it into a logged-in user. A 401 becomes a redirect
to `/register` rather than a browser password box.

Anonymous exceptions:

```apache
<LocationMatch "^/rpc/?$">        Require all granted </LocationMatch>
<LocationMatch "^/register$">     Require all granted </LocationMatch>
<LocationMatch "^/access-denied$">Require all granted </LocationMatch>
<LocationMatch "^/.*favicon.ico$">Require all granted </LocationMatch>
```

`/rpc/` is open because the git-mirroring script
(`cmweb-scripts/bin/mirror_repo.sh`) queries it for the mirror manifest — **the
application and its own data pipeline are circularly dependent.**

### Cache suppression for task polling

```apache
<LocationMatch "^/backend/tasks/.*/status$">
    Header Set Pragma "no-cache"
    Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
    Header Unset ETag
    FileETag None
</LocationMatch>
```

Production caches pages for ten minutes site-wide. Without these blocks the
progress display would freeze on the first response. See
[05-celery-tasks.md](05-celery-tasks.md).

### Legacy URL rewrites

```apache
RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ \
            /labels/$1/\+$2/$3 [R,N]
RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]
```

Old bookmarks and scripts keep working. Note the second one adds the `+` prefix
that build sub-pages now use — see [03-views.md](03-views.md#the--convention).

### Limits

```apache
LimitRequestBody 10048576        # 10 MB uploads
LimitRequestFieldSize 32760      # large headers
TimeOut 250
```

The field-size bump exists because build pages submit very large forms — the
same reason `settings.py` sets `DATA_UPLOAD_MAX_NUMBER_FIELDS = None`.

### Static files

```apache
Alias /static/ /srv/www/{{ hostname }}/htdocs/static/
```

Apache serves static files directly; they never reach Python. The directory is a
symlink to `static/`, populated by `make static` (collectstatic + compression).

---

## Part E — Reload vs restart

The Ansible role distinguishes two handlers, and the mechanism is worth
understanding:

```yaml
- name: Reload Apache
  ansible.builtin.service:
    name: apache2
    state: reloaded

- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

- **Reload Apache** — for vhost or module changes.
- **Restart WSGI** — for *code* changes, done by **touching `wsgi.py`**. In
  mod_wsgi daemon mode, a change to the script file's mtime makes the daemon
  reload the application. Apache itself never restarts, so no requests are
  dropped.

The trigger is neat:

```yaml
- name: Freeze manifest
  ansible.builtin.command:
    cmd: repo manifest -r
  register: static_manifest

- name: Check code change
  ansible.builtin.copy:
    content: '{{ static_manifest.stdout }}'
    dest: "/srv/www/{{ hostname }}/static-manifest-wsgi.xml"
  notify: Restart WSGI
```

`repo manifest -r` prints the exact revision of every repository. Ansible writes
it to a file and only reports *changed* if the content differs — so the app
reloads **exactly when the deployed code actually moved**, and not otherwise.

> **Latent bug worth knowing about.** The `Restart WSGI` handler has
> `changed_when: result.rc == 0` but never registers `result`. It reads whatever
> `result` was last registered — in this play, the `Update CA crt` task.
> Harmless today, but the handler's reported status is meaningless and it will
> break confusingly if the roles are reordered.

---

## Part F — Apache module setup

The role symlinks modules into `mods-enabled`. The list tells you what the
config relies on:

`rewrite`, `status`, `auth_basic`, `wsgi`, `expires`, `proxy`,
`proxy_balancer`, `cache`, `cache_disk`, `headers`, `ldap`, `authnz_ldap`,
`vhost_alias`, `slotmem_shm`, `ssl`, `socache_shmcb`

Also:

```yaml
- name: Increase max open files to avoid "Too many open files" error
  ansible.builtin.replace:
    dest: /usr/sbin/apache2ctl
    regexp: 'ULIMIT_MAX_FILES="\$\{APACHE_ULIMIT_MAX_FILES:-ulimit -n \d+\}"'
    replace: 'ULIMIT_MAX_FILES="${APACHE_ULIMIT_MAX_FILES:-ulimit -n {{ pam_limits_nofile_soft }}}"'
```

It edits Apache's own init script by regex to raise the file-descriptor limit to
33,333 — 240 threads each holding database and file handles exhaust the default.
Fragile: an `apache2` package upgrade can silently revert it.

---

## Part G — The deployed filesystem

```
/srv/www/cmweb.ptc.sony.co.jp/
├── site/                    ← cmweb-project (python-path)
│   ├── cmweb/
│   │   ├── wsgi.py          ← WSGIScriptAlias target; touch to reload
│   │   ├── secure.py        ← rendered by Ansible, gitignored
│   │   └── settings_deployed.py → settings_prod.py   (symlink)
│   └── apps/                ← cmweb-app
├── ENV/                     ← virtualenv (python-home)
├── htdocs/
│   └── static/ → ../static  (Apache serves this directly)
├── static/                  ← collectstatic + compressed output
├── repository/ → /mnt/nfs/cmweb/repo-mirror   (bare git mirrors)
├── cache/
├── var/log/                 ← django.json, wsgi.json
└── static-manifest-wsgi.xml ← the reload trigger
```

---

## Part H — Troubleshooting

| Symptom | Look at |
| --- | --- |
| 500 with a Paste traceback | The traceback itself — it is detailed. Also `/var/log/apache2/<host>_error.log` |
| Changes not appearing | Was `wsgi.py` touched? Did the ten-minute page cache serve a stale copy? |
| New CSS/JS not loading | `make static` not run; also `X-PJAX-Version` unchanged so clients kept the old assets |
| Login loops | LDAP bind credentials in `secure.py`, or the `users-serviceusername` `Parameter` overriding them |
| A public endpoint 401s | Missing `Require all granted` block — Apache rejects before Django sees it |
| A public endpoint redirects to `/access-denied` | Apache is fine; `NO_AUTH_URLS` in `cmweb/middleware.py` is missing the pattern |
| `ImportError` at startup | `python-path` wrong, or `apps/` missing under `site/` |
| Slow under load | 240 slots; check `maximum-requests` recycling and database connections |

Adding a public endpoint needs **three** edits — URLconf, `NO_AUTH_URLS`, Apache.
The middle two rows above are how you tell which one you missed.

**Next:** [08-ansible.md](08-ansible.md)
