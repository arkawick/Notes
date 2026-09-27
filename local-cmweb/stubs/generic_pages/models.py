"""Shim models for ``generic-pages``.

`GenericPage` is a real concrete model, not a raise-on-use stub: `blog.Post`
subclasses it and `blog/migrations/0001_initial.py` declares a foreign key onto
``generic_pages.GenericPage``, so the table has to exist for the schema to build.

Field names are taken from how the application uses them -- `base/tests/
test_views.py` constructs a page with title/slug/body/status/publish, and
`blog.Post` calls `get_previous_by_publish(status__gte=2)`.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .managers import PublicManager

DRAFT = 1
PUBLIC = 2

STATUS_CHOICES = (
    (DRAFT, 'Draft'),
    (PUBLIC, 'Public'),
)


class GenericPage(models.Model):
    """A simple flat page addressed by slug."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    body = models.TextField(blank=True)
    # blog.Post inherits this: blog/views.py filters Post.objects on author=,
    # blog/admin.py assigns it on save, and the post templates render the
    # author's profile link and gravatar.
    author = models.ForeignKey(settings.AUTH_USER_MODEL,
                               on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name='generic_pages')
    status = models.IntegerField(choices=STATUS_CHOICES, default=PUBLIC,
                                 db_index=True)
    publish = models.DateTimeField(default=timezone.now, db_index=True)
    # Both are read by cmweb-project/templates/generic_pages/page.html:
    # auto_toc switches on the sidebar table of contents, show_published
    # renders the publish date above the body.
    auto_toc = models.BooleanField(default=False)
    show_published = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    objects = PublicManager()

    class Meta:
        """Meta data class for GenericPage."""

        verbose_name = 'generic page'
        verbose_name_plural = 'generic pages'
        ordering = ('-publish',)
        get_latest_by = 'publish'

    def __str__(self):
        """Return the page title."""
        return self.title

    def get_absolute_url(self):
        """Return the URL of this page."""
        return reverse('page', kwargs={'slug': self.slug})

    def is_public(self):
        """Return True if the page is publicly visible."""
        return self.status >= PUBLIC
