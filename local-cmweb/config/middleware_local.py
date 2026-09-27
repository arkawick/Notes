"""Local replacement for ``cmweb.middleware.PermissionCheckMiddleware``.

In production every request reaches Django already authenticated: Apache
performs LDAP basic auth and ``RemoteUserMiddleware`` turns that into a Django
user, then `PermissionCheckMiddleware` checks the ``users.view_all_pages``
permission and redirects anyone without it.

There is no Apache locally, so this middleware reproduces the *assumption* that
requests arrive authenticated: it signs every request in as a local superuser.
Without it the site is unbrowsable, because almost every view is behind that
permission check.

Set ``CMWEB_LOCAL_AUTOLOGIN=0`` in the environment to turn this off and browse
anonymously (most pages will then redirect to the branch-request list, exactly
as production does for an unprivileged user).
"""

import os

from django.contrib.auth import get_user_model, login

LOCAL_USER = os.environ.get('CMWEB_LOCAL_USER', 'local')
AUTOLOGIN = os.environ.get('CMWEB_LOCAL_AUTOLOGIN', '1') != '0'
BACKEND = 'django.contrib.auth.backends.ModelBackend'


class LocalPermissionMiddleware(object):
    """Sign every request in as a local superuser."""

    def __init__(self, get_response):
        """Store the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Authenticate the request, then hand off down the chain."""
        if AUTOLOGIN and not request.user.is_authenticated:
            user = self._local_user()
            if user is not None:
                login(request, user, backend=BACKEND)
        return self.get_response(request)

    @staticmethod
    def _local_user():
        """Return (creating if needed) the local superuser."""
        model = get_user_model()
        try:
            user, created = model.objects.get_or_create(
                username=LOCAL_USER,
                defaults={
                    'is_staff': True,
                    'is_superuser': True,
                    'is_active': True,
                    'first_name': 'Local',
                    'last_name': 'Developer',
                    'email': 'local@local.invalid',
                },
            )
            if created:
                user.set_unusable_password()
                user.save()
            if not (user.is_staff and user.is_superuser):
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=['is_staff', 'is_superuser'])
            return user
        except Exception:
            # Before migrate has run there is no auth_user table yet.
            return None
