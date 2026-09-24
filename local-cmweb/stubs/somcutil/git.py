"""Shim for ``somcutil.git`` -- faithfully reimplemented (pure string logic)."""

import re

RE_SHA1 = re.compile(r'^[0-9a-fA-F]{40}$')
RE_SHORT_SHA1 = re.compile(r'^[0-9a-fA-F]{7,40}$')


def is_sha1(value):
    """Return True if ``value`` looks like a full git SHA-1."""
    if not value:
        return False
    return bool(RE_SHA1.match(str(value).strip()))


def is_tag(value):
    """Return True if ``value`` looks like a tag ref rather than a SHA-1."""
    if not value:
        return False
    value = str(value).strip()
    if value.startswith('refs/tags/'):
        return True
    return not RE_SHORT_SHA1.match(value)
