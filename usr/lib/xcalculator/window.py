# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The calculator window."""
import gi
import json
import os
import random
import re
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
from i18n import N_, _
from config import (
    APP_AUTHORS, APP_COPYRIGHT, APP_CREDIT, APP_ID, APP_VERSION, APP_WEBSITE, CONFIG_FILE,
    CONVERTER_MODES, DEFAULT_FONT_SIZE, HISTORY_MIN_HEIGHT, MODE_KEYS, MODE_WIDTHS, VALID_MODES
)
from engine import (
    DEFAULT_DECIMALS, MAX_DECIMALS, NUMBER_FORMAT, PLAIN_MATH, fit_text, format_number,
    group_digits, show_math, show_minus
)
from basic import BasicMode
from scientific import ScientificMode
from financial import FinancialMode
from programmer import PROG_BACKSPACE_TOKENS, PROG_BASES, PROG_TOOLTIPS, PROG_WORDS, ProgrammerMode
from converter import CONVERTER_CATEGORIES, CONVERTER_START, CONVERTER_UNITS, ConverterMode
from history import HistoryPanel
from printing import TapePrinting
from preferences import PreferencesActions
from documentation import HelpWindow
from easter_egg import UpsideDown
from currency import CURRENCY, CURRENCY_START, CODE_RE, DEFAULT_INTERVAL, MAX_INTERVAL, CurrencyMode


