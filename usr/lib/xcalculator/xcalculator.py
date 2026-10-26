#!/usr/bin/env python3
# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
import gi
import math
import traceback
import json
import os
import re
import ast
import operator
import random
import subprocess
import sys
from datetime import datetime
from decimal import Decimal, localcontext, ROUND_HALF_EVEN, ROUND_HALF_UP
from fractions import Fraction
gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

# High-precision maths (package python3-mpmath): up to 50 decimal places instead of 15.
# Without it the calculator uses ordinary floating-point numbers.
try:
    import mpmath
except ImportError:
    mpmath = None

# The 5318008 easter egg and printing need cairo (package python3-gi-cairo).
# Without it the calculator works normally; those two are skipped or greyed out.
try:
    gi.require_foreign('cairo')
    import cairo
except ImportError:
    cairo = None

CONFIG_FILE = os.path.expanduser("~/.config/xcalculator_bounds.json")
HISTORY_FILE = os.path.expanduser("~/.config/xcalculator_history.json")
MAX_SAVED_HISTORY = 500
APP_VERSION = "0.9"
APP_WEBSITE = "https://github.com/xlcheese/Xcalculator"
APP_AUTHORS = ["Wesley Hayslip"]
APP_COPYRIGHT = "Copyright © 2026 Wesley Hayslip"
APP_CREDIT = "Developed with the help of Claude, an AI assistant by Anthropic"

DEFAULT_FONT_SIZE = 15
HISTORY_MIN_HEIGHT = 75     # results area: first-time height and the smallest allowed (~3½ lines)
# window width for each mode; the height fits the buttons plus the results area
MODE_WIDTHS = {"Basic": 340, "Scientific": 460, "Financial": 500,
               "Programmer": 500, "Unit Converter": 500}

VALID_MODES = ("Basic", "Scientific", "Financial", "Programmer", "Unit Converter")
MODE_KEYS = {"Basic": "b", "Scientific": "s", "Financial": "f", "Programmer": "p", "Unit Converter": "u"}


class FinanceError(ValueError):
    """A financial calculation that cannot be done; the message is shown to the user."""


class ProgrammerError(ValueError):
    """A programmer-mode calculation that cannot be done; the message is shown to the user."""


# ---------------------------------------------------------------------------
# Expression handling
# ---------------------------------------------------------------------------

MAX_INT_BITS = 14000      # keeps results printable (Python limits int->str to 4300 digits)
MAX_FACTORIAL = 1000
MAX_PERIODS = 5000        # cap on amortization periods / expanded cash flows

# Easter egg: "5318008 =" turns the calculator upside down.
FLIP_TRIGGER = "5318008"
FLIP_TURN_SECONDS = 0.6   # time to spin over (and back)
FLIP_HOLD_SECONDS = 5.0   # time spent upside down


class FloatMath:
    """Ordinary floating-point numbers (about 15 significant digits)."""
    name = "float"
    sin, cos, tan, asin, acos, atan = math.sin, math.cos, math.tan, math.asin, math.acos, math.atan
    sinh, cosh, tanh, asinh, acosh, atanh = math.sinh, math.cosh, math.tanh, math.asinh, math.acosh, math.atanh
    sqrt, log, log10, log2 = math.sqrt, math.log, math.log10, math.log2
    radians, degrees = math.radians, math.degrees
    floor, ceil, trunc = math.floor, math.ceil, math.trunc

    @staticmethod
    def number(text):                   # a typed number like 0.1
        return float(text)

    @staticmethod
    def constant(name):
        return {"pi": math.pi, "e": math.e}[name]

    @staticmethod
    def cbrt(x):
        return math.copysign(abs(x) ** (1 / 3), x)

    @staticmethod
    def divide(a, b):
        return a / b

    @staticmethod
    def power(a, b):
        result = operator.pow(a, b)
        if isinstance(result, complex):
            raise ValueError("complex result")
        return result

    @staticmethod
    def epsilon():                      # below this counts as zero (cos 90° = 6e-17)
        return 1e-12

    @staticmethod
    def to_decimal(x):
        return Decimal(repr(x))

    @staticmethod
    def is_number(x):
        return isinstance(x, float)


def _real_only(function):
    """An mpmath function that, like ordinary maths, refuses complex or infinite answers."""
    def f(*args):
        result = function(*args)
        if isinstance(result, mpmath.mpc):
            if result.imag != 0:
                raise ValueError("complex result")
            result = result.real
        if mpmath.isinf(result) or mpmath.isnan(result):
            raise ValueError("undefined")
        return result
    return staticmethod(f)


class HighMath:
    """mpmath numbers: as many digits as the chosen decimal places need.
    Only real answers are allowed, as with ordinary floats (√−1 is an error)."""
    name = "mpmath"
    _real = _real_only

    if mpmath:
        sin, cos, tan = _real(mpmath.sin), _real(mpmath.cos), _real(mpmath.tan)
        asin, acos, atan = _real(mpmath.asin), _real(mpmath.acos), _real(mpmath.atan)
        sinh, cosh, tanh = _real(mpmath.sinh), _real(mpmath.cosh), _real(mpmath.tanh)
        asinh, acosh, atanh = _real(mpmath.asinh), _real(mpmath.acosh), _real(mpmath.atanh)
        sqrt, log, log10 = _real(mpmath.sqrt), _real(mpmath.ln), _real(mpmath.log10)
        log2 = _real(lambda x: mpmath.log(x, 2))
        radians, degrees = staticmethod(mpmath.radians), staticmethod(mpmath.degrees)

    @staticmethod
    def floor(x):
        return int(mpmath.floor(x))

    @staticmethod
    def ceil(x):
        return int(mpmath.ceil(x))

    @staticmethod
    def trunc(x):
        return int(x)

    @staticmethod
    def number(text):
        return mpmath.mpf(text)         # exact: 0.1 stays one tenth, not a binary fraction

    @staticmethod
    def constant(name):
        return +{"pi": mpmath.pi, "e": mpmath.e}[name]     # + gives it at today's precision

    @staticmethod
    def cbrt(x):
        root = mpmath.cbrt(abs(x))
        return -root if x < 0 else root

    @staticmethod
    def divide(a, b):
        if b == 0:
            raise ZeroDivisionError
        return mpmath.mpf(a) / b

    @staticmethod
    def power(a, b):
        if a == 0 and b < 0:
            raise ZeroDivisionError
        result = mpmath.power(a, b)
        if isinstance(result, mpmath.mpc):
            if result.imag != 0:
                raise ValueError("complex result")
            result = result.real
        if mpmath.isinf(result):
            raise OverflowError("result too large")
        return result

    @staticmethod
    def epsilon():
        return mpmath.mpf(10) ** -(mpmath.mp.dps - 5)

    @staticmethod
    def to_decimal(x):
        return Decimal(mpmath.nstr(x, mpmath.mp.dps - 5, strip_zeros=False))

    @staticmethod
    def is_number(x):
        return isinstance(x, mpmath.mpf)


MATH = HighMath if mpmath else FloatMath
MAX_TRIG_BITS = 4000        # angles beyond about 10^1200 would make mpmath work out π to that many digits


def check_angle(x):
    """sin, cos and tan of an astronomically large angle: refuse instead of hanging."""
    if mpmath and isinstance(x, mpmath.mpf) and x != 0 and mpmath.mag(x) > MAX_TRIG_BITS:
        raise OverflowError("angle too large")
    return x


def set_precision(decimals, whole_digits=0):
    """mpmath works with the shown decimal places, the digits before the point, and guard digits."""
    if mpmath:
        mpmath.mp.dps = max(decimals, FLOAT_DIGITS) + whole_digits + GUARD_DIGITS


def digits_before_point(value):
    """About how many digits an mpmath answer has before the decimal point (0 for small ones)."""
    if not (mpmath and isinstance(value, mpmath.mpf)) or value == 0:
        return 0
    return max(0, int(mpmath.mag(value) * 0.30103) + 1)       # mag is the power of two


def _snap(value):
    """Remove arithmetic dust such as cos(90 deg) = 6e-17."""
    return 0 * value if abs(value) < MATH.epsilon() else value


def _safe_pow(a, b):
    # Stop things like 9^9^9 from freezing the window.
    if isinstance(a, int) and isinstance(b, int) and b > 0 and abs(a) > 1:
        if b * math.log2(abs(a)) > MAX_INT_BITS:
            raise OverflowError("result too large")
    if isinstance(a, int) and isinstance(b, int) and b >= 0:
        return a ** b                       # whole numbers stay exact
    return MATH.power(a, b)


def _divide(a, b):
    return MATH.divide(a, b)


def _modulo(a, b):
    if b == 0:
        raise ZeroDivisionError
    return a % b


def _factorial(x):
    if x != int(x) or x < 0:
        raise ValueError("factorial needs a non-negative integer")
    if x > MAX_FACTORIAL:
        raise OverflowError("result too large")
    return math.factorial(int(x))


def _percent_change(old, new):
    return _divide(new - old, old) * 100


def _margin(cost, price):
    return _divide(price - cost, price) * 100


# '@' is used internally for "old D% new" and '//' for "cost Mrgn price"
# (see XCalculator.prepare); they share the precedence of * and /.
BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: _divide, ast.Mod: _modulo, ast.Pow: _safe_pow,
    ast.MatMult: _percent_change, ast.FloorDiv: _margin,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
CONSTANTS = ("pi", "e")

TOKEN_RE = re.compile(r'\d+\.?\d*|\.\d+|[A-Za-z_]\w*|\*\*|\S')
# (?<!\d) and the single way to split digits keep these fast on huge numbers;
# the plain form takes about a minute on a 3800-digit number mid-expression.
TRAILING_NUM_RE = re.compile(r'(?<!\d)(\d+(?:\.\d*)?|\.\d+)$')


# Preferences → General: how answers are written. Set by the calculator at start-up.
NUMBER_FORMAT = {"decimals": 10, "show_all": False}
DEFAULT_DECIMALS = 10
FLOAT_DIGITS = 15           # significant digits ordinary arithmetic keeps reliably
MAX_DECIMALS = 50 if mpmath else FLOAT_DIGITS
GUARD_DIGITS = 20           # extra digits mpmath works with, so the shown ones are right


def format_decimal(number):
    """An exact Decimal as answer text, rounded to the chosen number of decimal places.

    A number so small it would round to 0 keeps its significant digits instead,
    so it can still be shown (in scientific notation if it doesn't fit).
    """
    decimals, show_all = NUMBER_FORMAT["decimals"], NUMBER_FORMAT["show_all"]
    if number == 0:
        text = "0"
    else:
        with localcontext() as ctx:
            ctx.prec = max(number.adjusted(), 0) + decimals + 10
            rounded = number.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)   # 2.5 -> 3, like school and money
            if rounded == 0:                # e.g. 0.0000000000123 with 10 decimals
                text = format(Decimal(format(number, f'.{max(decimals, 1)}g')), 'f')
                return text.rstrip('0').rstrip('.') if '.' in text else text
            text = format(rounded, 'f')
        if '.' in text and not show_all:
            text = text.rstrip('0').rstrip('.')
        if text == "-0":
            text = "0"
    if show_all and decimals and '.' not in text:
        text += '.' + '0' * decimals        # "Show all decimal places": 2 -> 2.0000000000
    return text


def format_number(value):
    """Turn a result into display text: no float noise, never uses e-notation."""
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int):
        if value.bit_length() > MAX_INT_BITS:
            raise OverflowError("result too large")
        return format_decimal(Decimal(value)) if NUMBER_FORMAT["show_all"] else str(value)
    if mpmath and isinstance(value, mpmath.mpc):
        raise ValueError("complex result")
    if mpmath and isinstance(value, mpmath.mpf):
        if mpmath.isnan(value):
            raise ValueError("not a number")
        if mpmath.isinf(value) or (value != 0 and mpmath.mag(value) > MAX_INT_BITS):
            raise OverflowError("result too large")
        return format_decimal(MATH.to_decimal(value))
    if math.isnan(value):
        raise ValueError("not a number")
    if math.isinf(value):
        raise OverflowError("result too large")
    return format_decimal(Decimal(f"{value:.{FLOAT_DIGITS}g}"))


def format_fraction(value):
    """An exact Fraction (Unit Converter) as answer text, using the same rules."""
    with localcontext() as ctx:
        ctx.prec = 140                      # 50 decimal places even on very large numbers
        return format_decimal(Decimal(value.numerator) / Decimal(value.denominator))


def group_digits(text):
    """Thousands separators in every whole-number part: 1234567.891 -> 1,234,567.891."""
    return re.sub(r'(?<![\d.,])(\d{4,})', lambda m: f"{int(m.group(1)):,}", text)


SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
# Expressions are kept with * / - inside; the screen and the printout show × ÷ −.
# Each swap is one character for one, so cursor positions line up exactly.
SHOW_MATH = str.maketrans({'*': '×', '/': '÷', '-': '−'})
PLAIN_MATH = str.maketrans({'×': '*', '÷': '/', '−': '-'})


def show_math(text):
    return text.translate(SHOW_MATH)


def show_minus(text):
    """Only the minus signs: for labels and units with a real "/" or hyphen (I/Y, km/h, 64-bit)."""
    return re.sub(r'-(?=[\d.(])', '−', text)
DECIMAL_RE = re.compile(r'-?\d+(\.\d+)?')
MAX_SHOWN_DIGITS = 60


