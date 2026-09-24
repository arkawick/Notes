"""Shim for ``django_auth_ldap.config``."""


class LDAPSearch(object):
    """Stand-in for an LDAP search specification."""

    def __init__(self, base_dn=None, scope=None, filterstr=None, **kwargs):
        """Store the search parameters."""
        self.base_dn = base_dn
        self.scope = scope
        self.filterstr = filterstr
        self.kwargs = kwargs


class LDAPSearchUnion(object):
    """Stand-in for a union of LDAP searches."""

    def __init__(self, *searches, **kwargs):
        """Store the component searches."""
        self.searches = searches
        self.kwargs = kwargs


class LDAPGroupType(object):
    """Base stand-in for group type handlers."""

    def __init__(self, name_attr='cn', **kwargs):
        """Store the naming attribute."""
        self.name_attr = name_attr
        self.kwargs = kwargs


class NestedActiveDirectoryGroupType(LDAPGroupType):
    """Stand-in for the nested Active Directory group type."""


class ActiveDirectoryGroupType(LDAPGroupType):
    """Stand-in for the flat Active Directory group type."""


class GroupOfNamesType(LDAPGroupType):
    """Stand-in for the groupOfNames group type."""
