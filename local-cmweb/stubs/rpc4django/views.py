"""Shim for ``rpc4django``'s request handler.

CMWEB exposes an XML-RPC endpoint at ``/rpc/`` that the git mirroring scripts
call to fetch the mirror manifest. Nothing local needs it, so the endpoint
answers with an explanatory notice instead.
"""

from django.http import HttpResponse

MESSAGE = (
    "<h1>XML-RPC endpoint</h1>"
    "<p>The <code>rpc4django</code> endpoint is shimmed out in local-cmweb. "
    "In production this is what <code>cmweb-scripts/bin/mirror_repo.sh</code> "
    "queries for the mirror manifest.</p>"
)


def serve_rpc_request(_request, *_args, **_kwargs):
    """Return a notice instead of serving an RPC call."""
    return HttpResponse(MESSAGE, status=501)
