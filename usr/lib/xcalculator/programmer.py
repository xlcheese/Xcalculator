# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Programmer mode: whole numbers of a fixed bit width, signed (two's complement)."""
import gi
import re
from decimal import Decimal
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from i18n import _
from easter_egg import FLIP_TRIGGER


class ProgrammerError(ValueError):
    """A programmer-mode calculation that cannot be done; the message is shown to the user."""


PROG_BASES = {'HEX': 16, 'DEC': 10, 'OCT': 8, 'BIN': 2}


PROG_WORDS = (('QWORD', 64), ('DWORD', 32), ('WORD', 16), ('BYTE', 8))


PROG_DIGITS = {16: '0-9A-F', 10: '0-9', 8: '0-7', 2: '01'}


PROG_FORMATS = {16: 'X', 8: 'o', 2: 'b'}


# button / key label -> text inserted into the expression
PROG_OP_TEXT = {
    '+': ' + ', '-': ' − ', '−': ' − ', '*': ' × ', '×': ' × ', '/': ' ÷ ', '÷': ' ÷ ',
    'mod': ' mod ', 'AND': ' AND ', 'OR': ' OR ', 'XOR': ' XOR ',
    'NAND': ' NAND ', 'NOR': ' NOR ', '<<': ' << ', '>>': ' >> ',
}


PROG_BACKSPACE_TOKENS = [text for text in dict.fromkeys(PROG_OP_TEXT.values())] + ['NOT ']


# lowest to highest precedence, as in C
PROG_PRECEDENCE = (
    ('OR', 'NOR'), ('XOR',), ('AND', 'NAND'), ('<<', '>>'),
    ('+', '−', '-'), ('×', '÷', '*', '/', 'mod'),
)


PROG_TOKEN_RE = re.compile(r'\s*(<<|>>|[()+\-−×÷*/]|[A-Za-z0-9]+)')


PROG_LITERAL_RE = re.compile(r'(?<![A-Za-z0-9])[0-9A-F]+(?![A-Za-z0-9])')


PROG_TRAILING_LITERAL_RE = re.compile(r'(?<![A-Za-z0-9])[0-9A-F]+$')


PROG_SINGLE_VALUE_RE = re.compile(r'-?[0-9A-F]+')


def prog_wrap(value, bits):
    """Fit value into a signed two's-complement integer of the given width."""
    size = 1 << bits
    value &= size - 1
    return value - size if value >= size >> 1 else value


def prog_format(value, base, bits):
    """DEC shows the signed value; HEX/OCT/BIN show the raw bit pattern."""
    if base == 10:
        return str(value)
    return format(value & ((1 << bits) - 1), PROG_FORMATS[base])


def prog_binary_groups(value, bits):
    """Bit pattern in groups of four, split over two lines for 64 bits."""
    pattern = format(value & ((1 << bits) - 1), f'0{bits}b')
    nibbles = [pattern[i:i + 4] for i in range(0, bits, 4)]
    if bits == 64:
        return ' '.join(nibbles[:8]) + '\n     ' + ' '.join(nibbles[8:])
    return ' '.join(nibbles)


def _prog_apply(op, a, b, bits):
    if op in ('OR', 'NOR'):
        result = a | b
        return ~result if op == 'NOR' else result
    if op == 'XOR':
        return a ^ b
    if op in ('AND', 'NAND'):
        result = a & b
        return ~result if op == 'NAND' else result
    if op in ('<<', '>>'):
        if b < 0:
            raise ProgrammerError(_("Shift amount must not be negative"))
        if b >= bits:                       # everything shifted out
            return 0 if op == '<<' or a >= 0 else -1
        return a << b if op == '<<' else a >> b
    if op == '+':
        return a + b
    if op in ('−', '-'):
        return a - b
    if op in ('×', '*'):
        return a * b
    # ÷ and mod round toward zero, like C and other programmer calculators
    if b == 0:
        raise ZeroDivisionError
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    return quotient if op in ('÷', '/') else a - b * quotient


