# How the site works

*One request from browser to PostgreSQL, and how the machine it lands on gets built.*

The other documents each take one layer. This one follows the whole path: what
Apache does before Django sees a request, what Django does with it, where the
data actually lives, and how Ansible and EC2 Image Builder produce the server
that runs all of it.

Everything below is drawn from `cmweb-project/cmweb/`, `cmweb-scripts/ansible/`
and `cmweb-scripts/cloudformation/`. Where the code disagrees with folklore, the
code wins and the disagreement is called out.

---

## 1. The shape of it

The single most useful thing to know about CMWEB is that **two separate tiers
share one database**, and they have opposite jobs.

```
  READ TIER                                     WRITE TIER
  +------------------+                     +----------------------+
  | EC2 web server   |                     | Jenkins agents       |
  | Apache+mod_wsgi  |                     | ci-tools.ptc...      |
  | 16 proc x 15 thr |                     | ~50 scheduled jobs   |
  +---+----------+---+                     +----+------------+----+
      |          |                              |            |
   serves      reads                       bulk writes   reads/writes
   pages        |                               |            |
      |         v                               v            |
      |    +-------------------------------------------+     |
      |    |  RDS PostgreSQL  :5432   database "cmweb"  |     |
      |    +-------------------------------------------+     |
      |    +-------------------------------------------+     |
      +--->|  ElastiCache memcached :11211              |     |
      |    |  page cache (10 min) + session store       |     |
      |    +-------------------------------------------+     |
      |    +-------------------------------------------+     |
      +--->|  EFS /mnt/nfs  bare git mirrors, media     |<----+
      |    +-------------------------------------------+
      |    +-------------------------------------------+
      +--->|  OpenSearch (VPC domain, HTTPS :443)       |<---- update_search_index
           +-------------------------------------------+

           Gerrit / git / C2D / JIRA  ---- read by the write tier
```

The web tier is **read-mostly**: it renders pages out of tables somebody else
filled in. Almost every row in the database was written by a Jenkins job running
`manage.py index_labels`, `sync_commits`, `sync_projects_from_gerrit` and
friends, not by a web request. User writes from the browser exist (branch
requests, cherry-pick policies, votes) but they are a thin layer on top.

That split explains a lot of otherwise odd decisions: why the page cache can be
ten minutes long, why the indexing pipeline lives in a different repository, and
why `cmweb-scripts` contains no application code but is still load-bearing.

### Three environments, three AWS accounts

| | Production | Stage | Test |
| --- | --- | --- | --- |
| Hostname | `cmweb.ptc.sony.co.jp` | `cmweb.ptc-stage.sony.co.jp` | `cmweb.ptc-test.sony.co.jp` |
| AWS account | `659398199407` | `009896685360` | `100267242497` |
| RDS host | `cmweb.cm8tmtafyb32...` | `cmweb.cl0tidynvdpp...` | `cmweb.cbes5fhcsnrc...` |
| Cache host | `cmweb.myfjt0...` | `cmweb-stage.rijg6j...` | `cmweb.mysvso...` |
| Manifest | `release.xml` (pinned) | `default.xml` (floating) | `default.xml` (floating) |
| EFS mount | yes | yes | **no** |
| Scheduled jobs | yes | yes | no |

The account id is not just bookkeeping — it is how a booting instance decides
which environment it is. See section 2.

---

## 2. EC2, and how the machine is baked

There is no "install the app on a server" step. The server *is* the artifact —
an AMI produced by **EC2 Image Builder**, with the whole application already on
disk.

```
  cloudformation/ec2imagebuilder/
  +--------------------------------------------------------------+
  | Pipeline   cmweb-on-ubuntu20  /  cmweb-on-ubuntu22            |
  |                                                              |
  |  InfrastructureConfiguration "release"                       |
  |    t3a.small - profile-cmweb-ec2-image-builder               |
  |    subnet + SG chosen by account id - S3 logs - SNS topic    |
  |                                                              |
  |  ImageRecipe                                                 |
  |    ParentImage = AWS ubuntu-server-20-lts / 22-lts           |
  |    6 components, in order:                                   |
  |      1 setup-proxy        4 get-scripts   (clones the repo)  |
  |      2 get-tools          5 provision-web (the real work)    |
  |      3 setup-password     6 teardown-password                |
  |                                                              |
  |  DistributionConfiguration                                   |
  |    AMI tagged System=cmweb, Name=cmweb-web, ap-northeast-1   |
  +--------------------------------------------------------------+
                            | bakes
                            v
                      AMI  cmweb-web
                            | launch
                            v
                  EC2 instance, ready to serve
```