def scientific_text(text, digits):
    """'369729637649...' with 3 digits -> '3.7×10¹⁹⁷' (trailing zeros dropped)."""
    with localcontext() as ctx:
        ctx.prec = digits
        ctx.rounding = ROUND_HALF_EVEN
        rounded = +Decimal(text)
        exponent = rounded.adjusted()
        mantissa = format(rounded.scaleb(-exponent), 'f')
    if '.' in mantissa:
        mantissa = mantissa.rstrip('0').rstrip('.')
    return f"{mantissa}×10{str(exponent).translate(SUPERSCRIPT)}"


def fit_text(text, width, measure):
    """The best way to show text in width pixels (measure gives a string's width).

    Shows text in full when it fits. A decimal number that doesn't fit switches to
    scientific notation with as many digits as fit; anything else (hex, binary) keeps
    its last digits after '…'. When nothing fits, returns the narrowest form.
    """
    if measure(text) <= width:
        return text
    with_unit = re.fullmatch(r'(-?\d+(?:\.\d+)?)( .+)', text)
    if with_unit:                           # "0.0000000358700642792 mi²" -> "3.587…×10⁻⁸ mi²"
        number, unit = with_unit.groups()
        shown = fit_text(number, max(0, width - measure(unit)), lambda s: measure(s + unit) - measure(unit))
        return shown + unit
    if DECIMAL_RE.fullmatch(text):
        significant = len(text.lstrip('-').replace('.', '').strip('0'))
        if significant == 0:
            return text
        candidate, count = (lambda k: scientific_text(text, k)), min(significant, MAX_SHOWN_DIGITS)
    else:
        candidate, count = (lambda k: '…' + text[-k:]), len(text) - 1
    if count < 1:
        return text
    low, high = 1, count                    # widest candidate that still fits
    while low < high:
        mid = (low + high + 1) // 2
        if measure(candidate(mid)) <= width:
            low = mid
        else:
            high = mid - 1
    best = candidate(low)
    return best if measure(best) < measure(text) else text


def operand_start(s):
    """Index where the operand at the end of s begins (number, constant, or (group))."""
    if s.endswith(')'):
        depth = 0
        for k in range(len(s) - 1, -1, -1):
            if s[k] == ')':
                depth += 1
            elif s[k] == '(':
                depth -= 1
                if depth == 0:
                    name = re.search(r'[A-Za-z_]\w*$', s[:k])
                    return name.start() if name else k
        return None
    m = re.search(r'((?<!\d)\d+(?:\.\d*)?|\.\d+|π|pi|e)$', s)
    return m.start() if m else None


def operand_end(s):
    """Length of the operand at the start of s (number, constant, name(...) or (group))."""
    m = re.match(r'-?(\d+(?:\.\d*)?|\.\d+)', s)
    if m:
        return m.end()
    m = re.match(r'-?[A-Za-z_]\w*', s)
    end = m.end() if m else (1 if s.startswith('-') else 0)
    if s[end:end + 1] != '(':
        return end if m else None           # a constant like pi, or nothing usable
    depth = 0
    for k in range(end, len(s)):
        if s[k] == '(':
            depth += 1
        elif s[k] == ')':
            depth -= 1
            if depth == 0:
                return k + 1
    return None


def expand_combinatorics(expr):
    """'5nCr2' -> 'comb(5,2)', '5nPr2' -> 'perm(5,2)'; they bind tighter than × and +."""
    for word, name in (('nCr', 'comb'), ('nPr', 'perm')):
        while word in expr:
            i = expr.index(word)
            left, right = expr[:i], expr[i + len(word):]
            start = operand_start(left) if left else None
            end = operand_end(right)
            if start is None or not end:
                raise SyntaxError(f"{word} needs a number on each side")
            expr = f"{left[:start]}{name}({left[start:]},{right[:end]}){right[end:]}"
    return expr


def _whole_number(x, what):
    if x != int(x) or x < 0:
        raise ValueError(f"{what} needs whole numbers of 0 or more")
    return int(x)


def _combinations(n, r):
    n, r = _whole_number(n, "nCr"), _whole_number(r, "nCr")
    if n > 100000:
        raise OverflowError("result too large")
    return math.comb(n, r)


def _permutations(n, r):
    n, r = _whole_number(n, "nPr"), _whole_number(r, "nPr")
    if n > 100000:
        raise OverflowError("result too large")
    return math.perm(n, r)


def _round_half_up(x):
    """School rounding: 2.5 -> 3, -2.5 -> -3 (Python's round() would give 2)."""
    if isinstance(x, int):
        return x
    number = MATH.to_decimal(x)
    with localcontext() as ctx:
        ctx.prec = max(number.adjusted(), 0) + 10           # room for every digit of a big number
        return int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _sign(x):
    return (x > 0) - (x < 0)


def expand_factorials(expr):
    while '!' in expr:
        i = expr.index('!')
        prev = expr[:i]
        start = operand_start(prev) if prev else None
        if start is None:
            raise SyntaxError("nothing before !")
        expr = prev[:start] + 'factorial(' + prev[start:] + ')' + expr[i + 1:]
    return expr


def add_implicit_multiplication(expr):
    """2pi -> 2*pi, 2(3+4) -> 2*(3+4), (1)(2) -> (1)*(2), 2sin(x) -> 2*sin(x)."""
    def kind(tok):
        if tok[0].isdigit() or (tok[0] == '.' and len(tok) > 1):
            return 'num'
        if tok[0].isalpha() or tok[0] == '_':
            return 'const' if tok in CONSTANTS else 'func'
        return tok

    out, prev = [], None
    for tok in TOKEN_RE.findall(expr):
        k = kind(tok)
        if prev is not None:
            if prev in ('num', 'const', ')') and k in ('(', 'const', 'func'):
                out.append('*')
            elif prev in ('const', ')') and k == 'num':
                out.append('*')
        out.append(tok)
        prev = k
    return ''.join(out)


# ---------------------------------------------------------------------------
# Programmer mode: whole numbers of a fixed bit width, signed (two's complement)
# ---------------------------------------------------------------------------

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
            raise ProgrammerError("Shift amount must not be negative")
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
    'HEX': "Hexadecimal (base 16): digits 0-9 and A-F. FF = 255",
    'DEC': "Decimal (base 10): ordinary numbers, shown with a sign",
    'OCT': "Octal (base 8): digits 0-7. 17 = 15",
    'BIN': "Binary (base 2): digits 0 and 1. 1010 = 10",
    'QWORD': "Word size: click to cycle 64 → 32 → 16 → 8 bits.\n"
             "Results wrap around like a real register.",
    '<<': "Shift left: move the bits left, filling with 0.\n1 << 4 = 16 (multiplies by 2 each step)",
    '>>': "Shift right: move the bits right, keeping the sign.\n16 >> 2 = 4 (divides by 2 each step)",
    'AND': "Bitwise AND: 1 only where both bits are 1.\n1100 AND 1010 = 1000",
    'OR': "Bitwise OR: 1 where either bit is 1.\n1100 OR 1010 = 1110",
    'XOR': "Bitwise XOR: 1 where the bits differ.\n1100 XOR 1010 = 0110",
    'NOT': "Bitwise NOT: flip every bit of the next number.\nNOT 0 = -1 (all bits set)",
    'NAND': "NOT (a AND b)",
    'NOR': "NOT (a OR b)",
    'mod': "Remainder after whole-number division. 17 mod 5 = 2",
    '÷': "Whole-number division; the remainder is dropped. 17 ÷ 5 = 3",
    '±': "Change the sign (two's complement negate)",
}

PROG_GUIDE = """Programmer mode works with whole numbers stored in a fixed number of bits, the way a computer does.

Number bases (HEX, DEC, OCT, BIN)
Click a base to type and show numbers in it. The number on screen is converted when you switch. The lines under the display always show the current value in all four bases.

Word size (QWORD / DWORD / WORD / BYTE)
The number of bits: 64, 32, 16 or 8. Numbers are signed: in BYTE the range is -128 to 127, and 127 + 1 wraps around to -128. In HEX, OCT and BIN you see the raw bits, so -1 in BYTE shows as FF.

Bitwise operators
AND, OR and XOR compare two numbers bit by bit. NOT flips every bit of the next number. NAND and NOR are NOT AND and NOT OR. Example: in BIN, 1100 AND 1010 = 1000.

Shifts
<< moves bits left (each step doubles the number); >> moves them right (each step halves it).

Arithmetic
+, −, × work as usual. ÷ drops the remainder and mod gives it: 17 ÷ 5 = 3 and 17 mod 5 = 2.

Order of operations (first to last)
NOT and minus sign, then × ÷ mod, then + −, then << >>, then AND, then XOR, then OR. Use parentheses when unsure.

Try it
1. Click HEX, type FF, press =. The lines below show DEC 255.
2. Click BYTE (cycle the word size) and DEC 255 becomes -1.
3. Click BIN and try 1100 XOR 1010 =.

Keyboard
All of Basic's keys work here too (except the decimal point: whole numbers only), plus:
  a–f  hex digits
  & | ^ ~  AND, OR, XOR, NOT
  < >  shift left and right
  ( )  parentheses
Two keys mean something different here: ^ is XOR (not power) and % is mod (not percent).

Hover over any button for a short explanation."""

# The Programmer guide is plain text; these lines are shown in bold, like the other pages' headings.
PROG_GUIDE_HEADINGS = (
    "Number bases (HEX, DEC, OCT, BIN)", "Word size (QWORD / DWORD / WORD / BYTE)", "Bitwise operators",
    "Shifts", "Arithmetic", "Order of operations (first to last)", "Try it", "Keyboard",
)


def prog_guide_markup():
    """PROG_GUIDE for the Documentation window: bold headings, and bold keys in the Keyboard list."""
    lines, in_keyboard = [], False
    for line in PROG_GUIDE.split("\n"):
        if line in PROG_GUIDE_HEADINGS:
            in_keyboard = line == "Keyboard"
            lines.append(f"<b>{GLib.markup_escape_text(line)}</b>")
        elif in_keyboard and line.startswith("  ") and "  " in line[2:]:
            keys, what = line[2:].split("  ", 1)        # "  a–f  hex digits"
            lines.append(f"  <b>{GLib.markup_escape_text(keys)}</b>  {GLib.markup_escape_text(what)}")
        else:
            lines.append(GLib.markup_escape_text(line))
    return "\n".join(lines)


# Help → Keyboard Shortcuts: (group, [(accelerator, what it does)]), in two columns like Xed
SHORTCUTS_PAGE = "shortcuts"
SHORTCUT_COLUMNS = (
    (("Windows", (("<Control>n", "Open a new window"),
                  ("<Control>w", "Close the window"),
                  ("<Control>q", "Quit Xcalculator"))),
     ("Modes", (("<Control><Alt>b", "Switch to Basic"),
                ("<Control><Alt>s", "Switch to Scientific"),
                ("<Control><Alt>f", "Switch to Financial"),
                ("<Control><Alt>p", "Switch to Programmer"),
                ("<Control><Alt>u", "Switch to Unit Converter"))),
     ("Help", (("F1", "Open the documentation"),
               ("<Control>F1", "Show the keyboard shortcuts"))),
     ("Printing", (("<Control>p", "Print the history"),
                   ("<Shift><Control>p", "Preview the printout")))),
    (("Copy and Paste", (("<Control>c", "Copy the display, or the highlighted part"),
                         ("<Control>x", "Cut the highlighted part"),
                         ("<Control>v", "Paste a number or calculation"),
                         ("<Control>a", "Highlight everything in the display"))),
     ("Text Size", (("<Control>equal", "Larger text"),
                    ("<Control>minus", "Smaller text"),
                    ("<Control>0", "Normal text size"))),
     ("Scientific", (("<Control>r", "Square root (²√x)"),
                     ("<Control>i", "Reciprocal (1/x)"))),
     ("Programmer", (("<Control>h", "Switch to HEX"),
                     ("<Control>d", "Switch to DEC"),
                     ("<Control>o", "Switch to OCT"),
                     ("<Control>b", "Switch to BIN")))),
)

