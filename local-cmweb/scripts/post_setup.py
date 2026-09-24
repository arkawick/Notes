"""Finish setting up the local database after migrate + loaddata.

The sample fixture contains build metadata but not the handful of rows that make
the site navigable, because those are environment-specific:

* the ``home`` generic page -- ``/`` is the catch-all generic_pages view, so
  without it the front page is a 404
* the ``Site`` row -- feeds and absolute URLs are built from it
* a local superuser -- the site is gated on the ``users.view_all_pages``
  permission, which nobody has on a fresh database

Run with:  .venv\\Scripts\\python.exe scripts\\post_setup.py
"""

import os
import sys

# Do not litter the source repositories with __pycache__ directories.
sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_local')

import django  # noqa: E402
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Permission  # noqa: E402
from django.contrib.sites.models import Site  # noqa: E402
from django.utils import timezone  # noqa: E402

USERNAME = os.environ.get('CMWEB_LOCAL_USER', 'local')
PASSWORD = os.environ.get('CMWEB_LOCAL_PASSWORD', 'local')


def ensure_site():
    """Point the default Site row at the local dev server."""
    site, _created = Site.objects.get_or_create(pk=1)
    site.domain = 'localhost:8000'
    site.name = 'CMWEB Local'
    site.save()
    print('  site           : {}'.format(site.domain))


def ensure_home_page():
    """Create the generic page that serves '/'."""
    from generic_pages.models import GenericPage
    page, created = GenericPage.objects.get_or_create(
        slug='home',
        defaults={
            'title': 'Home',
            'status': 2,
            'publish': timezone.now(),
            'body': (
                'Local CMWEB instance running against the sample dataset '
                'from `explorer/fixtures/testdata.json`.\n\n'
                'Try **Browse -> explorer.Label** for indexed builds, or '
                '**explorer.Commit** for commits.'
            ),
        },
    )
    print('  home page      : {}'.format('created' if created else 'present'))
    return page


def ensure_user():
    """Create the local superuser the auto-login middleware signs in as."""
    model = get_user_model()
    user, created = model.objects.get_or_create(
        username=USERNAME,
        defaults={
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
            'first_name': 'Local',
            'last_name': 'Developer',
            'email': 'local@local.invalid',
        },
    )
    user.is_staff = True
    user.is_superuser = True
    user.set_password(PASSWORD)
    user.save()
    # Explicitly grant the permission the real middleware gates the site on,
    # so browsing still works if auto-login is turned off.
    try:
        perm = Permission.objects.get(codename='view_all_pages')
        user.user_permissions.add(perm)
    except Permission.DoesNotExist:
        print('  ! users.view_all_pages permission not found')
    print('  superuser      : {} / {}'.format(USERNAME, PASSWORD))
    return user


def report():
    """Print a short summary of what the sample data contains."""
    from django.apps import apps
    interesting = [
        ('explorer', 'label', 'builds'),
        ('explorer', 'commit', 'commits'),
        ('explorer', 'project', 'repositories'),
        ('explorer', 'manifestbranch', 'manifest branches'),
        ('issues', 'issue', 'issues'),
        ('packages', 'packagerevision', 'package revisions'),
        ('users', 'profile', 'user profiles'),
    ]
    print('\nSample data loaded:')
    for app_label, model_name, label in interesting:
        try:
            model = apps.get_model(app_label, model_name)
            print('  {:<18} {}'.format(label, model.objects.count()))
        except Exception as exc:  # pragma: no cover - diagnostic only
            print('  {:<18} ? ({})'.format(label, exc))


def main():
    """Run every post-setup step."""
    print('Finishing local setup:')
    ensure_site()
    ensure_home_page()
    ensure_user()
    report()
    print('\nStart the server with:  .\\run.ps1')


if __name__ == '__main__':
    main()
