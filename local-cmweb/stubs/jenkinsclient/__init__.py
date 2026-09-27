"""Shim for the internal ``jenkinsclient`` package."""

from _shim import ShimObject


class JenkinsError(Exception):
    """Raised for any Jenkins API failure."""


class JenkinsBuild(ShimObject):
    """Stand-in for a Jenkins build."""

    _shim_package = 'jenkinsclient'


class JenkinsJob(ShimObject):
    """Stand-in for a Jenkins job."""

    _shim_package = 'jenkinsclient'
