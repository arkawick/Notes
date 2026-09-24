"""Shim for ``somcutil.matcher`` -- faithfully reimplemented (regex matching)."""

import re


class IncludeExcludeMatcher(object):
    """Match strings against include patterns minus exclude patterns."""

    def __init__(self, includes=None, excludes=None):
        """Compile the include and exclude pattern lists."""
        self.includes = [re.compile(p) for p in (includes or [])]
        self.excludes = [re.compile(p) for p in (excludes or [])]

    def match(self, value):
        """Return True if ``value`` is included and not excluded."""
        if self.excludes and any(p.match(value) for p in self.excludes):
            return False
        if not self.includes:
            return True
        return any(p.match(value) for p in self.includes)

    __call__ = match
