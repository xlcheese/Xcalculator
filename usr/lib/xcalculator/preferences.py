# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit → Preferences, laid out like Xed's."""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from i18n import _
from config import CONVERTER_MODES, VALID_MODES
from currency import DEFAULT_INTERVAL, MAX_INTERVAL, Rates, background_refresh_available, set_background_refresh
from engine import DEFAULT_DECIMALS, MAX_DECIMALS, NUMBER_FORMAT, format_number, mpmath
from history import SavedHistory


MODE_DESCRIPTIONS = {
    "Basic": _("Everyday arithmetic"),
    "Scientific": _("Powers, roots, trigonometry, logarithms and more"),
    "Financial": _("Loans, savings, cash flows and depreciation"),
    "Programmer": _("Hexadecimal, binary and bitwise operations"),
    "Unit Converter": _("Lengths, weights, temperatures and more"),
    "Currency Converter": _("Exchange rates from the European Central Bank"),
}


PREF_BASES = ((_("Hexadecimal (HEX)"), 16), (_("Decimal (DEC)"), 10), (_("Octal (OCT)"), 8), (_("Binary (BIN)"), 2))


PREF_WORDS = ((_("64-bit (QWORD)"), 64), (_("32-bit (DWORD)"), 32), (_("16-bit (WORD)"), 16), (_("8-bit (BYTE)"), 8))


