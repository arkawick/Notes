"""Shim views for ``generic-pages``."""

from django.views.generic import DetailView

from .models import GenericPage


class PageDetail(DetailView):
    """Render a single `GenericPage` by slug.

    `vendorsync.views.Index` subclasses this and overrides `get_object`, so the
    queryset and template must both be permissive.
    """

    model = GenericPage
    template_name = 'generic_pages/page.html'
    context_object_name = 'page'

    def get_template_names(self):
        """Prefer the home template for the root page."""
        names = ['generic_pages/page.html']
        obj = getattr(self, 'object', None)
        if obj is not None and getattr(obj, 'slug', '') == 'home':
            names.insert(0, 'generic_pages/home.html')
        return names

    def get_context_data(self, **kwargs):
        """Expose the page as both ``page`` and ``object``."""
        context = super(PageDetail, self).get_context_data(**kwargs)
        context.setdefault('object', self.object)
        context.setdefault('page', self.object)
        return context


class HomePage(PageDetail):
    """Render the page slugged ``home``, which serves ``/``."""

    def get_object(self, queryset=None):
        """Return the home page, creating an empty one if absent."""
        page, _created = GenericPage.objects.get_or_create(
            slug='home', defaults={'title': 'Home', 'body': ''})
        return page