### The component that does everything

`builder-cmweb-component-provision-web.yaml` is five lines of bash, and it is
the hinge of the entire deployment:

```bash
export HOME=/root
cd ~/cmweb-scripts/ansible
ACCOUNT_ID=`curl -s http://169.254.169.254/latest/meta-data/identity-credentials/ec2/info/ | jq -r ".AccountId"`
if [ "659398199407" = "${ACCOUNT_ID}" ];then ENV="prod"; elif [ "009896685360" = "${ACCOUNT_ID}" ];then ENV="stage"; elif [ "100267242497" = "${ACCOUNT_ID}" ];then ENV="test"; fi
ansible-playbook --vault-password-file ~/.vault -c local -i hosts/$ENV web-servers.yml
```

Three things follow from those five lines:

1. **The build instance asks the instance metadata service who it is** and maps
   the AWS account id to an environment name. The same recipe therefore produces
   a prod AMI in the prod account and a stage AMI in the stage account, with no
   parameter to get wrong.
2. **`-c local` finally makes sense.** Ansible is not pushing config to a remote
   host from a control node — it is running *on* the machine being built,
   configuring itself. Every inventory file is one line: `localhost prod=1`.
3. **The vault password lives at `~/.vault` on the build instance**, placed by
   the `setup-password` component and removed again by `teardown-password` so it
   does not survive into the AMI.

### What the running instance is allowed to do

`profile-cmweb-web` is deliberately small:

| Managed policy | Why |
| --- | --- |
| `AmazonS3FullAccess` | artefact and log buckets |
| `AmazonSSMManagedInstanceCore` | Session Manager access instead of SSH |

Note what is *absent*: no RDS, ElastiCache or Secrets Manager permissions. The
database password does not come from AWS at runtime — it is baked into
`site/cmweb/secure.py` at image build time from the Ansible vault (section 6),
and network access to RDS is granted by security group, not by IAM.

> **Not in this repository.** `cloudformation/` holds only the image pipeline,
> three IAM instance profiles and three security groups. There is no load
> balancer, target group or auto-scaling group anywhere in the tree — though the
> CloudWatch agent config appends an `AutoScalingGroupName` dimension, which
> implies instances do run in an ASG created outside this repo. If you are
> looking for the ALB, it is not here.

---

## 3. Apache, the front door

`ansible/roles/apache-server/templates/apache/cmweb.conf.j2`. Read it before
debugging any auth or URL problem — a surprising amount of CMWEB's behaviour is
decided before Python starts.

```
  browser
     |  HTTPS :443
     v
  +----------------------------------------------------------+
  | Apache vhost                                             |
  |                                                          |
  |  1. TLS terminate     /etc/ssl/certs/cmweb.pem           |
  |  2. RewriteRule x4    legacy URL shapes -> current ones  |
  |  3. Alias /static/  ------------> htdocs/static/  -------+--> served from
  |  4. LDAP basic auth   ldaps://LDAP.jp.sony.com:3269      |    disk, never
  |       Require valid-user, 4 anonymous exceptions         |    reaches Python
  |  5. no-cache headers  /backend/tasks/...                 |
  +-----------------------+----------------------------------+
                          |  WSGI, username in REMOTE_USER
                          v
      WSGIDaemonProcess: 16 processes x 15 threads = 240 slots
      user=cmweb   maximum-requests=2000
      python-path=/srv/www/<host>/site   python-home=/srv/www/<host>/ENV/
                          |
                          v
      /srv/www/<host>/site/cmweb/wsgi.py
```

### Authentication happens twice

**Apache authenticates the whole site against LDAP first.** Django never sees an
unauthenticated request except on the four excepted paths.

```apache
<Location "/">
    AuthType Basic
    AuthBasicProvider ldap
    AuthLDAPURL  "ldaps://LDAP.jp.sony.com:3269/DC=sony,DC=com?sAMAccountName"
    AuthLDAPBindDN "CN={{ system_account }},OU=Users,OU=JPUsers,DC=jp,DC=sony,DC=com"
    AuthLDAPBindPassword "{{ system_password }}"
    Require valid-user
    ErrorDocument 401 "<html><meta http-equiv=\"refresh\" content=\"0;url=/register\"></html>"
