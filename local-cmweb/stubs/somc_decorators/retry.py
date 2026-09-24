"""Shim for ``somc_decorators.retry``.

This one is faithfully reimplemented: it is a generic retry decorator with no
internal service behind it, and application code depends on its semantics.
"""

import functools
import logging
import time


def retry(exceptions, tries=3, delay=1, backoff=2, logger=None,
          error_handler=None):
    """Retry the wrapped callable when ``exceptions`` is raised.

    ``error_handler`` is called with the exception as ``exception=`` and must
    return True for the retry to proceed -- this is how `request.models` retries
    only on Gerrit 401/502 responses.
    """
    def _decorator(func):
        @functools.wraps(func)
        def _wrapper(*args, **kwargs):
            remaining, wait = tries, delay
            while remaining > 1:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if error_handler is not None:
                        try:
                            proceed = error_handler(*args, exception=exc,
                                                    **kwargs)
                        except TypeError:
                            proceed = error_handler(exception=exc)
                        if not proceed:
                            raise
                    (logger or logging).warning(
                        '%s, retrying in %s seconds...', exc, wait)
                    time.sleep(wait)
                    remaining -= 1
                    wait *= backoff
            return func(*args, **kwargs)
        return _wrapper
    return _decorator
