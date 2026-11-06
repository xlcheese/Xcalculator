#!/usr/bin/env python3
# xl-Calculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""xl-Calculator: a calculator for Linux Mint and the Cinnamon desktop.

Start it with "python3 xl_calculator.py", or "xl-calculator" once it is installed. The other
files in this folder hold the modes, the history, printing, Preferences and the documentation."""
import os
import sys

if __name__ == "__main__" and sys.argv[1:] == ["--refresh-rates"]:
    # the daily background check (xl-calculator-rates.timer): no window, so no GTK
    from currency import refresh_from_command_line
    sys.exit(refresh_from_command_line())

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from config import APP_ID
from window import XCalculator


class XlCalculatorApplication(Gtk.Application):
    """One xl-Calculator program: opening it again from the menu opens another window in it."""

    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        XCalculator(application=self).show_all()


def move_from_old_name():
    """Bring over what Xcalculator (this program's name before 0.10) saved, including its
    daily rates timer if it was switched on."""
    import json
    import config
    if not config.move_from_old_name():
        return
    try:
        with open(config.CONFIG_FILE) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return
    if settings.get("currency_auto") is True and settings.get("currency_background") is True:
        from currency import set_background_refresh
        set_background_refresh(True)


if __name__ == "__main__":
    move_from_old_name()
    GLib.set_prgname("xl-calculator")         # the window's class matches the .desktop file,
    Gdk.set_program_class("xl-calculator")    # so the panel groups the window with its menu entry
    GLib.set_application_name("xl-Calculator")
    # the icon is installed under the app's ID; from the source folder, it's in usr/share/icons
    Gtk.IconTheme.get_default().append_search_path(
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "share", "icons")))
    Gtk.Window.set_default_icon_name(APP_ID)
    sys.exit(XlCalculatorApplication().run(sys.argv))