class PreferencesWindow(Gtk.Window):
    """Edit → Preferences, laid out like Xed's: pages on the left, buttons along the bottom.
    Every change takes effect at once."""

    def __init__(self, calculator):
        super().__init__(title=_("Xcalculator Preferences"), transient_for=calculator, destroy_with_parent=True)
        self.calculator = calculator
        self.syncing = False
        self.set_default_size(620, self.screen_height(820))    # every General setting, if the screen allows
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self.stack = Gtk.Stack()
        self.stack.add_titled(self.build_general_page(), "General", _("General"))
        self.stack.add_titled(self.build_modes_page(), "Modes", _("Modes"))
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        pages = Gtk.Box()
        pages.pack_start(sidebar, False, False, 0)
        pages.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        pages.pack_start(self.stack, True, True, 0)
        frame = Gtk.Frame()
        frame.add(pages)

        documentation = Gtk.Button(label=_("Documentation"))
        documentation.connect("clicked", lambda b: calculator.show_help_contents(page="Preferences"))
        reset = Gtk.Button(label=_("Reset to Defaults"))
        reset.set_tooltip_text(_("Put every preference back the way it was the first time. "
                                 "The saved history is kept."))
        reset.connect("clicked", lambda b: calculator.reset_preferences())
        close = Gtk.Button(label=_("Close"))
        close.connect("clicked", lambda b: self.destroy())
        buttons = Gtk.Box(spacing=6)
        buttons.pack_start(documentation, False, False, 0)
        buttons.set_center_widget(reset)
        buttons.pack_end(close, False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("start", "end", "top", "bottom"):
            getattr(outer, f"set_margin_{side}")(12)
        outer.pack_start(frame, True, True, 0)
        outer.pack_start(buttons, False, False, 0)
        self.add(outer)
        self.connect("key-press-event", self.on_key)
        self.sync()
        self.show_all()

    # --- building blocks
    @staticmethod
    def page():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{side}")(16)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(box)
        return scroller, box

    @staticmethod
    def screen_height(wanted):
        """wanted, or less on a short screen, leaving room for the panel and the title bar."""
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return min(wanted, monitor.get_workarea().height - 80) if monitor else wanted

    @staticmethod
    def heading(box, text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        if box.get_children():
            label.set_margin_top(10)
        box.pack_start(label, False, False, 0)

    @staticmethod
    def row(box, title, control, subtitle=None):
        """A setting: its name (and an example underneath) on the left, the control on the right."""
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        name = Gtk.Label(label=title, xalign=0)
        text.pack_start(name, False, False, 0)
        hint = None
        if subtitle is not None:
            hint = Gtk.Label(label=subtitle, xalign=0)
            hint.get_style_context().add_class("dim-label")
            hint.set_line_wrap(True)
            text.pack_start(hint, False, False, 0)
        line = Gtk.Box(spacing=12)
        line.set_margin_start(12)
        line.pack_start(text, True, True, 0)
        control.set_valign(Gtk.Align.CENTER)
        line.pack_end(control, False, False, 0)
        box.pack_start(line, False, False, 0)
        return hint

    @staticmethod
    def combo(choices, changed):
        combo = Gtk.ComboBoxText()
        for label, value in choices:
            combo.append_text(label)
        combo.connect("changed", changed)
        return combo

    def build_general_page(self):
        scroller, box = self.page()
        c = self.calculator
        self.heading(box, _("Numbers"))
        self.decimals = Gtk.SpinButton.new_with_range(0, MAX_DECIMALS, 1)
        self.decimals.connect("value-changed", lambda s: self.changed(lambda: c.set_number_format(decimals=s.get_value_as_int())))
        self.row(box, _("Decimal places"), self.decimals,
                 _("Up to 50 places, using high-precision math (mpmath).") if mpmath
                 else _("Up to 15 places. Install python3-mpmath for up to 50."))
        self.show_all_switch = Gtk.Switch()
        self.show_all_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_number_format(show_all=s.get_active())))
        self.show_all_hint = self.row(box, _("Show all decimal places"), self.show_all_switch, "")
        self.thousands_switch = Gtk.Switch()
        self.thousands_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_number_format(thousands=s.get_active())))
        self.row(box, _("Thousands separators"), self.thousands_switch, _("1234567 shows as 1,234,567."))

        self.heading(box, _("Scientific"))
        self.angle = self.combo(((_("Degrees"), False), (_("Radians"), True)),
                                lambda w: self.changed(lambda: c.set_angle_mode(w.get_active() == 1)))
        self.row(box, _("Angle units"), self.angle, _("Also changed by the Rad/Deg button."))

        self.heading(box, _("Programmer"))
        self.word = self.combo(PREF_WORDS, lambda w: self.changed(
            lambda: c.set_programmer_format(c.prog_base, PREF_WORDS[w.get_active()][1])))
        self.row(box, _("Word size"), self.word, _("Also changed by the QWORD/DWORD/WORD/BYTE button."))
        self.base = self.combo(PREF_BASES, lambda w: self.changed(
            lambda: c.set_programmer_format(PREF_BASES[w.get_active()][1], c.prog_bits)))
        self.row(box, _("Starting number base"), self.base, _("Also changed by the HEX, DEC, OCT and BIN buttons."))

        self.heading(box, _("Currency Converter"))
        self.currency_auto_switch = Gtk.Switch()
        self.currency_auto_switch.connect("notify::active", lambda s, p: self.changed(
            lambda: c.set_currency_auto(s.get_active())))
        self.currency_auto_hint = self.row(box, _("Refresh rates automatically"), self.currency_auto_switch, "")
        self.currency_days = Gtk.SpinButton.new_with_range(1, MAX_INTERVAL, 1)
        self.currency_days.connect("value-changed", lambda s: self.changed(
            lambda: c.set_currency_interval(s.get_value_as_int())))
        self.row(box, _("Refresh interval in days"), self.currency_days, _("Number of days between automatic refreshes."))
        self.currency_closed_switch = Gtk.Switch()
        self.currency_closed_switch.connect("notify::active", lambda s, p: self.changed(
            lambda: c.set_currency_background(s.get_active())))
        self.currency_closed_hint = self.row(box, _("Also when Xcalculator is closed"), self.currency_closed_switch, "")

        self.heading(box, _("History"))
        self.keep_switch = Gtk.Switch()
        self.keep_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_keep_history(s.get_active())))
        self.row(box, _("Keep history after closing"), self.keep_switch,
                 _("Show the saved history when Xcalculator opens. It is always saved "
                   "in ~/.config/xcalculator/history.json."))
        delete = Gtk.Button(label=_("Delete Saved History…"))
        delete.connect("clicked", self.on_delete_history)
        self.row(box, _("Saved history"), delete, _("Clear the history and delete the saved file."))
        return scroller

    def build_modes_page(self):
        scroller, box = self.page()
        self.heading(box, _("Show in the Mode menu"))
        self.mode_switches = {}
        for mode in VALID_MODES:
            switch = Gtk.Switch()
            switch.connect("notify::active", lambda s, p, m=mode: self.changed(
                lambda: self.calculator.set_mode_enabled(m, s.get_active())))
            self.row(box, _(mode), switch, MODE_DESCRIPTIONS[mode])
            self.mode_switches[mode] = switch
        note = Gtk.Label(label=_("At least one mode stays on."), xalign=0)
        note.get_style_context().add_class("dim-label")
        note.set_margin_top(10)
        box.pack_start(note, False, False, 0)
        return scroller

    # --- keeping the controls and the calculator in step
    def changed(self, apply):
        if not self.syncing:
            apply()
            self.sync()

    def sync(self):
        """Show the calculator's current settings (they can also change from its buttons)."""
        c = self.calculator
        self.syncing = True
        decimals = NUMBER_FORMAT["decimals"]
        self.decimals.set_value(decimals)
        self.show_all_switch.set_active(NUMBER_FORMAT["show_all"])
        self.show_all_hint.set_text(_("2.5 shows as {example}.").format(example="2.5" + "0" * (decimals - 1))
                                    if decimals > 1 else _("Pads answers with zeros to every decimal place."))
        self.thousands_switch.set_active(c.thousands)
        self.angle.set_active(1 if c.use_radians else 0)
        self.word.set_active([bits for name, bits in PREF_WORDS].index(c.prog_bits))
        self.base.set_active([base for name, base in PREF_BASES].index(c.prog_base))
        self.keep_switch.set_active(c.keep_history)
        have_rates = Rates.get() is not None
        self.currency_auto_switch.set_active(c.currency_auto)
        self.currency_auto_switch.set_sensitive(have_rates)     # like the Auto Refresh button
        self.currency_auto_hint.set_text(
            _("The same as the Auto Refresh button. Rates come from the European Central Bank.") if have_rates
            else _("Click Download Rates in the Currency Converter first."))
        self.currency_days.set_value(c.currency_interval)
        self.currency_days.set_sensitive(c.currency_auto)
        available = background_refresh_available()
        self.currency_closed_switch.set_active(c.currency_background)
        self.currency_closed_switch.set_sensitive(c.currency_auto and available)
        self.currency_closed_hint.set_text(
            _("Needs Xcalculator installed from its package.") if not available
            else _("Rates will refresh in the background even when closed.") if c.currency_background
            else _("Rates will only refresh while Xcalculator is open."))
        for mode, switch in self.mode_switches.items():
            on = mode in c.enabled_modes
            switch.set_active(on)
            switch.set_sensitive(not (on and len(c.enabled_modes) == 1))   # the last one can't go
        self.syncing = False

    def on_delete_history(self, button):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text=_("Delete the saved history?"))
        dialog.format_secondary_text(_("This clears the history and deletes the saved file. It can't be undone."))
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Delete"), Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
        if dialog.run() == Gtk.ResponseType.OK:
            self.calculator.delete_saved_history()
        dialog.destroy()

    def on_key(self, widget, event):
        if Gdk.keyval_name(event.keyval) == "Escape":
            self.destroy()
            return True
        return False


