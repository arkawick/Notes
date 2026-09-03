# CMWEB

CMWEB is Sony Mobile's internal **Configuration Management** web application. It indexes Android
platform build metadata out of Gerrit, git and repo manifests — repositories, manifest branches, builds
("labels"), commits and issues — and layers release-engineering workflow on top of it: branch and
repository requests, automated cherry-picking, rebase tracking, vendor release synchronisation and
per-user dashboards.

| Environment | URL |
| --- | --- |
| Production | `https://cmweb.ptc.sony.co.jp/` |
| Stage | `https://cmweb.ptc-stage.sony.co.jp/` |
| Test | `https://cmweb.ptc-test.sony.co.jp/` |

## The three repositories

This working tree holds three separate git repositories, stitched together by the `repo` tool from the
`cmweb-manifest` project. Two of them are the Django application; the third is the infrastructure that
builds, deploys and drives it.

```
                    ┌──────────────────── the Django application ────────────────────┐

  cmweb-project/                        cmweb-app/                     cmweb-scripts/
  ├── cmweb/          settings,         ├── base/        shared        ├── ansible/      server config
  │                   URLconf, WSGI,    ├── explorer/    core domain   ├── jobs_on_cloud/ Jenkins jobs
  │                   Celery, middleware├── issues/                    ├── cloudformation/ AWS stacks
  ├── templates/      site-wide         ├── request/     workflow      ├── agent/        Jenkins AMI
  ├── static/         CSS/JS/vendor     ├── harvest/     cherry-picks  ├── bin/          git mirroring
  ├── manage.py                         ├── rebase/                    └── etc/          mirror rules
  └── Makefile        build/test/lint   └── … 20+ apps
```

**`cmweb-project` and `cmweb-app` are one application.** `cmweb-project` is the Django *project*
(configuration and entry points) and `cmweb-app` holds every Django *app* (all the models, views and
business logic). Neither runs without the other — `cmweb-project/cmweb/settings.py` appends
`<project>/apps` to `sys.path`, so **`cmweb-app` must be checked out at `cmweb-project/apps/`** (it is
listed in `cmweb-project/.gitignore` for exactly this reason). The split exists so the two can be
reviewed and released independently, not because they are independent components.

**`cmweb-scripts` is a different kind of repository.** It contains no application code. It is the
Ansible, CloudFormation and Jenkins Job Builder definitions that provision the AWS servers, deploy the
application, mirror the git repositories the indexer reads, and run the ~50 scheduled jobs that keep the
database populated. It has its own release cycle and its own review branch.

On a deployed host the manifest assembles them like this:

```
/srv/www/cmweb.ptc.sony.co.jp/
├── site/            ← cmweb-project      (PATH_SITE)
│   ├── cmweb/         settings, secure.py, settings_deployed.py → settings_prod.py
│   └── apps/        ← cmweb-app          (APPS_DIR, on sys.path)
├── ENV/               virtualenv
├── static/            collectstatic + compressed output
├── repository/      → /mnt/nfs/cmweb/repo-mirror   bare git mirrors read by the indexer
├── cache/             label metadata cache
└── var/log/           application logs
```

Everything in `settings.py` is derived from that layout: `PATH_PROJECT` → `site/cmweb`, `PATH_SITE` →
`site`, `PATH_ROOT` → the deployment root, and `PATH_REPOSITORY` → the NFS git mirror.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/how-the-site-works.md](docs/how-the-site-works.md) | **End to end** — one request from browser to PostgreSQL, and how EC2, Apache, Django, RDS and Ansible fit together |
| [docs/architecture.md](docs/architecture.md) | The domain model, how indexing works, the app catalogue, request/response mechanics |
| [docs/development.md](docs/development.md) | Local setup, build/test/lint commands, code conventions, the Gerrit review flow |
| [docs/internals.md](docs/internals.md) | **Start here if you are new to Django** — index to eight deep-dive guides: apps, management commands, views, middleware, Celery, migrations, Apache, Ansible |
| [docs/infrastructure.md](docs/infrastructure.md) | `cmweb-scripts`: AWS topology, Ansible deployment, Jenkins jobs, git mirroring |
| [local-cmweb/README.md](local-cmweb/README.md) | Running the app on a local machine against the sample dataset |

`cmweb-project/README.rst` is the original upstream setup guide. Its content has been folded into
[docs/development.md](docs/development.md), corrected where it had gone stale, and it is now redundant.

## Stack at a glance

- **Django 5.2** on Ubuntu 22.04 / Python 3.10 (Django 4.2 on the Ubuntu 20.04 build)
- **PostgreSQL** (Amazon RDS) in every deployed environment; SQLite for a throwaway local database
- **memcached** (Amazon ElastiCache) for the cache and the session store
- **Celery** with an SQS broker and `django-celery-results`; eager/in-process during development
- **OpenSearch** (Amazon OpenSearch Service) for full-text search via `django-opensearch-dsl`
- **Apache + mod_wsgi**, with LDAP basic auth in front of Django's own LDAP backends
- **dulwich** for reading bare git repositories, **pygerrit2** for the Gerrit REST API
- **Bootstrap 3**, PJAX, d3/c3 charts; assets compressed offline by `django-compressor`

## Getting started

```bash
# Get all repositories in the right layout
repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest -b cloudj2
repo sync

cd site
make install      # virtualenv, apt packages, pip requirements
make db           # migrate
make static       # collectstatic + compress
./manage.py runserver 0:8000
```

See [docs/development.md](docs/development.md) for the details, including the mandatory `cmweb/secure.py`
file and how to get indexed data into a fresh database.
