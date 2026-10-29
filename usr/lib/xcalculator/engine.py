# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The arithmetic behind every mode: numbers (ordinary floats, or mpmath for up to
50 decimal places), turning answers into text, and reading what was typed."""
import ast
import math
import operator
import re
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext


# High-precision math (package python3-mpmath): up to 50 decimal places instead of 15.
# Without it the calculator uses ordinary floating-point numbers.
try:
    import mpmath
except ImportError:
    mpmath = None


MAX_INT_BITS = 14000      # keeps results printable (Python limits int->str to 4300 digits)


MAX_FACTORIAL = 1000


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
    """An mpmath function that, like ordinary math, refuses complex or infinite answers."""
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