def prog_evaluate(text, base, bits):
    """Evaluate a programmer-mode expression; every step wraps to the word size."""
    tokens, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = PROG_TOKEN_RE.match(text, pos)
        if not m:
            raise SyntaxError("bad character")
        tokens.append(m.group(1))
        pos = m.end()

    literal = re.compile(f'[{PROG_DIGITS[base]}]+')
    index = 0

    def peek():
        return tokens[index] if index < len(tokens) else None

    def take():
        nonlocal index
        index += 1
        return tokens[index - 1]

    def level(i):
        if i == len(PROG_PRECEDENCE):
            return unary()
        left = level(i + 1)
        while peek() in PROG_PRECEDENCE[i]:
            op = take()
            left = prog_wrap(_prog_apply(op, left, level(i + 1), bits), bits)
        return left

    def unary():
        tok = peek()
        if tok in ('-', '−'):
            take()
            return prog_wrap(-unary(), bits)
        if tok == 'NOT':
            take()
            return prog_wrap(~unary(), bits)
        if tok == '(':
            take()
            value = level(0)
            if peek() == ')':
                take()
            elif peek() is not None:        # a missing ')' is fine only at the end
                raise SyntaxError("expected )")
            return value
        if tok is not None and literal.fullmatch(tok):
            take()
            return prog_wrap(int(tok, base), bits)
        raise SyntaxError("expected a number")

    value = level(0)
    if index != len(tokens):
        raise SyntaxError("unexpected input")
    return value


def prog_convert(expr, old_base, old_bits, new_base, new_bits):
    """Rewrite an expression for a new base and/or word size."""
    if PROG_SINGLE_VALUE_RE.fullmatch(expr):
        value = prog_wrap(prog_evaluate(expr, old_base, old_bits), new_bits)
        return prog_format(value, new_base, new_bits)

    def literal(m):
        pattern = int(m.group(), old_base) & ((1 << old_bits) - 1) & ((1 << new_bits) - 1)
        return format(pattern, PROG_FORMATS.get(new_base, 'd'))
    return PROG_LITERAL_RE.sub(literal, expr)


PROG_TOOLTIPS = {
    'HEX': _("Hexadecimal (base 16): digits 0-9 and A-F. FF = 255"),
    'DEC': _("Decimal (base 10): ordinary numbers, shown with a sign"),
    'OCT': _("Octal (base 8): digits 0-7. 17 = 15"),
    'BIN': _("Binary (base 2): digits 0 and 1. 1010 = 10"),
    'QWORD': _("Word size: click to cycle 64 → 32 → 16 → 8 bits.\n"
             "Results wrap around like a real register."),
    '<<': _("Shift left: move the bits left, filling with 0.\n1 << 4 = 16 (multiplies by 2 each step)"),
    '>>': _("Shift right: move the bits right, keeping the sign.\n16 >> 2 = 4 (divides by 2 each step)"),
    'AND': _("Bitwise AND: 1 only where both bits are 1.\n1100 AND 1010 = 1000"),
    'OR': _("Bitwise OR: 1 where either bit is 1.\n1100 OR 1010 = 1110"),
    'XOR': _("Bitwise XOR: 1 where the bits differ.\n1100 XOR 1010 = 0110"),
    'NOT': _("Bitwise NOT: flip every bit of the next number.\nNOT 0 = -1 (all bits set)"),
    'NAND': _("NOT (a AND b)"),
    'NOR': _("NOT (a OR b)"),
    'mod': _("Remainder after whole-number division. 17 mod 5 = 2"),
    '÷': _("Whole-number division; the remainder is dropped. 17 ÷ 5 = 3"),
    '±': _("Change the sign (two's complement negate)"),
}


