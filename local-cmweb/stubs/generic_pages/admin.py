"""Shim admin registration for ``generic-pages``."""

from django.contrib import admin

from .models import GenericPage


@admin.register(GenericPage)
class GenericPageAdmin(admin.ModelAdmin):
    """Admin for `GenericPage` -- this is how the home page gets created."""

    list_display = ('title', 'slug', 'status', 'publish')
    list_filter = ('status',)
    search_fields = ('title', 'body')
    prepopulated_fields = {'slug': ('title',)}
