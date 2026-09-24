"""Shim for ``somcutil.cron``."""

from _shim import ShimNotAvailable


def parse(*_args, **_kwargs):
    """Raise -- cron expression parsing is not reimplemented locally."""
    raise ShimNotAvailable('somcutil', 'cron.parse()')


def next_run(*_args, **_kwargs):
    """Raise -- cron scheduling is not reimplemented locally."""
    raise ShimNotAvailable('somcutil', 'cron.next_run()')
