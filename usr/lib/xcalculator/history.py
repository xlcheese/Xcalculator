# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The history above the display: rows that shrink with the window, and the saved file."""
import gi
import json
import os
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
from i18n import _
from config import CONFIG_DIR, CONVERTER_MODES, HISTORY_FILE, MAX_SAVED_HISTORY
from engine import fit_text, show_math, show_minus
from converter import CONVERTER_UNITS
from currency import CURRENCY


class FitLabel(Gtk.Label):
    """A label that shows its text in full when it fits, else a shorter form (see fit_text)."""

    def __init__(self, text, template="{}", show=None):
        super().__init__()
        self.full_text = text
        self.template = template            # markup around the text, e.g. "<b>{}</b>"
        self.show = show or (lambda s: s)   # how the text looks on screen, e.g. − for -
        self.show_text(text)

    def markup_for(self, text):
        return self.template.format(GLib.markup_escape_text(self.show(text)))

    def show_text(self, text):
        markup = self.markup_for(text)
        if markup != self.get_label():
            self.set_markup(markup)

    def measure(self, text):
        layout = self.create_pango_layout(None)
        layout.set_markup(self.markup_for(text), -1)
        return layout.get_pixel_size()[0]

    def refresh(self):
        """Redraw now with the current look (e.g. thousands separators switched on).
        The next layout pass shortens it again if the new look no longer fits."""
        self.show_text(self.full_text)
        self.queue_resize()

    def do_get_preferred_width(self):
        # asks for the full width, but can make do with the shortest form
        return (self.measure(fit_text(self.full_text, 0, self.measure)),
                self.measure(self.full_text))

    def do_size_allocate(self, allocation):
        self.show_text(fit_text(self.full_text, allocation.width, self.measure))
        Gtk.Label.do_size_allocate(self, allocation)


class HistoryRow(Gtk.Box):
    """Formula then result, right-aligned. When space runs short the formula keeps
    up to half the row (cut at the front with '…') and the result fits in the rest."""
    GAP = 4

    def __init__(self, formula_widget, result_widget):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=self.GAP)
        self.formula_widget = formula_widget
        self.result_widget = result_widget
        self.pack_start(formula_widget, False, False, 0)
        self.pack_start(result_widget, False, False, 0)

    def do_size_allocate(self, allocation):
        Gtk.Box.do_size_allocate(self, allocation)      # sizes the box itself
        formula_min, formula_nat = self.formula_widget.get_preferred_width()
        result_min, result_nat = self.result_widget.get_preferred_width()
        width = allocation.width
        formula_share = max(formula_min, min(formula_nat, width // 2))
        result_w = max(result_min, min(result_nat, width - self.GAP - formula_share))
        label = self.result_widget.get_child()
        if isinstance(label, FitLabel):     # only as wide as the shortened text
            result_w = min(result_w, label.measure(fit_text(label.full_text, result_w, label.measure)))
        formula_w = max(0, min(formula_nat, width - self.GAP - result_w))
        right = allocation.x + width
        for widget, x, w in ((self.result_widget, right - result_w, result_w),
                             (self.formula_widget, right - result_w - self.GAP - formula_w, formula_w)):
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = x, allocation.y, w, allocation.height
            widget.size_allocate(rect)


class SavedHistory:
    """The saved history file, shared by every window: each answer is added to the end."""
    rows = None                             # read from the file the first time it's needed

    @classmethod
    def load(cls):
        if cls.rows is None:
            cls.rows = []
            try:
                with open(HISTORY_FILE) as f:
                    cls.rows = [r for r in json.load(f)
                                if isinstance(r, dict) and "formula" in r and "result" in r][-MAX_SAVED_HISTORY:]
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"Failed to read saved history: {e}")
        return cls.rows

    @classmethod
    def add(cls, row):
        rows = cls.load()
        rows.append(row)
        del rows[:-MAX_SAVED_HISTORY]       # keep the newest 500 lines
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(HISTORY_FILE, "w") as f:
                json.dump(rows, f)
        except Exception as e:
            print(f"Failed to save history: {e}")

    @classmethod
    def delete(cls):
        cls.rows = []
        try:
            os.remove(HISTORY_FILE)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"Failed to delete saved history: {e}")


