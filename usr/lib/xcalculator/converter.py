# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit Converter mode: exact factors from the official definitions."""
import re
from decimal import Decimal, localcontext
from fractions import Fraction
from i18n import N_, _
from config import CONVERTER_MODES
from engine import DECIMAL_RE, format_fraction
from currency import CURRENCY, CURRENCY_START


PI = Fraction("3.14159265358979323846264338327950288419716939937510582097494")


_LB = Fraction("0.45359237")                # kg, exact


_LBF = _LB * Fraction("9.80665")            # N, exact


_IN = Fraction("0.0254")                    # m, exact


_GAL = Fraction("0.003785411784")           # US gallon in m³, exact


# category -> [(name, symbol, size in the category's base unit)], US units first.
# Temperature has no single factor; its entries are converted by temperature_to_kelvin.
CONVERTER_UNITS = {
    N_("Angle"): [(N_("Degree"), "°", 1), (N_("Radian"), "rad", 180 / PI), (N_("Gradian"), "grad", Fraction("0.9")),
              (N_("Arcminute"), "′", Fraction(1, 60)), (N_("Arcsecond"), "″", Fraction(1, 3600)), (N_("Turn"), "turn", 360)],
    N_("Area"): [(N_("Square inch"), "in²", _IN ** 2), (N_("Square foot"), "ft²", (12 * _IN) ** 2),
             (N_("Square yard"), "yd²", (36 * _IN) ** 2), (N_("Acre"), "ac", 43560 * (12 * _IN) ** 2),
             (N_("Square mile"), "mi²", (63360 * _IN) ** 2), (N_("Square centimeter"), "cm²", Fraction(1, 10000)),
             (N_("Square meter"), "m²", 1), (N_("Hectare"), "ha", 10000), (N_("Square kilometer"), "km²", 1000000)],
    N_("Density"): [(N_("Gram per cubic centimeter"), "g/cm³", 1000), (N_("Kilogram per cubic meter"), "kg/m³", 1),
                (N_("Gram per milliliter"), "g/mL", 1000), (N_("Kilogram per liter"), "kg/L", 1000),
                (N_("Pound per cubic foot"), "lb/ft³", _LB / (12 * _IN) ** 3),
                (N_("Pound per cubic inch"), "lb/in³", _LB / _IN ** 3),
                (N_("Pound per gallon"), "lb/gal", _LB / _GAL)],
    N_("Digital Storage"): [(N_("Bit"), "bit", 1), (N_("Byte"), "B", 8), (N_("Kilobyte"), "kB", 8 * 10 ** 3),
                        (N_("Megabyte"), "MB", 8 * 10 ** 6), (N_("Gigabyte"), "GB", 8 * 10 ** 9),
                        (N_("Terabyte"), "TB", 8 * 10 ** 12), (N_("Petabyte"), "PB", 8 * 10 ** 15),
                        (N_("Kibibyte"), "KiB", 8 * 2 ** 10), (N_("Mebibyte"), "MiB", 8 * 2 ** 20),
                        (N_("Gibibyte"), "GiB", 8 * 2 ** 30), (N_("Tebibyte"), "TiB", 8 * 2 ** 40),
                        (N_("Kilobit"), "kbit", 10 ** 3), (N_("Megabit"), "Mbit", 10 ** 6), (N_("Gigabit"), "Gbit", 10 ** 9)],
    N_("Energy"): [(N_("Joule"), "J", 1), (N_("Kilojoule"), "kJ", 1000), (N_("Calorie"), "cal", Fraction("4.184")),
               (N_("Food Calorie"), "kcal", 4184), (N_("Watt-hour"), "Wh", 3600), (N_("Kilowatt-hour"), "kWh", 3600000),
               (N_("British thermal unit"), "BTU", Fraction("1055.05585262")),
               (N_("Foot-pound"), "ft·lbf", 12 * _IN * _LBF), (N_("Electronvolt"), "eV", Fraction("1.602176634e-19"))],
    N_("Length"): [(N_("Inch"), "in", _IN), (N_("Foot"), "ft", 12 * _IN), (N_("Yard"), "yd", 36 * _IN),
               (N_("Mile"), "mi", 63360 * _IN), (N_("Nautical mile"), "nmi", 1852), (N_("Millimeter"), "mm", Fraction(1, 1000)),
               (N_("Centimeter"), "cm", Fraction(1, 100)), (N_("Meter"), "m", 1), (N_("Kilometer"), "km", 1000)],
    N_("Mass"): [(N_("Ounce"), "oz", _LB / 16), (N_("Pound"), "lb", _LB), (N_("Stone"), "st", 14 * _LB),
             (N_("US ton"), "ton", 2000 * _LB), (N_("Milligram"), "mg", Fraction(1, 10 ** 6)),
             (N_("Gram"), "g", Fraction(1, 1000)), (N_("Kilogram"), "kg", 1), (N_("Metric ton"), "t", 1000)],
    N_("Pressure"): [(N_("Pound per square inch"), "psi", _LBF / _IN ** 2), (N_("Inch of mercury"), "inHg", Fraction("3386.389")),
                 (N_("Millimeter of mercury"), "mmHg", Fraction("133.322387415")), (N_("Atmosphere"), "atm", 101325),
                 (N_("Bar"), "bar", 100000), (N_("Pascal"), "Pa", 1), (N_("Kilopascal"), "kPa", 1000),
                 (N_("Megapascal"), "MPa", 10 ** 6)],
    N_("Speed"): [(N_("Mile per hour"), "mph", 63360 * _IN / 3600), (N_("Foot per second"), "ft/s", 12 * _IN),
              (N_("Knot"), "kn", Fraction(1852, 3600)), (N_("Kilometer per hour"), "km/h", Fraction(1000, 3600)),
              (N_("Meter per second"), "m/s", 1)],
    N_("Temperature"): [(N_("Fahrenheit"), "°F", None), (N_("Celsius"), "°C", None), (N_("Kelvin"), "K", None)],
    N_("Time"): [(N_("Millisecond"), "ms", Fraction(1, 1000)), (N_("Second"), "s", 1), (N_("Minute"), "min", 60),
             (N_("Hour"), "h", 3600), (N_("Day"), "d", 86400), (N_("Week"), "wk", 604800),
             (N_("Month (average)"), "mo", Fraction("2629746")), (N_("Year (average)"), "yr", Fraction("31556952"))],
    N_("Volume"): [(N_("Teaspoon"), "tsp", _GAL / 768), (N_("Tablespoon"), "tbsp", _GAL / 256), (N_("Fluid ounce"), "fl oz", _GAL / 128),
               (N_("Cup"), "cup", _GAL / 16), (N_("Pint"), "pt", _GAL / 8), (N_("Quart"), "qt", _GAL / 4),
               (N_("Gallon"), "gal", _GAL), (N_("Milliliter"), "mL", Fraction(1, 10 ** 6)), (N_("Liter"), "L", Fraction(1, 1000)),
               (N_("Cubic meter"), "m³", 1), (N_("Cubic inch"), "in³", _IN ** 3), (N_("Cubic foot"), "ft³", (12 * _IN) ** 3),
               (N_("Imperial gallon"), "imp gal", Fraction("0.00454609"))],
}


