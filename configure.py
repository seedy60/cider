"""Entry point for the Cider configuration wizard.

Launches a guided setup that writes a valid ``config.json`` so new users do not
have to hand-edit JSON.  The front end is chosen automatically:

* Windows -> graphical (wxPython) wizard.
* Linux / headless -> terminal wizard (works over plain SSH).

Override with ``--gui`` or ``--tui``.  Run ``python configure.py --help`` for
options.
"""

import sys

from bot.config_ui import main

if __name__ == "__main__":
    sys.exit(main())