# Help → Documentation: (page title, the mode it explains or None, Pango markup)
HELP_PAGES = (
    ("Getting Started", None, """<big><b>Getting Started</b></big>

Xcalculator has five modes. Pick one from the <b>Mode</b> menu:
  • <b>Basic</b> for everyday sums
  • <b>Scientific</b> for powers, roots, trigonometry, logarithms and more
  • <b>Financial</b> for loans, savings, cash flows and depreciation
  • <b>Programmer</b> for hexadecimal, binary and bitwise work
  • <b>Unit Converter</b> for lengths, weights, temperatures and more

<b>Typing</b>
Click the buttons or use the keyboard. Click in the display, or use the arrow keys, to move the cursor; typing, Backspace and Delete work at the cursor. Highlighted text is replaced by what you type.

<b>The history</b>
Every answer is added to the history above the display. Click an answer to use it in your next calculation, or click a calculation to bring it back. <b>View → Clear History</b> empties it, and <b>File → Print</b> prints it like an adding-machine tape. The history is saved when you close; see Preferences to show it again next time.

<b>Long numbers</b>
An answer too wide for the window is shown in scientific notation, like 3.7×10²⁰. Widen the window to see it in full. Copy and the history always keep the full number.

<b>Copy and paste</b>
<b>Edit → Copy</b> copies the display. <b>Edit → Paste</b> pastes a number or a simple calculation.

<b>Window size and text size</b>
Stretch the history taller and every mode keeps that height. Each mode remembers its own width. <b>View → Larger Font</b>, <b>Smaller Font</b> and <b>Reset Font Size</b> change the text size, and <b>View → Reset View</b> returns to the original window size.

<b>Preferences</b>
<b>Edit → Preferences</b> sets decimal places, thousands separators, angle units and more, and which modes appear in the Mode menu."""),

    ("Basic", "Basic", """<big><b>Basic</b></big>

The everyday keypad. Every other mode builds on it.

  <b>⌫</b>  delete the character before the cursor
  <b>Clear</b>  start again
  <b>%</b>  percent: 50% = 0.5, and 200 × 15% = 30
  <b>±</b>  change the sign of the number you are typing
  <b>=</b>  work out the answer (or press Enter)

Multiplication and division are done before addition and subtraction, so 2 + 3 × 4 = 14.

<b>Typing with the keyboard</b>
  <b>0–9</b>, <b>.</b>  numbers
  <b>+  -  *  /</b>  add, subtract, multiply, divide
  <b>%</b>  percent
  <b>Enter</b> or <b>=</b>  work out the answer
  <b>Backspace</b>  delete before the cursor;  <b>Delete</b>  delete after it
  <b>Escape</b>  clear
  <b>← →  Home  End</b>  move the cursor;  hold <b>Shift</b> to highlight

The other modes use these keys too; each mode's page lists what it adds or changes. For the Ctrl shortcuts, see the Keyboard page."""),

    ("Scientific", "Scientific", """<big><b>Scientific</b></big>

Everything in Basic, plus:

<b>Powers and roots</b>
  <b>x²</b>, <b>x³</b>, <b>xʸ</b>  powers;  <b>eˣ</b>, <b>10ˣ</b>  powers of e and 10
  <b>²√x</b>, <b>³√x</b>, <b>ʸ√x</b>  square, cube and y-th roots;  <b>1/x</b>  reciprocal
  <b>EE</b>  times ten to the power: 3 EE 5 = 300000

<b>Trigonometry</b>
  <b>sin</b>, <b>cos</b>, <b>tan</b> and the hyperbolic <b>sinh</b>, <b>cosh</b>, <b>tanh</b>
  <b>2nd</b>  switches these buttons to their inverses (sin⁻¹ and so on)
  <b>Rad</b> / <b>Deg</b>  switches between radians and degrees. Degrees are used until you switch.

<b>Logarithms and constants</b>
  <b>ln</b>  natural logarithm;  <b>log₁₀</b>  base-10 logarithm
  <b>π</b>, <b>e</b>  the constants;  <b>Rand</b>  a random number between 0 and 1
  <b>x!</b>  factorial: 5! = 120

<b>More functions</b>
  <b>|x|</b>  absolute value: |−5| = 5
  <b>nCr</b>  combinations, when order doesn't matter: 5 nCr 2 = 10
  <b>nPr</b>  permutations, when order matters: 5 nPr 2 = 20
  <b>round</b>  to the nearest whole number: round(2.5) = 3
  <b>mod</b>  the remainder: 17 mod 5 = 2
  <b>f(x)</b>  a menu of more functions, each with a short explanation

<b>Memory</b>
  <b>M+</b> adds the display to the memory, <b>M−</b> subtracts it, <b>MR</b> recalls it and <b>MC</b> clears it.

<b>Keyboard</b>
All of Basic's keys work here too, plus:
  <b>^</b>  power;  <b>( )</b>  parentheses;  <b>!</b>  factorial;  <b>e</b>  the constant e;  <b>p</b>  π"""),

    ("Financial", "Financial", """<big><b>Financial</b></big>

The lines under the display always show the values stored so far.

<b>Loans and savings (time value of money)</b>
The five keys <b>N</b>, <b>I/Y</b>, <b>PV</b>, <b>PMT</b> and <b>FV</b> are the number of payments, the yearly interest rate in percent, the present value, the payment and the future value.
  1. Type a number and press a key to store it. Press a key on its own to see what it holds.
  2. Store four of the five.
  3. Press <b>CPT</b>, then the fifth key, to work it out.
Money you receive is positive and money you pay out is negative. For a loan of 20,000, store PV = 20000, and the payment PMT comes out negative.
  <b>P/Y</b>  payments per year (12 to start); type a number and press P/Y to change it
  <b>BGN</b>  switches between payments at the end of each period (END) and the beginning (BGN)

<b>Cash flows</b>
  <b>CFj</b>  type an amount and press CFj; the first one is the starting amount, usually an investment entered as negative
  <b>Nj</b>  type a count and press Nj to repeat the last cash flow that many times
  <b>NPV</b>  type the discount rate in percent and press NPV for the net present value
  <b>IRR</b>  the internal rate of return

<b>Loan schedule (amortization)</b>
With the loan stored, type a payment number and press <b>P1</b>, then another and press <b>P2</b>.
  <b>BAL</b>  the balance left after payment P2
  <b>PRN</b>, <b>INT</b>  the principal and the interest paid from P1 to P2

<b>Depreciation</b>
Store the asset's life in years as N, its cost as PV and its salvage value as FV. Type a year and press <b>SL</b> (straight line), <b>SYD</b> (sum of the years' digits) or <b>DB</b> (declining balance; store the declining percent, such as 200, as I/Y).

<b>Interest rates</b>
  <b>EFF</b>  type a nominal yearly rate for the effective yearly rate, compounding P/Y times a year
  <b>NOM</b>  the reverse

<b>Business</b>
  <b>Mrgn</b>  profit margin: cost Mrgn price, then =. 60 Mrgn 100 = 40 (percent)
  <b>Δ%</b>  percent change: old Δ% new, then =. 80 Δ% 100 = 25 (percent)

<b>Clear All</b> erases every stored financial value.

Financial answers are worked out to about 15 significant digits, whatever the decimal places setting: far more than money needs.

<b>Keyboard</b>
All of Basic's keys work here too, plus <b>( )</b> for parentheses. The financial keys (N, PMT, CPT and so on) are on the buttons only."""),

    ("Programmer", "Programmer", None),     # filled from PROG_GUIDE below

    ("Unit Converter", "Unit Converter", """<big><b>Unit Converter</b></big>

  1. Pick a category: Angle, Area, Density, Digital Storage, Energy, Length, Mass, Pressure, Speed, Temperature, Time or Volume.
  2. Pick a unit beside each box.
  3. Type a number in either box. The other box converts as you type; the box with the green outline is the one you are typing in.

The line under the boxes shows the formula used. ≈ means the number in it is rounded.

  <b>Capture</b> (or Enter)  saves the conversion to the history
  <b>±</b>  makes the number negative, for temperatures below zero

Click a captured line in the history to bring back that conversion: its category, both units and the number.

Conversions use the official definitions (for example, 1 inch is exactly 2.54 cm) and are shown with the decimal places set in Preferences. The converter remembers your category and the units you chose in each.

<b>Keyboard</b>
Basic's number, Backspace, Delete, Escape and cursor keys work here too. Two keys work differently:
  <b>-</b>  makes the number negative (like ±)
  <b>Enter</b> or <b>=</b>  Capture
The other operator keys (+ * / %) do nothing here, since the converter has no operators."""),

    ("Preferences", None, """<big><b>Preferences</b></big>

Open <b>Edit → Preferences</b>. Changes take effect at once. <b>Reset to Defaults</b> puts every preference back the way it was the first time; it doesn't touch the saved history.

<b>General</b>
  <b>Decimal places</b>  how many places answers are rounded to, from 0 to 50 (10 to start). Up to 50 places uses high-precision maths from the python3-mpmath package, which is installed with Xcalculator; without it the limit is 15. Very small answers keep their digits instead of rounding to 0, and switch to scientific notation if they don't fit. Changing it re-shows the answer on screen; lines already in the history keep their digits.
  <b>Show all decimal places</b>  pads answers with zeros, so with 2 places 19.5 shows as 19.50. Handy for money.
  <b>Thousands separators</b>  1234567 shows as 1,234,567 in answers, the history and the printout (not while typing, and not in Programmer mode). Copy still gives plain digits.
  <b>Angle units</b>  degrees or radians for sin, cos and tan. The Rad/Deg button in Scientific changes the same setting.
  <b>Word size</b> and <b>Starting number base</b>  for Programmer mode; its buttons change the same settings.
  <b>Keep history after closing</b>  shows the saved history when Xcalculator opens. The history is always saved, in ~/.config/xcalculator_history.json (the newest 500 lines). <b>View → Clear History</b> only empties the window. <b>Delete Saved History</b> clears the history and deletes the file.

<b>Modes</b>
Switch off the modes you don't use, and they disappear from the Mode menu. At least one mode stays on."""),

    ("Keyboard", None, SHORTCUTS_PAGE),     # drawn with key caps, like Xed's shortcuts window
)


# ---------------------------------------------------------------------------
# Unit Converter: exact factors from the official definitions
# ---------------------------------------------------------------------------

PI = Fraction("3.14159265358979323846264338327950288419716939937510582097494")
_LB = Fraction("0.45359237")                # kg, exact
_LBF = _LB * Fraction("9.80665")            # N, exact
_IN = Fraction("0.0254")                    # m, exact
_GAL = Fraction("0.003785411784")           # US gallon in m³, exact

# category -> [(name, symbol, size in the category's base unit)], US units first.
# Temperature has no single factor; its entries are converted by temperature_to_kelvin.
CONVERTER_UNITS = {
    "Angle": [("Degree", "°", 1), ("Radian", "rad", 180 / PI), ("Gradian", "grad", Fraction("0.9")),
              ("Arcminute", "′", Fraction(1, 60)), ("Arcsecond", "″", Fraction(1, 3600)), ("Turn", "turn", 360)],
    "Area": [("Square inch", "in²", _IN ** 2), ("Square foot", "ft²", (12 * _IN) ** 2),
             ("Square yard", "yd²", (36 * _IN) ** 2), ("Acre", "ac", 43560 * (12 * _IN) ** 2),
             ("Square mile", "mi²", (63360 * _IN) ** 2), ("Square centimeter", "cm²", Fraction(1, 10000)),
             ("Square meter", "m²", 1), ("Hectare", "ha", 10000), ("Square kilometer", "km²", 1000000)],
    "Density": [("Gram per cubic centimeter", "g/cm³", 1000), ("Kilogram per cubic meter", "kg/m³", 1),
                ("Gram per milliliter", "g/mL", 1000), ("Kilogram per liter", "kg/L", 1000),
                ("Pound per cubic foot", "lb/ft³", _LB / (12 * _IN) ** 3),
                ("Pound per cubic inch", "lb/in³", _LB / _IN ** 3),
                ("Pound per gallon", "lb/gal", _LB / _GAL)],
    "Digital Storage": [("Bit", "bit", 1), ("Byte", "B", 8), ("Kilobyte", "kB", 8 * 10 ** 3),
                        ("Megabyte", "MB", 8 * 10 ** 6), ("Gigabyte", "GB", 8 * 10 ** 9),
                        ("Terabyte", "TB", 8 * 10 ** 12), ("Petabyte", "PB", 8 * 10 ** 15),
                        ("Kibibyte", "KiB", 8 * 2 ** 10), ("Mebibyte", "MiB", 8 * 2 ** 20),
                        ("Gibibyte", "GiB", 8 * 2 ** 30), ("Tebibyte", "TiB", 8 * 2 ** 40),
                        ("Kilobit", "kbit", 10 ** 3), ("Megabit", "Mbit", 10 ** 6), ("Gigabit", "Gbit", 10 ** 9)],
    "Energy": [("Joule", "J", 1), ("Kilojoule", "kJ", 1000), ("Calorie", "cal", Fraction("4.184")),
               ("Food Calorie", "kcal", 4184), ("Watt-hour", "Wh", 3600), ("Kilowatt-hour", "kWh", 3600000),
               ("British thermal unit", "BTU", Fraction("1055.05585262")),
               ("Foot-pound", "ft·lbf", 12 * _IN * _LBF), ("Electronvolt", "eV", Fraction("1.602176634e-19"))],
    "Length": [("Inch", "in", _IN), ("Foot", "ft", 12 * _IN), ("Yard", "yd", 36 * _IN),
               ("Mile", "mi", 63360 * _IN), ("Nautical mile", "nmi", 1852), ("Millimeter", "mm", Fraction(1, 1000)),
               ("Centimeter", "cm", Fraction(1, 100)), ("Meter", "m", 1), ("Kilometer", "km", 1000)],
    "Mass": [("Ounce", "oz", _LB / 16), ("Pound", "lb", _LB), ("Stone", "st", 14 * _LB),
             ("US ton", "ton", 2000 * _LB), ("Milligram", "mg", Fraction(1, 10 ** 6)),
             ("Gram", "g", Fraction(1, 1000)), ("Kilogram", "kg", 1), ("Metric ton", "t", 1000)],
    "Pressure": [("Pound per square inch", "psi", _LBF / _IN ** 2), ("Inch of mercury", "inHg", Fraction("3386.389")),
                 ("Millimeter of mercury", "mmHg", Fraction("133.322387415")), ("Atmosphere", "atm", 101325),
                 ("Bar", "bar", 100000), ("Pascal", "Pa", 1), ("Kilopascal", "kPa", 1000),
                 ("Megapascal", "MPa", 10 ** 6)],
    "Speed": [("Mile per hour", "mph", 63360 * _IN / 3600), ("Foot per second", "ft/s", 12 * _IN),
              ("Knot", "kn", Fraction(1852, 3600)), ("Kilometer per hour", "km/h", Fraction(1000, 3600)),
              ("Meter per second", "m/s", 1)],
    "Temperature": [("Fahrenheit", "°F", None), ("Celsius", "°C", None), ("Kelvin", "K", None)],
    "Time": [("Millisecond", "ms", Fraction(1, 1000)), ("Second", "s", 1), ("Minute", "min", 60),
             ("Hour", "h", 3600), ("Day", "d", 86400), ("Week", "wk", 604800),
             ("Month (average)", "mo", Fraction("2629746")), ("Year (average)", "yr", Fraction("31556952"))],
    "Volume": [("Teaspoon", "tsp", _GAL / 768), ("Tablespoon", "tbsp", _GAL / 256), ("Fluid ounce", "fl oz", _GAL / 128),
               ("Cup", "cup", _GAL / 16), ("Pint", "pt", _GAL / 8), ("Quart", "qt", _GAL / 4),
               ("Gallon", "gal", _GAL), ("Milliliter", "mL", Fraction(1, 10 ** 6)), ("Liter", "L", Fraction(1, 1000)),
               ("Cubic meter", "m³", 1), ("Cubic inch", "in³", _IN ** 3), ("Cubic foot", "ft³", (12 * _IN) ** 3),
               ("Imperial gallon", "imp gal", Fraction("0.00454609"))],
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
    return next(Fraction(size) for _, sym, size in CONVERTER_UNITS[category] if sym == symbol)


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
        return "Same unit"
    if category == "Temperature":
        return "Formula:  " + TEMPERATURE_FORMULAS[(from_symbol, to_symbol)]
    factor = converter_factor(category, from_symbol) / converter_factor(category, to_symbol)
    if is_terminating(factor) and (factor >= 1 or not is_terminating(1 / factor)):
        op, number = "×", factor
    elif is_terminating(1 / factor):
        op, number = "÷", 1 / factor
    else:                                   # neither is exact: show the one that is at least 1
        op, number = ("×", factor) if factor >= 1 else ("÷", 1 / factor)
    equals = "=" if is_terminating(number) else "≈"
    return f"Formula:  {to_symbol} {equals} {from_symbol} {op} {group_thousands(format_exact(number))}"


# ---------------------------------------------------------------------------
# History widgets that shrink with the window instead of widening it
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Printing the history as a calculator tape (Print and Print Preview share this)
# ---------------------------------------------------------------------------

TAPE_WIDTH = 252            # points: a 3½-inch paper-tape column centered on the page
TAPE_FONT = "Monospace 10"
TAPE_GAP = 8                # points between calculations


def _tape_layout(new_layout, text, width, bold=False, size_scale=1.0, align=Pango.Alignment.RIGHT):
    layout = new_layout()
    font = Pango.FontDescription.from_string(TAPE_FONT)
    if size_scale != 1.0:
        font.set_size(int(font.get_size() * size_scale))
    if bold:
        font.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(font)
    layout.set_width(int(width * Pango.SCALE))
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)   # very long numbers wrap instead of running off
    layout.set_alignment(align)
    layout.set_text(text, -1)
    return layout


