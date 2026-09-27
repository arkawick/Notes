"""Create the rows the fixture deliberately does not contain.

``testdata.json`` holds build metadata, not environment configuration, so a
freshly loaded database is still not browsable. Three things are missing:

* **The Site row.** CMWEB uses the Django sites framework, and ``settings.py``
  defines no ``SITE_ID`` -- only ``FEED_SITE_ID = 1``. Without ``SITE_ID``,
  ``Site.objects.get_current(request)`` resolves the site by matching the
  request's ``Host`` header against ``Site.domain``. That is why the upstream
  Quick Guide tells you to create a Site whose domain is exactly
  ``localhost:8000``: browse on a different host or port and it will not match.
  This script sets *and* points ``pk=1`` at that domain, so the host lookup and
  ``FEED_SITE_ID`` both resolve.

* **The home page.** ``/`` is served by the catch-all generic_pages view, so
  without a page at slug ``home`` the front page is a 404.

* **A user who can see anything.** ``PermissionCheckMiddleware`` gates the site
  on ``users.view_all_pages``. The fixture's ``admin`` user (password
  ``s3cr17``) is a superuser, but the fixture was dumped with
  ``--exclude auth.permission``, so its permission rows are not guaranteed to
  survive a fresh ``migrate``. Both ``admin`` and a ``local`` account are
  granted the permission explicitly here.

    ENV/bin/python3 scripts/post_setup.py [host:port]
"""

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SITE = os.path.join(BASE, 'site')

sys.path.insert(0, SITE)
sys.path.append(os.path.join(BASE, 'stubs'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cmweb.settings')

import django  # noqa: E402
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Permission  # noqa: E402
from django.contrib.sites.models import Site  # noqa: E402
from django.utils import timezone  # noqa: E402

USERNAME = os.environ.get('CMWEB_LOCAL_USER', 'local')
PASSWORD = os.environ.get('CMWEB_LOCAL_PASSWORD', 'local')


def ensure_site(domain):
    """Point the default Site row at the local dev server."""
    site, _created = Site.objects.get_or_create(pk=1)
    site.domain = domain
    site.name = 'CMWEB Local'
    site.save()
    print('  site            : {}'.format(site.domain))


def ensure_home_page():
    """Create the generic page that serves '/'."""
    from generic_pages.models import GenericPage
    _page, created = GenericPage.objects.get_or_create(
        slug='home',
        defaults={
            'title': 'Home',
            'status': 2,
            'publish': timezone.now(),
            'body': (
                'Local CMWEB instance (Linux) running against the sample '
                'dataset from `explorer/fixtures/testdata.json`.\n\n'
                'Try **/builds/** for indexed builds, or **/commits/**.'
            ),
        },
    )
    print('  home page       : {}'.format('created' if created else 'present'))


def grant_view_all_pages(user):
    """Give a user the permission the whole site is gated on."""
    try:
        user.user_permissions.add(
            Permission.objects.get(codename='view_all_pages'))
        return True
    except Permission.DoesNotExist:
        return False


def ensure_users():
    """Create the local account and re-grant the fixture admin's permission."""
    model = get_user_model()

    user, _created = model.objects.get_or_create(
        username=USERNAME,
        defaults={
            'first_name': 'Local',
            'last_name': 'Developer',
            'email': 'local@local.invalid',
        },
    )
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.set_password(PASSWORD)
    user.save()
    ok = grant_view_all_pages(user)
    print('  superuser       : {} / {}'.format(USERNAME, PASSWORD))

    admin = model.objects.filter(username='admin').first()
    if admin is not None:
        grant_view_all_pages(admin)
        print('  fixture admin   : admin / s3cr17')
    else:
        print('  fixture admin   : not present (was the fixture loaded?)')

    if not ok:
        print('  ! users.view_all_pages not found -- run migrate first')


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
    domain = sys.argv[1] if len(sys.argv) > 1 else 'localhost:8000'
    print('Finishing local setup:')
    ensure_site(domain)
    ensure_home_page()
    ensure_users()
    report()


if __name__ == '__main__':
    main()
