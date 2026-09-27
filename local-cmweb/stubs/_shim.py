"""Shared helpers for the local-only shim packages.

Every module in ``local-cmweb/stubs`` stands in for a Sony-internal package that
is not published on public PyPI. The shims exist so the application can be
imported and browsed against sample data on a machine with no access to the
internal package index.

They deliberately do **not** reimplement the real behaviour. Anything that would
need to reach Gerrit, C2D, JIRA, Jenkins, M+ or DMS raises `ShimNotAvailable`
with a message naming the real package, so a failure is never mistaken for a bug
in CMWEB itself.
"""


class ShimNotAvailable(NotImplementedError):
    """Raised when code reaches a shim that has no local implementation."""

    def __init__(self, package, detail=""):
        """Build a message naming the real package that would be required."""
        message = (
            "'{}' is a Sony-internal package with no public release, so "
            "local-cmweb ships a shim instead. The code path you just hit "
            "needs the real implementation.".format(package)
        )
        if detail:
            message = "{} ({})".format(message, detail)
        super(ShimNotAvailable, self).__init__(message)


def unavailable(package, detail=""):
    """Return a function that raises `ShimNotAvailable` when called."""
    def _raise(*_args, **_kwargs):
        raise ShimNotAvailable(package, detail)
    return _raise


# Names that must never be answered by a catch-all __getattr__.
#
# Django and the standard library probe objects with hasattr() for protocol
# hooks. A __getattr__ that returns a callable for *any* name makes every such
# probe succeed, and the caller then invokes something that raises.
#
# This bit us for real: request/models.py builds an MPlusAPI instance inside the
# body of the RepositoryRequest model class (to populate FUNCTIONAL_AREAS), so
# the instance ends up as a class attribute. Django's ModelBase.add_to_class
# then checks hasattr(value, 'contribute_to_class') -- which a naive shim
# answers yes to, breaking model construction at import time.
_PROTOCOL_NAMES = frozenset((
    'contribute_to_class',
    'deconstruct',
    'get_absolute_url',
    'resolve_expression',
    'as_sql',
    'prepare_database_save',
    '__iter__',
    '__len__',
    '__getitem__',
    '__call__',
    '__deepcopy__',
    '__copy__',
    '__reduce__',
    '__reduce_ex__',
    '__getstate__',
    '__setstate__',
))


class ShimObject(object):
    """Base for shim clients whose every real method needs a live service.

    Construction always succeeds -- application code frequently builds a client
    outside the try/except that guards the actual request. Calling a method
    raises `ShimNotAvailable`.

    Unknown *protocol* names raise `AttributeError` instead, so `hasattr()`
    probes answer False and callers take their normal "object does not support
    this" path.
    """

    _shim_package = 'unknown'

    def __init__(self, *args, **kwargs):
        """Accept and record whatever the real client takes."""
        self._args = args
        self._kwargs = kwargs

    def __getattr__(self, name):
        """Return a raising callable, or refuse protocol probes."""
        if name.startswith('_') or name in _PROTOCOL_NAMES:
            raise AttributeError(name)
        package = type(self)._shim_package
        detail = '{}.{}()'.format(type(self).__name__, name)

        def _call(*_args, **_kwargs):
            raise ShimNotAvailable(package, detail)
        return _call

    def __repr__(self):
        """Return a debug representation naming the shimmed package."""
        return '<{} shim for {}>'.format(type(self).__name__,
                                         type(self)._shim_package)
