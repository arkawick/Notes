"""Shim managers for ``generic-pages``."""

from django.db import models


class PublicManager(models.Manager):
    """Manager exposing a ``public()`` shortcut for published rows."""

    def public(self):
        """Return only rows with a public status."""
        return self.get_queryset().filter(status__gte=2)

    def published(self):
        """Alias for `public`."""
        return self.public()