class PreferencesActions:
    """What the Preferences window changes; every open window follows."""

    def show_preferences(self, widget=None):
        """Edit → Preferences."""
        if self.preferences_window is None:
            self.preferences_window = PreferencesWindow(self)
            self.preferences_window.connect("destroy", lambda *args: setattr(self, "preferences_window", None))
        self.preferences_window.present()

    def sync_preferences(self):
        """Keep an open Preferences window in step with the buttons (Rad/Deg, bases, word size)."""
        if self.preferences_window is not None:
            self.preferences_window.sync()

    def set_number_format(self, decimals=None, show_all=None, thousands=None, everywhere=True):
        if decimals is not None:
            NUMBER_FORMAT["decimals"] = decimals
        if show_all is not None:
            NUMBER_FORMAT["show_all"] = show_all
        if thousands is not None:
            self.thousands = thousands
        # re-show the answer on screen with the new settings; the history keeps its digits
        if self.current_mode in CONVERTER_MODES:
            self.conv_refresh()
        elif self.is_result_active and self.result_value is not None and self.current_mode != "Programmer":
            try:
                text = format_number(self.result_value)
            except (OverflowError, ValueError):
                text = self.expression
            self.expression = text
            self.set_display(text, fit=True)
        else:
            self.refit_display()
        for row in self.history_listbox.get_children():     # thousands separators in the history
            row.get_child().get_child().result_widget.get_child().refresh()
        self.save_window_settings()
        if everywhere:
            for window in self.other_calculators():
                window.set_number_format(decimals, show_all, thousands, everywhere=False)
                window.sync_preferences()

    def set_programmer_format(self, base, bits):
        if self.current_mode == "Programmer":
            self.prog_change_format(base, bits)     # also converts the number on screen
        else:
            self.prog_base, self.prog_bits = base, bits
            self.save_window_settings()

    def set_mode_enabled(self, mode, enabled, everywhere=True):
        if enabled and mode not in self.enabled_modes:
            self.enabled_modes = [m for m in VALID_MODES if m in self.enabled_modes or m == mode]
        elif not enabled and mode in self.enabled_modes and len(self.enabled_modes) > 1:
            self.enabled_modes = [m for m in self.enabled_modes if m != mode]
        self.apply_enabled_modes()
        self.save_window_settings()
        if everywhere:
            for window in self.other_calculators():
                window.set_mode_enabled(mode, enabled, everywhere=False)
                window.sync_preferences()

    def apply_enabled_modes(self):
        """Hide switched-off modes from the Mode menu; leave a switched-off mode if it's in use."""
        for mode, item in self.mode_items.items():
            item.set_visible(mode in self.enabled_modes)
        if self.current_mode not in self.enabled_modes:
            self.mode_items[self.enabled_modes[0]].set_active(True)

    def set_keep_history(self, keep, everywhere=True):
        """Whether the saved history is shown when the calculator opens. It is always saved."""
        self.keep_history = keep
        self.save_window_settings()
        if everywhere:
            for window in self.other_calculators():
                window.set_keep_history(keep, everywhere=False)
                window.sync_preferences()

    def set_currency_auto(self, on, everywhere=True):
        """Preferences → Refresh rates automatically, and the Auto Refresh button."""
        self.currency_auto = on
        self.currency_settings_changed(everywhere, lambda window: window.set_currency_auto(on, everywhere=False))
        if on and self.current_mode == "Currency Converter":
            self.currency_entered()             # rates already due: refresh now

    def set_currency_interval(self, days, everywhere=True):
        self.currency_interval = days
        self.currency_settings_changed(everywhere, lambda window: window.set_currency_interval(days, everywhere=False))

    def set_currency_background(self, on, everywhere=True):
        self.currency_background = on
        self.currency_settings_changed(everywhere, lambda window: window.set_currency_background(on, everywhere=False))

    def currency_settings_changed(self, everywhere, same_in):
        self.save_window_settings()
        if self.current_mode == "Currency Converter":
            self.currency_refresh_buttons()
        if everywhere:
            for window in self.other_calculators():
                same_in(window)
                window.sync_preferences()
            # the daily background check runs only while both switches are on
            set_background_refresh(self.currency_auto and self.currency_background)

    def delete_saved_history(self):
        """Preferences → Delete Saved History: empties the history in every window, and its saved file."""
        SavedHistory.delete()
        for window in [self] + self.other_calculators():
            window.clear_history(None)

    def reset_preferences(self):
        """Preferences → Reset to Defaults."""
        self.set_angle_mode(False)
        self.set_programmer_format(10, 64)
        for mode in VALID_MODES:
            self.set_mode_enabled(mode, True)
        self.set_keep_history(False)        # the saved file itself is left alone
        self.set_number_format(DEFAULT_DECIMALS, False, False)
        self.set_currency_background(False)
        self.set_currency_interval(DEFAULT_INTERVAL)
        self.set_currency_auto(False)
        self.sync_preferences()
