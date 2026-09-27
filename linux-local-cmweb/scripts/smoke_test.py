"""Request the main CMWEB pages and report what works locally.

Uses Django's test client against the real local database, so it exercises the
same view/template/ORM path a browser would without needing a running server.

    ENV/bin/python3 scripts/smoke_test.py

Set SMOKE_TRACEBACK=1 for full tracebacks on failures.

Note: the test client bypasses WSGI_APPLICATION entirely, so a green run here
does not prove ``./run.sh`` works. Check both.
"""

import os
import sys
import traceback

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SITE = os.path.join(BASE, 'site')

sys.path.insert(0, SITE)
sys.path.append(os.path.join(BASE, 'stubs'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cmweb.settings')

import django  # noqa: E402
django.setup()

from django.test import Client  # noqa: E402

PAGES = [
    ('/', 'home page'),
    ('/builds/', 'build list'),
    ('/commits/', 'commit list'),
    ('/repositories/', 'repository list'),
    ('/branches/', 'manifest branches'),
    ('/issues/', 'issue list'),
    ('/packages/', 'package list'),
    ('/news/', 'blog'),
    ('/request/branches/', 'branch requests'),
    ('/harvest/', 'harvest index'),
    ('/historian/', 'historian index'),
    ('/vendors/', 'vendor releases'),
    ('/accounts/login/', 'login form'),
    ('/admin/', 'django admin'),
    ('/api/', 'browsable API'),
    ('/api/builds/?format=json', 'API: builds'),
    ('/api/commits/?format=json', 'API: commits'),
]


def build_urls():
    """Return detail URLs for a build from the sample data, if any."""
    from django.apps import apps
    label = apps.get_model('explorer', 'label').objects.exclude(
        status='DELTA').first()
    if label is None or label.manifest_branch is None:
        return []
    branch = label.manifest_branch
    base = '/branches/{}/{}'.format(branch.project.name, branch.name)
    return [
        (base, 'build detail ({})'.format(branch.name)),
        (base + '/+commits', 'build commits'),
        (base + '/+repositories', 'build repositories'),
        (base + '/+issues', 'build issues'),
    ]


def main():
    """Request every page and print a status line each."""
    from django.contrib.auth import get_user_model
    client = Client()
    user = get_user_model().objects.filter(username='local').first()
    if user is not None:
        client.force_login(user)
    else:
        print('! no "local" user -- run scripts/post_setup.py\n')

    pages = PAGES + build_urls()
    width = max(len(url) for url, _ in pages) + 2

    print('{:<{w}}{:<7}{}'.format('URL', 'STATUS', 'PAGE', w=width))
    print('-' * (width + 40))

    ok = other = failed = 0
    for url, name in pages:
        try:
            status = client.get(url).status_code
        except Exception as exc:
            failed += 1
            print('{:<{w}}{:<7}{}  <-- {}'.format(
                url, 'ERR', name, exc.__class__.__name__, w=width))
            if os.environ.get('SMOKE_TRACEBACK'):
                traceback.print_exc()
            continue
        if status == 200:
            ok += 1
        else:
            other += 1
        print('{:<{w}}{:<7}{}'.format(url, status, name, w=width))

    print('\n{} ok, {} redirect/not-found, {} failing'.format(
        ok, other, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
