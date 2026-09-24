"""Shim for ``django_auth_ldap.backend``.

`LDAPBackend` is present so `users.auth.AuthLDAPBackend` can subclass it, but it
never authenticates anyone locally -- `authenticate()` returns None so Django
falls through to `ModelBackend` and the local user table.
"""

import logging

logger = logging.getLogger(__name__)


class _Settings(object):
    """Minimal stand-in for django_auth_ldap's settings object."""

    def __init__(self, defaults=None):
        """Seed the settings from a defaults mapping."""
        self.BIND_DN = ''
        self.BIND_PASSWORD = ''
        for key, value in (defaults or {}).items():
            setattr(self, key, value)

    def __getattr__(self, name):
        """Return None for any setting that was not supplied."""
        return None


class LDAPBackend(object):
    """Stand-in for the django-auth-ldap authentication backend."""

    settings_prefix = 'AUTH_LDAP_'
    default_settings = {}

    def __init__(self, *args, **kwargs):
        """Build the settings object the real backend exposes."""
        self.settings = _Settings(getattr(self, 'default_settings', {}))

    def authenticate(self, request=None, username=None, password=None,
                     **kwargs):
        """Return None -- local login goes through Django's ModelBackend."""
        logger.debug('LDAP shim: declining authentication for %r', username)
        return None

    def get_user(self, user_id):
        """Return None -- user loading is handled by ModelBackend."""
        return None

    def populate_user(self, username):
        """Return None -- there is no directory to populate from."""
        return None

    def get_or_build_user(self, username, ldap_user=None):
        """Return None -- there is no directory to build from."""
        return None


class LDAPBackendException(Exception):
    """Raised for backend configuration errors."""


def populate_user(*_args, **_kwargs):
    """No-op stand-in for the populate_user signal helper."""
    return None
