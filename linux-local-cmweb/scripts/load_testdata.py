"""Load explorer/fixtures/testdata.json with model signals muted.

The upstream equivalent is ``make install-testdata``, which is a plain
``loaddata``. That works, but the fixture is a ``dumpdata`` snapshot of an
*already-indexed* database: replaying it through Django's normal save path
re-fires every indexing signal the application defines, which tries to reach
JIRA and M+ once per issue, recomputes label completion, and writes a
django-reversion revision per row. None of that work is wanted -- the results
are already in the file -- and on SQLite it turns a ~90 second load into a very
long one.

So this script detaches every model signal for the duration of the load and
restores them afterwards.

    ENV/bin/python3 scripts/load_testdata.py [path/to/fixture.json]
"""

import os
import sys
import time

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SITE = os.path.join(BASE, 'site')

# settings.py appends site/apps itself; site/ has to be importable for the
# cmweb package, and stubs/ for the Sony-internal shims.
sys.path.insert(0, SITE)
sys.path.append(os.path.join(BASE, 'stubs'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cmweb.settings')

import django  # noqa: E402
django.setup()

from django.core.management import call_command  # noqa: E402
from django.db.models import signals  # noqa: E402

SIGNALS = ('pre_init', 'post_init', 'pre_save', 'post_save', 'pre_delete',
           'post_delete', 'm2m_changed')

DEFAULT_FIXTURE = os.path.join(
    os.path.dirname(BASE), 'cmweb-app', 'explorer', 'fixtures',
    'testdata.json')


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