def _tape_header_text(printed_at):
    return f"Xcalculator  ·  {printed_at:%b %d, %Y  %I:%M %p}"


def paginate_tape(new_layout, entries, page_width, page_height, printed_at):
    """Split the history into pages: a list of lists of entry numbers."""
    column = min(TAPE_WIDTH, page_width)
    header = _tape_layout(new_layout, _tape_header_text(printed_at), column, size_scale=0.8).get_pixel_size()[1]
    footer = _tape_layout(new_layout, "Page 1 of 1", column, size_scale=0.8).get_pixel_size()[1]
    room = page_height - header - footer - 4 * TAPE_GAP
    pages, current, used = [], [], 0
    for index, (formula, result) in enumerate(entries):
        height = (_tape_layout(new_layout, formula, column).get_pixel_size()[1]
                  + _tape_layout(new_layout, "= " + result, column, bold=True).get_pixel_size()[1] + TAPE_GAP)
        if current and used + height > room:
            pages.append(current)
            current, used = [], 0
        current.append(index)
        used += height
    if current:
        pages.append(current)
    return pages or [[]]


def draw_tape_page(cr, new_layout, entries, pages, page_number, page_width, page_height, printed_at):
    """Draw one page of the tape in points, with (0, 0) at the top-left of the printable area."""
    column = min(TAPE_WIDTH, page_width)
    left = (page_width - column) / 2

    def show(layout, y, gray=0.0):
        cr.set_source_rgb(gray, gray, gray)
        cr.move_to(left, y)
        PangoCairo.show_layout(cr, layout)
        return y + layout.get_pixel_size()[1]

    def tear_line(y):                       # the dashed edge of a paper tape
        cr.save()
        cr.set_source_rgb(0.55, 0.55, 0.55)
        cr.set_line_width(0.6)
        cr.set_dash([3, 3])
        cr.move_to(left, y)
        cr.line_to(left + column, y)
        cr.stroke()
        cr.restore()

    y = show(_tape_layout(new_layout, _tape_header_text(printed_at), column, size_scale=0.8,
                          align=Pango.Alignment.CENTER), 0, gray=0.35) + TAPE_GAP
    tear_line(y)
    y += TAPE_GAP
    for index in pages[page_number]:
        formula, result = entries[index]
        y = show(_tape_layout(new_layout, formula, column), y, gray=0.25)
        y = show(_tape_layout(new_layout, "= " + result, column, bold=True), y) + TAPE_GAP
    if page_number == len(pages) - 1:
        tear_line(y)
    footer = _tape_layout(new_layout, f"Page {page_number + 1} of {len(pages)}", column, size_scale=0.8,
                          align=Pango.Alignment.CENTER)
    show(footer, page_height - footer.get_pixel_size()[1], gray=0.35)


class PrintPreview(Gtk.Window):
    """File → Print Preview: each page drawn the way Print will draw it."""
    SCALE = 0.75                            # preview pixels per point

    def __init__(self, calculator, entries, page_setup):
        super().__init__(title="Print Preview - Xcalculator", transient_for=calculator)
        self.calculator, self.entries, self.page_setup = calculator, entries, page_setup
        self.printed_at = datetime.now()
        self.paper_width = page_setup.get_paper_width(Gtk.Unit.POINTS)
        self.paper_height = page_setup.get_paper_height(Gtk.Unit.POINTS)
        self.left = page_setup.get_left_margin(Gtk.Unit.POINTS)
        self.top = page_setup.get_top_margin(Gtk.Unit.POINTS)
        self.width = page_setup.get_page_width(Gtk.Unit.POINTS)
        self.height = page_setup.get_page_height(Gtk.Unit.POINTS)
        measure = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)) if cairo else None
        self.pages = (paginate_tape(points_layout_maker(measure), entries, self.width, self.height, self.printed_at)
                      if measure else [[]])
        self.page = 0

        bar = Gtk.Box(spacing=6)
        bar.set_margin_start(8); bar.set_margin_end(8); bar.set_margin_top(8); bar.set_margin_bottom(8)
        self.back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        self.back.set_tooltip_text("Previous page")
        self.back.connect("clicked", lambda b: self.go(-1))
        self.forward = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        self.forward.set_tooltip_text("Next page")
        self.forward.connect("clicked", lambda b: self.go(1))
        self.page_label = Gtk.Label()
        print_button = Gtk.Button(label="Print…")
        print_button.connect("clicked", self.on_print)
        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda b: self.destroy())
        for widget in (self.back, self.page_label, self.forward):
            bar.pack_start(widget, False, False, 0)
        bar.pack_end(close_button, False, False, 0)
        bar.pack_end(print_button, False, False, 0)

        self.area = Gtk.DrawingArea()
        self.area.set_size_request(int(self.paper_width * self.SCALE) + 40, int(self.paper_height * self.SCALE) + 40)
        self.area.connect("draw", self.on_draw)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.area)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(bar, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 0)
        box.pack_start(scroller, True, True, 0)
        self.add(box)
        self.set_default_size(int(self.paper_width * self.SCALE) + 60, min(900, int(self.paper_height * self.SCALE) + 110))
        self.connect("key-press-event", self.on_key)
        self.go(0)

    def go(self, step):
        self.page = max(0, min(len(self.pages) - 1, self.page + step))
        self.page_label.set_text(f"Page {self.page + 1} of {len(self.pages)}")
        self.back.set_sensitive(self.page > 0)
        self.forward.set_sensitive(self.page < len(self.pages) - 1)
        self.area.queue_draw()

    def on_key(self, widget, event):
        name = Gdk.keyval_name(event.keyval)
        if name == "Escape":
            self.destroy()
        elif name in ("Page_Down", "Right"):
            self.go(1)
        elif name in ("Page_Up", "Left"):
            self.go(-1)
        else:
            return False
        return True

    def on_draw(self, area, cr):
        x = max(20, (area.get_allocated_width() - self.paper_width * self.SCALE) / 2)
        cr.set_source_rgb(0.5, 0.5, 0.5)            # page shadow
        cr.rectangle(x + 3, 23, self.paper_width * self.SCALE, self.paper_height * self.SCALE)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)                  # the paper
        cr.rectangle(x, 20, self.paper_width * self.SCALE, self.paper_height * self.SCALE)
        cr.fill()
        cr.translate(x, 20)
        cr.scale(self.SCALE, self.SCALE)
        cr.translate(self.left, self.top)
        draw_tape_page(cr, points_layout_maker(cr), self.entries, self.pages, self.page,
                       self.width, self.height, self.printed_at)
        return True

    def on_print(self, button):
        self.calculator.print_history(parent=self)


MODE_DESCRIPTIONS = {
    "Basic": "Everyday arithmetic",
    "Scientific": "Powers, roots, trigonometry, logarithms and more",
    "Financial": "Loans, savings, cash flows and depreciation",
    "Programmer": "Hexadecimal, binary and bitwise operations",
    "Unit Converter": "Lengths, weights, temperatures and more",
}
PREF_BASES = (("Hexadecimal (HEX)", 16), ("Decimal (DEC)", 10), ("Octal (OCT)", 8), ("Binary (BIN)", 2))
PREF_WORDS = (("64-bit (QWORD)", 64), ("32-bit (DWORD)", 32), ("16-bit (WORD)", 16), ("8-bit (BYTE)", 8))


