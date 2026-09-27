"""Shim for the internal ``c2dclient`` package (the C2D build-system REST API)."""

from _shim import ShimObject

C2D_GLOBAL = 'global'
C2D_REST_SITES = {
    'global': 'https://c2d.local.invalid/',
}

XB_SEMC_MANIFEST_BRANCH = 'semc.manifest.branch'


class C2DError(Exception):
    """Raised for any C2D API failure."""


class C2DRESTAPI(ShimObject):
    """Stand-in for the C2D REST client."""

    _shim_package = 'c2dclient'
