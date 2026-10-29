# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scientific mode: functions, the 2nd key, angle units and the f(x) menu."""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from i18n import _
from engine import (
    MATH, _combinations, _factorial, _permutations, _round_half_up, _sign, _snap, check_angle
)


class ScientificMode:
    """The Scientific keys that Basic doesn't have."""

    # button label -> text inserted into the expression
    FUNCTION_MAP = {
        'sin': 'sin(', 'cos': 'cos(', 'tan': 'tan(',
        'sinh': 'sinh(', 'cosh': 'cosh(', 'tanh': 'tanh(',
        'sin⁻¹': 'asin(', 'cos⁻¹': 'acos(', 'tan⁻¹': 'atan(',
        'sinh⁻¹': 'asinh(', 'cosh⁻¹': 'acosh(', 'tanh⁻¹': 'atanh(',
        '²√x': 'sqrt(', 'sqrt': 'sqrt(', '³√x': 'cbrt(',
        'ln': 'log(', 'log₁₀': 'log10(',
        '|x|': 'abs(', 'round': 'round(',
        'floor': 'floor(', 'ceil': 'ceil(', 'int': 'int(', 'frac': 'frac(', 'sgn': 'sgn(',
        'log₂': 'log2(', 'sec': 'sec(', 'csc': 'csc(', 'cot': 'cot(',
    }

    # Scientific's f(x) menu: (button label, what it does)
    MORE_FUNCTIONS = (
        ('floor', _("round down to a whole number:  floor(2.7) = 2")),
        ('ceil', _("round up to a whole number:  ceil(2.1) = 3")),
        ('int', _("the whole-number part:  int(−2.7) = −2")),
        ('frac', _("the part after the decimal point:  frac(2.75) = 0.75")),
        ('sgn', _("the sign:  −1, 0, or 1")),
        ('log₂', _("logarithm base 2:  log₂(8) = 3")),
        ('sec', _("secant, 1 ÷ cos")),
        ('csc', _("cosecant, 1 ÷ sin")),
        ('cot', _("cotangent, cos ÷ sin")),
    )

    SCIENTIFIC_TOOLTIPS = {
        '|x|': _("Absolute value: the number without its sign.  |−5| = 5"),
        'nCr': _("Combinations: ways to choose r items from n when order doesn't matter.\n5 nCr 2 = 10"),
        'nPr': _("Permutations: ways to arrange r items from n when order matters.\n5 nPr 2 = 20"),
        'round': _("Round to the nearest whole number.  round(2.5) = 3"),
        'f(x)': _("More functions"),
        'mod': _("Remainder after division.  17 mod 5 = 2"),
    }

    SECOND_FUNCTIONS = {
        'sin': 'sin⁻¹', 'cos': 'cos⁻¹', 'tan': 'tan⁻¹',
        'sinh': 'sinh⁻¹', 'cosh': 'cosh⁻¹', 'tanh': 'tanh⁻¹',
    }

    SCIENTIFIC_CONTROL_KEYS = {"r": "²√x", "i": "1/x"}     # GNOME Calculator's square root and inverse

    def build_functions(self):
        M = MATH                            # ordinary floats, or mpmath when installed

        def to_rad(x):
            return check_angle(x if self.use_radians else M.radians(x))

        def from_rad(x):
            return x if self.use_radians else M.degrees(x)

        def tan(x):
            r = to_rad(x)
            if abs(M.cos(r)) < M.epsilon():
                raise ValueError("tan is undefined here")
            return _snap(M.tan(r))

        def reciprocal_trig(function, name):
            def f(x):
                value = _snap(function(to_rad(x)))
                if value == 0:
                    raise ValueError(f"{name} is undefined here")
                return M.divide(1, value)
            return f

        def cot(x):                         # cos ÷ sin, so cot(90°) = 0
            r = to_rad(x)
            sine = _snap(M.sin(r))
            if sine == 0:
                raise ValueError("cot is undefined here")
            return M.divide(_snap(M.cos(r)), sine)

        def whole(function):                # floor, ceil and int give whole numbers
            return lambda x: x if isinstance(x, int) else function(x)

        return {
            "sin": lambda x: _snap(M.sin(to_rad(x))),
            "cos": lambda x: _snap(M.cos(to_rad(x))),
            "tan": tan,
            "asin": lambda x: from_rad(M.asin(x)),
            "acos": lambda x: from_rad(M.acos(x)),
            "atan": lambda x: from_rad(M.atan(x)),
            "sinh": M.sinh, "cosh": M.cosh, "tanh": M.tanh,
            "asinh": M.asinh, "acosh": M.acosh, "atanh": M.atanh,
            "sqrt": M.sqrt, "cbrt": M.cbrt,
            "log": M.log, "log10": M.log10,
            "factorial": _factorial,
            "abs": abs, "round": _round_half_up, "floor": whole(M.floor), "ceil": whole(M.ceil),
            "int": whole(M.trunc), "frac": lambda x: x - whole(M.trunc)(x), "sgn": _sign, "log2": M.log2,
            "sec": reciprocal_trig(M.cos, "sec"), "csc": reciprocal_trig(M.sin, "csc"),
            "cot": cot,
            "comb": _combinations, "perm": _permutations,
        }

    def make_more_functions_button(self):
        """Scientific's f(x): a menu of extra functions, each with a short explanation."""
        menu = Gtk.Menu()
        for name, description in self.MORE_FUNCTIONS:
            item = Gtk.MenuItem()
            label = Gtk.Label(xalign=0)
            label.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>   "
                             f"<span alpha='65%'>{GLib.markup_escape_text(description)}</span>")
            item.add(label)
            item.connect("activate", lambda _item, n=name: self.execute_action_by_label(n))
            menu.append(item)
        menu.show_all()
        button = Gtk.MenuButton()
        box = Gtk.Box(spacing=4)
        box.set_halign(Gtk.Align.CENTER)
        box.pack_start(Gtk.Label(label="f(x)"), False, False, 0)
        box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        button.add(box)
        button.set_popup(menu)
        return button

    def toggle_second(self):
        self.second_active = not self.second_active
        for base, inverse in self.SECOND_FUNCTIONS.items():
            button = self.buttons.get(base)
            if button:
                button.set_label(inverse if self.second_active else base)

    def set_angle_mode(self, radians):
        self.use_radians = radians
        button = self.buttons.get('Rad')
        if button:
            button.set_label('Deg' if radians else 'Rad')
        self.save_window_settings()
        self.sync_preferences()