</Location>
```

A failed login is not a browser password box — the 401 is rewritten into a
redirect to `/register`. The four paths granted anonymous access:

| Path | Why it must be open |
| --- | --- |
| `^/rpc/?$` | `bin/mirror_repo.sh` asks CMWEB for the mirror manifest |
| `^/register$` | the 401 target; it would loop otherwise |
| `^/access-denied$` | Django's own rejection page |
| `^/.*favicon.ico$` | browsers request it before authenticating |

`/rpc/` is the interesting one: **the git-mirroring pipeline calls back into the
web application it feeds.** The app and its own data source are circular, and
this exception is what keeps the loop from deadlocking on auth.

Then Django's `PermissionCheckMiddleware` gates the site a *second* time, on the
`users.view_all_pages` permission. Opening a URL to anonymous users needs edits
in **both** places, plus the URLconf — three edits, and the symptom tells you
which one you missed:

| Symptom | What is missing |
| --- | --- |
| 401 from Apache | a `Require all granted` block in the vhost |
| Redirect to `/access-denied` | the pattern in `NO_AUTH_URLS` in `cmweb/middleware.py` |
| 404 | the URLconf entry |

### The rest of the vhost

| Directive | Value | Why |
| --- | --- | --- |
| `processes=16 threads=15` | 240 concurrent slots | |
| `maximum-requests=2000` | recycle each process | papers over slow memory growth |
| `LimitRequestFieldSize` | 32760 | build pages submit very large forms — the same reason `settings.py` sets `DATA_UPLOAD_MAX_NUMBER_FIELDS = None` |
| `LimitRequestBody` | 10 MB | upload ceiling |
| `TimeOut` | 250 s | indexing-adjacent views are slow |
| `Alias /static/` | `htdocs/static/` -> `../static` | Apache serves assets directly |
| `ExtendedStatus On` | | feeds the 5-minute `apache_status_logging.py` cron |

Four rewrites keep old bookmarks working, including the one that adds the `+`
prefix that build sub-pages now use:

```apache
RewriteRule ^/projects/(.*)\.git(.*)$ /repositories/$1$2 [R,N]
RewriteRule ^/labels/(.*)/(repositories|summary|issues|commits|decoupled)/(.*)$ /labels/$1/\+$2/$3 [R,N]
RewriteRule ^/tags/schedule/(.*)$ /schedule/branches/$1 [R,N]
```

Two `LocationMatch` blocks strip caching from `/backend/tasks/*/status` and
`/backend/tasks/apply/*`. Without them the ten-minute page cache would freeze
every task progress display on its first response.

---

## 4. Inside Django

### The settings chain

Five levels deep, and the symlink in the middle is the pivot the whole
deployment turns on:

```
  cmweb/wsgi.py
    sets DJANGO_SETTINGS_MODULE = cmweb.settings_wsgi
      |
      v
  settings_wsgi.py          IS_WSGI = True; root log level ERROR
      |  from .settings_deployed import *      (no try/except - fails loudly)
      v
  settings_deployed.py  ->  SYMLINK created by Ansible
      |
      v
  settings_prod.py  (or _stage / _test)
      |  from .settings import *
      v
  settings.py
      |  from .secure import *
      v
  secure.py            rendered by Ansible from the vault, gitignored
```

| Layer | Purpose |
| --- | --- |
| `settings.py` | base: everything common, plus the `GLOBALS` dict |
| `secure.py` | credentials and host names — **never committed**, rendered per host |
| `settings_prod/stage/test.py` | per-environment database, cache, hostnames, LDAP |
| `settings_deployed.py` | the symlink, so Celery and management commands can name one stable module |
| `settings_wsgi.py` | sets `IS_WSGI = True` so logging splits `wsgi.json` from `django.json` |

`secure.py` is only twelve assignments, but nothing imports without it:

```python
DATABASES__DEFAULT__HOST = '{{ django_db_host }}'
DATABASES__DEFAULT__PASSWORD = '{{ django_db_password }}'
CACHES__DEFAULT__HOST = '{{ django_cache_host }}'
AUTH_DEFAULT_SERVICE_USERNAME = '{{ system_account }}'
OPENSEARCH_HOST = '{{ opensearch_host }}'
...
```

`settings.py` imports it inside a `try/except`, but then references those names
unguarded, so a missing `secure.py` fails with `NameError: OPENSEARCH_HOST`
rather than a readable message.

### The middleware stack

Base `settings.py` defines eleven; `settings_prod.py` wraps the list in caching
and compression:

```python
MIDDLEWARE = \
    ['django.middleware.cache.UpdateCacheMiddleware'] + \
    ['django.middleware.gzip.GZipMiddleware'] + \
    list(MIDDLEWARE) + \
    ['django.middleware.cache.FetchFromCacheMiddleware']
```

so the production order is:

| # | Middleware | Effect |
| --- | --- | --- |
| 1 | `UpdateCacheMiddleware` | stores the rendered page for `CACHE_MIDDLEWARE_SECONDS` = 600 |
| 2 | `GZipMiddleware` | compresses responses |
| 3 | `CommonMiddleware` | |
| 4 | `SessionMiddleware` | sessions live in memcached, not the database |
| 5 | `SessionTimeoutMiddleware` | idle expiry |
| 6 | `CsrfViewMiddleware` | |
| 7 | `AuthenticationMiddleware` | |
| 8 | `RemoteUserMiddleware` | **turns Apache's LDAP result into a Django user** |
| 9 | `MessageMiddleware` | |
| 10 | `PaginationMiddleware` | |
| 11 | `PjaxVersionMiddleware` | stamps `X-PJAX-Version` = app version + static asset hash |
| 12 | `PermissionCheckMiddleware` | the site-wide `users.view_all_pages` gate |
| 13 | `FetchFromCacheMiddleware` | serves the cached page if there is one |

Two consequences worth internalising:

- **`RemoteUserMiddleware` is why the local dev harness has to fake a login.**
  With no Apache in front setting `REMOTE_USER`, it logs every request out.
- **`PjaxVersionMiddleware` is the cache-busting mechanism for the front end.**
  Bootstrap 3 + PJAX means clients hold onto assets; a changed version header
  forces a full reload.

### The permission gate, exactly as written

```python
if 'HTTP_AUTHORIZATION' in request.META:
    auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
    username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
    ...
if user.is_anonymous and username:
    request_user = User.objects.filter(username=username)
    if request_user:
        user = request_user[0]
```

**It base64-decodes the HTTP Basic header and trusts the username without ever
checking the password.** That is only safe because Apache already bound that
username against LDAP before the request arrived. If the site were ever moved
behind something that does not authenticate, this becomes an authentication
bypass. It is the strongest argument for treating the vhost as part of the
application rather than as deployment trivia.

### `wsgi.py` is not the Django default

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmweb.settings_wsgi")
application = get_wsgi_application()
# ~90 lines monkey-patching Paste's make_catching_iter for Python 3 generators
conf = {'debug': True, 'show_exceptions_in_wsgi_errors': True}
application = ErrorMiddleware(application, global_conf=conf)
```

Django is wrapped in Paste's `ErrorMiddleware`. The practical effect: an
unhandled exception renders a **Paste traceback page**, not Django's 500 — and
that `debug: True` is independent of Django's `DEBUG = False` in
`settings_prod`. Detailed tracebacks are visible in production.

> `get_wsgi_application()` is a *factory*. The module-level `application` must
> hold its **result**. Point a server at the function and every request fails
> with `get_wsgi_application() takes 0 positional arguments but 2 were given`.

---

## 5. RDS and the shared state

Four stores sit behind the web tier. Only one of them is authoritative.

### RDS PostgreSQL

```python
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': DATABASES__DEFAULT__NAME,      # cmweb
    'USER': 'cmweb',
    'HOST': DATABASES__DEFAULT__HOST,      # the RDS endpoint
    'PORT': DATABASES__DEFAULT__PORT,      # 5432
    'PASSWORD': DATABASES__DEFAULT__PASSWORD,
}
DATABASE_ALIAS_FOR_WRITE = 'default'
```

Access is by network, not IAM. `cloudformation/vpc/sg-cmweb-rds.yaml` is the
whole access policy:

```yaml
SecurityGroupIngress:
  - IpProtocol: tcp
    FromPort: 5432
    ToPort: 5432
    CidrIp: 10.0.0.0/8
```

Anything on the corporate 10/8 network that has the password can connect. That
is how the Jenkins agents write to the same database the web servers read.

Two things about how the ORM talks to it:

- **There is a read-replica router, and it is switched off.** `settings_prod.py`
  carries the comment *"disabled until we know what's causing pgpool-II to raise
  OOM"*. Indexing code still writes with an explicit
  `using=settings.DATABASE_ALIAS_FOR_WRITE` — keep following that convention in
  new indexing code, because the router may come back.
- **`CONN_MAX_AGE` is never set**, so it is Django's default of `0`: every
  request opens a new PostgreSQL connection and closes it at the end. With 240
  request slots that is a lot of connection churn, and it is the first thing to
  look at if RDS connection counts become a problem.

### ElastiCache memcached

```python
CACHES['default'] = {
    'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
    'LOCATION': CACHES__DEFAULT__HOST + ':' + CACHES__DEFAULT__PORT,
    'TIMEOUT': 60 * 60 * 12,
}
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
```

It carries three different kinds of state, which is worth separating in your
head when something goes stale:

| What | Lifetime | Set by |
| --- | --- | --- |
| Whole rendered pages | 10 min | `CACHE_MIDDLEWARE_SECONDS` |
| Sessions | `SESSION_ENGINE` = cache | login state — **flushing the cache logs everyone out** |
| Application values | 12 h default | `base.cache.cache`, `Parameter`, `PropertyCacheMixin` |

### EFS

Mounted at `/mnt/nfs` over NFSv4 by the `efs` role (prod: `10.26.14.9:/`), then
symlinked into the site:

| Symlink | Target | Contents |
| --- | --- | --- |
| `<site>/repository` | `/mnt/nfs/cmweb/repo-mirror` | bare git mirrors read with dulwich |
| `<site>/static/media` | `/mnt/nfs/media` | uploaded media |

This is the shared surface between the two tiers: the `mirror_gits` job writes
the mirror, the web application and the indexing jobs read it. Commit diffs,
file browsing and manifest rendering all go through it — which is why they are
the first pages to break when the mount is missing (and why the test
environment, which has no EFS, cannot serve them).

> **The uid and gid are hardcoded**: group `1111`, user `2222`, in
> `roles/cmweb-account`. On shared EFS the numeric ids must match on every
> instance or permissions break. Do not "clean up" those literals.

### OpenSearch

A VPC domain reached over HTTPS on 443 with basic auth from `secure.py`.
`OPENSEARCH_DSL_AUTOSYNC = False` — the index is **not** updated on save. The
`update_search_index` Jenkins job refreshes it every two hours through
`search.search_signals.CustomSignalProcessor`. Search results being a couple of
hours behind the database is expected behaviour, not a bug.

---

## 6. Ansible builds all of it

One playbook, `ansible/web-servers.yml`, with three plays — prod, stage, test —
running the same eleven roles against different inventories and variable files.
Test omits `efs` and `cronjob`; that is the only structural difference.

```bash
cd ansible
ansible-playbook --vault-password-file ../.vault -c local -i hosts/prod web-servers.yml
```

Role order is not arbitrary:

| # | Role | Responsibility |
| --- | --- | --- |
| 1 | `environment` | `/etc/environment`, needrestart set to `a` (auto, no prompts) |
| 2 | `sonyca` | Sony Root / Intranet / B2B CA certificates |
| 3 | `certificate` | Sony package-repository certificates |
| 4 | `package` | base OS packages, per Ubuntu release (bionic / focal / jammy) |
| 5 | `cmweb-account` | the `cmweb` user (uid 2222), SSH keys, sudo rules |
| 6 | `cmweb-node` | **the application deploy** |
| 7 | `apache-server` | vhost, modules, SSL, static compression, reload |
| 8 | `cloudwatch-agent` | log and metric shipping |
| 9 | `efs` | mounts `/mnt/nfs` (not on test) |
| 10 | `cronjob` | `apache_status_logging.py` every 5 minutes |
| 11 | `c1ws` | Trend Micro workload security agent |

CAs before packages, because the package repo is HTTPS. The account before the
deploy that runs as it. The deploy before Apache, which serves it.

### `cmweb-node` — the deploy itself

1. Raise `nofile` ulimits to 33333 soft / 64000 hard. 240 threads each holding
   database and file handles exhaust the default.
2. `repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -m {{ manifest }}.xml -b cloudj2`
   then `repo sync -c -d`. This is what produces the `site/` + `site/apps/`
   layout Django requires. Prod pins `release.xml`; stage and test float on
   `default.xml`. The `creates:` argument makes the init idempotent.
3. Render `site/cmweb/secure.py` from `templates/django/secure.py.j2`, mode
   `0640`, owner `cmweb`. **This is the only place those credentials touch disk.**
4. Symlink `settings_deployed.py` -> `settings_<env>.py`.
5. Symlink `static/media` -> `/mnt/nfs/media` and `repository` ->
   `/mnt/nfs/cmweb/repo-mirror`.
6. `make static` with `DJANGO_SETTINGS_MODULE=cmweb.settings_deployed`, which
   builds the virtualenv into `ENV/` and compresses assets offline.
7. Inject the three Sony CAs into the virtualenv's `certifi/cacert.pem` with
   `blockinfile`, so `requests` can reach internal HTTPS services.
8. Install logrotate config for `var/log`.

Note what is **absent from the deploy: there is no `migrate`.** Schema changes
run through the separate `migrate_db` Jenkins job. A deploy that ships a
migration is two operations, not one.

### The reload trick

The `apache-server` role distinguishes two handlers, and the trigger is the neat
part:

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

`repo manifest -r` prints the exact revision of every repository. Ansible writes
it to a file and reports *changed* only if the content differs — so the app
reloads **exactly when the deployed code actually moved**, and not otherwise.

"Restart WSGI" does not restart anything:

```yaml
- name: Restart WSGI
  ansible.builtin.command:
    cmd: "touch /srv/www/{{ hostname }}/site/cmweb/wsgi.py"
```

In mod_wsgi daemon mode, changing the script file's mtime makes the daemon
reload the application. Apache itself never restarts, so no requests are
dropped. "Reload Apache" (`service apache2 reloaded`) is the other handler, for
vhost and module changes.

### The vault convention

Secrets live in `encrypted_vars/*.yml`, `ansible-vault`-encrypted. The rule the
repo's own README insists on:

- variables inside the vault are named `vault_*`
- `group_vars/*` maps them: `django_db_password: "{{ vault_django_db_password }}"`
- **roles only ever reference the unprefixed name**

So roles do not need to know what is secret, and you can grep for a variable
name without decrypting anything. `.vault`, `.key` and `.vault_password` are
gitignored; the password is on the internal Confluence page "Service accounts
and passwords".

```bash
ansible-vault edit encrypted_vars/access-prod.yml

# plaintext diffs for vaulted files
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"

export ANSIBLE_VAULT_PASSWORD_FILE=.vault
ansible-lint web-servers.yml        # must pass clean
```

### The deployed filesystem

```
/srv/www/cmweb.ptc.sony.co.jp/
|-- site/                      <- cmweb-project      (python-path)
|   |-- cmweb/
|   |   |-- wsgi.py            <- WSGIScriptAlias target; touch to reload
|   |   |-- secure.py          <- rendered by Ansible, gitignored
|   |   `-- settings_deployed.py -> settings_prod.py   (symlink)
|   `-- apps/                  <- cmweb-app
|-- ENV/                       <- virtualenv          (python-home)
|-- htdocs/static -> ../static <- what Apache serves directly
|-- static/                    <- collectstatic + compressed output
|-- repository -> /mnt/nfs/cmweb/repo-mirror
|-- cache/
|-- var/log/                   <- django.json, wsgi.json
`-- static-manifest-wsgi.xml   <- the reload trigger
```

---

## 7. The write tier

The web servers barely write. Almost everything in the database arrives through
Jenkins jobs defined in `cmweb-scripts/jobs_on_cloud/*.yaml` and executed by
`bin/run_commands.sh`, which builds its own copy of the site:

```
  Jenkins job (e.g. index_labels, hourly 08-20)
     |
     |  1. repo sync the cmweb-manifest into the workspace
     |  2. mount EFS, symlink repository -> $REPO_MIRROR
     |  3. write cmweb/secure.py   -- same endpoints as Ansible, chosen by $JENKINS_URL
     |  4. write cmweb/settings_management.py:
     |         from .settings_prod import *
     |         CELERY_TASK_ALWAYS_EAGER = True
     |  5. make install NO_APT_INSTALL=1
     |  6. for each ';'-separated $COMMANDS:
     |         ./manage.py <cmd> -v3 --traceback
     v
  the same RDS instance the web tier reads
```

So a management command run by Jenkins is not talking to a service — **it is a
second, temporary installation of the whole application, pointed at production
data.** That is why indexing bugs show up as production data problems rather
than as failed HTTP requests.

The scheduled jobs at a glance (Jenkins cron, `H` hashed):

| Job | Schedule | Purpose |
| --- | --- | --- |
| `mirror_gits` | hourly | `repo sync --mirror` of the EFS git mirror |
| `sync_projects_from_gerrit` | hourly | repository list from Gerrit |
| `index_labels`, `index_latest`, `index_pp_apps` | hourly, 08-20 | import builds from C2D |
| `index_delta_labels` | every 30 min | materialise delta builds requested in the UI |
| `update_cherries`, `sync_rebase_records` | hourly | cherry-pick and rebase automation |
| `update_search_index` | every 2 h | OpenSearch reindex |
| `index_labels_more`, `sync_commits_more`, `detect_branchpoints` | nightly | deeper backfill |
| `clean_old_entries_in_db`, `sync_projects_from_git` | nightly ~04 | housekeeping |
| `disable_indexing_jobs` | 20:00 daily | the indexers stand down overnight |
| `migrate_db` | manual | **the only thing that runs migrations** |

`disable_indexing_jobs` at 20:00 is why the hourly indexers are scoped to
`H 8-20`.

> **The endpoints are written down twice.** `ansible/group_vars/<env>` and
> `bin/run_commands.sh` (plus `jobs_on_cloud/macros.yaml`) each carry their own
> copy of the RDS, cache and OpenSearch host names, selected by account id in
> one and by `$JENKINS_URL` in the other. Changing an endpoint means editing
> both. Nothing enforces that they agree.

### Where Celery actually is

`cmweb/celery.py` exists, `@shared_task` modules exist per app, and
`django_celery_results` is in `INSTALLED_APPS`. But:

- `CELERY_TASK_ALWAYS_EAGER = True` is set in base `settings.py` and is **not
  overridden** in `settings_prod.py`, `settings_stage.py` or `settings_test.py`;
- no broker URL is configured anywhere in `cmweb-project`, `cmweb-app` or
  `secure.py.j2`;
- no Ansible role installs, configures or starts a worker process;
- `run_commands.sh` re-asserts `CELERY_TASK_ALWAYS_EAGER = True` for Jenkins.

**As deployed, there is no Celery worker and no queue.** Every `.delay()` runs
inline and synchronously, inside the Apache worker thread that is serving the
request or the management command that called it. Treat the task modules as
structured helpers, not as background work — a slow task is a slow page. This
contradicts the older description of an SQS broker; if a broker is ever
reintroduced it will need a `CELERY_BROKER_URL`, an override of
`CELERY_TASK_ALWAYS_EAGER`, and a worker service in the Ansible roles.

---

## 8. Operating it

### Where the logs are

| Log | Path | Shipped to CloudWatch as |
| --- | --- | --- |
| Apache access | `/var/log/apache2/<host>_access.log` | `cmweb/apache/accesslog` |
| Apache error | `/var/log/apache2/<host>_error.log` | not shipped |
| Django under WSGI | `<site>/var/log/wsgi.json` | `cmweb/apache/wsgi` |
| Management commands | `<site>/var/log/django.json` | not shipped |
| `server-status` samples | `/srv/cron/logs/apache_status.log` | `cmweb/apache/server-status` |

`settings_wsgi.py` sets `IS_WSGI = True` purely so the logging config can split
`wsgi.json` from `django.json`. The CloudWatch agent also collects collectd
metrics, memory and disk usage at 60-second intervals, dimensioned by instance
id, and `apache_status_logging.py` samples `BusyWorkers` / `IdleWorkers` /
scoreboard state every five minutes — that is the signal to watch for
saturation of the 240 slots.

The access log has one subtlety:

```apache
SetEnvIf X-Forwarded-For "^.*\..*\..*\..*" forwarded
CustomLog ... env=!forwarded
```

**Proxied requests are deliberately not logged locally.** If requests are
missing from the access log, check whether they arrived with an
`X-Forwarded-For` header before assuming they never reached the server.

### Troubleshooting by symptom

| Symptom | Look at |
| --- | --- |
| 500 with a Paste traceback | the traceback itself — it is detailed; also `<host>_error.log` |
| Code change not appearing | was `wsgi.py` touched? did the 10-minute page cache serve a stale copy? |
| New CSS/JS not loading | `make static` not run; or `X-PJAX-Version` unchanged so clients kept old assets |
| Login loops | LDAP bind credentials in `secure.py`, or a `users-serviceusername` `Parameter` overriding them |
| Everyone logged out at once | the memcached cluster was flushed or replaced — sessions live there |
| A public endpoint 401s | missing `Require all granted` — Apache rejects before Django sees it |
| A public endpoint redirects to `/access-denied` | Apache is fine; `NO_AUTH_URLS` is missing the pattern |
| `ImportError` at startup | `python-path` wrong, or `apps/` missing under `site/` |
| `NameError: OPENSEARCH_HOST` | `secure.py` is missing or was not rendered |
| Commit diffs / file browsing 500 | the EFS mount or the `repository` symlink is gone |
| Search results stale | expected — `update_search_index` runs every 2 hours |
| A new branch never appears | no `IncludedBranchRule` matches it; nothing is indexed without one |
| Slow under load | 240 slots; check `maximum-requests` recycling and RDS connection count |

### Making a change safely

```
application code   -> Gerrit review -> verify_cmweb_changes (make clean kwalitee test)
                   -> repo manifest pin -> Ansible/AMI rebuild -> touch wsgi.py
schema change      -> the same, plus the migrate_db Jenkins job
infrastructure     -> Gerrit review -> verify_ansible_playbook -> test, then stage, then prod
Jenkins job change -> Gerrit review -> verify_jenkins_jobs -> deploy_jenkins_jobs
```

Checklist for a `cmweb-scripts` change:

```
[ ] ansible-lint passes clean
[ ] new secrets are vault_-prefixed and mapped through group_vars
[ ] file/template changes notify the right handler
[ ] tasks are idempotent (creates:, state:, changed_when:)
[ ] endpoint changes applied to bin/run_commands.sh and macros.yaml too
[ ] tested on test before stage before prod
```

---

## 9. Sharp edges

Verified in the source, in rough order of how much time they cost.

1. **`cmweb-app` must sit at `cmweb-project/apps/`.** `python-path` plus the
   `sys.path.append` in `settings.py` is what makes apps importable by bare
   name. Nothing works without it.
2. **A public endpoint needs three edits** — URLconf, `NO_AUTH_URLS`, and an
   Apache `Require all granted` block.
3. **`PermissionCheckMiddleware` trusts the HTTP Basic username without checking
   the password.** Safe only because Apache authenticated first.
4. **The deploy does not run migrations.** `migrate_db` is a separate Jenkins
   job. Shipping a migration is two operations.
5. **Flushing memcached logs every user out**, because `SESSION_ENGINE` is the
   cache backend.
6. **Endpoints are duplicated** between `ansible/group_vars/<env>` and
   `bin/run_commands.sh` / `jobs_on_cloud/macros.yaml`, with nothing enforcing
   agreement.
7. **The certifi CA injection edits a file inside an installed package.**
   Reinstalling or upgrading `certifi` silently undoes it, and internal HTTPS
   calls start failing. Note this is separate from the *system* bundle at
   `/etc/ssl/certs/ca-certificates.crt` that `GerritRESTClientMixin` hardcodes —
   two bundles, both needed, used by different code.
8. **The Apache ulimit patch is a regex edit of `/usr/sbin/apache2ctl`.** An
   `apache2` package upgrade can silently revert it, and "Too many open files"
   returns.
9. **The `Restart WSGI` handler has `changed_when: result.rc == 0` but never
   registers `result`** — it reads whatever was last registered, which in this
   play is the `Update CA crt` task. Its reported status is meaningless today
   and will break confusingly if the roles are reordered.
10. **The TLS private key is written mode `0644`** by
    `roles/apache-server/tasks/main.yml` ("Put SSL Certificate Key File"), so it
    is world-readable on the instance. `0600` would be the expected mode.
11. **Paste's `ErrorMiddleware` runs with `debug: True` in production**,
    independent of Django's `DEBUG = False`. Unhandled exceptions render full
    tracebacks to whoever triggered them.
12. **`CONN_MAX_AGE` is unset**, so all 240 request slots open and close a
    PostgreSQL connection per request.
13. **There is no Celery worker.** See section 7 — every task runs inline.

---

## Related documents

- [architecture.md](architecture.md) — the domain model and the indexing pipeline
- [internals.md](internals.md) — eight deep-dive guides, no Django assumed
- [infrastructure.md](infrastructure.md) — `cmweb-scripts` in full, job by job
- [development.md](development.md) — setup, build, test, lint, review flow
- [../local-cmweb/README.md](../local-cmweb/README.md) — running it on your machine
