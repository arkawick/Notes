"""Shim for ``somc-django-inlines``' ``inlines_tags`` template library.

This one is a genuine reimplementation rather than a raise-on-use stub: almost
every CMWEB template renders objects through ``{% show_object %}``, so nothing
would display without it.

The contract is inferred from the templates that ship with the application:

* ``{% show_object obj %}`` renders ``obj`` with the first template that exists
  out of ``inlines/<app_label>_<model_name>.html`` and ``inlines/default.html``.
  The per-model templates in the repository extend ``inlines/standard.html``,
  ``inlines/nocache.html`` or ``inlines/standard_nocache.html``, all of which
  live in ``cmweb-project/templates/inlines/``.
* The rendering context carries ``object``, ``model``, ``mode``, ``cache_key``
  and any extra keyword arguments, plus ``request`` from the parent context.
* ``{% show_object_list qs %}`` renders a list via the same lookup, passing
  ``object_list``.
* ``{% inline_url obj %}`` reverses the ``generic_inline`` view in the base app,
  which is what the PJAX/AJAX refresh hooks fetch.
"""

import re

from django import template
from django.apps import apps
from django.template.loader import select_template
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

register = template.Library()

# Markup embedded in page and post bodies, e.g.
#   <inline type="explorer.label" ids="1,2" class="foo" />
# The admin change form in blog/templates/admin/blog/post/change_form.html
# builds exactly this string, which is where the attribute names come from.
RE_INLINE = re.compile(
    r'<inline\s+type="(?P<type>[^"]+)"\s+ids="(?P<ids>[^"]*)"'
    r'(?:\s+class="(?P<class>[^"]*)")?\s*/?>',
    re.IGNORECASE)


def _names_for(obj, suffix=''):
    """Return candidate inline template names, most specific first."""
    meta = obj._meta
    base = 'inlines/{}_{}'.format(meta.app_label, meta.model_name)
    names = []
    if suffix:
        names.append('{}_{}.html'.format(base, suffix))
    names.append('{}.html'.format(base))
    names.append('inlines/default.html')
    return names


def _render(obj_context, obj, context, suffix='', **kwargs):
    """Render the best-matching inline template for ``obj``."""
    if obj is None:
        return ''
    try:
        names = _names_for(obj, suffix)
    except AttributeError:
        # Not a model instance -- fall back to plain text rendering.
        return str(obj)
    tpl = select_template(names)
    data = {
        obj_context: obj,
        'model': getattr(obj._meta, 'model_name', ''),
        'app_label': getattr(obj._meta, 'app_label', ''),
        'mode': kwargs.pop('mode', None) or '',
        'cache_key': kwargs.pop('cache_key', None) or '',
        'no_actions': kwargs.pop('no_actions', False),
    }
    inlines_kwargs = kwargs.pop('inlines_kwargs', None)
    if isinstance(inlines_kwargs, dict):
        data.update(inlines_kwargs)
        data['inlines_kwargs'] = inlines_kwargs
    data.update(kwargs)
    request = context.get('request') if hasattr(context, 'get') else None
    if request is not None:
        data['request'] = request
        data['user'] = getattr(request, 'user', None)
    return tpl.render(data, request)


@register.simple_tag(takes_context=True)
def show_object(context, obj, **kwargs):
    """Render a single object with its inline template."""
    return _render('object', obj, context, **kwargs)


@register.simple_tag(takes_context=True)
def show_object_list(context, object_list, **kwargs):
    """Render a queryset or list with the inline list template."""
    items = list(object_list or [])
    if not items:
        return ''
    return _render('object_list', items[0], context,
                   object_list=items, **kwargs)


@register.simple_tag(takes_context=True)
def show_objects(context, object_list, **kwargs):
    """Alias for `show_object_list`."""
    return show_object_list(context, object_list, **kwargs)


@register.simple_tag
def inline_url(obj):
    """Return the generic-inline URL for ``obj``."""
    if obj is None or not hasattr(obj, '_meta'):
        return ''
    try:
        return reverse('generic_inline', kwargs={
            'app': obj._meta.app_label,
            'model': obj._meta.model_name,
            'pk': obj.pk,
        })
    except NoReverseMatch:
        return ''


@register.filter
def render_inlines(value):
    """Expand ``<inline type="app.model" ids="1,2" />`` markup in ``value``.

    Applied to free-text bodies -- generic pages, blog posts and comments --
    where an author has embedded a reference to another object. Each match is
    replaced with that object's inline template; unresolvable references are
    dropped rather than left as raw markup.
    """
    if not value:
        return value

    def _replace(match):
        try:
            app_label, model_name = match.group('type').split('.', 1)
            model = apps.get_model(app_label, model_name)
        except (ValueError, LookupError):
            return ''
        ids = [i.strip() for i in (match.group('ids') or '').split(',')
               if i.strip()]
        if not ids:
            return ''
        objects = list(model._default_manager.filter(pk__in=ids))
        if not objects:
            return ''
        css = match.group('class') or ''
        out = []
        for obj in objects:
            try:
                tpl = select_template(_names_for(obj))
            except template.TemplateDoesNotExist:
                out.append(str(obj))
                continue
            out.append(tpl.render({
                'object': obj,
                'model': obj._meta.model_name,
                'app_label': obj._meta.app_label,
                'class': css,
                'mode': '',
                'cache_key': '',
                'no_actions': True,
            }))
        return ''.join(out)

    return mark_safe(RE_INLINE.sub(_replace, str(value)))


@register.simple_tag
def inline_list_url(model):
    """Return the generic-inline list URL for a model or instance."""
    meta = getattr(model, '_meta', None)
    if meta is None:
        return ''
    try:
        return reverse('generic_inline_list', kwargs={
            'app': meta.app_label,
            'model': meta.model_name,
        })
    except NoReverseMatch:
        return ''
