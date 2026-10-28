#!/usr/bin/env python3
# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.

Start it with "python3 xcalculator.py", or "xcalculator" once it is installed. The other
files in this folder hold the modes, the history, printing, Preferences and the documentation."""
import gi
import sys
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from config import APP_ID
from window import XCalculator


class XcalculatorApplication(Gtk.Application):
    """One Xcalculator program: opening it again from the menu opens another window in it."""

    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        XCalculator(application=self).show_all()


if __name__ == "__main__":
    GLib.set_prgname("xcalculator")         # the window's class matches the .desktop file,
    Gdk.set_program_class("Xcalculator")    # so the panel groups the window with its menu entry
    GLib.set_application_name("Xcalculator")
    Gtk.Window.set_default_icon_name("accessories-calculator")    # the icon theme's calculator, like Xed's
    sys.exit(XcalculatorApplication().run(sys.argv))