CONVERTER_CATEGORIES = tuple(CONVERTER_UNITS)


# what each category starts with the first time: (top unit, bottom unit)
CONVERTER_START = {
    "Angle": ("°", "rad"), "Area": ("ft²", "m²"), "Density": ("g/cm³", "lb/ft³"),
    "Digital Storage": ("GB", "GiB"), "Energy": ("kcal", "kJ"), "Length": ("in", "cm"),
    "Mass": ("lb", "kg"), "Pressure": ("psi", "bar"), "Speed": ("mph", "km/h"),
    "Temperature": ("°F", "°C"), "Time": ("h", "min"), "Volume": ("gal", "L"),
}


TEMPERATURE_FORMULAS = {
    ("°F", "°C"): "°C = (°F − 32) × 5 ÷ 9", ("°C", "°F"): "°F = °C × 9 ÷ 5 + 32",
    ("°C", "K"): "K = °C + 273.15", ("K", "°C"): "°C = K − 273.15",
    ("°F", "K"): "K = (°F − 32) × 5 ÷ 9 + 273.15", ("K", "°F"): "°F = (K − 273.15) × 9 ÷ 5 + 32",
}


CONVERTER_MAX_INPUT = 40                    # characters in a box


def converter_factor(category, symbol):
    return next(Fraction(size) for name, sym, size in CONVERTER_UNITS[category] if sym == symbol)