class HistoryPanel:
    """Adding answers to the history, clicking them, clearing and loading it."""

    HISTORY_KEYS = ("formula", "result", "clickable", "click_text", "restore", "grouping")

    def scroll_to_bottom(self):
        """Show the newest line. GTK measures a new row a little later, so keep following
        the history's height for a moment (see on_history_height_changed)."""
        self.follow_history = True
        adj = self.scrolled_window.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        GLib.timeout_add(500, self.stop_following_history)
        return False

    def stop_following_history(self):
        self.follow_history = False
        return False

    def on_history_height_changed(self, adj):
        if getattr(self, "follow_history", False):
            adj.set_value(adj.get_upper() - adj.get_page_size())

    def add_to_history_display(self, formula, result, formula_clickable=True, click_text=None,
                               restore=None, grouping=True, save=True):
        """click_text is the decimal value inserted when the result is clicked.
        restore: a Unit Converter conversion that clicking the row brings back.
        grouping: the result may get thousands separators (not for Programmer answers)."""
        try:
            expr_box = Gtk.EventBox()
            expr_box.set_visible_window(False)
            is_calculation = formula_clickable and not restore   # Basic/Scientific: × ÷ − on screen
            shown_formula = show_math(formula) if is_calculation else show_minus(formula)
            # the calculation in the history's own text color, softer, so the answer stands out
            expr_label = Gtk.Label(label=f"<span alpha='60%'>{GLib.markup_escape_text(shown_formula)}  =</span>")
            expr_label.set_use_markup(True)
            expr_label.set_ellipsize(Pango.EllipsizeMode.START)
            expr_box.add(expr_label)
            if restore:
                expr_box.connect("button-press-event", self.on_history_conversion_clicked, restore, None)
                expr_box.set_tooltip_text(_("Click to bring back this conversion"))
            elif formula_clickable:     # financial entries are labels, not formulas
                expr_box.connect("button-press-event", self.on_history_expr_clicked, formula)
                expr_box.set_tooltip_text(_("Click to use this calculation again"))

            res_box = Gtk.EventBox()
            res_box.set_visible_window(False)
            res_box.add(FitLabel(result, "<b>{}</b>", show=lambda s, g=grouping: self.history_result_look(s, g)))
            if restore:
                res_box.connect("button-press-event", self.on_history_conversion_clicked, restore, click_text)
                res_box.set_tooltip_text(_("Click to bring back this conversion"))
            else:
                res_box.connect("button-press-event", self.on_history_res_clicked, click_text or result)
                res_box.set_tooltip_text(_("Click to use this number"))

            hbox = HistoryRow(expr_box, res_box)
            hbox.set_margin_end(2)

            row_container = Gtk.EventBox()
            row_container.get_style_context().add_class("history-row")
            row_container.set_visible_window(False)
            row_container.add(hbox)

            self.history_listbox.add(row_container)
            self.history_entries.append({"formula": formula, "result": result, "shown_formula": shown_formula,
                                         "clickable": formula_clickable, "click_text": click_text,
                                         "restore": list(restore) if restore else None, "grouping": grouping})
            self.update_print_actions()
            if save:
                SavedHistory.add({k: self.history_entries[-1][k] for k in self.HISTORY_KEYS})
            self.history_listbox.show_all()
            GLib.idle_add(self.scroll_to_bottom)
        except Exception as e:
            print(f"History display error: {e}")

    def on_history_expr_clicked(self, widget, event, formula):
        if event.button == 1 and self.current_mode == "Programmer":
            return True                     # decimal formulas can't be edited as programmer input
        if event.button == 1:
            self.error_label.set_text("")
            if self.is_result_active or not self.expression:
                self.expression = formula
            else:
                self.expression += f"({formula})"
            self.is_result_active = False
            self.token_stack = []
            self.update_display()
            return True
        return False

    def on_history_conversion_clicked(self, widget, event, restore, number):
        """A captured conversion: bring it back, or use its number in the other modes."""
        if event.button != 1:
            return False
        if self.current_mode == ("Currency Converter" if restore[0] == CURRENCY else "Unit Converter"):
            self.error_label.set_text("")
            self.conv_restore(*restore)
        elif number is not None:
            self.on_history_res_clicked(widget, event, number)
        return True

    def on_history_res_clicked(self, widget, event, result):
        if event.button == 1:
            self.error_label.set_text("")
            if self.current_mode in CONVERTER_MODES:
                self.conv_paste_number(result)
            elif self.current_mode == "Programmer":
                self.edit_at_cursor(lambda: self.prog_insert_decimal(result))
            else:
                self.edit_at_cursor(lambda: self.insert_value(result))
            return True
        return False

    def clear_history(self, widget):
        """View → Clear History empties the window; the saved file keeps the record."""
        for child in self.history_listbox.get_children():
            self.history_listbox.remove(child)
        self.history_entries = []
        self.update_print_actions()

    def load_saved_history(self):
        """Read the saved record; show it in the window only if Keep history is on."""
        rows = SavedHistory.load()
        if not self.keep_history:
            return
        try:
            for row in list(rows):
                restore = row.get("restore")
                if restore and not (len(restore) == 4 and (restore[0] in CONVERTER_UNITS or restore[0] == CURRENCY)):
                    restore = None
                self.add_to_history_display(str(row["formula"]), str(row["result"]), row.get("clickable") is True,
                                            row.get("click_text"), tuple(restore) if restore else None,
                                            row.get("grouping") is not False, save=False)
        except Exception as e:
            print(f"Failed to read saved history: {e}")
