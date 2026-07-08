"""Front-end selection for the Cider configuration wizard.

Chooses between the wxPython GUI and the terminal wizard based on the platform
and command-line overrides:

* Windows -> wxPython GUI by default.
* Linux / other -> terminal wizard by default (safe over SSH / headless).
* ``--gui`` / ``--tui`` force a specific front end.
* On a non-Windows box with no display, the GUI is refused with a clear
  message (and, without ``--gui``, the terminal wizard is used automatically).

``wx`` is imported lazily inside :func:`run`, so importing this package on a
headless Linux server never requires wxPython.
"""

from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from typing import List, Optional

from bot.config_ui.wizard import DEFAULT_CONFIG_PATH


def has_display() -> bool:
    """Return True if a graphical display is (likely) available."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def select_frontend(force_gui: bool, force_tui: bool) -> str:
    """Return "gui" or "tui" from the platform and the override flags."""
    if force_gui and force_tui:
        raise SystemExit("Choose only one of --gui / --tui.")
    if force_tui:
        return "tui"
    if force_gui:
        if not has_display():
            raise SystemExit(
                "--gui was requested but no graphical display is available. "
                "Use the terminal wizard instead (--tui)."
            )
        return "gui"
    # Auto: GUI on Windows, terminal wizard everywhere else / when headless.
    if sys.platform == "win32" and has_display():
        return "gui"
    return "tui"


def run(config_path: str, force_gui: bool = False, force_tui: bool = False) -> int:
    """Launch the appropriate wizard front end. Returns a process exit code."""
    frontend = select_frontend(force_gui, force_tui)
    if frontend == "gui":
        try:
            from bot.config_ui import wx_ui
        except ImportError as exc:
            print(
                f"Could not load the graphical wizard ({exc}). "
                "Falling back to the terminal wizard.\n"
            )
            from bot.config_ui import tui

            return tui.run(config_path)
        return wx_ui.run(config_path)
    from bot.config_ui import tui

    return tui.run(config_path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = ArgumentParser(
        description="Guided setup wizard that writes a valid Cider config.json.",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="Path to the configuration file to write",
        default=DEFAULT_CONFIG_PATH,
    )
    parser.add_argument(
        "--gui",
        help="Force the graphical (wxPython) wizard",
        action="store_true",
    )
    parser.add_argument(
        "--tui",
        help="Force the terminal wizard (useful over SSH / headless)",
        action="store_true",
    )
    args = parser.parse_args(argv)
    return run(args.config, force_gui=args.gui, force_tui=args.tui)
