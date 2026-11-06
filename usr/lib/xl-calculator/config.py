# xl-Calculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where xl-Calculator keeps its settings, and facts about the program and its modes."""
import gi
import os
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from i18n import N_, _


CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "xl-calculator")     # ~/.config/xl-calculator


CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")


HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")


# Before version 0.10 the program was called Xcalculator and kept its files under that name
OLD_CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "xcalculator")   # settings and history
OLD_CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "xcalculator")     # downloaded rates
OLD_TIMER_LINK = os.path.join(GLib.get_user_config_dir(), "systemd", "user",
                              "timers.target.wants", "xcalculator-rates.timer")


def move_from_old_name():
    """Copy settings, history and rates kept under the old name, once (the old folders are
    left alone, so nothing is lost if something goes wrong). Returns True if the old daily
    rates timer was switched on: its link is removed, and the caller switches on the new one."""
    import shutil
    if os.path.isdir(OLD_CONFIG_DIR) and not os.path.exists(CONFIG_DIR):
        try:
            shutil.copytree(OLD_CONFIG_DIR, CONFIG_DIR)
        except OSError as error:
            print(f"Couldn't copy the settings from {OLD_CONFIG_DIR}: {error}")
    new_cache = os.path.join(GLib.get_user_cache_dir(), "xl-calculator")
    if os.path.isdir(OLD_CACHE_DIR) and not os.path.exists(new_cache):
        try:
            shutil.copytree(OLD_CACHE_DIR, new_cache)
        except OSError as error:
            print(f"Couldn't copy the rates from {OLD_CACHE_DIR}: {error}")
    if os.path.islink(OLD_TIMER_LINK):
        try:
            os.remove(OLD_TIMER_LINK)   # its program is gone with the old package
            return True
        except OSError as error:
            print(f"Couldn't remove the old rates timer: {error}")
    return False


MAX_SAVED_HISTORY = 500


APP_ID = "io.github.xlcheese.XlCalculator"     # also the name of the .desktop and metainfo files


APP_VERSION = "0.10"


APP_WEBSITE = "https://github.com/xlcheese/xl-calculator"


APP_AUTHORS = ["Wesley Hayslip"]


APP_COPYRIGHT = "Copyright © 2026 Wesley Hayslip"


APP_CREDIT = _("Developed with the help of Claude, an AI assistant by Anthropic")


DEFAULT_FONT_SIZE = 15


HISTORY_MIN_HEIGHT = 75     # results area: first-time height and the smallest allowed (~3½ lines)


# window width for each mode; the height fits the buttons plus the results area
MODE_WIDTHS = {"Basic": 340, "Scientific": 460, "Financial": 500,
               "Programmer": 500, "Unit Converter": 500, "Currency Converter": 500}


VALID_MODES = (N_("Basic"), N_("Scientific"), N_("Financial"), N_("Programmer"), N_("Unit Converter"),
               N_("Currency Converter"))
CONVERTER_MODES = ("Unit Converter", "Currency Converter")     # the modes with two boxes


MODE_KEYS = {"Basic": "b", "Scientific": "s", "Financial": "f", "Programmer": "p", "Unit Converter": "u",
             "Currency Converter": "c"}
