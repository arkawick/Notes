"""WSGI application for the local CMWEB instance.

``WSGI_APPLICATION`` must name an application *object*, not a factory. Pointing
it straight at ``django.core.wsgi.get_wsgi_application`` makes runserver call
the factory with (environ, start_response) and every request 500s with
"get_wsgi_application() takes 0 positional arguments".
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_local')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
