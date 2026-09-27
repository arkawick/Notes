"""Shim for ``jiraapi.rest``."""

from _shim import ShimObject


class JiraRestAPIError(Exception):
    """Raised for any JIRA REST failure."""


class JiraRestAPI(ShimObject):
    """Stand-in for the JIRA REST client."""

    _shim_package = 'jiraapi'