class PreferencesWindow(Gtk.Window):
    """Edit → Preferences, laid out like Xed's: pages on the left, buttons along the bottom.
    Every change takes effect at once."""

    def __init__(self, calculator):
        super().__init__(title="Xcalculator Preferences", transient_for=calculator)
        self.calculator = calculator
        self.syncing = False
        self.set_default_size(620, 640)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self.stack = Gtk.Stack()
        self.stack.add_titled(self.build_general_page(), "General", "General")
        self.stack.add_titled(self.build_modes_page(), "Modes", "Modes")
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        pages = Gtk.Box()
        pages.pack_start(sidebar, False, False, 0)
        pages.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        pages.pack_start(self.stack, True, True, 0)
        frame = Gtk.Frame()
        frame.add(pages)

        documentation = Gtk.Button(label="Documentation")
        documentation.connect("clicked", lambda b: calculator.show_help_contents(page="Preferences"))
        reset = Gtk.Button(label="Reset to Defaults")
        reset.set_tooltip_text("Put every preference back the way it was the first time. "
                               "The saved history is kept.")
        reset.connect("clicked", lambda b: calculator.reset_preferences())
        close = Gtk.Button(label="Close")
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
        for label, _ in choices:
            combo.append_text(label)
        combo.connect("changed", changed)
        return combo

    def build_general_page(self):
        scroller, box = self.page()
        c = self.calculator
        self.heading(box, "Numbers")
        self.decimals = Gtk.SpinButton.new_with_range(0, MAX_DECIMALS, 1)
        self.decimals.connect("value-changed", lambda s: self.changed(lambda: c.set_number_format(decimals=s.get_value_as_int())))
        self.row(box, "Decimal places", self.decimals,
                 "Up to 50 places, using high-precision maths (mpmath)." if mpmath
                 else "Up to 15 places. Install python3-mpmath for up to 50.")
        self.show_all_switch = Gtk.Switch()
        self.show_all_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_number_format(show_all=s.get_active())))
        self.show_all_hint = self.row(box, "Show all decimal places", self.show_all_switch, "")
        self.thousands_switch = Gtk.Switch()
        self.thousands_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_number_format(thousands=s.get_active())))
        self.row(box, "Thousands separators", self.thousands_switch, "1234567 shows as 1,234,567")

        self.heading(box, "Scientific")
        self.angle = self.combo((("Degrees", False), ("Radians", True)),
                                lambda w: self.changed(lambda: c.set_angle_mode(w.get_active() == 1)))
        self.row(box, "Angle units", self.angle, "Also changed by the Rad/Deg button")

        self.heading(box, "Programmer")
        self.word = self.combo(PREF_WORDS, lambda w: self.changed(
            lambda: c.set_programmer_format(c.prog_base, PREF_WORDS[w.get_active()][1])))
        self.row(box, "Word size", self.word, "Also changed by the QWORD/DWORD/WORD/BYTE button")
        self.base = self.combo(PREF_BASES, lambda w: self.changed(
            lambda: c.set_programmer_format(PREF_BASES[w.get_active()][1], c.prog_bits)))
        self.row(box, "Starting number base", self.base, "Also changed by the HEX, DEC, OCT and BIN buttons")

        self.heading(box, "History")
        self.keep_switch = Gtk.Switch()
        self.keep_switch.connect("notify::active", lambda s, p: self.changed(lambda: c.set_keep_history(s.get_active())))
        self.row(box, "Keep history after closing", self.keep_switch,
                 "Show the saved history when Xcalculator opens. It is always saved, "
                 "in ~/.config/xcalculator_history.json")
        delete = Gtk.Button(label="Delete Saved History…")
        delete.connect("clicked", self.on_delete_history)
        self.row(box, "Saved history", delete, "Clear the history and delete the saved file")
        return scroller

    def build_modes_page(self):
        scroller, box = self.page()
        self.heading(box, "Show in the Mode menu")
        self.mode_switches = {}
        for mode in VALID_MODES:
            switch = Gtk.Switch()
            switch.connect("notify::active", lambda s, p, m=mode: self.changed(
                lambda: self.calculator.set_mode_enabled(m, s.get_active())))
            self.row(box, mode, switch, MODE_DESCRIPTIONS[mode])
            self.mode_switches[mode] = switch
        note = Gtk.Label(label="At least one mode stays on.", xalign=0)
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
        self.show_all_hint.set_text(f"2.5 shows as 2.5{'0' * (decimals - 1)}" if decimals > 1
                                    else "Pads answers with zeros to every decimal place")
        self.thousands_switch.set_active(c.thousands)
        self.angle.set_active(1 if c.use_radians else 0)
        self.word.set_active([bits for _, bits in PREF_WORDS].index(c.prog_bits))
        self.base.set_active([base for _, base in PREF_BASES].index(c.prog_base))
        self.keep_switch.set_active(c.keep_history)
        for mode, switch in self.mode_switches.items():
            on = mode in c.enabled_modes
            switch.set_active(on)
            switch.set_sensitive(not (on and len(c.enabled_modes) == 1))   # the last one can't go
        self.syncing = False

    def on_delete_history(self, button):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text="Delete the saved history?")
        dialog.format_secondary_text("This clears the history and deletes the saved file. It can't be undone.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Delete", Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
        if dialog.run() == Gtk.ResponseType.OK:
            self.calculator.delete_saved_history()
        dialog.destroy()

    def on_key(self, widget, event):
        if Gdk.keyval_name(event.keyval) == "Escape":
            self.destroy()
            return True
        return False


class HelpWindow(Gtk.Window):
    """Help → Documentation: one page per topic, picked from a list on the left."""

    def __init__(self, calculator):
        super().__init__(title="Help - Xcalculator", transient_for=calculator)
        self.set_default_size(860, 700)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.page_for_mode = {}
        for title, mode, markup in HELP_PAGES:
            if markup == SHORTCUTS_PAGE:
                self.stack.add_titled(self.build_shortcuts_page(), title, title)
                continue
            if markup is None:              # the Programmer page is the Programmer guide
                markup = "<big><b>Programmer</b></big>\n\n" + prog_guide_markup()
            label = Gtk.Label()
            label.set_markup(markup)
            label.set_line_wrap(True)
            label.set_xalign(0)
            label.set_yalign(0)
            label.set_selectable(True)
            label.set_max_width_chars(70)
            label.set_margin_start(24); label.set_margin_end(24); label.set_margin_top(18); label.set_margin_bottom(24)
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.add(label)
            self.stack.add_titled(scroller, title, title)
            if mode:
                self.page_for_mode[mode] = title
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        box = Gtk.Box()
        box.pack_start(sidebar, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        box.pack_start(self.stack, True, True, 0)
        self.add(box)
        self.connect("key-press-event", lambda w, e: Gdk.keyval_name(e.keyval) == "Escape" and (self.destroy() or True))
        self.show_all()

    @staticmethod
    def build_shortcuts_page():
        """Shortcut keys drawn as key caps (Ctrl + N), in groups and two columns, like Xed."""
        title = Gtk.Label(xalign=0)
        title.set_markup("<big><b>Keyboard Shortcuts</b></big>")
        columns = Gtk.Box(spacing=36, homogeneous=True)
        for groups in SHORTCUT_COLUMNS:
            grid = Gtk.Grid(column_spacing=18, row_spacing=6)   # one grid: descriptions share an edge
            row = 0
            for group, shortcuts in groups:
                heading = Gtk.Label(xalign=0)
                heading.set_markup(f"<b>{GLib.markup_escape_text(group)}</b>")
                heading.set_margin_top(12 if row else 0)
                grid.attach(heading, 0, row, 2, 1)
                row += 1
                for accelerator, description in shortcuts:
                    keys = Gtk.ShortcutLabel(accelerator=accelerator)
                    keys.set_halign(Gtk.Align.START)
                    grid.attach(keys, 0, row, 1, 1)
                    what = Gtk.Label(label=description, xalign=0)
                    what.set_line_wrap(True)
                    what.set_hexpand(True)
                    grid.attach(what, 1, row, 1, 1)
                    row += 1
            columns.pack_start(grid, True, True, 0)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_start(24); page.set_margin_end(24); page.set_margin_top(18); page.set_margin_bottom(24)
        page.pack_start(title, False, False, 0)
        page.pack_start(columns, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(page)
        return scroller

    def show_page_for(self, mode, page=None):
        self.stack.set_visible_child_name(page or self.page_for_mode.get(mode, HELP_PAGES[0][0]))


def points_layout_maker(cr):
    """new_layout() for drawing on an ordinary cairo surface where 1 unit = 1 point."""
    context = PangoCairo.create_context(cr)
    PangoCairo.context_set_resolution(context, 72)
    return lambda: Pango.Layout.new(context)


class XCalculator(Gtk.Window):
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
        ('floor', "round down to a whole number:  floor(2.7) = 2"),
        ('ceil', "round up to a whole number:  ceil(2.1) = 3"),
        ('int', "the whole-number part:  int(−2.7) = −2"),
        ('frac', "the part after the decimal point:  frac(2.75) = 0.75"),
        ('sgn', "the sign:  −1, 0 or 1"),
        ('log₂', "logarithm base 2:  log₂(8) = 3"),
        ('sec', "secant, 1 ÷ cos"),
        ('csc', "cosecant, 1 ÷ sin"),
        ('cot', "cotangent, cos ÷ sin"),
    )
    SCIENTIFIC_TOOLTIPS = {
        '|x|': "Absolute value: the number without its sign.  |−5| = 5",
        'nCr': "Combinations: ways to choose r items from n when order doesn't matter.\n5 nCr 2 = 10",
        'nPr': "Permutations: ways to arrange r items from n when order matters.\n5 nPr 2 = 20",
        'round': "Round to the nearest whole number.  round(2.5) = 3",
        'f(x)': "More functions",
        'mod': "Remainder after division.  17 mod 5 = 2",
    }
    SECOND_FUNCTIONS = {
        'sin': 'sin⁻¹', 'cos': 'cos⁻¹', 'tan': 'tan⁻¹',
        'sinh': 'sinh⁻¹', 'cosh': 'cosh⁻¹', 'tanh': 'tanh⁻¹',
    }
    BINARY_OPS = {
        '+': '+', '-': '-', '*': '*', '/': '/', '^': '^', 'mod': 'mod',
        '×': '*', '÷': '/', '−': '-', 'Δ%': 'Δ%', 'Mrgn': 'Mrgn', 'nCr': 'nCr', 'nPr': 'nPr',
    }
    WORD_OPS = ('mod', 'Δ%', 'Mrgn', 'nCr', 'nPr')
    FIN_TVM_KEYS = ('N', 'I/Y', 'PV', 'PMT', 'FV')
    FIN_ACTIONS = ('CPT', 'P/Y', 'BGN', 'CFj', 'Nj', 'NPV', 'IRR', 'P1', 'P2',
                   'BAL', 'PRN', 'INT', 'SL', 'SYD', 'DB', 'EFF', 'NOM', 'Clear All')
    POSTFIX_OPS = {'x²': '^2', 'x³': '^3', '%': '%', 'x!': '!', '!': '!'}
    INFIX_OPS = {'xʸ': '^', 'ʸ√x': '^(1/', 'EE': '*10^'}
    BACKSPACE_TOKENS = [
        "asinh(", "acosh(", "atanh(", "asin(", "acos(", "atan(",
        "sinh(", "cosh(", "tanh(", "sin(", "cos(", "tan(",
        "sqrt(", "cbrt(", "log10(", "log2(", "log(", "mod", "Δ%", "Mrgn", "nCr", "nPr",
        "abs(", "round(", "floor(", "ceil(", "int(", "frac(", "sgn(", "sec(", "csc(", "cot(",
    ]

    def __init__(self):
        super().__init__(title="Xcalculator")
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
        self.saved_before = []          # saved history not shown in the window (kept in the file)
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
        file_item = Gtk.MenuItem(label="File")
        file_item.set_submenu(file_menu)
        menubar.append(file_item)

        new_window_item = Gtk.MenuItem(label="New Window")
        new_window_item.add_accelerator("activate", accel_group, Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        new_window_item.connect("activate", self.open_new_window)
        file_menu.append(new_window_item)

        file_menu.append(Gtk.SeparatorMenuItem())

        self.print_preview_item = Gtk.MenuItem(label="Print Preview")
        self.print_preview_item.add_accelerator("activate", accel_group, Gdk.KEY_p,
                                                Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK, Gtk.AccelFlags.VISIBLE)
        self.print_preview_item.connect("activate", self.show_print_preview)
        file_menu.append(self.print_preview_item)

        self.print_item = Gtk.MenuItem(label="Print…")
        self.print_item.add_accelerator("activate", accel_group, Gdk.KEY_p, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        self.print_item.connect("activate", self.print_history)
        file_menu.append(self.print_item)

        file_menu.append(Gtk.SeparatorMenuItem())

        close_item = Gtk.MenuItem(label="Close")
        close_item.add_accelerator("activate", accel_group, Gdk.KEY_w, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        close_item.connect("activate", lambda w: self.close())
        file_menu.append(close_item)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.add_accelerator("activate", accel_group, Gdk.KEY_q, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        quit_item.connect("activate", lambda w: Gtk.main_quit())
        file_menu.append(quit_item)

        edit_menu = Gtk.Menu()
        edit_item = Gtk.MenuItem(label="Edit")
        edit_item.set_submenu(edit_menu)
        menubar.append(edit_item)

        copy_item = Gtk.MenuItem(label="Copy")
        copy_item.add_accelerator("activate", accel_group, Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        copy_item.connect("activate", self.copy_to_clipboard)
        edit_menu.append(copy_item)

        paste_item = Gtk.MenuItem(label="Paste")
        paste_item.add_accelerator("activate", accel_group, Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        paste_item.connect("activate", self.paste_from_clipboard)
        edit_menu.append(paste_item)

        edit_menu.append(Gtk.SeparatorMenuItem())

        preferences_item = Gtk.MenuItem(label="Preferences")
        preferences_item.connect("activate", self.show_preferences)
        edit_menu.append(preferences_item)

        mode_menu = Gtk.Menu()
        mode_item = Gtk.MenuItem(label="Mode")
        mode_item.set_submenu(mode_menu)

        basic_radio = Gtk.RadioMenuItem(label="Basic")
        basic_radio.set_active(self.current_mode == "Basic")
        basic_radio.connect("activate", self.on_menu_mode_changed, "Basic")
        mode_menu.append(basic_radio)

        sci_radio = Gtk.RadioMenuItem(group=basic_radio, label="Scientific")
        sci_radio.set_active(self.current_mode == "Scientific")
        sci_radio.connect("activate", self.on_menu_mode_changed, "Scientific")
        mode_menu.append(sci_radio)

        financial_radio = Gtk.RadioMenuItem(group=basic_radio, label="Financial")
        financial_radio.set_active(self.current_mode == "Financial")
        financial_radio.connect("activate", self.on_menu_mode_changed, "Financial")
        mode_menu.append(financial_radio)

        programmer_radio = Gtk.RadioMenuItem(group=basic_radio, label="Programmer")
        programmer_radio.set_active(self.current_mode == "Programmer")
        programmer_radio.connect("activate", self.on_menu_mode_changed, "Programmer")
        mode_menu.append(programmer_radio)

        converter_radio = Gtk.RadioMenuItem(group=basic_radio, label="Unit Converter")
        converter_radio.set_active(self.current_mode == "Unit Converter")
        converter_radio.connect("activate", self.on_menu_mode_changed, "Unit Converter")
        mode_menu.append(converter_radio)
        self.mode_items = dict(zip(VALID_MODES, (basic_radio, sci_radio, financial_radio,
                                                 programmer_radio, converter_radio)))
        for mode, item in self.mode_items.items():      # Ctrl+Alt+B, S, F, P, U like GNOME Calculator
            item.add_accelerator("activate", accel_group, Gdk.keyval_from_name(MODE_KEYS[mode]),
                                 Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK,
                                 Gtk.AccelFlags.VISIBLE)

        view_menu = Gtk.Menu()
        view_item = Gtk.MenuItem(label="View")
        view_item.set_submenu(view_menu)
        menubar.append(view_item)
        menubar.append(mode_item)           # File Edit View Mode Help

        clear_history_item = Gtk.MenuItem(label="Clear History")
        clear_history_item.connect("activate", self.clear_history)
        view_menu.append(clear_history_item)

        divider2 = Gtk.SeparatorMenuItem()
        view_menu.append(divider2)

        larger_font_item = Gtk.MenuItem(label="Larger Font")
        larger_font_item.add_accelerator("activate", accel_group, Gdk.KEY_equal, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        larger_font_item.connect("activate", self.change_font_zoom, 1)
        view_menu.append(larger_font_item)

        smaller_font_item = Gtk.MenuItem(label="Smaller Font")
        smaller_font_item.add_accelerator("activate", accel_group, Gdk.KEY_minus, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        smaller_font_item.connect("activate", self.change_font_zoom, -1)
        view_menu.append(smaller_font_item)

        reset_font_item = Gtk.MenuItem(label="Reset Font Size")
        reset_font_item.add_accelerator("activate", accel_group, Gdk.KEY_0, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        reset_font_item.connect("activate", self.reset_font_size)
        view_menu.append(reset_font_item)

        divider3 = Gtk.SeparatorMenuItem()
        view_menu.append(divider3)

        reset_view_item = Gtk.MenuItem(label="Reset View")
        reset_view_item.connect("activate", self.reset_view)
        view_menu.append(reset_view_item)

        help_menu = Gtk.Menu()
        help_item = Gtk.MenuItem(label="Help")
        help_item.set_submenu(help_menu)
        menubar.append(help_item)

        contents_item = Gtk.MenuItem(label="Documentation")
        contents_item.add_accelerator("activate", accel_group, Gdk.KEY_F1, 0, Gtk.AccelFlags.VISIBLE)
        contents_item.connect("activate", self.show_help_contents)
        help_menu.append(contents_item)

        shortcuts_item = Gtk.MenuItem(label="Keyboard Shortcuts")
        shortcuts_item.add_accelerator("activate", accel_group, Gdk.KEY_F1, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        shortcuts_item.connect("activate", lambda w: self.show_help_contents(page="Keyboard"))
        help_menu.append(shortcuts_item)

        help_menu.append(Gtk.SeparatorMenuItem())

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.show_about)
        help_menu.append(about_item)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
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
        self.scrolled_window.set_vexpand(True)
        self.scrolled_window.set_overlay_scrolling(False)

        self.history_listbox = Gtk.ListBox()
        self.history_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.history_listbox.set_valign(Gtk.Align.END)
        self.history_listbox.get_style_context().add_class("view")
        self.history_listbox.get_style_context().add_class("calc-history")

        self.scrolled_window.add(self.history_listbox)
        vbox.pack_start(self.scrolled_window, True, True, 0)

        self.display_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.pack_start(self.display_vbox, False, True, 4)

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
        self.display_vbox.pack_start(self.conv_bottom_row, False, True, 4)

        self.error_label = Gtk.Label(label="")
        self.error_label.set_xalign(1.0)
        self.error_label.get_style_context().add_class("calc-error-label")
        self.display_vbox.pack_start(self.error_label, False, True, 2)

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
        self.connect("destroy", Gtk.main_quit)
        self.display.grab_focus_without_selecting()     # show the cursor from the start
        self.update_print_actions()
        self.apply_enabled_modes()
        self.load_saved_history()

    # ------------------------------------------------------------------
    # Layout / menus / settings
    # ------------------------------------------------------------------

    def update_view_mode_layout(self):
        for child in self.grid.get_children():
            self.grid.remove(child)

        self.buttons = {}
        self.second_active = False

        programmer = self.current_mode == "Programmer"
        converter = self.current_mode == "Unit Converter"
        rows_data = self.layouts.get(self.current_mode, self.layouts["Scientific"])

        for row_idx, row_items in enumerate(rows_data):
            current_col = 0
            for item in row_items:
                label, span = item
                # bases and categories stay selected, drawn with the theme's selected look
                selectable = (programmer and label in PROG_BASES) or (converter and label in CONVERTER_UNITS)
                if label == 'f(x)':
                    button = self.make_more_functions_button()
                else:
                    button = Gtk.ToggleButton(label=label) if selectable else Gtk.Button(label=label)
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
                    button.set_tooltip_text("Add this conversion to the history")
                if label == 'Clear All':
                    button.set_tooltip_text("Clear all stored financial values: N, I/Y, PV, PMT, FV, "
                                            "cash flows, P1/P2, and the P/Y and BGN settings")
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
            self.conv_set_category(self.conv_category)
        else:
            self.conv_bottom_row.hide()
            self.conv_combos[0].hide()
            self.conv_use_box(0)
        if self.display_bottom.is_focus() or converter:
            self.display_top.grab_focus_without_selecting()
        self.update_status()
        self.set_title(f"{self.current_mode} - Xcalculator")
        self.apply_mode_size()

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
            if {"Programmer", "Unit Converter"} & {mode_name, self.current_mode}:
                # programmer, converter and decimal expressions don't mix
                self.expression = ""
                self.is_result_active = False
                self.token_stack = []
                self.error_label.set_text("")
            self.current_mode = mode_name
            self.update_view_mode_layout()
            self.update_display()
            self.save_window_settings()

    def clear_history(self, widget):
        """View → Clear History empties the window; the saved file keeps the record."""
        for child in self.history_listbox.get_children():
            self.history_listbox.remove(child)
        self.saved_before += [{k: e[k] for k in self.HISTORY_KEYS} for e in self.history_entries]
        self.history_entries = []
        self.update_print_actions()
        self.save_history()

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

    def apply_custom_styles(self):
        display_font = self.base_font_size + 5
        error_font = max(10, self.base_font_size - 2)
        error_color = self.theme_destructive_color() or "@error_color"

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
                color: gray;
                padding-left: 6px;
            }}
            .calc-history {{ font-size: {self.base_font_size}px; }}
            .history-row {{ padding: 2px; border-radius: 3px; }}
            .history-row:hover {{ background-color: rgba(200, 200, 200, 0.2); }}
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
                        if isinstance(pair, list) and len(pair) == 2 and all(s in symbols for s in pair):
                            self.conv_units[name] = list(pair)
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

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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

    def prepare(self, expr):
        expr = (expr.replace('×', '*').replace('÷', '/').replace('−', '-')
                    .replace('π', 'pi'))
        expr = expr.replace('Δ%', '@').replace('Mrgn', '//')   # financial infix operators
        expr = expr.replace('%', '/100')       # percent first ...
        expr = expr.replace('mod', '%')        # ... then mod becomes Python's %
        expr = expr.replace('^', '**')
        depth = expr.count('(') - expr.count(')')
        if depth > 0:
            expr += ')' * depth                # auto-close open parentheses
        expr = expand_factorials(expr)
        expr = expand_combinatorics(expr)
        return add_implicit_multiplication(expr)

    def evaluate(self, expr):
        decimals = NUMBER_FORMAT["decimals"]
        set_precision(decimals)
        self.source = self.prepare(expr)
        tree = ast.parse(self.source, mode='eval')
        value = self.eval_node(tree.body)
        if mpmath and isinstance(value, mpmath.mpf) and value != 0 and mpmath.mag(value) > MAX_INT_BITS:
            raise OverflowError("result too large")     # e.g. sinh(π^38): too big to show
        whole = digits_before_point(value)
        if whole > FLOAT_DIGITS:            # a big answer: work it out again with room for every digit
            set_precision(decimals, whole + 5)
            value = self.eval_node(tree.body)
        return value

    def eval_node(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if isinstance(node.value, float):   # read 0.1 from the text, so mpmath gets it exactly
                return MATH.number(ast.get_source_segment(self.source, node))
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            return BIN_OPS[type(node.op)](self.eval_node(node.left), self.eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](self.eval_node(node.operand))
        if isinstance(node, ast.Name) and node.id in CONSTANTS:
            return MATH.constant(node.id)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in self.functions and not node.keywords):
            arity = 2 if node.func.id in ("comb", "perm") else 1
            if len(node.args) != arity:         # e.g. cos(cos(cos( closes to cos(cos(cos()))
                raise SyntaxError("function needs a number")
            return self.functions[node.func.id](*[self.eval_node(a) for a in node.args])
        raise SyntaxError("unsupported expression")     # e.g. () with nothing inside

    def show_error(self, error):
        if isinstance(error, (FinanceError, ProgrammerError)):
            message = str(error)
        elif isinstance(error, SyntaxError):
            message = "Malformed Expression"
        elif isinstance(error, ZeroDivisionError):
            message = "Cannot divide by zero"
        elif isinstance(error, OverflowError):
            message = "Result too large"
        elif isinstance(error, ValueError):
            message = "Invalid input"
        else:
            traceback.print_exception(error)
            message = "Calculation Error"
        self.error_label.set_text(message)
        self.is_result_active = False

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

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
        elif self.current_mode == "Unit Converter":
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
        if self.current_mode == "Unit Converter":
            self.refit_result()
        return False

    def queue_display_refit(self):
        # after a resize: refit once the new size is settled
        if (self.display_fit or self.current_mode == "Unit Converter") and not self.refit_pending:
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
        elif self.current_mode == "Unit Converter":
            self.refit_result()

    def on_display_focus_in(self, entry, event):
        """Unit Converter: clicking the other box makes it the one you type in."""
        if self.current_mode == "Unit Converter" and entry is not self.display:
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

    @staticmethod
    def wrap_negative(text):
        return f"({text})" if text.startswith("-") else text

    def insert_value(self, text):
        """Insert a whole value (memory, Rand, a history result). Replaces a number being typed."""
        if self.is_result_active:
            self.expression = ""
            self.is_result_active = False
        if re.search(r'[\d.]$', self.expression):
            self.expression = TRAILING_NUM_RE.sub('', self.expression)
        self.expression += self.wrap_negative(text)
        self.token_stack = []
        self.update_display()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def handle_backspace(self):
        if self.is_result_active:
            self.is_result_active = False
            self.token_stack = []
        if not self.expression:
            return

        if self.token_stack and self.expression.endswith(self.token_stack[-1]):
            token = self.token_stack.pop()
            self.expression = self.expression[:-len(token)]
        else:
            self.token_stack = []
            tokens = (PROG_BACKSPACE_TOKENS if self.current_mode == "Programmer"
                      else self.BACKSPACE_TOKENS)
            for token in tokens:
                if self.expression.endswith(token):
                    self.expression = self.expression[:-len(token)]
                    break
            else:
                self.expression = self.expression[:-1]

        self.update_display()

    SCIENTIFIC_CONTROL_KEYS = {"r": "²√x", "i": "1/x"}     # GNOME Calculator's square root and inverse
    PROGRAMMER_CONTROL_KEYS = {"h": "HEX", "d": "DEC", "o": "OCT", "b": "BIN"}

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

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

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
        elif self.current_mode == "Unit Converter":
            self.conv_paste_number(text)
        else:
            self.paste_labels(text, "0123456789.+-*/^()%!×÷−e")

    def paste_labels(self, text, allowed, message="Can't paste that"):
        """Paste by pressing the matching buttons, so the usual typing rules apply."""
        if len(text) > 200 or any(ch not in allowed for ch in text):
            self.error_label.set_text(message)
            return
        for ch in text:
            self.execute_action_by_label(ch)

    def paste_programmer(self, text):
        prefixed = re.fullmatch(r'(-?)0([xXbBoO])([0-9A-Fa-f]+)', text)
        if prefixed:                        # 0xFF, 0b1010 and 0o17 work in any base
            sign, kind, digits = prefixed.groups()
            try:
                value = int(digits, {'x': 16, 'b': 2, 'o': 8}[kind.lower()])
            except ValueError:
                self.error_label.set_text("Can't paste that")
                return
            self.edit_at_cursor(lambda: self.prog_insert_decimal(str(-value if sign else value)))
            return
        digits = "0123456789ABCDEF"[:self.prog_base]
        self.paste_labels(text.upper(), digits + "+-*/()×÷−",
                          f"Can't paste that in {self.prog_base_name()}")

    def execute_action_by_label(self, label):
        class MockWidget:
            def __init__(self, lbl): self.lbl = lbl
            def get_label(self): return self.lbl
        self.on_button_clicked(MockWidget(label))

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def scroll_to_bottom(self):
        try:
            adj = self.scrolled_window.get_vadjustment()
            if adj: adj.set_value(adj.get_upper() - adj.get_page_size())
        except Exception as e:
            print(f"Scrolling warning: {e}")
        return False

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
            expr_label = Gtk.Label(label=f"<span color='gray'>{GLib.markup_escape_text(shown_formula)}  =</span>")
            expr_label.set_use_markup(True)
            expr_label.set_ellipsize(Pango.EllipsizeMode.START)
            expr_box.add(expr_label)
            if restore:
                expr_box.connect("button-press-event", self.on_history_conversion_clicked, restore, None)
                expr_box.set_tooltip_text("Click to bring back this conversion")
            elif formula_clickable:     # financial entries are labels, not formulas
                expr_box.connect("button-press-event", self.on_history_expr_clicked, formula)
                expr_box.set_tooltip_text("Click to use this calculation again")

            res_box = Gtk.EventBox()
            res_box.set_visible_window(False)
            res_box.add(FitLabel(result, "<b>{}</b>", show=lambda s, g=grouping: self.history_result_look(s, g)))
            if restore:
                res_box.connect("button-press-event", self.on_history_conversion_clicked, restore, click_text)
                res_box.set_tooltip_text("Click to bring back this conversion")
            else:
                res_box.connect("button-press-event", self.on_history_res_clicked, click_text or result)
                res_box.set_tooltip_text("Click to use this number")

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
                self.save_history()
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
        if self.current_mode == "Unit Converter":
            self.error_label.set_text("")
            self.conv_restore(*restore)
        elif number is not None:
            self.on_history_res_clicked(widget, event, number)
        return True

    def on_history_res_clicked(self, widget, event, result):
        if event.button == 1:
            self.error_label.set_text("")
            if self.current_mode == "Unit Converter":
                self.conv_paste_number(result)
            elif self.current_mode == "Programmer":
                self.edit_at_cursor(lambda: self.prog_insert_decimal(result))
            else:
                self.edit_at_cursor(lambda: self.insert_value(result))
            return True
        return False

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def on_button_clicked(self, widget):
        if self.syncing_widgets:
            return                          # a toggle button changed by the code, not a click
        label = widget.get_label()

        if label != '=':
            self.error_label.set_text("")

        if self.current_mode == "Programmer":
            self.programmer_action(label)
            return
        if self.current_mode == "Unit Converter":
            self.converter_action(label)
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

    def calculate(self):
        if self.is_result_active or not self.expression:
            return
        formula = self.expression
        try:
            value = self.evaluate(formula)
            result_text = format_number(value)
        except Exception as error:
            self.show_error(error)
            return

        self.result_value = value
        self.set_display(result_text, fit=True)
        self.add_to_history_display(formula, result_text)
        self.expression = result_text
        self.is_result_active = True
        self.token_stack = []

        if formula == FLIP_TRIGGER:
            # wait a moment so the new history row is laid out before the snapshot
            GLib.timeout_add(50, self.start_flip)

    # ------------------------------------------------------------------
    # Easter egg: turn the window upside down
    #
    # GTK 3 cannot rotate real widgets, so we draw the window contents into
    # an image and spin that image on an overlay that covers the window.
    # ------------------------------------------------------------------

    def start_flip(self):
        if cairo is None or self.flip_snapshot is not None:
            return False
        alloc = self.main_vbox.get_allocation()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
        cr = cairo.Context(surface)
        Gtk.render_background(self.get_style_context(), cr, 0, 0, alloc.width, alloc.height)
        self.main_vbox.draw(cr)

        self.flip_snapshot = surface
        self.flip_angle = 0.0
        self.flip_start_time = GLib.get_monotonic_time()
        self.flip_area.show()
        GLib.timeout_add(16, self.flip_tick)
        return False

    def flip_tick(self):
        elapsed = (GLib.get_monotonic_time() - self.flip_start_time) / 1e6
        turn, hold = FLIP_TURN_SECONDS, FLIP_HOLD_SECONDS

        if elapsed < turn:
            progress = elapsed / turn                           # spinning over
        elif elapsed < turn + hold:
            progress = 1.0                                      # upside down
        elif elapsed < 2 * turn + hold:
            progress = 1.0 - (elapsed - turn - hold) / turn     # spinning back
        else:
            self.flip_area.hide()
            self.flip_snapshot = None
            return False

        eased = progress * progress * (3 - 2 * progress)        # smoothstep
        self.flip_angle = eased * math.pi
        self.flip_area.queue_draw()
        return True

    def on_flip_draw(self, widget, cr):
        if self.flip_snapshot is None:
            return False
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        Gtk.render_background(self.get_style_context(), cr, 0, 0, width, height)

        w = self.flip_snapshot.get_width()
        h = self.flip_snapshot.get_height()
        c = abs(math.cos(self.flip_angle))
        s = abs(math.sin(self.flip_angle))
        # shrink while sideways so the spinning image stays inside the window
        scale = min(width / (w * c + h * s), height / (w * s + h * c), 1.0)

        cr.translate(width / 2, height / 2)
        cr.rotate(self.flip_angle)
        cr.scale(scale, scale)
        cr.set_source_surface(self.flip_snapshot, -w / 2, -h / 2)
        cr.paint()
        return True

    def memory_add(self, sign):
        if not self.expression:
            return
        try:
            total = self.memory + sign * self.evaluate(self.expression)
            format_number(total)            # refuse a total too large to show (MR could not recall it)
            self.memory = total
        except Exception as error:
            self.show_error(error)

    def toggle_sign(self):
        expr = self.expression
        if expr in ("", "0"):
            return
        if re.fullmatch(r'-?(\d+\.?\d*|\.\d+)', expr):
            expr = expr[1:] if expr.startswith('-') else '-' + expr
        else:
            wrapped = re.search(r'\(-(\d+\.?\d*|\.\d+)\)$', expr)
            number = TRAILING_NUM_RE.search(expr)
            if wrapped:
                expr = expr[:wrapped.start()] + wrapped.group(1)
            elif number:
                expr = expr[:number.start()] + '(-' + number.group(0) + ')'
            else:
                return
        self.expression = expr
        self.token_stack = []
        self.update_display()

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

    # ------------------------------------------------------------------
    # Financial mode
    #
    # Sign convention (same as TI BA II Plus): money you receive is positive,
    # money you pay out is negative. Enter a loan as PV = +amount and CPT PMT
    # returns a negative payment.
    # ------------------------------------------------------------------

    @staticmethod
    def _annuity_factor(i, n):
        """((1+i)^n - 1) / i, with the i -> 0 limit handled."""
        if abs(i) < 1e-12:
            return n
        if 1 + i <= 0:
            raise FinanceError("Rate out of range")
        return ((1 + i) ** n - 1) / i

    @staticmethod
    def _find_root(f, low=-0.99, high=20.0, step=0.0005):
        """Root of f nearest zero on [low, high]: scan for sign changes, then bisect."""
        brackets = []
        x = low
        previous = None
        while x <= high:
            try:
                value = f(x)
            except (OverflowError, ZeroDivisionError, ValueError):
                value = None
            if value is not None and previous is not None and previous[1] is not None:
                if value == 0:
                    brackets.append((x, x))
                elif previous[1] * value < 0:
                    brackets.append((previous[0], x))
            previous = (x, value)
            # coarser steps once past 100% so the scan stays fast
            x += step if x < 1.0 else step * 100
        if not brackets:
            raise FinanceError("No solution")
        roots = []
        for a, b in brackets:
            if a == b:
                roots.append(a)
                continue
            fa = f(a)
            for _ in range(200):
                m = (a + b) / 2
                fm = f(m)
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
            roots.append((a + b) / 2)
        return min(roots, key=abs)

    def periodic_rate(self):
        if self.periods_per_year <= 0:
            raise FinanceError("P/Y must be positive")
        return self.tvm['I/Y'] / (100 * self.periods_per_year)

    def compute_tvm(self, key):
        n, pv, pmt, fv = (self.tvm[k] for k in ('N', 'PV', 'PMT', 'FV'))
        b = 1 if self.begin_mode else 0
        py = self.periods_per_year
        if py <= 0:
            raise FinanceError("P/Y must be positive")

        if key == 'I/Y':
            if n <= 0:
                raise FinanceError("N must be positive")

            def equation(i):
                growth = (1 + i) ** n
                return pv * growth + pmt * (1 + i * b) * self._annuity_factor(i, n) + fv
            return self._find_root(equation) * py * 100

        i = self.periodic_rate()
        if 1 + i <= 0:
            raise FinanceError("Rate out of range")
        growth = (1 + i) ** n
        annuity = (1 + i * b) * self._annuity_factor(i, n)

        if key == 'FV':
            return -(pv * growth + pmt * annuity)
        if key == 'PV':
            return -(fv + pmt * annuity) / growth
        if key == 'PMT':
            if annuity == 0:
                raise FinanceError("N must not be 0")
            return -(pv * growth + fv) / annuity
        if key == 'N':
            if abs(i) < 1e-12:
                if pmt == 0:
                    raise FinanceError("PMT must not be 0")
                return -(pv + fv) / pmt
            a = pmt * (1 + i * b) / i
            numerator, denominator = a - fv, a + pv
            if denominator == 0 or numerator / denominator <= 0:
                raise FinanceError("No solution")
            return math.log(numerator / denominator) / math.log(1 + i)
        raise FinanceError("Unknown key")

    def expanded_cash_flows(self):
        flows = []
        for amount, count in self.cash_flows:
            if len(flows) + int(count) > MAX_PERIODS:    # check before building the list
                raise FinanceError("Too many cash flows")
            flows.extend([amount] * int(count))
        return flows

    def compute_npv(self, rate_percent):
        flows = self.expanded_cash_flows()
        if not flows:
            raise FinanceError("Enter cash flows with CFj")
        r = float(rate_percent) / 100      # Financial works in ordinary floats (15 digits)
        if 1 + r <= 0:
            raise FinanceError("Rate out of range")
        return sum(cf / (1 + r) ** t for t, cf in enumerate(flows))

    def compute_irr(self):
        flows = self.expanded_cash_flows()
        if len(flows) < 2 or not (any(c > 0 for c in flows) and any(c < 0 for c in flows)):
            raise FinanceError("IRR needs inflows and outflows")
        return self._find_root(lambda r: sum(c / (1 + r) ** t for t, c in enumerate(flows))) * 100

    def compute_amortization(self):
        if self.amort_p1 is None or self.amort_p2 is None:
            raise FinanceError("Set P1 and P2 first")
        p1, p2 = self.amort_p1, self.amort_p2
        if p1 < 1 or p2 < p1:
            raise FinanceError("P2 must be at least P1")
        if p2 > MAX_PERIODS:
            raise FinanceError("Too many periods")
        i = self.periodic_rate()
        pmt = self.tvm['PMT']
        balance = self.tvm['PV']
        begin = self.begin_mode
        principal_total = interest_total = 0.0
        for k in range(1, p2 + 1):
            interest = 0.0 if (begin and k == 1) else balance * i
            principal = -pmt - interest
            balance -= principal
            if k >= p1:
                principal_total += principal
                interest_total += interest
        return balance, principal_total, interest_total

    def compute_depreciation(self, method, year):
        cost, salvage, life = self.tvm['PV'], self.tvm['FV'], self.tvm['N']
        if life <= 0:
            raise FinanceError("Set N to the asset life")
        if year < 1 or year > math.ceil(life):
            raise FinanceError("Year must be within the asset life")
        if method == 'SL':
            return (cost - salvage) / life
        if method == 'SYD':
            n = int(life)
            if n != life:
                raise FinanceError("SYD needs a whole-number life")
            return (cost - salvage) * (n - year + 1) / (n * (n + 1) / 2)
        # declining balance: I/Y holds the declining percent (200 = double declining)
        factor = self.tvm['I/Y'] / 100
        if factor <= 0:
            raise FinanceError("Set I/Y to the declining % (e.g. 200)")
        if year > MAX_PERIODS:
            raise FinanceError("Too many periods")
        book = cost
        depreciation = 0.0
        for _ in range(int(year)):
            depreciation = min(book * factor / life, max(book - salvage, 0.0))
            book -= depreciation
        return depreciation

    def entered_value(self):
        """The number currently on the display, or None when nothing was entered."""
        if not self.expression:
            return None
        return self.evaluate(self.expression)

    def typed_value(self):
        """Like entered_value, but ignores a display that only echoes a stored value."""
        if self.is_result_active and self.display_is_echo:
            return None
        return self.entered_value()

    def entered_count(self, minimum=1):
        value = self.typed_value()
        if value is None or value != int(value) or value < minimum:
            raise FinanceError(f"Enter a whole number >= {minimum}")
        return int(value)

    def show_result(self, value, record=None, echo=False):
        text = format_number(value)
        self.result_value = value
        self.display_is_echo = echo
        self.set_display(text, fit=True)
        self.expression = text
        self.is_result_active = True
        self.token_stack = []
        if record:
            self.add_to_history_display(record, text, formula_clickable=False)

    def financial_action(self, label):
        try:
            self.run_financial_action(label)
        except Exception as error:
            self.cpt_pending = False
            self.show_error(error)
        self.update_status()

    def run_financial_action(self, label):
        if label == 'CPT':
            self.cpt_pending = True
            return

        if label in self.FIN_TVM_KEYS:
            if self.cpt_pending:
                self.cpt_pending = False
                result = self.compute_tvm(label)
                self.tvm[label] = float(result)
                self.show_result(result, record=f"CPT {label}")
                return
            value = self.typed_value()
            if value is None:                       # nothing typed: recall the stored value
                self.show_result(self.tvm[label], echo=True)
            else:
                self.tvm[label] = float(value)
                self.show_result(value, echo=True)
            return

        if label == 'P/Y':
            value = self.typed_value()
            if value is None:
                self.show_result(self.periods_per_year, echo=True)
                return
            if value <= 0:
                raise FinanceError("P/Y must be positive")
            self.periods_per_year = float(value)
            self.show_result(value, echo=True)
        elif label == 'BGN':
            self.begin_mode = not self.begin_mode
        elif label == 'Clear All':
            self.tvm = {k: 0.0 for k in self.tvm}
            self.cash_flows = []
            self.amort_p1 = self.amort_p2 = None
            self.periods_per_year = 12
            self.begin_mode = False
            self.expression = ""
            self.is_result_active = False
            self.token_stack = []
            self.update_display()
        elif label == 'CFj':
            value = self.typed_value()
            if value is None:
                raise FinanceError("Enter a cash flow first")
            self.cash_flows.append([float(value), 1])
            self.show_result(value, echo=True)
        elif label == 'Nj':
            if not self.cash_flows:
                raise FinanceError("Enter a cash flow with CFj first")
            count = self.entered_count()
            if count > MAX_PERIODS:
                raise FinanceError(f"Nj can be at most {MAX_PERIODS}")
            self.cash_flows[-1][1] = count
            self.show_result(count, echo=True)
        elif label == 'NPV':
            rate = self.typed_value()
            if rate is None:
                raise FinanceError("Enter the discount rate % first")
            self.show_result(self.compute_npv(rate), record="NPV")
        elif label == 'IRR':
            self.show_result(self.compute_irr(), record="IRR")
        elif label in ('P1', 'P2'):
            count = self.entered_count()
            if label == 'P1':
                self.amort_p1 = count
            else:
                self.amort_p2 = count
            self.show_result(count, echo=True)
        elif label in ('BAL', 'PRN', 'INT'):
            balance, principal, interest = self.compute_amortization()
            result = {'BAL': balance, 'PRN': principal, 'INT': interest}[label]
            self.show_result(result, record=label)
        elif label in ('SL', 'SYD', 'DB'):
            year = self.entered_count()
            self.show_result(self.compute_depreciation(label, year), record=f"{label} yr {year}")
        elif label in ('EFF', 'NOM'):
            rate = self.entered_value()
            rate = None if rate is None else float(rate)
            m = self.periods_per_year
            if rate is None:
                raise FinanceError("Enter a rate % first")
            if m <= 0:
                raise FinanceError("P/Y must be positive")
            if label == 'EFF':
                if 1 + rate / 100 / m <= 0:
                    raise FinanceError("Rate out of range")
                result = ((1 + rate / 100 / m) ** m - 1) * 100
            else:
                if 1 + rate / 100 <= 0:
                    raise FinanceError("Rate out of range")
                result = m * ((1 + rate / 100) ** (1 / m) - 1) * 100
            self.show_result(result, record=label)

    def update_status(self):
        """Show stored financial values, or the value in every base, under the display."""
        visible = self.current_mode in ("Financial", "Programmer", "Unit Converter")
        self.status_label.set_visible(visible)
        context = self.status_label.get_style_context()
        if self.current_mode == "Programmer":
            context.add_class("calc-mono")
            self.status_label.set_text(show_minus(self.programmer_status_text()))
            return
        context.remove_class("calc-mono")
        if self.current_mode == "Unit Converter":
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

    # ------------------------------------------------------------------
    # Programmer mode
    # ------------------------------------------------------------------

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
            f"{self.prog_word_name()} ({bits}-bit, signed)  ·  typing in {self.prog_base_name()}",
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
            names = [name for name, _ in PROG_WORDS]
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
        # anything else ('.', '!', ...) has no meaning for whole numbers

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
                raise ProgrammerError("Not a whole number")
        except ArithmeticError:
            self.show_error(ProgrammerError("Not a whole number"))
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

    # ------------------------------------------------------------------
    # Unit Converter mode
    #
    # self.expression is the number typed in the active box (top or bottom);
    # the other box shows it converted, updated on every change.
    # ------------------------------------------------------------------

    def conv_other_entry(self):
        return self.display_bottom if self.display is self.display_top else self.display_top

    def conv_use_box(self, index):
        self.conv_active = index
        self.display = (self.display_top, self.display_bottom)[index]

    def conv_set_category(self, category):
        self.conv_category = category
        units = CONVERTER_UNITS[category]
        self.syncing_widgets = True
        for name in CONVERTER_UNITS:
            button = self.buttons.get(name)
            if button:
                button.set_active(name == category)
        for index, combo in enumerate(self.conv_combos):
            combo.remove_all()
            for name, symbol, _ in units:
                combo.append(symbol, f"{name} ({symbol})")
            combo.set_active_id(self.conv_units[category][index])
        self.syncing_widgets = False
        self.conv_refresh()

    def on_conv_unit_changed(self, combo, index):
        if self.syncing_widgets or combo.get_active_id() is None:
            return
        self.conv_units[self.conv_category][index] = combo.get_active_id()
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
        if self.current_mode != "Unit Converter":
            return
        category = self.conv_category
        from_symbol = self.conv_units[category][self.conv_active]
        to_symbol = self.conv_units[category][1 - self.conv_active]
        value = self.conv_input_value()
        self.conv_result_full = ("" if value is None else
                                 format_fraction(convert_units(value, category, from_symbol, to_symbol)))
        self.refit_result()
        self.conv_formula = converter_formula(category, from_symbol, to_symbol)
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
        # operators and other keys have no meaning here

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
            self.error_label.set_text("Can't paste that")
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
        category = self.conv_category
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

    # ------------------------------------------------------------------
    # File menu: new window and printing
    # ------------------------------------------------------------------

    def open_new_window(self, widget):
        """File → New Window: start another, separate calculator."""
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], start_new_session=True)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

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

    def set_number_format(self, decimals=None, show_all=None, thousands=None):
        if decimals is not None:
            NUMBER_FORMAT["decimals"] = decimals
        if show_all is not None:
            NUMBER_FORMAT["show_all"] = show_all
        if thousands is not None:
            self.thousands = thousands
        # re-show the answer on screen with the new settings; the history keeps its digits
        if self.current_mode == "Unit Converter":
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

    def set_programmer_format(self, base, bits):
        if self.current_mode == "Programmer":
            self.prog_change_format(base, bits)     # also converts the number on screen
        else:
            self.prog_base, self.prog_bits = base, bits
            self.save_window_settings()

    def set_mode_enabled(self, mode, enabled):
        if enabled and mode not in self.enabled_modes:
            self.enabled_modes = [m for m in VALID_MODES if m in self.enabled_modes or m == mode]
        elif not enabled and mode in self.enabled_modes and len(self.enabled_modes) > 1:
            self.enabled_modes = [m for m in self.enabled_modes if m != mode]
        self.apply_enabled_modes()
        self.save_window_settings()

    def apply_enabled_modes(self):
        """Hide switched-off modes from the Mode menu; leave a switched-off mode if it's in use."""
        for mode, item in self.mode_items.items():
            item.set_visible(mode in self.enabled_modes)
        if self.current_mode not in self.enabled_modes:
            self.mode_items[self.enabled_modes[0]].set_active(True)

    HISTORY_KEYS = ("formula", "result", "clickable", "click_text", "restore", "grouping")

    def set_keep_history(self, keep):
        """Whether the saved history is shown when the calculator opens. It is always saved."""
        self.keep_history = keep
        self.save_window_settings()

    def save_history(self):
        """The saved file is the full record: earlier sessions, then this one (newest 500 lines)."""
        try:
            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            rows = self.saved_before + [{k: e[k] for k in self.HISTORY_KEYS} for e in self.history_entries]
            with open(HISTORY_FILE, "w") as f:
                json.dump(rows[-MAX_SAVED_HISTORY:], f)
        except Exception as e:
            print(f"Failed to save history: {e}")

    def delete_saved_history(self):
        """Preferences → Delete Saved History: empties the history and its saved file."""
        self.clear_history(None)            # (this moves the window's lines into the record...)
        self.saved_before = []              # (...which is then emptied)
        try:
            os.remove(HISTORY_FILE)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"Failed to delete saved history: {e}")

    def load_saved_history(self):
        """Read the saved record; show it in the window only if Keep history is on."""
        if not os.path.exists(HISTORY_FILE):
            return
        try:
            with open(HISTORY_FILE) as f:
                rows = [r for r in json.load(f) if isinstance(r, dict) and "formula" in r and "result" in r]
            if not self.keep_history:
                self.saved_before = rows[-MAX_SAVED_HISTORY:]
                return
            for row in rows[-MAX_SAVED_HISTORY:]:
                restore = row.get("restore")
                if restore and not (len(restore) == 4 and restore[0] in CONVERTER_UNITS):
                    restore = None
                self.add_to_history_display(str(row["formula"]), str(row["result"]), row.get("clickable") is True,
                                            row.get("click_text"), tuple(restore) if restore else None,
                                            row.get("grouping") is not False, save=False)
        except Exception as e:
            print(f"Failed to read saved history: {e}")

    def reset_preferences(self):
        """Preferences → Reset to Defaults."""
        self.set_angle_mode(False)
        self.set_programmer_format(10, 64)
        self.enabled_modes = list(VALID_MODES)
        self.apply_enabled_modes()
        self.set_keep_history(False)        # the saved file itself is left alone
        self.set_number_format(DEFAULT_DECIMALS, False, False)
        self.sync_preferences()

    def tape_entries(self):
        """The history as printed: the same text as on screen, with today's settings."""
        return [(e["shown_formula"], self.history_result_look(e["result"], e["grouping"]))
                for e in self.history_entries]

    def update_print_actions(self):
        """Print needs something in the history, and cairo (python3-gi-cairo) to draw it."""
        can_print = bool(self.history_entries) and cairo is not None
        for item in (self.print_item, self.print_preview_item):
            item.set_sensitive(can_print)

    def print_history(self, widget=None, parent=None):
        """File → Print: the standard GTK print dialog, as in Xed."""
        if not self.history_entries:
            return
        entries, printed_at = self.tape_entries(), datetime.now()
        pages = []
        operation = Gtk.PrintOperation()
        operation.set_job_name("Xcalculator tape")
        operation.set_unit(Gtk.Unit.POINTS)
        operation.set_default_page_setup(self.page_setup)
        if self.print_settings:
            operation.set_print_settings(self.print_settings)

        def begin_print(op, context):
            pages[:] = paginate_tape(context.create_pango_layout, entries,
                                     context.get_width(), context.get_height(), printed_at)
            op.set_n_pages(len(pages))

        def draw_page(op, context, page_number):
            draw_tape_page(context.get_cairo_context(), context.create_pango_layout, entries, pages,
                           page_number, context.get_width(), context.get_height(), printed_at)

        operation.connect("begin-print", begin_print)
        operation.connect("draw-page", draw_page)
        try:
            result = operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent or self)
        except GLib.Error as error:
            self.show_message("Printing failed", error.message)
            return
        if result == Gtk.PrintOperationResult.APPLY:
            self.print_settings = operation.get_print_settings()

    def show_print_preview(self, widget=None):
        """File → Print Preview: the pages exactly as Print will draw them."""
        if not self.history_entries:
            return
        PrintPreview(self, self.tape_entries(), self.page_setup).show_all()

    def show_message(self, title, text):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    # ------------------------------------------------------------------
    # Help menu
    # ------------------------------------------------------------------

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
        dialog.set_comments("A calculator for Linux Mint and the Cinnamon desktop, with Basic, "
                            "Scientific, Financial, Programmer and Unit Converter modes.")
        dialog.set_logo_icon_name("accessories-calculator")
        dialog.set_website(APP_WEBSITE)
        dialog.set_authors(APP_AUTHORS)
        dialog.set_copyright(f"{APP_COPYRIGHT}\n{APP_CREDIT}")    # the credit sits right below the author
        dialog.set_license_type(Gtk.License.GPL_3_0)    # GTK shows it as "version 3 or later"
        dialog.run()
        dialog.destroy()

    def push(self, text):
        self.expression += text
        self.token_stack.append(text)

    @classmethod
    def ends_with_operator(cls, expr):
        return bool(expr) and (expr[-1] in '+-*/^' or expr.endswith(cls.WORD_OPS))

    def append_token(self, label):
        digits = "0123456789"
        if len(label) == 1 and label in digits:
            kind = 'digit'
        elif label == '.':
            kind = 'dot'
        elif label in self.BINARY_OPS:
            kind = 'binary'
        elif label in self.POSTFIX_OPS or label in self.INFIX_OPS:
            kind = 'postfix'
        elif label == '1/x':
            kind = 'recip'
        elif label in self.FUNCTION_MAP:
            kind = 'func'
        elif label in ('π', 'e', 'eˣ', '10ˣ'):
            kind = 'value'
        elif label == '(':
            kind = 'open'
        elif label == ')':
            kind = 'close'
        else:
            return

        # Operators and postfix actions continue from a result; anything else starts fresh.
        continuing = kind in ('binary', 'postfix', 'recip')
        if self.is_result_active:
            if not continuing:
                self.expression = ""
                self.token_stack = []
            self.is_result_active = False

        expr = self.expression

        if kind == 'digit':
            if re.search(r'(?<![\d.])0$', expr):           # no leading zeros: 5*07 -> 5*7
                self.expression = expr[:-1]
                if self.token_stack and self.token_stack[-1] == '0':
                    self.token_stack.pop()
            self.push(label)

        elif kind == 'dot':
            current_number = re.search(r'[\d.]*$', expr).group()
            if '.' in current_number:
                pass                                        # ignore a second decimal point
            else:
                self.push('0.' if current_number == '' else '.')

        elif kind == 'binary':
            op = self.BINARY_OPS[label]
            if expr == '-':
                pass
            elif expr == '':
                if op == '-':
                    self.push('-')
                else:
                    self.push('0')
                    self.push(op)
            elif expr.endswith('('):
                if op == '-':
                    self.push('-')
            elif self.ends_with_operator(expr):
                if op == '-' and (expr[-1] in '*/^+' or expr.endswith(('Δ%', 'Mrgn'))) \
                        and not expr.endswith(('mod', 'nCr', 'nPr')):
                    self.push('-')                          # unary minus: 5*-3
                else:
                    base = re.sub(r'(mod|Δ%|Mrgn|nCr|nPr|[+\-*/^])+$', '', expr)
                    if base == '':
                        self.expression, self.token_stack = '', []
                        if op == '-':
                            self.push('-')
                        else:
                            self.push('0')
                            self.push(op)
                    elif base.endswith('(') and op != '-':
                        pass
                    else:
                        self.expression = base
                        self.token_stack = []
                        self.push(op)
            else:
                self.push(op)

        elif kind == 'postfix':
            add = self.POSTFIX_OPS.get(label) or self.INFIX_OPS[label]
            if expr == '':
                self.push('0')
                self.push(add)
            elif expr == '-' or expr.endswith('(') or self.ends_with_operator(expr):
                pass                                        # nothing to apply it to
            else:
                self.push(add)

        elif kind == 'recip':
            start = operand_start(expr) if expr else None
            if expr == '':
                self.push('1/')
            elif start is not None:
                self.expression = expr[:start] + '1/(' + expr[start:] + ')'
                self.token_stack = []
            elif expr.endswith('(') or self.ends_with_operator(expr) or expr == '-':
                self.push('1/')

        elif kind == 'func':
            self.push(self.FUNCTION_MAP[label])

        elif kind == 'value':
            if label == 'eˣ':
                self.push('e^')
            elif label == '10ˣ':
                self.push('*10^' if re.search(r'[\d.]$', expr) else '10^')
            else:
                self.push(label)

        elif kind == 'open':
            self.push('(')

        elif kind == 'close':
            if expr.count('(') > expr.count(')'):
                self.push(')')

        self.update_display()


if __name__ == "__main__":
    GLib.set_prgname("xcalculator")         # the window's class matches xcalculator.desktop,
    Gdk.set_program_class("Xcalculator")    # so the panel groups the window with its menu entry
    GLib.set_application_name("Xcalculator")
    Gtk.Window.set_default_icon_name("accessories-calculator")    # the icon theme's calculator, like Xed's
    app = XCalculator()
    app.show_all()
    Gtk.main()
