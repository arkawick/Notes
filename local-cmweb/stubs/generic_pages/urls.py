"""Shim URLconf for ``generic-pages``.

Included last in the root URLconf, so the slug pattern acts as the site-wide
catch-all -- which is why an absent home page turns ``/`` into a 404 on a fresh
database.
"""

from django.urls import path, re_path

from .views import HomePage, PageDetail

urlpatterns = [
    path('', HomePage.as_view(), name='home'),
    re_path(r'^(?P<slug>[-\w]+)/?$', PageDetail.as_view(), name='page'),
]
