"""Shim for ``dmsclient.dmsodbc`` (the legacy DMS issue database over ODBC)."""

from _shim import ShimObject


class DMSODBCError(Exception):
    """Raised for any DMS ODBC failure."""


class DMSODBC(ShimObject):
    """Stand-in for the DMS ODBC client."""

    _shim_package = 'somc-dmsclient'
