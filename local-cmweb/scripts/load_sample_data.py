"""Load the CMWEB sample dataset into the local database.

Use this instead of a bare ``manage.py loaddata``.

``cmweb-app/explorer/fixtures/testdata.json`` is a ``dumpdata`` snapshot of an
already-indexed database: ~22k rows covering builds, commits, repositories,
issues, packages and users. Replaying it through Django's normal save path
re-fires every indexing signal the application defines -- which tries to reach
JIRA and M+ for each issue, recomputes label completion, and writes a
django-reversion revision per row. On SQLite that turns a ~30 second load into
a very long one, and none of the work is wanted: the fixture already contains
the results.

So this script mutes model signals for the duration of the load and restores
them afterwards.
"""

import os
import sys
import time

# Do not litter the source repositories with __pycache__ directories.
sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_local')

import django  # noqa: E402
django.setup()

from django.core.management import call_command  # noqa: E402
from django.db.models import signals  # noqa: E402

SIGNALS = ('pre_init', 'post_init', 'pre_save', 'post_save', 'pre_delete',
           'post_delete', 'm2m_changed')

DEFAULT_FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))),
    'cmweb-app', 'explorer', 'fixtures', 'testdata.json')


class muted_signals(object):
    """Context manager that detaches every model signal receiver."""

    def __enter__(self):
        """Stash and clear the receiver lists."""
        self._saved = {}
        for name in SIGNALS:
            sig = getattr(signals, name)
            self._saved[name] = sig.receivers
            sig.receivers = []
            sig.sender_receivers_cache.clear()
        return self

    def __exit__(self, *_exc):
        """Put the receiver lists back."""
        for name in SIGNALS:
            sig = getattr(signals, name)
            sig.receivers = self._saved[name]
            sig.sender_receivers_cache.clear()
        return False


def main():
    """Load the fixture with signals muted."""
    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    if not os.path.exists(fixture):
        sys.exit('Fixture not found: {}'.format(fixture))
    size = os.path.getsize(fixture) / (1024.0 * 1024.0)
    print('Loading {} ({:.1f} MB) with model signals muted...'.format(
        os.path.basename(fixture), size))
    started = time.time()
    with muted_signals():
        call_command('loaddata', fixture, verbosity=1, skip_checks=True)
    print('Done in {:.0f}s.'.format(time.time() - started))


if __name__ == '__main__':
    main()
