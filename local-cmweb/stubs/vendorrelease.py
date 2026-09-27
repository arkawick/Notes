"""Shim for the internal ``vendorrelease`` package."""

from _shim import ShimObject


class CAFRelease(ShimObject):
    """Stand-in for a CAF/vendor release descriptor."""

    _shim_package = 'vendorrelease'
