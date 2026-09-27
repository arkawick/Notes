"""Shim URLconf for the internal ``commit-message-checker`` app.

The real app validates commit messages against Sony's format rules. Locally it
serves a single page explaining that the checker is not available, so the URL
include in the root URLconf still resolves.
"""

from django.http import HttpResponse
from django.urls import path

MESSAGE = (
    "<h1>Commit message checker</h1>"
    "<p>The <code>commit-message-checker</code> package is Sony-internal and "
    "has no public release, so local-cmweb ships a shim for it. The rest of "
    "the site is unaffected.</p>"
)


def unavailable(_request):
    """Return a page explaining that this feature is shimmed locally."""
    return HttpResponse(MESSAGE, status=501)


urlpatterns = [
    path('', unavailable, name='commit_message_checker_index'),
]