class XCalculator(BasicMode, ScientificMode, FinancialMode, ProgrammerMode, ConverterMode, CurrencyMode,
                  HistoryPanel, TapePrinting, PreferencesActions, UpsideDown, Gtk.Window):
    """One calculator window: the menus, the display, the keypad for the current mode,
    and the history. Each mode's own keys come from its module (see the classes above)."""

    # buttons whose label is a word: translated on screen, still known by the English name
    WORD_BUTTONS = (N_("Clear"), N_("Clear All"), N_("Capture"), N_("Swap"), N_("Auto Refresh"), N_("Refresh Rates"))

    def __init__(self, application=None):
        super().__init__(title="Xcalculator", application=application)
        self.set_border_width(0)
        self.set_decorated(True)

        self.expression = ""
        self.memory = 0
        self.is_result_active = False
        self.token_stack = []          # pieces appended by buttons, so backspace undoes one button press
        self.use_radians = False        # Preferences → Angle units; loaded from settings below
        self.second_active = False
        self.buttons = {}
        self.current_mode = "Basic"         # first-time default
        self.base_font_size = DEFAULT_FONT_SIZE
        self.history_height = HISTORY_MIN_HEIGHT   # kept the same in every mode
        self.mode_widths = {}           # widths the user stretched each mode to
        self.expected_size = None       # the size the calculator last asked for
        self.track_history = False      # the user resized the window: remember the new height
        self.settling = 0               # >0 just after the calculator resized itself
        self.functions = self.build_functions()

        # Financial mode state
        self.tvm = {'N': 0.0, 'I/Y': 0.0, 'PV': 0.0, 'PMT': 0.0, 'FV': 0.0}
        self.periods_per_year = 12
        self.begin_mode = False
        self.cpt_pending = False
        self.cash_flows = []            # [[amount, repeat_count], ...]; first entry is CF0
        self.amort_p1 = None
        self.amort_p2 = None
        self.display_is_echo = False    # display just repeats a value the user stored

        # Upside-down easter egg state
        self.flip_snapshot = None       # cairo surface of the window contents
        self.flip_start_time = 0
        self.flip_angle = 0.0

        # Programmer mode state
        self.prog_base = 10
        self.prog_bits = 64
        self.prog_preview = 0           # value shown in every base under the display

        # Unit Converter state
        self.conv_category = "Length"
        self.conv_units = {c: list(pair) for c, pair in CONVERTER_START.items()}   # [top, bottom]
        self.conv_units[CURRENCY] = list(CURRENCY_START)
        self.currency_auto = False      # Preferences → Currency Converter, and the Auto Refresh button
        self.currency_interval = DEFAULT_INTERVAL
        self.currency_background = False
        self.currency_window_ready()
        self.conv_active = 0            # 0: typing in the top box, 1: the bottom box
        self.conv_formula = ""
        self.edit_tail = ""             # text after the cursor while edit_at_cursor runs an action

        # what the history holds, for printing: [(calculation, full result), ...]
        self.history_entries = []
        self.print_settings = None      # remembered from the last print dialog this session
        self.page_setup = Gtk.PageSetup()
        self.help_window = None
        self.syncing_widgets = False    # set while the code (not the user) updates buttons/menus

        # Preferences (General and Modes pages)
        self.thousands = False
        self.keep_history = False       # show the saved history when the calculator opens
        self.enabled_modes = list(VALID_MODES)
        self.result_value = None        # the answer on screen, unrounded, to re-show if decimals change
        self.preferences_window = None
        NUMBER_FORMAT.update(decimals=DEFAULT_DECIMALS, show_all=False)

        self.load_window_settings()

        self.css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.apply_custom_styles()
        # pick up the new red if the user changes theme while the calculator is open
        Gtk.Settings.get_default().connect(
            "notify::gtk-theme-name", lambda *args: GLib.idle_add(self.apply_custom_styles))

        accel_group = Gtk.AccelGroup()
        self.add_accel_group(accel_group)

        # The overlay carries a hidden drawing area used by the upside-down easter egg.
        overlay = Gtk.Overlay()
        self.add(overlay)

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        overlay.add(main_vbox)
        self.main_vbox = main_vbox

        self.flip_area = Gtk.DrawingArea()
        self.flip_area.set_no_show_all(True)
        self.flip_area.connect("draw", self.on_flip_draw)
        overlay.add_overlay(self.flip_area)

        menubar = Gtk.MenuBar()
        main_vbox.pack_start(menubar, False, False, 0)

        file_menu = Gtk.Menu()
        file_item = Gtk.MenuItem(label=_("File"))
        file_item.set_submenu(file_menu)
        menubar.append(file_item)

        new_window_item = Gtk.MenuItem(label=_("New Window"))
        new_window_item.add_accelerator("activate", accel_group, Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        new_window_item.connect("activate", self.open_new_window)
        file_menu.append(new_window_item)

        file_menu.append(Gtk.SeparatorMenuItem())

        self.print_preview_item = Gtk.MenuItem(label=_("Print Preview"))
        self.print_preview_item.add_accelerator("activate", accel_group, Gdk.KEY_p,
                                                Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK, Gtk.AccelFlags.VISIBLE)
        self.print_preview_item.connect("activate", self.show_print_preview)
        file_menu.append(self.print_preview_item)

        self.print_item = Gtk.MenuItem(label=_("Print…"))
        self.print_item.add_accelerator("activate", accel_group, Gdk.KEY_p, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        self.print_item.connect("activate", self.print_history)
        file_menu.append(self.print_item)

        file_menu.append(Gtk.SeparatorMenuItem())

        close_item = Gtk.MenuItem(label=_("Close"))
        close_item.add_accelerator("activate", accel_group, Gdk.KEY_w, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        close_item.connect("activate", lambda w: self.close())
        file_menu.append(close_item)

        quit_item = Gtk.MenuItem(label=_("Quit"))
        quit_item.add_accelerator("activate", accel_group, Gdk.KEY_q, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        quit_item.connect("activate", self.quit_calculator)
        file_menu.append(quit_item)

        edit_menu = Gtk.Menu()
        edit_item = Gtk.MenuItem(label=_("Edit"))
        edit_item.set_submenu(edit_menu)
        menubar.append(edit_item)

        copy_item = Gtk.MenuItem(label=_("Copy"))
        copy_item.add_accelerator("activate", accel_group, Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        copy_item.connect("activate", self.copy_to_clipboard)
        edit_menu.append(copy_item)

        paste_item = Gtk.MenuItem(label=_("Paste"))
        paste_item.add_accelerator("activate", accel_group, Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        paste_item.connect("activate", self.paste_from_clipboard)
        edit_menu.append(paste_item)

        edit_menu.append(Gtk.SeparatorMenuItem())

        preferences_item = Gtk.MenuItem(label=_("Preferences"))
        preferences_item.connect("activate", self.show_preferences)
        edit_menu.append(preferences_item)

        mode_menu = Gtk.Menu()
        mode_item = Gtk.MenuItem(label=_("Mode"))
        mode_item.set_submenu(mode_menu)

        basic_radio = Gtk.RadioMenuItem(label=_("Basic"))
        basic_radio.set_active(self.current_mode == "Basic")
        basic_radio.connect("activate", self.on_menu_mode_changed, "Basic")
        mode_menu.append(basic_radio)

        sci_radio = Gtk.RadioMenuItem(group=basic_radio, label=_("Scientific"))
        sci_radio.set_active(self.current_mode == "Scientific")
        sci_radio.connect("activate", self.on_menu_mode_changed, "Scientific")
        mode_menu.append(sci_radio)

        financial_radio = Gtk.RadioMenuItem(group=basic_radio, label=_("Financial"))
        financial_radio.set_active(self.current_mode == "Financial")
        financial_radio.connect("activate", self.on_menu_mode_changed, "Financial")
        mode_menu.append(financial_radio)

        programmer_radio = Gtk.RadioMenuItem(group=basic_radio, label=_("Programmer"))
        programmer_radio.set_active(self.current_mode == "Programmer")
        programmer_radio.connect("activate", self.on_menu_mode_changed, "Programmer")
        mode_menu.append(programmer_radio)

        converter_radio = Gtk.RadioMenuItem(group=basic_radio, label=_("Unit Converter"))
        converter_radio.set_active(self.current_mode == "Unit Converter")
        converter_radio.connect("activate", self.on_menu_mode_changed, "Unit Converter")
        mode_menu.append(converter_radio)

        currency_radio = Gtk.RadioMenuItem(group=basic_radio, label=_("Currency Converter"))
        currency_radio.set_active(self.current_mode == "Currency Converter")
        currency_radio.connect("activate", self.on_menu_mode_changed, "Currency Converter")
        mode_menu.append(currency_radio)
        self.mode_items = dict(zip(VALID_MODES, (basic_radio, sci_radio, financial_radio,
                                                 programmer_radio, converter_radio, currency_radio)))
        for mode, item in self.mode_items.items():      # Ctrl+Alt and the first letter: B, S, F, P, U and C
            item.add_accelerator("activate", accel_group, Gdk.keyval_from_name(MODE_KEYS[mode]),
                                 Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK,
                                 Gtk.AccelFlags.VISIBLE)

        view_menu = Gtk.Menu()
        view_item = Gtk.MenuItem(label=_("View"))
        view_item.set_submenu(view_menu)
        menubar.append(view_item)
        menubar.append(mode_item)           # File Edit View Mode Help

        clear_history_item = Gtk.MenuItem(label=_("Clear History"))
        clear_history_item.connect("activate", self.clear_history)
        view_menu.append(clear_history_item)

        divider2 = Gtk.SeparatorMenuItem()
        view_menu.append(divider2)

        larger_font_item = Gtk.MenuItem(label=_("Larger Font"))
        larger_font_item.add_accelerator("activate", accel_group, Gdk.KEY_equal, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        larger_font_item.connect("activate", self.change_font_zoom, 1)
        view_menu.append(larger_font_item)

        smaller_font_item = Gtk.MenuItem(label=_("Smaller Font"))
        smaller_font_item.add_accelerator("activate", accel_group, Gdk.KEY_minus, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        smaller_font_item.connect("activate", self.change_font_zoom, -1)
        view_menu.append(smaller_font_item)

        reset_font_item = Gtk.MenuItem(label=_("Reset Font Size"))
        reset_font_item.add_accelerator("activate", accel_group, Gdk.KEY_0, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        reset_font_item.connect("activate", self.reset_font_size)
        view_menu.append(reset_font_item)

        divider3 = Gtk.SeparatorMenuItem()
        view_menu.append(divider3)

        reset_view_item = Gtk.MenuItem(label=_("Reset View"))
        reset_view_item.connect("activate", self.reset_view)
        view_menu.append(reset_view_item)

        help_menu = Gtk.Menu()
        help_item = Gtk.MenuItem(label=_("Help"))
        help_item.set_submenu(help_menu)
        menubar.append(help_item)

        contents_item = Gtk.MenuItem(label=_("Documentation"))
        contents_item.add_accelerator("activate", accel_group, Gdk.KEY_F1, 0, Gtk.AccelFlags.VISIBLE)
        contents_item.connect("activate", self.show_help_contents)
        help_menu.append(contents_item)

        shortcuts_item = Gtk.MenuItem(label=_("Keyboard Shortcuts"))
        shortcuts_item.add_accelerator("activate", accel_group, Gdk.KEY_F1, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        shortcuts_item.connect("activate", lambda w: self.show_help_contents(page="Keyboard"))
        help_menu.append(shortcuts_item)

        help_menu.append(Gtk.SeparatorMenuItem())

        about_item = Gtk.MenuItem(label=_("About"))
        about_item.connect("activate", self.show_about)
        help_menu.append(about_item)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)   # 6 px between the history and the display
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(12)
        main_vbox.pack_start(vbox, True, True, 0)

        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_propagate_natural_height(True)
        self.scrolled_window.set_min_content_height(HISTORY_MIN_HEIGHT)
        self.scrolled_window.connect("size-allocate", self.on_history_allocated)
        self.scrolled_window.get_vadjustment().connect("changed", self.on_history_height_changed)
        self.scrolled_window.set_vexpand(True)
        self.scrolled_window.set_overlay_scrolling(True)    # the scrollbar shows only when needed, as in Xed
        self.scrolled_window.set_shadow_type(Gtk.ShadowType.IN)     # a box like the display (see apply_custom_styles)
        self.scrolled_window.get_style_context().add_class("calc-history-frame")

        self.history_listbox = Gtk.ListBox()
        self.history_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.history_listbox.set_valign(Gtk.Align.END)
        self.history_listbox.get_style_context().add_class("view")
        self.history_listbox.get_style_context().add_class("calc-history")

        self.scrolled_window.add(self.history_listbox)
        vbox.pack_start(self.scrolled_window, True, True, 0)

        self.display_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.pack_start(self.display_vbox, False, True, 0)
        self.display_vbox.set_margin_bottom(6)  # and 12 px, as before, above the keypad

        # The display is editable only so it shows a cursor you can place with the
        # mouse or arrow keys. All changes go through set_display(); typing straight
        # into the field is blocked and buttons/keys edit self.expression instead.
        # Unit Converter mode adds a unit menu beside the display and a second box
        # below it. self.display is always the box being typed in; in the converter
        # that is whichever box was clicked last, and the other shows the result.
        self.display_full = "0"         # what the display holds; may be shown shortened
        self.display_fit = False        # True for results, which may switch to 1.2×10⁹⁹
        self.updating_display = False
        self.refit_pending = False
        self.display_top = self.make_display_entry()
        self.display_bottom = self.make_display_entry()
        self.display = self.display_top
        self.conv_result_full = "0"     # what the converter's other box holds

        self.conv_combos = [Gtk.ComboBoxText(), Gtk.ComboBoxText()]     # units for top, bottom
        for index, combo in enumerate(self.conv_combos):
            combo.set_size_request(190, -1)
            combo.set_no_show_all(True)
            Gtk.Widget.set_focus_on_click(combo, False)  # ComboBox's own version is deprecated
            combo.connect("changed", self.on_conv_unit_changed, index)
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top_row.pack_start(self.display_top, True, True, 0)
        top_row.pack_start(self.conv_combos[0], False, False, 0)
        self.display_vbox.pack_start(top_row, False, True, 0)
        self.conv_bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.conv_bottom_row.pack_start(self.display_bottom, True, True, 0)
        self.conv_bottom_row.pack_start(self.conv_combos[1], False, False, 0)
        self.conv_bottom_row.set_no_show_all(True)
        self.display_vbox.pack_start(self.conv_bottom_row, False, True, 0)
        self.conv_bottom_row.set_margin_top(4)  # 6 px between the boxes; nothing extra below

        self.error_label = Gtk.Label(label="")
        self.error_label.set_xalign(1.0)
        self.error_label.get_style_context().add_class("calc-error-label")
        self.display_vbox.pack_start(self.error_label, False, True, 0)
        self.error_label.set_margin_top(1)      # error text 6 px under the display, like the history above it
        self.error_label.set_margin_bottom(2)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_no_show_all(True)
        self.status_label.get_style_context().add_class("calc-status-label")
        self.display_vbox.pack_start(self.status_label, False, True, 2)

        self.layouts = {
            # Basic is the keypad every mode shares; the other modes add rows above it
            "Basic": [
                [('⌫', 3), ('Clear', 3), ('%', 3), ('÷', 3)],
                [('7', 3), ('8', 3), ('9', 3), ('×', 3)],
                [('4', 3), ('5', 3), ('6', 3), ('−', 3)],
                [('1', 3), ('2', 3), ('3', 3), ('+', 3)],
                [('±', 3), ('0', 3), ('.', 3), ('=', 3)]
            ],
            "Scientific": [
                [('(', 2), (')', 2), ('MC', 2), ('M+', 2), ('M−', 2), ('MR', 2)],
                [('2nd', 2), ('x²', 2), ('x³', 2), ('xʸ', 2), ('eˣ', 2), ('10ˣ', 2)],
                [('1/x', 2), ('²√x', 2), ('³√x', 2), ('ʸ√x', 2), ('ln', 2), ('log₁₀', 2)],
                [('x!', 2), ('sin', 2), ('cos', 2), ('tan', 2), ('e', 2), ('EE', 2)],
                [('Rand', 2), ('sinh', 2), ('cosh', 2), ('tanh', 2), ('π', 2), ('Rad', 2)],
                [('|x|', 2), ('nCr', 2), ('nPr', 2), ('round', 2), ('f(x)', 2), ('mod', 2)],
                [('⌫', 3), ('Clear', 3), ('%', 3), ('÷', 3)],
                [('7', 3), ('8', 3), ('9', 3), ('×', 3)],
                [('4', 3), ('5', 3), ('6', 3), ('−', 3)],
                [('1', 3), ('2', 3), ('3', 3), ('+', 3)],
                [('±', 3), ('0', 3), ('.', 3), ('=', 3)]
            ],
            "Financial": [
                [('N', 2), ('I/Y', 2), ('PV', 2), ('PMT', 2), ('FV', 2), ('CPT', 2)],
                [('P/Y', 2), ('BGN', 2), ('CFj', 2), ('Nj', 2), ('NPV', 2), ('IRR', 2)],
                [('P1', 2), ('P2', 2), ('BAL', 2), ('PRN', 2), ('INT', 2), ('Mrgn', 2)],
                [('SL', 2), ('SYD', 2), ('DB', 2), ('EFF', 2), ('NOM', 2), ('Δ%', 2)],
                [('M+', 2), ('M−', 2), ('MR', 2), ('(', 2), (')', 2), ('Clear All', 2)],
                [('⌫', 3), ('Clear', 3), ('%', 3), ('÷', 3)],
                [('7', 3), ('8', 3), ('9', 3), ('×', 3)],
                [('4', 3), ('5', 3), ('6', 3), ('−', 3)],
                [('1', 3), ('2', 3), ('3', 3), ('+', 3)],
                [('±', 3), ('0', 3), ('.', 3), ('=', 3)]
            ],
            "Programmer": [
                [('HEX', 3), ('DEC', 3), ('OCT', 3), ('BIN', 3)],
                [('QWORD', 2), ('<<', 2), ('>>', 2), ('(', 2), (')', 2), ('mod', 2)],
                [('AND', 2), ('OR', 2), ('XOR', 2), ('NOT', 2), ('NAND', 2), ('NOR', 2)],
                [('A', 2), ('B', 2), ('C', 2), ('D', 2), ('E', 2), ('F', 2)],
                [('⌫', 3), ('Clear', 3), ('±', 3), ('÷', 3)],
                [('7', 3), ('8', 3), ('9', 3), ('×', 3)],
                [('4', 3), ('5', 3), ('6', 3), ('−', 3)],
                [('1', 3), ('2', 3), ('3', 3), ('+', 3)],
                [('0', 6), ('=', 6)]
            ],
            "Unit Converter": [
                [(c, 3) for c in CONVERTER_CATEGORIES[0:4]],
                [(c, 3) for c in CONVERTER_CATEGORIES[4:8]],
                [(c, 3) for c in CONVERTER_CATEGORIES[8:12]],
                [('⌫', 4), ('Clear', 4), ('Capture', 4)],
                [('7', 4), ('8', 4), ('9', 4)],
                [('4', 4), ('5', 4), ('6', 4)],
                [('1', 4), ('2', 4), ('3', 4)],
                [('±', 4), ('0', 4), ('.', 4)]
            ],
            "Currency Converter": [
                [('Swap', 4), ('Auto Refresh', 4), ('Refresh Rates', 4)],
                [('⌫', 4), ('Clear', 4), ('Capture', 4)],
                [('7', 4), ('8', 4), ('9', 4)],
                [('4', 4), ('5', 4), ('6', 4)],
                [('1', 4), ('2', 4), ('3', 4)],
                [('±', 4), ('0', 4), ('.', 4)]
            ]
        }

        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(6)
        self.grid.set_column_spacing(6)
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)
        vbox.pack_start(self.grid, False, True, 0)

        self.update_view_mode_layout()

        self.connect("configure-event", self.on_window_resized)
        self.connect("key-press-event", self.on_key_pressed)
        if application is None:
            self.connect("destroy", Gtk.main_quit)     # run on its own; an application quits after its last window
        self.display.grab_focus_without_selecting()     # show the cursor from the start
        self.update_print_actions()
        self.apply_enabled_modes()
        self.load_saved_history()

    def update_view_mode_layout(self):
        for child in self.grid.get_children():
            self.grid.remove(child)

        self.buttons = {}
        self.second_active = False

        programmer = self.current_mode == "Programmer"
        converter = self.current_mode in CONVERTER_MODES
        currency = self.current_mode == "Currency Converter"
        rows_data = self.layouts.get(self.current_mode, self.layouts["Scientific"])

        for row_idx, row_items in enumerate(rows_data):
            current_col = 0
            for item in row_items:
                label, span = item
                # bases and categories stay selected, drawn with the theme's selected look
                selectable = ((programmer and label in PROG_BASES) or (converter and label in CONVERTER_UNITS)
                              or (currency and label == 'Auto Refresh'))
                if label == 'f(x)':
                    button = self.make_more_functions_button()
                else:
                    shown = _(label) if label in self.WORD_BUTTONS or label in CONVERTER_UNITS else label
                    if label == 'Swap':
                        shown = "⇅ " + shown
                    button = Gtk.ToggleButton(label=shown) if selectable else Gtk.Button(label=shown)
                    if shown != label or label in self.WORD_BUTTONS:
                        button.key = label      # what on_button_clicked goes by
                    button.connect("clicked", self.on_button_clicked)
                button.set_focus_on_click(False)    # keep the cursor in the display
                context = button.get_style_context()

                if label in ('Clear', 'Clr', '⌫') or (label == 'C' and not programmer):   # C is a hex digit there
                    context.add_class("destructive-action")
                elif label in ('=', 'Capture'):
                    context.add_class("suggested-action")
                elif label.isdigit() or (programmer and len(label) == 1 and label in 'ABCDEF'):
                    context.add_class("numeric-button")
                if programmer and label in PROG_TOOLTIPS:
                    button.set_tooltip_text(PROG_TOOLTIPS[label])
                if (converter and label in CONVERTER_UNITS) or label == 'Clear All':
                    context.add_class("compact")    # long labels: narrower padding keeps the width
                if label == 'Capture':
                    button.set_tooltip_text(_("Add this conversion to the history"))
                if currency and label in self.CURRENCY_TOOLTIPS:
                    button.set_tooltip_text(_(self.CURRENCY_TOOLTIPS[label]))
                if label == 'Clear All':
                    button.set_tooltip_text(_("Clear all stored financial values: N, I/Y, PV, PMT, FV, "
                                              "cash flows, P1/P2, and the P/Y and BGN settings"))
                if self.current_mode == "Scientific" and label in self.SCIENTIFIC_TOOLTIPS:
                    button.set_tooltip_text(self.SCIENTIFIC_TOOLTIPS[label])

                self.buttons[label] = button
                self.grid.attach(button, current_col, row_idx, span, 1)
                current_col += span

        if self.use_radians and 'Rad' in self.buttons:
            self.buttons['Rad'].set_label('Deg')
        if programmer:
            self.prog_refresh_buttons()

        self.show_all()
        if converter:
            # these are left out of show_all(), so show them one by one
            for widget in (self.conv_bottom_row, self.display_bottom, *self.conv_combos):
                widget.show()
            self.conv_use_box(0)            # start in the top box
            self.conv_set_category(CURRENCY if currency else self.conv_category)
            if currency:
                self.currency_entered()
        else:
            self.conv_bottom_row.hide()
            self.conv_combos[0].hide()
            self.conv_use_box(0)
        if self.display_bottom.is_focus() or converter:
            self.display_top.grab_focus_without_selecting()
        self.update_status()
        # Translators: the window title, e.g. "Basic - Xcalculator"
        self.set_title(_("{mode} - Xcalculator").format(mode=_(self.current_mode)))
        self.apply_mode_size()

    def apply_mode_size(self):
        """Size the window for this mode, keeping the results area at its remembered height."""
        content = self.get_child()
        width = self.mode_widths.get(self.current_mode, MODE_WIDTHS.get(self.current_mode, 460))
        width = max(width, content.get_preferred_width()[0])
        height = content.get_preferred_height_for_width(width)[0] + self.history_height - HISTORY_MIN_HEIGHT
        self.expected_size = (width, height)
        self.resize(width, height)
        self.begin_settling()
        return False

    def begin_settling(self):
        """For a moment, size changes are the window settling, not the user resizing."""
        self.settling += 1
        GLib.timeout_add(500, self.end_settling)

    def end_settling(self):
        self.settling -= 1
        return False

    def on_history_allocated(self, widget, allocation):
        if not self.track_history or self.settling:
            self.track_history = False
            return
        self.track_history = False
        extra = allocation.height - widget.get_preferred_height()[0]
        self.history_height = HISTORY_MIN_HEIGHT + max(0, extra)
        self.save_window_settings()

    def reset_view(self, widget):
        """View → Reset View: the window size the calculator first opened with, in every mode."""
        self.history_height = HISTORY_MIN_HEIGHT
        self.mode_widths = {}
        self.apply_mode_size()
        self.save_window_settings()

    def reset_font_size(self, widget):
        self.base_font_size = DEFAULT_FONT_SIZE
        self.begin_settling()
        self.apply_custom_styles()
        GLib.timeout_add(150, self.apply_mode_size)
        self.save_window_settings()

    def on_menu_mode_changed(self, radio_item, mode_name):
        if radio_item.get_active() and self.current_mode != mode_name:
            if {"Programmer", *CONVERTER_MODES} & {mode_name, self.current_mode}:
                # programmer, converter and decimal expressions don't mix
                self.expression = ""
                self.is_result_active = False
                self.token_stack = []
            self.error_label.set_text("")           # an error belongs to the mode it happened in
            self.current_mode = mode_name
            self.update_view_mode_layout()
            self.update_display()
            self.save_window_settings()

    def change_font_zoom(self, widget, direction):
        new_size = self.base_font_size + direction
        if 10 <= new_size <= 24:
            self.base_font_size = new_size
            self.begin_settling()           # the window may grow to fit the new font
            self.apply_custom_styles()
            GLib.timeout_add(150, self.apply_mode_size)     # once the new font has applied: keep the results height
            self.save_window_settings()

    @staticmethod
    def theme_destructive_color():
        """The red the theme paints Clear buttons with, as CSS; None if it can't be read."""
        probe = Gtk.Button()
        probe.get_style_context().add_class("destructive-action")
        rgba = probe.get_style_context().get_property("background-color", Gtk.StateFlags.NORMAL)
        probe.destroy()
        if rgba is None or rgba.alpha < 0.5:   # theme draws it with an image instead
            return None
        return rgba.to_string()

    @staticmethod
    def theme_entry_look():
        """The theme's input field as CSS: (border color, corner radius, background color,
        text color, a faint tint of the text color for pointing at a history line)."""
        probe = Gtk.Entry()
        context = probe.get_style_context()
        border = context.get_property("border-top-color", Gtk.StateFlags.NORMAL)
        radius = context.get_property("border-radius", Gtk.StateFlags.NORMAL)
        background = context.get_property("background-color", Gtk.StateFlags.NORMAL)
        text = context.get_color(Gtk.StateFlags.NORMAL)
        probe.destroy()
        tint = f"rgba({round(text.red * 255)}, {round(text.green * 255)}, {round(text.blue * 255)}, 0.08)"
        return (border.to_string() if border is not None and border.alpha > 0 else "@borders",
                radius if isinstance(radius, int) else 3,
                background.to_string() if background is not None and background.alpha >= 0.5 else "@theme_base_color",
                text.to_string(), tint)

    @staticmethod
    def theme_button_text_color():
        """The color the theme writes button labels in, as CSS."""
        probe = Gtk.Button()
        color = probe.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        probe.destroy()
        return color.to_string()

    def apply_custom_styles(self):
        display_font = self.base_font_size + 5
        error_font = max(10, self.base_font_size - 2)
        error_color = self.theme_destructive_color() or "@error_color"
        # the history is a box drawn like the display: the same border, corners and background
        entry_border, entry_radius, entry_background, entry_text, entry_tint = self.theme_entry_look()

        style_css = f"""
            .calc-display {{
                font-size: {display_font}px;
                font-weight: bold;
                padding: 6px;
            }}
            .calc-error-label {{
                font-size: {error_font}px;
                font-weight: normal;
                color: {error_color};
                padding-right: 6px;
            }}
            .calc-status-label {{
                font-size: {max(9, self.base_font_size - 4)}px;
                color: {self.theme_button_text_color()};    /* like the buttons: easy to read on the window's grey */
                padding-left: 6px;
            }}
            .calc-history {{ font-size: {self.base_font_size}px; background-color: transparent; color: {entry_text};
                             padding: 2px 12px 2px 4px; }}  /* room on the right for the scrollbar when it shows */
            scrolledwindow.calc-history-frame {{
                border: 1px solid {entry_border};
                border-radius: {entry_radius}px;
                background-color: {entry_background};
            }}
            scrolledwindow.calc-history-frame viewport {{ background-color: transparent; }}
            .history-row {{ padding: 2px; border-radius: 3px; }}
            .history-row:hover {{ background-color: {entry_tint}; }}
            .calc-mono {{ font-family: monospace; }}
            button.compact {{ padding-left: 2px; padding-right: 2px; }}
            .numeric-button label {{ font-weight: bold; font-size: {self.base_font_size}px; }}
            button {{ padding: 8px; }}
            button label {{ font-size: {self.base_font_size}px; }}
        """.encode('utf-8')
        self.css_provider.load_from_data(style_css)

    def load_window_settings(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    mode = config.get("mode", "Basic")
                    self.current_mode = mode if mode in VALID_MODES else "Basic"
                    size = config.get("font_size", 15)
                    self.base_font_size = size if isinstance(size, int) and 10 <= size <= 24 else DEFAULT_FONT_SIZE
                    widths = config.get("mode_widths", {})
                    for name, width in (widths.items() if isinstance(widths, dict) else []):
                        if name in VALID_MODES and isinstance(width, int) and 200 <= width <= 10000:
                            self.mode_widths[name] = width
                    decimals = config.get("decimals", DEFAULT_DECIMALS)
                    if isinstance(decimals, int) and decimals >= 0:
                        NUMBER_FORMAT["decimals"] = min(decimals, MAX_DECIMALS)   # 15 without mpmath
                    NUMBER_FORMAT["show_all"] = config.get("show_all_decimals") is True
                    self.thousands = config.get("thousands") is True
                    self.use_radians = config.get("use_radians") is True
                    self.keep_history = config.get("keep_history") is True
                    modes = config.get("enabled_modes")
                    if isinstance(modes, list) and any(m in VALID_MODES for m in modes):
                        self.enabled_modes = [m for m in VALID_MODES if m in modes]
                    if self.current_mode not in self.enabled_modes:
                        self.current_mode = self.enabled_modes[0]
                    height = config.get("history_height")
                    if isinstance(height, int) and HISTORY_MIN_HEIGHT <= height <= 4000:
                        self.history_height = height
                    self.prog_base = PROG_BASES.get(config.get("prog_base"), 10)
                    bits = config.get("prog_bits")
                    self.prog_bits = bits if bits in dict(PROG_WORDS).values() else 64
                    category = config.get("conv_category")
                    self.conv_category = category if category in CONVERTER_UNITS else "Length"
                    saved_units = config.get("conv_units", {})
                    for name, pair in (saved_units.items() if isinstance(saved_units, dict) else []):
                        symbols = [unit[1] for unit in CONVERTER_UNITS.get(name, [])]
                        valid = (lambda s: isinstance(s, str) and CODE_RE.fullmatch(s)) if name == CURRENCY \
                            else (lambda s: s in symbols)
                        if isinstance(pair, list) and len(pair) == 2 and all(valid(s) for s in pair):
                            self.conv_units[name] = list(pair)
                    self.currency_auto = config.get("currency_auto") is True
                    interval = config.get("currency_interval")
                    if isinstance(interval, int) and 1 <= interval <= MAX_INTERVAL:
                        self.currency_interval = interval
                    self.currency_background = config.get("currency_background") is True
                    return
        except Exception as e:
            print(f"Failed to read settings cache: {e}")

    def save_window_settings(self):
        try:
            width, height = self.get_size()
            config = {
                "width": width,
                "height": height,
                "mode": self.current_mode,
                "font_size": self.base_font_size,
                "history_height": self.history_height,
                "mode_widths": self.mode_widths,
                "decimals": NUMBER_FORMAT["decimals"],
                "show_all_decimals": NUMBER_FORMAT["show_all"],
                "thousands": self.thousands,
                "use_radians": self.use_radians,
                "keep_history": self.keep_history,
                "enabled_modes": self.enabled_modes,
                "prog_base": self.prog_base_name(),
                "prog_bits": self.prog_bits,
                "conv_category": self.conv_category,
                "conv_units": self.conv_units,
                "currency_auto": self.currency_auto,
                "currency_interval": self.currency_interval,
                "currency_background": self.currency_background,
            }
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def on_window_resized(self, widget, event):
        if not self.settling and (event.width, event.height) != self.expected_size:
            self.track_history = True       # the user resized it, not a mode or font change
            if event.width != self.expected_size[0]:
                self.mode_widths[self.current_mode] = event.width
        self.save_window_settings()
        return False

    def make_display_entry(self):
        entry = Gtk.Entry()
        entry.set_alignment(1.0)
        entry.set_text("0")
        entry.get_style_context().add_class("entry")
        entry.get_style_context().add_class("calc-display")
        entry.connect("key-press-event", self.on_display_key_pressed)
        entry.connect("button-press-event", self.on_display_button_pressed)
        entry.connect("changed", self.on_display_changed)
        entry.drag_dest_unset()             # no dropping text into it
        entry.connect("paste-clipboard", self.on_display_paste)
        entry.connect("cut-clipboard", self.on_display_cut)
        entry.connect("notify::cursor-position", self.on_display_cursor_moved)
        entry.connect("focus-in-event", self.on_display_focus_in)
        entry.connect("size-allocate", lambda *args: self.queue_display_refit())
        return entry

    def update_display(self):
        self.set_display(self.expression or "0", fit=self.is_result_active)
        if self.current_mode == "Programmer":
            self.update_status()
        elif self.current_mode in CONVERTER_MODES:
            self.conv_refresh()

    def set_display(self, text, fit=False):
        """Show text with the cursor at the end. fit: shorten it if it doesn't fit."""
        self.display_full = text
        self.display_fit = fit
        self.refit_display()

    def answer_look(self, text):
        """An answer in a display box: × ÷ −, plus thousands separators if switched on."""
        text = show_math(text)
        return group_digits(text) if self.thousands and self.current_mode != "Programmer" else text

    def history_result_look(self, text, grouping=True):
        text = show_minus(text)
        return group_digits(text) if self.thousands and grouping else text

    def show_in_entry(self, entry, text, fit):
        """fit: an answer, which may be shortened and gets thousands separators."""
        look = self.answer_look if fit else show_math
        width = entry.get_text_area().width - 4
        if fit and width > 0:
            text = fit_text(text, width, lambda s: entry.create_pango_layout(look(s)).get_pixel_size()[0])
        text = look(text)
        self.updating_display = True
        if entry.get_text() != text:
            entry.set_text(text)
        entry.set_position(-1)
        self.updating_display = False

    def refit_display(self):
        self.refit_pending = False
        self.show_in_entry(self.display, self.display_full, self.display_fit)
        return False

    def refit_result(self):
        """The converter's other box: always a result, so it may be shortened."""
        self.show_in_entry(self.conv_other_entry(), self.conv_result_full, True)

    def refit_after_resize(self):
        self.refit_pending = False
        if self.display_fit:
            self.refit_display()
        if self.current_mode in CONVERTER_MODES:
            self.refit_result()
        return False

    def queue_display_refit(self):
        # after a resize: refit once the new size is settled
        if (self.display_fit or self.current_mode in CONVERTER_MODES) and not self.refit_pending:
            self.refit_pending = True
            GLib.idle_add(self.refit_after_resize)

    def place_cursor(self, position):
        self.updating_display = True
        self.display.set_position(position)
        self.updating_display = False

    DISPLAY_NAVIGATION_KEYS = {
        "Left", "Right", "Home", "End", "KP_Left", "KP_Right", "KP_Home", "KP_End",
        "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
    }

    def on_display_key_pressed(self, entry, event):
        """Let the display move the cursor and select, but never edit text itself."""
        keyname = Gdk.keyval_name(event.keyval)
        if keyname in self.DISPLAY_NAVIGATION_KEYS:
            return False
        if event.state & Gdk.ModifierType.CONTROL_MASK and keyname in ("a", "A", "c", "x"):
            return False                    # select all, copy, cut
        return True

    def on_display_button_pressed(self, entry, event):
        return event.button == 2            # no middle-click paste

    def on_display_changed(self, entry):
        # safety net: anything else that changes the text directly (the right-click
        # menu's Delete, an emoji) is undone
        if self.updating_display:
            return
        if entry is self.display:
            self.refit_display()
        elif self.current_mode in CONVERTER_MODES:
            self.refit_result()

    def on_display_focus_in(self, entry, event):
        """The converters: clicking the other box makes it the one you type in."""
        if self.current_mode in CONVERTER_MODES and entry is not self.display:
            self.conv_switch_box(0 if entry is self.display_top else 1)
        return False

    def on_display_paste(self, entry):
        entry.stop_emission_by_name("paste-clipboard")
        self.paste_from_clipboard(None)

    def on_display_cut(self, entry):
        entry.stop_emission_by_name("cut-clipboard")
        self.copy_to_clipboard(None)
        self.edit_at_cursor(self.handle_backspace, deleting=True)

    def on_display_cursor_moved(self, entry, pspec):
        """Clicking into a result (or moving the cursor in it) makes it editable."""
        if (self.updating_display or not self.is_result_active or self.flip_snapshot is not None
                or entry is not self.display):
            return
        self.is_result_active = False
        self.token_stack = []
        if self.display.get_text() != show_math(self.expression):     # was shown shortened
            self.set_display(self.expression, fit=False)
        else:
            self.display_fit = False

    def edit_at_cursor(self, action, deleting=False):
        """Run an editing action at the cursor instead of at the end.

        The action sees only the text before the cursor (or selection), so all the
        usual typing rules apply there; the text after it is put back afterwards.
        """
        expr = self.expression
        bounds = self.display.get_selection_bounds()
        if bounds:
            start, end = sorted(min(b, len(expr)) for b in bounds)
        else:
            start = end = min(self.display.get_position(), len(expr))
        if self.is_result_active or (start == end == len(expr)):
            action()                        # typing at the end, as before
            return
        head, tail = expr[:start], expr[end:]
        self.token_stack = []
        if deleting and start != end:       # backspace or Delete on a selection
            self.expression = head + tail
        else:
            self.expression = head
            self.edit_tail = tail
            action()
            self.edit_tail = ""
            head = self.expression
            self.expression = head + tail
            self.token_stack = []
        self.is_result_active = False
        self.update_display()
        self.place_cursor(len(head))

    def delete_forward(self):
        """Delete key: remove what's after the cursor; at the very end it clears, as before."""
        expr = self.expression
        bounds = self.display.get_selection_bounds()
        if bounds and not self.is_result_active:
            self.edit_at_cursor(self.handle_backspace, deleting=True)
            return
        position = min(self.display.get_position(), len(expr))
        if self.is_result_active or position >= len(expr):
            self.execute_action_by_label("Clr")
            return
        tail = expr[position:]
        tokens = PROG_BACKSPACE_TOKENS if self.current_mode == "Programmer" else self.BACKSPACE_TOKENS
        size = next((len(t) for t in tokens if tail.startswith(t)), 1)
        self.expression = expr[:position] + tail[size:]
        self.token_stack = []
        self.update_display()
        self.place_cursor(position)

    def on_key_pressed(self, widget, event):
        keyname = Gdk.keyval_name(event.keyval)
        if self.flip_snapshot is not None:
            return True                     # ignore typing while upside down
        modifiers = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
                                   | Gdk.ModifierType.SHIFT_MASK)
        if modifiers == Gdk.ModifierType.CONTROL_MASK and keyname:
            key = keyname.lower()
            if self.current_mode == "Scientific" and key in self.SCIENTIFIC_CONTROL_KEYS:
                self.execute_action_by_label(self.SCIENTIFIC_CONTROL_KEYS[key])
                return True
            if self.current_mode == "Programmer" and key in self.PROGRAMMER_CONTROL_KEYS:
                self.execute_action_by_label(self.PROGRAMMER_CONTROL_KEYS[key])
                return True
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if self.current_mode == "Scientific" and keyname == "p":
            self.execute_action_by_label("π")
            return True

        if keyname in ["BackSpace", "KP_Delete"]:
            self.execute_action_by_label("⌫")
            return True
        if keyname == "Delete":
            self.error_label.set_text("")
            self.delete_forward()
            return True

        direct_mappings = {
            "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
            "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
            "plus": "+", "minus": "-", "asterisk": "*", "slash": "/",
            "period": ".", "parenleft": "(", "parenright": ")",
            "percent": "%", "asciicircum": "^", "exclam": "!", "e": "e"
        }
        numpad_mappings = {
            "KP_0": "0", "KP_1": "1", "KP_2": "2", "KP_3": "3", "KP_4": "4",
            "KP_5": "5", "KP_6": "6", "KP_7": "7", "KP_8": "8", "KP_9": "9",
            "KP_Add": "+", "KP_Subtract": "-", "KP_Multiply": "*", "KP_Divide": "/",
            "KP_Decimal": ".", "KP_Insert": "0"
        }
        programmer_mappings = {
            "ampersand": "AND", "bar": "OR", "asciicircum": "XOR", "asciitilde": "NOT",
            "less": "<<", "greater": ">>", "percent": "mod",
        }

        if self.current_mode == "Programmer":
            if len(keyname) == 1 and keyname.upper() in "ABCDEF":
                self.execute_action_by_label(keyname.upper())
                return True
            if keyname in programmer_mappings:
                self.execute_action_by_label(programmer_mappings[keyname])
                return True

        if keyname in direct_mappings:
            self.execute_action_by_label(direct_mappings[keyname])
            return True
        elif keyname in numpad_mappings:
            self.execute_action_by_label(numpad_mappings[keyname])
            return True
        elif keyname in ["Return", "KP_Enter", "equal"]:
            self.execute_action_by_label("=")
            return True
        elif keyname == "Escape":
            self.execute_action_by_label("Clr")
            return True
        return False

    def copy_to_clipboard(self, widget):
        """Copy the selected part of the display, or all of it (always the full number).

        The clipboard gets plain * / - (spreadsheets don't read − as a minus sign).
        """
        bounds = self.display.get_selection_bounds()
        text = self.display_full
        if bounds:
            shown = self.display.get_text()
            if shown == show_math(self.display_full):   # shown in full: same positions
                text = self.display_full[bounds[0]:bounds[1]]
            else:                                       # shown shortened, like 3.7×10²⁰
                text = shown[bounds[0]:bounds[1]].translate(PLAIN_MATH).replace(",", "")
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()                   # keep it after the calculator closes

    def paste_from_clipboard(self, widget):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(self.on_clipboard_text)

    def on_clipboard_text(self, clipboard, text):
        if self.flip_snapshot is not None or not text:
            return
        self.error_label.set_text("")
        text = text.translate(PLAIN_MATH)   # pasting 12×3 or −5 works too
        # drop spaces and thousands separators: "1,234 567" -> "1234567"
        text = re.sub(r'(?<=\d)[,\s_](?=\d)', '', text.strip())
        if self.current_mode == "Programmer":
            self.paste_programmer(text)
        elif self.current_mode in CONVERTER_MODES:
            self.conv_paste_number(text)
        else:
            self.paste_labels(text, "0123456789.+-*/^()%!×÷−e")

    def paste_labels(self, text, allowed, message=None):
        """Paste by pressing the matching buttons, so the usual typing rules apply."""
        if len(text) > 200 or any(ch not in allowed for ch in text):
            self.error_label.set_text(message or _("Can't paste that"))
            return
        for ch in text:
            self.execute_action_by_label(ch)

    def execute_action_by_label(self, label):
        class MockWidget:
            def __init__(self, lbl): self.lbl = lbl
            def get_label(self): return self.lbl
        self.on_button_clicked(MockWidget(label))

    def on_button_clicked(self, widget):
        if self.syncing_widgets:
            return                          # a toggle button changed by the code, not a click
        label = getattr(widget, "key", None) or widget.get_label()

        if label != '=':
            self.error_label.set_text("")

        if self.current_mode == "Programmer":
            self.programmer_action(label)
            return
        if self.current_mode == "Unit Converter":
            self.converter_action(label)
            return
        if self.current_mode == "Currency Converter":
            self.currency_action(label)
            return

        if self.cpt_pending and label not in self.FIN_TVM_KEYS and label != 'CPT':
            self.cpt_pending = False
            self.update_status()

        if label in self.FIN_TVM_KEYS or label in self.FIN_ACTIONS:
            self.financial_action(label)
        elif label in ('Clear', 'Clr', 'C'):
            self.expression = ""
            self.is_result_active = False
            self.token_stack = []
            self.update_display()
        elif label == '⌫':
            self.edit_at_cursor(self.handle_backspace, deleting=True)
        elif label in ('M+', 'm+'):
            self.memory_add(1)
        elif label in ('M−', 'M-', 'm-'):
            self.memory_add(-1)
        elif label in ('MC', 'mc'):
            self.memory = 0
        elif label in ('MR', 'mr'):
            try:
                memory_text = format_number(self.memory)
            except (OverflowError, ValueError) as error:
                self.show_error(error)
            else:
                self.edit_at_cursor(lambda: self.insert_value(memory_text))
        elif label == 'Rand':
            self.edit_at_cursor(lambda: self.insert_value(format_number(random.random())))
        elif label == '±':
            self.edit_at_cursor(self.toggle_sign)
        elif label == '=':
            self.calculate()
        elif label == '2nd':
            self.toggle_second()
        elif label in ('Rad', 'Deg'):
            self.set_angle_mode(label == 'Rad')
        else:
            self.edit_at_cursor(lambda: self.append_token(label))

    def update_status(self):
        """Show stored financial values, or the value in every base, under the display."""
        visible = self.current_mode in ("Financial", "Programmer", *CONVERTER_MODES)
        self.status_label.set_visible(visible)
        context = self.status_label.get_style_context()
        if self.current_mode == "Programmer":
            context.add_class("calc-mono")
            self.status_label.set_text(show_minus(self.programmer_status_text()))
            return
        context.remove_class("calc-mono")
        # the Currency Converter's two lines never wrap, so its boxes don't move when the
        # message changes; a line too long for the window ends in "…" (the tooltip has it all)
        currency = self.current_mode == "Currency Converter"
        self.status_label.set_line_wrap(not currency)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END if currency else Pango.EllipsizeMode.NONE)
        self.status_label.set_tooltip_text(self.conv_formula.strip() if currency else None)
        if self.current_mode in CONVERTER_MODES:
            self.status_label.set_text(self.conv_formula)
            return
        if not visible:
            self.status_label.set_text("")
            return

        def fmt(value):
            try:
                return format_number(value)
            except (ValueError, OverflowError):
                return str(value)

        header = f"{'BGN' if self.begin_mode else 'END'}  ·  P/Y {fmt(self.periods_per_year)}"
        if self.cpt_pending:
            header += "  ·  CPT…"
        t = self.tvm
        lines = [
            header,
            f"N {fmt(t['N'])}   I/Y {fmt(t['I/Y'])}   PV {fmt(t['PV'])}",
            f"PMT {fmt(t['PMT'])}   FV {fmt(t['FV'])}",
        ]
        if self.cash_flows:
            parts = [fmt(a) + (f"×{c}" if c > 1 else "") for a, c in self.cash_flows[:8]]
            more = " …" if len(self.cash_flows) > 8 else ""
            lines.append("CF: " + ", ".join(parts) + more)
        if self.amort_p1 is not None or self.amort_p2 is not None:
            lines.append(f"P1 {self.amort_p1 or '—'}   P2 {self.amort_p2 or '—'}")
        self.status_label.set_text(show_minus("\n".join(lines)))

    def open_new_window(self, widget=None):
        """File → New Window: another calculator window, sharing the preferences and the saved history."""
        XCalculator(application=self.get_application()).show_all()

    def quit_calculator(self, widget=None):
        """File → Quit closes every window."""
        application = self.get_application()
        if application is None:
            Gtk.main_quit()
        else:
            application.quit()

    def other_calculators(self):
        """The other open calculator windows, which share the Preferences settings."""
        application = self.get_application()
        return [w for w in (application.get_windows() if application else [])
                if isinstance(w, XCalculator) and w is not self]

    def show_help_contents(self, widget=None, page=None):
        """Help → Documentation (F1): opens on the page for the current mode (or `page`)."""
        if self.help_window is None:
            self.help_window = HelpWindow(self)
            self.help_window.connect("destroy", lambda *args: setattr(self, "help_window", None))
        self.help_window.show_page_for(self.current_mode, page)
        self.help_window.present()

    def show_about(self, widget=None):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name("Xcalculator")
        dialog.set_version(APP_VERSION)
        dialog.set_comments(_("A calculator for Linux Mint and the Cinnamon desktop, with Basic, "
                              "Scientific, Financial, Programmer, Unit Converter, and Currency Converter modes."))
        dialog.set_logo_icon_name(APP_ID)
        # Translators: your name (and email), one translator per line; shown in About → Credits
        credits = _("translator-credits")
        if credits != "translator-credits":     # untranslated (English, or no translator named yet)
            dialog.set_translator_credits(credits)
        dialog.set_website(APP_WEBSITE)
        dialog.set_authors(APP_AUTHORS)
        dialog.set_copyright(f"{APP_COPYRIGHT}\n{APP_CREDIT}")    # the credit sits right below the author
        dialog.set_license_type(Gtk.License.GPL_3_0)    # GTK shows it as "version 3 or later"
        dialog.run()
        dialog.destroy()
