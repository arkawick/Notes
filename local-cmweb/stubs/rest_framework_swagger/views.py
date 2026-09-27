"""Shim for ``django-rest-swagger``'s view factory.

The real package (2.1.1) predates DRF 3.15 and does not import on it. The
browsable DRF API at ``/api/`` is unaffected -- only the Swagger UI page is
replaced by this notice.
"""

from django.http import HttpResponse

MESSAGE = (
    "<h1>API documentation</h1>"
    "<p><code>django-rest-swagger</code> 2.1.1 is incompatible with the "
    "Django and DRF versions used by local-cmweb, so the Swagger UI is "
    "shimmed out. The browsable API is available at "
    "<a href='/api/'>/api/</a>.</p>"
)


def get_swagger_view(title=None, url=None, patterns=None, urlconf=None):
    """Return a view rendering a short notice instead of the Swagger UI."""
    def _view(_request, *_args, **_kwargs):
        return HttpResponse(MESSAGE, status=501)
    return _view