def temperature_to_kelvin(value, symbol):
    if symbol == "°F":
        return (value - 32) * Fraction(5, 9) + Fraction("273.15")
    if symbol == "°C":
        return value + Fraction("273.15")
    return value


def temperature_from_kelvin(value, symbol):
    if symbol == "°F":
        return (value - Fraction("273.15")) * Fraction(9, 5) + 32
    if symbol == "°C":
        return value - Fraction("273.15")
    return value


def convert_units(value, category, from_symbol, to_symbol):
    """Convert an exact Fraction between two units of a category."""
    if category == "Temperature":
        return temperature_from_kelvin(temperature_to_kelvin(value, from_symbol), to_symbol)
    return value * converter_factor(category, from_symbol) / converter_factor(category, to_symbol)


def format_exact(value, digits=12):
    """A Fraction as plain decimal text, rounded to 12 significant digits like the other modes."""
    if value == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 60
        rounded = Decimal(format(Decimal(value.numerator) / Decimal(value.denominator), f'.{digits}g'))
        text = format(rounded, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def is_terminating(value, digits=12):
    """True when a Fraction is written exactly in at most `digits` significant digits."""
    return Fraction(Decimal(format_exact(value, digits))) == value


def group_thousands(text):
    whole, dot, fraction = text.partition('.')
    return f"{int(whole):,}{dot}{fraction}" if len(whole.lstrip('-')) > 4 else text


def converter_formula(category, from_symbol, to_symbol):
    """The line under the boxes, e.g. 'cm = in × 2.54' or 'mi² = ft² ÷ 27,878,400'."""
    if from_symbol == to_symbol:
        return _("Same unit")
    if category == "Temperature":
        return _("Formula:  {formula}").format(formula=TEMPERATURE_FORMULAS[(from_symbol, to_symbol)])
    factor = converter_factor(category, from_symbol) / converter_factor(category, to_symbol)
    if is_terminating(factor) and (factor >= 1 or not is_terminating(1 / factor)):
        op, number = "×", factor
    elif is_terminating(1 / factor):
        op, number = "÷", 1 / factor
    else:                                   # neither is exact: show the one that is at least 1
        op, number = ("×", factor) if factor >= 1 else ("÷", 1 / factor)
    equals = "=" if is_terminating(number) else "≈"
    formula = f"{to_symbol} {equals} {from_symbol} {op} {group_thousands(format_exact(number))}"
    return _("Formula:  {formula}").format(formula=formula)


class ConverterMode:
    """The Unit Converter: two boxes, a unit beside each, converted as you type."""

    def conv_other_entry(self):
        return self.display_bottom if self.display is self.display_top else self.display_top

    def conv_use_box(self, index):
        self.conv_active = index
        self.display = (self.display_top, self.display_bottom)[index]
        self.show_backspace_icon()

    def conv_current_category(self):
        """The category on screen; the Currency Converter's is CURRENCY."""
        return CURRENCY if self.current_mode == "Currency Converter" else self.conv_category

    def conv_set_category(self, category):
        if category == CURRENCY:
            units = self.currency_units()
            codes = [code for name, code, size in units]
            if not all(code in codes for code in self.conv_units[CURRENCY]):
                self.conv_units[CURRENCY] = list(CURRENCY_START)    # a currency the bank dropped
        else:
            self.conv_category = category
            units = CONVERTER_UNITS[category]
        self.syncing_widgets = True
        for name in CONVERTER_UNITS:
            button = self.buttons.get(name)
            if button:
                button.set_active(name == category)
        for index, combo in enumerate(self.conv_combos):
            combo.remove_all()
            for name, symbol, size in units:
                shown = name if category == CURRENCY else _(name)     # currency names come translated
                combo.append(symbol, f"{shown} ({symbol})" if name != symbol else symbol)
            combo.set_active_id(self.conv_units[category][index])
        self.syncing_widgets = False
        self.conv_refresh()

    def on_conv_unit_changed(self, combo, index):
        if self.syncing_widgets or combo.get_active_id() is None:
            return
        self.conv_units[self.conv_current_category()][index] = combo.get_active_id()
        self.conv_refresh()
        self.save_window_settings()

    def conv_input_value(self):
        """The typed number as an exact Fraction; an empty box counts as 0."""
        text = self.expression
        if text in ("", "-", ".", "-."):
            return Fraction(0)
        try:
            return Fraction(text)
        except (ValueError, ZeroDivisionError):
            return None

    def conv_refresh(self):
        """Convert the typed number into the other box and update the formula line."""
        if self.current_mode not in CONVERTER_MODES:
            return
        category = self.conv_current_category()
        from_symbol = self.conv_units[category][self.conv_active]
        to_symbol = self.conv_units[category][1 - self.conv_active]
        value = self.conv_input_value()
        if category == CURRENCY:
            self.conv_result_full, self.conv_formula = self.currency_convert(value, from_symbol, to_symbol)
        else:
            self.conv_result_full = ("" if value is None else
                                     format_fraction(convert_units(value, category, from_symbol, to_symbol)))
            self.conv_formula = converter_formula(category, from_symbol, to_symbol)
        self.refit_result()
        self.update_status()

    def conv_switch_box(self, index):
        """Type in the other box from now on, starting from the number it shows."""
        number = self.conv_result_full
        self.conv_use_box(index)
        self.expression = number if DECIMAL_RE.fullmatch(number) else ""
        self.token_stack = []
        self.is_result_active = False
        self.update_display()

    def converter_action(self, label):
        if label in CONVERTER_UNITS:
            self.conv_set_category(label)
            self.save_window_settings()
        elif label in ('Clear', 'C', 'Clr'):
            self.expression = ""
            self.update_display()
        elif label == '⌫':
            self.edit_at_cursor(self.handle_backspace, deleting=True)
        elif label in ('Capture', '='):
            self.conv_capture()
        elif label in ('±', '-', '−'):
            self.conv_toggle_sign()
        elif label == '.':
            if '.' not in self.expression:
                self.edit_at_cursor(lambda: self.conv_type('.'))
        elif len(label) == 1 and label.isdigit():
            self.edit_at_cursor(lambda: self.conv_type(label))

    def conv_type(self, char):
        head = self.expression              # the text before the cursor
        if len(head) + len(self.edit_tail) >= CONVERTER_MAX_INPUT:
            return
        if char == '.':
            self.expression = head + ('0.' if head in ('', '-') else '.')
        elif head in ('0', '-0') and not self.edit_tail:
            self.expression = head[:-1] + char     # no leading zeros
        else:
            self.expression = head + char
        self.update_display()

    def conv_toggle_sign(self):
        position = min(self.display.get_position(), len(self.expression))
        if self.expression.startswith('-'):
            self.expression = self.expression[1:]
            position = max(0, position - 1)
        else:
            self.expression = '-' + self.expression
            position += 1
        self.update_display()
        self.place_cursor(position)

    def conv_paste_number(self, text):
        """Paste (or a clicked history result): a plain number, inserted at the cursor."""
        if not re.fullmatch(r'-?(\d+(?:\.\d*)?|\.\d+)', text) or len(text) > CONVERTER_MAX_INPUT:
            self.error_label.set_text(_("Can't paste that"))
            return
        if text.startswith('-'):
            if not self.expression.startswith('-'):
                self.conv_toggle_sign()
            text = text[1:]
        for char in text:
            self.converter_action(char)

    def conv_capture(self):
        """Capture: add the conversion on screen to the history."""
        if not self.conv_result_full:
            return
        category = self.conv_current_category()
        from_symbol = self.conv_units[category][self.conv_active]
        to_symbol = self.conv_units[category][1 - self.conv_active]
        typed = self.expression if self.expression not in ("", "-", ".", "-.") else "0"
        self.add_to_history_display(f"{typed} {from_symbol}", f"{self.conv_result_full} {to_symbol}",
                                    click_text=self.conv_result_full,
                                    restore=(category, from_symbol, to_symbol, typed))

    def conv_restore(self, category, from_symbol, to_symbol, typed):
        """Bring back a captured conversion: category, both units and the number."""
        self.conv_units[category] = [from_symbol, to_symbol]
        self.conv_use_box(0)
        self.expression = typed
        self.token_stack = []
        self.conv_set_category(category)
        self.update_display()
        self.display.grab_focus_without_selecting()
        self.save_window_settings()