class ProgrammerMode:
    """The Programmer keypad: bases, word sizes and bitwise operators."""

    PROGRAMMER_CONTROL_KEYS = {"h": "HEX", "d": "DEC", "o": "OCT", "b": "BIN"}

    def paste_programmer(self, text):
        prefixed = re.fullmatch(r'(-?)0([xXbBoO])([0-9A-Fa-f]+)', text)
        if prefixed:                        # 0xFF, 0b1010 and 0o17 work in any base
            sign, kind, digits = prefixed.groups()
            try:
                value = int(digits, {'x': 16, 'b': 2, 'o': 8}[kind.lower()])
            except ValueError:
                self.error_label.set_text(_("Can't paste that"))
                return
            self.edit_at_cursor(lambda: self.prog_insert_decimal(str(-value if sign else value)))
            return
        digits = "0123456789ABCDEF"[:self.prog_base]
        self.paste_labels(text.upper(), digits + "+-*/()×÷−",
                          _("Can't paste that in {base}").format(base=self.prog_base_name()))

    def prog_base_name(self):
        return next(name for name, base in PROG_BASES.items() if base == self.prog_base)

    def prog_word_name(self):
        return next(name for name, bits in PROG_WORDS if bits == self.prog_bits)

    def prog_eval(self, expr):
        return prog_evaluate(expr, self.prog_base, self.prog_bits)

    def prog_text(self, value):
        return prog_format(value, self.prog_base, self.prog_bits)

    def programmer_status_text(self):
        if not self.expression:
            self.prog_preview = 0
        else:
            try:
                self.prog_preview = self.prog_eval(self.expression)
            except Exception:
                pass                            # half-typed expression: keep the last value
        value, bits = self.prog_preview, self.prog_bits
        return "\n".join([
            # Translators: under the Programmer display, e.g. "QWORD (64-bit, signed)  ·  typing in DEC"
            _("{word} ({bits}-bit, signed)  ·  typing in {base}").format(
                word=self.prog_word_name(), bits=bits, base=self.prog_base_name()),
            f"HEX  {prog_format(value, 16, bits)}",
            f"DEC  {value}",
            f"OCT  {prog_format(value, 8, bits)}",
            f"BIN  {prog_binary_groups(value, bits)}",
        ])

    def prog_refresh_buttons(self):
        for digit in "23456789ABCDEF":
            button = self.buttons.get(digit)
            if button:
                button.set_sensitive(int(digit, 16) < self.prog_base)
        self.syncing_widgets = True
        for name, base in PROG_BASES.items():
            button = self.buttons.get(name)
            if button:
                button.set_active(base == self.prog_base)
        self.syncing_widgets = False
        word_button = self.buttons.get('QWORD')
        if word_button:
            word_button.set_label(self.prog_word_name())

    def prog_ends_with_operand(self, expr):
        return expr.endswith(')') or bool(PROG_TRAILING_LITERAL_RE.search(expr))

    def prog_operand_start(self, expr):
        """Index where the number or (group) at the end of expr begins."""
        if expr.endswith(')'):
            depth = 0
            for k in range(len(expr) - 1, -1, -1):
                if expr[k] == ')':
                    depth += 1
                elif expr[k] == '(':
                    depth -= 1
                    if depth == 0:
                        return k
            return None
        m = PROG_TRAILING_LITERAL_RE.search(expr)
        return m.start() if m else None

    def programmer_action(self, label):
        if label in PROG_BASES:
            self.prog_change_format(PROG_BASES[label], self.prog_bits)
        elif label in dict(PROG_WORDS):
            names = [name for name, bits in PROG_WORDS]
            next_name = names[(names.index(self.prog_word_name()) + 1) % len(names)]
            self.prog_change_format(self.prog_base, dict(PROG_WORDS)[next_name])
        elif label in ('Clear', 'Clr'):
            self.expression = ""
            self.is_result_active = False
            self.token_stack = []
            self.update_display()
        elif label == '⌫':
            self.edit_at_cursor(self.handle_backspace, deleting=True)
        elif label == '±':
            self.edit_at_cursor(self.prog_toggle_sign)
        elif label == '=':
            self.prog_calculate()
        elif label == 'NOT':
            self.edit_at_cursor(self.prog_not)
        elif len(label) == 1 and label in "0123456789ABCDEF":
            self.edit_at_cursor(lambda: self.prog_digit(label))
        elif label in PROG_OP_TEXT:
            self.edit_at_cursor(lambda: self.prog_binary(PROG_OP_TEXT[label]))
        elif label in ('(', ')'):
            self.edit_at_cursor(lambda: self.prog_paren(label))

    def prog_change_format(self, base, bits):
        if (base, bits) == (self.prog_base, self.prog_bits):
            self.prog_refresh_buttons()     # clicking the selected base keeps it selected
            return
        try:
            self.expression = prog_convert(self.expression, self.prog_base, self.prog_bits, base, bits)
        except Exception:
            self.expression = ""                # can't be converted: start over
            self.is_result_active = False
        self.token_stack = []
        self.prog_base, self.prog_bits = base, bits
        self.prog_refresh_buttons()
        self.update_display()
        self.save_window_settings()
        self.sync_preferences()

    def prog_digit(self, digit):
        if int(digit, 16) >= self.prog_base:
            return
        if self.is_result_active:
            self.expression = ""
            self.token_stack = []
            self.is_result_active = False
        expr = self.expression
        if expr.endswith(')'):
            return
        m = PROG_TRAILING_LITERAL_RE.search(expr)
        number = (m.group() if m else '') + digit
        # stop typing once the number no longer fits in the word size
        limit = (1 << (self.prog_bits - 1)) if self.prog_base == 10 else (1 << self.prog_bits) - 1
        if int(number, self.prog_base) > limit:
            return
        if m and m.group() == '0':              # no leading zeros
            self.expression = expr[:-1]
            if self.token_stack and self.token_stack[-1] == '0':
                self.token_stack.pop()
        self.push(digit)
        self.update_display()

    def prog_binary(self, op_text):
        self.is_result_active = False           # operators continue from a result
        expr = self.expression
        minus = op_text == ' − '
        if expr == '':
            if minus:
                self.push('-')
            else:
                self.push('0')
                self.push(op_text)
        elif expr.endswith(('(', '-')):
            if minus and not expr.endswith('-'):
                self.push('-')                  # unary minus: (-5
        elif expr.endswith(' '):                # ends with an operator or "NOT "
            if expr.endswith('NOT '):
                pass
            elif minus:
                self.push('-')                  # unary minus: 5 × -3
            else:
                for text in PROG_BACKSPACE_TOKENS:
                    if expr.endswith(text):     # replace the previous operator
                        self.expression = expr[:-len(text)]
                        self.token_stack = []
                        self.push(op_text)
                        break
        else:
            self.push(op_text)
        self.update_display()

    def prog_not(self):
        self.is_result_active = False
        expr = self.expression
        start = self.prog_operand_start(expr) if expr else None
        if start is not None:                   # NOT applies to the number just typed
            self.expression = expr[:start] + 'NOT ' + expr[start:]
            self.token_stack = []
        else:
            self.push('NOT ')
        self.update_display()

    def prog_paren(self, paren):
        expr = self.expression
        if paren == '(':
            if self.is_result_active:
                self.expression, self.token_stack = "", []
                self.is_result_active = False
            elif self.prog_ends_with_operand(expr):
                return
            self.push('(')
        elif expr.count('(') > expr.count(')') and self.prog_ends_with_operand(expr):
            self.push(')')
        self.update_display()

    def prog_toggle_sign(self):
        expr = self.expression
        if expr in ("", "0"):
            return
        if PROG_SINGLE_VALUE_RE.fullmatch(expr):
            self.expression = self.prog_text(prog_wrap(-self.prog_eval(expr), self.prog_bits))
        else:
            wrapped = re.search(r'\(-([0-9A-F]+)\)$', expr)
            number = PROG_TRAILING_LITERAL_RE.search(expr)
            if wrapped:
                self.expression = expr[:wrapped.start()] + wrapped.group(1)
            elif number:
                self.expression = expr[:number.start()] + '(-' + number.group() + ')'
            else:
                return
        self.token_stack = []
        self.update_display()

    def prog_insert_decimal(self, text):
        """Insert a decimal value (a history result) in the current base."""
        try:
            number = Decimal(text)
            if not number.is_finite() or number != number.to_integral_value():
                raise ProgrammerError(_("Not a whole number"))
        except ArithmeticError:
            self.show_error(ProgrammerError(_("Not a whole number")))
            return
        except ProgrammerError as error:
            self.show_error(error)
            return
        piece = self.prog_text(prog_wrap(int(number), self.prog_bits))
        if self.is_result_active or not self.expression:
            self.expression = piece
        else:
            expr = self.expression
            if expr.endswith(')'):
                return
            m = PROG_TRAILING_LITERAL_RE.search(expr)
            if m:
                expr = expr[:m.start()]
            self.expression = expr + (f"({piece})" if piece.startswith('-') and expr else piece)
        self.is_result_active = False
        self.token_stack = []
        self.update_display()

    def prog_calculate(self):
        if self.is_result_active or not self.expression:
            return
        formula = self.expression
        try:
            value = self.prog_eval(formula)
        except Exception as error:
            self.show_error(error)
            return
        result_text = self.prog_text(value)
        self.set_display(result_text, fit=True)
        self.add_to_history_display(f"{formula.strip()}   [{self.prog_base_name()}]", result_text, grouping=False,
                                    formula_clickable=False, click_text=str(value))
        self.expression = result_text
        self.is_result_active = True
        self.token_stack = []
        self.update_status()

        if self.prog_base == 10 and formula == FLIP_TRIGGER:
            GLib.timeout_add(50, self.start_flip)
