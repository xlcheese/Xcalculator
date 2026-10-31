# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typing a calculation and working it out: the keypad Basic, Scientific and Financial share."""
import gi
import ast
import re
import traceback
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from i18n import _
from engine import (
    BIN_OPS, CONSTANTS, FLOAT_DIGITS, MATH, MAX_INT_BITS, NUMBER_FORMAT, TRAILING_NUM_RE,
    UNARY_OPS, add_implicit_multiplication, digits_before_point, expand_combinatorics,
    expand_factorials, format_number, mpmath, operand_start, set_precision
)
from financial import FinanceError
from programmer import PROG_BACKSPACE_TOKENS, ProgrammerError
from easter_egg import FLIP_TRIGGER


class BasicMode:
    """Builds the expression from button presses, then evaluates it safely."""

    BINARY_OPS = {
        '+': '+', '-': '-', '*': '*', '/': '/', '^': '^', 'mod': 'mod',
        '×': '*', '÷': '/', '−': '-', 'Δ%': 'Δ%', 'Mrgn': 'Mrgn', 'nCr': 'nCr', 'nPr': 'nPr',
    }

    WORD_OPS = ('mod', 'Δ%', 'Mrgn', 'nCr', 'nPr')

    POSTFIX_OPS = {'x²': '^2', 'x³': '^3', '%': '%', 'x!': '!', '!': '!'}

    INFIX_OPS = {'xʸ': '^', 'ʸ√x': '^(1/', 'EE': '*10^'}

    BACKSPACE_TOKENS = [
        "asinh(", "acosh(", "atanh(", "asin(", "acos(", "atan(",
        "sinh(", "cosh(", "tanh(", "sin(", "cos(", "tan(",
        "sqrt(", "cbrt(", "log10(", "log2(", "log(", "mod", "Δ%", "Mrgn", "nCr", "nPr",
        "abs(", "round(", "floor(", "ceil(", "int(", "frac(", "sgn(", "sec(", "csc(", "cot(",
    ]

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
            message = _("Malformed Expression")
        elif isinstance(error, ZeroDivisionError):
            message = _("Cannot divide by zero")
        elif isinstance(error, OverflowError):
            message = _("Result too large")
        elif isinstance(error, ValueError):
            message = _("Invalid input")
        else:
            traceback.print_exception(error)
            message = _("Calculation Error")
        self.error_label.set_text(message)
        self.is_result_active = False

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
        elif label == '√':
            kind = 'root'
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
        continuing = kind in ('binary', 'postfix', 'recip', 'root')
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

        elif kind == 'root':
            # Basic's √, as on a pocket calculator: the square root of the number just typed
            # (or of the answer). 9 √ gives sqrt(9); √ with no number yet starts sqrt(.
            start = operand_start(expr) if expr else None
            if re.fullmatch(r'-[\d.]+', expr):
                start = 0                                   # a negative answer, sign and all
            if start is not None:
                self.expression = expr[:start] + 'sqrt(' + expr[start:] + ')'
                self.token_stack = []
            elif expr == '' or expr == '-' or expr.endswith('(') or self.ends_with_operator(expr):
                self.push('sqrt(')

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
