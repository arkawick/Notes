"""Request the main CMWEB pages and report what works locally.

Uses Django's test client against the real local database, so it exercises the
same view/template/ORM path the browser would, without needing a running
server.

    .venv\\Scripts\\python.exe scripts\\smoke_test.py
"""

import os
import sys
import traceback

# Do not litter the source repositories with __pycache__ directories.
sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_local')

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
    ('/admin/', 'django admin'),
    ('/api/', 'browsable API'),
    ('/api/builds/?format=json', 'API: builds'),
    ('/api/commits/?format=json', 'API: commits'),
]


def first_build_urls():
    """Return detail URLs for a build from the sample data, if any."""
    from django.apps import apps
    Label = apps.get_model('explorer', 'label')
    label = Label.objects.exclude(status='DELTA').first()
    if label is None:
        return []
    try:
        base = label.get_absolute_url().rstrip('/')
    except Exception:
        return []
    return [
        (base, 'build detail ({})'.format(label.name)),
        (base + '/+commits', 'build commits'),
        (base + '/+repositories', 'build repositories'),
        (base + '/+issues', 'build issues'),
    ]


def main():
    """Fetch every page and print a status line for each."""
    client = Client()
    pages = PAGES + first_build_urls()
    width = max(len(url) for url, _ in pages) + 2
    ok = warn = bad = 0

    print('{:<{w}} {:<6} {}'.format('URL', 'STATUS', 'PAGE', w=width))
    print('-' * (width + 40))
    for url, label in pages:
        try:
            response = client.get(url, follow=True)
            code = response.status_code
        except Exception as exc:
            print('{:<{w}} {:<6} {} -- {}: {}'.format(
                url, 'ERROR', label, type(exc).__name__, exc, w=width))
            if os.environ.get('SMOKE_TRACEBACK'):
                traceback.print_exc()
            bad += 1
            continue
        if code == 200:
            ok += 1
        elif code in (301, 302, 404):
            warn += 1
        else:
            bad += 1
        print('{:<{w}} {:<6} {}'.format(url, code, label, w=width))

    print('\n{} ok, {} redirect/not-found, {} failing'.format(ok, warn, bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
