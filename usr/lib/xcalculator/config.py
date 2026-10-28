# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Xcalculator keeps its settings, and facts about the program and its modes."""
import gi
import os
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from i18n import N_, _


CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "xcalculator")     # ~/.config/xcalculator


CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")


HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")


MAX_SAVED_HISTORY = 500


APP_ID = "io.github.xlcheese.Xcalculator"     # also the name of the .desktop and metainfo files


APP_VERSION = "0.9"


APP_WEBSITE = "https://github.com/xlcheese/Xcalculator"


APP_AUTHORS = ["Wesley Hayslip"]


APP_COPYRIGHT = "Copyright © 2026 Wesley Hayslip"


APP_CREDIT = _("Developed with the help of Claude, an AI assistant by Anthropic")


DEFAULT_FONT_SIZE = 15


HISTORY_MIN_HEIGHT = 75     # results area: first-time height and the smallest allowed (~3½ lines)


# window width for each mode; the height fits the buttons plus the results area
MODE_WIDTHS = {"Basic": 340, "Scientific": 460, "Financial": 500,
               "Programmer": 500, "Unit Converter": 500}


VALID_MODES = (N_("Basic"), N_("Scientific"), N_("Financial"), N_("Programmer"), N_("Unit Converter"))


MODE_KEYS = {"Basic": "b", "Scientific": "s", "Financial": "f", "Programmer": "p", "Unit Converter": "u"}
