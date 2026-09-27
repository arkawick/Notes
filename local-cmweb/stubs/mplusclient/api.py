"""Shim for ``mplusclient.api`` (the internal M+ product-data service)."""

from _shim import ShimObject


class MPlusAPIError(Exception):
    """Raised for any M+ API failure."""


class MPlusAPI(ShimObject):
    """Stand-in for the M+ client.

    `request.models.RepositoryRequest` constructs one of these *in its class
    body* to populate ``FUNCTIONAL_AREAS``, so the instance survives as a model
    class attribute -- see the protocol-probe handling in `_shim.ShimObject`.
    """

    _shim_package = 'mplusclient'
