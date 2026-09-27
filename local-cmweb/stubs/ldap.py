"""Shim for ``python-ldap``.

python-ldap needs a C toolchain and OpenLDAP headers, which Windows does not
have by default. Local CMWEB authenticates against the local Django user table
instead, so nothing here is ever reached -- but `users/auth.py` imports the
module at module level, so it has to exist.
"""

from _shim import ShimNotAvailable

# Constants referenced by django_auth_ldap and application code.
SCOPE_BASE = 0
SCOPE_ONELEVEL = 1
SCOPE_SUBTREE = 2
OPT_REFERRALS = 8
OPT_PROTOCOL_VERSION = 17
OPT_X_TLS_REQUIRE_CERT = 24582
OPT_X_TLS_NEVER = 0
OPT_X_TLS_DEMAND = 2
VERSION3 = 3


class LDAPError(Exception):
    """Base LDAP error."""


class SERVER_DOWN(LDAPError):  # noqa: N801  (matches python-ldap naming)
    """Raised when the directory server cannot be reached."""


class INVALID_CREDENTIALS(LDAPError):  # noqa: N801
    """Raised when a bind is rejected."""


class NO_SUCH_OBJECT(LDAPError):  # noqa: N801
    """Raised when a DN does not exist."""


class TIMEOUT(LDAPError):  # noqa: N801
    """Raised when an operation times out."""


def initialize(*_args, **_kwargs):
    """Raise -- there is no directory server to talk to locally."""
    raise ShimNotAvailable('python-ldap', 'ldap.initialize()')


def set_option(*_args, **_kwargs):
    """Accept and ignore global option setting."""
    return None
