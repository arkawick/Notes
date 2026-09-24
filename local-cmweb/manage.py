#!/usr/bin/env python
"""Django entry point for the local CMWEB instance.

Use this instead of ``cmweb-project/manage.py``. It selects the local settings
module; the path wiring that joins cmweb-project, cmweb-app and the shims lives
in ``config/settings_local.py`` so it applies to the WSGI path too.
"""

import os
import sys

# Keep the source repositories pristine: importing cmweb-app and cmweb-project
# would otherwise scatter __pycache__ directories through them.
sys.dont_write_bytecode = True


def main():
    """Run a Django management command against the local settings."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_local')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
