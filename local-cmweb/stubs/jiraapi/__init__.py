"""Shim for the internal ``jiraapi`` package."""

from _shim import ShimNotAvailable
from .rest import JiraRestAPI, JiraRestAPIError  # noqa: F401


class JiraClient(object):
    """Stand-in for the high-level JIRA client.

    Constructing the client must succeed even though no request can: callers in
    `issues/indexing.py` build the client outside their try/except and only
    guard the request itself, e.g.::

        client = get_jira_client()      # must not raise
        try:
            return client.get(...)      # may raise; None means "not in JIRA"
        except Exception:
            pass

    So `instance` returns a real object and `get` raises, which the application
    reads as "this issue/project does not exist in JIRA" -- the correct
    behaviour when there is no JIRA to ask.
    """

    def __init__(self, url='', auth=None, proxies=None, **kwargs):
        """Store connection details without contacting anything."""
        self.url = url
        self.auth = auth
        self.proxies = proxies
        self.kwargs = kwargs

    @classmethod
    def instance(cls, url='', auth=None, proxies=None, **kwargs):
        """Return a client instance, matching the real classmethod factory."""
        return cls(url=url, auth=auth, proxies=proxies, **kwargs)

    def get(self, *_args, **_kwargs):
        """Raise -- callers treat the failure as "not found in JIRA"."""
        raise ShimNotAvailable('jiraapi', 'JiraClient.get()')

    def post(self, *_args, **_kwargs):
        """Raise -- no JIRA instance to write to."""
        raise ShimNotAvailable('jiraapi', 'JiraClient.post()')

    def put(self, *_args, **_kwargs):
        """Raise -- no JIRA instance to write to."""
        raise ShimNotAvailable('jiraapi', 'JiraClient.put()')
