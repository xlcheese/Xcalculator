# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Financial mode: loans and savings, cash flows, amortization and depreciation."""
import math
from i18n import _
from engine import format_number


class FinanceError(ValueError):
    """A financial calculation that cannot be done; the message is shown to the user."""


MAX_PERIODS = 5000        # cap on amortization periods / expanded cash flows


class FinancialMode:
    """The Financial keypad. Values are stored with keys like a business calculator's."""

    FIN_TVM_KEYS = ('N', 'I/Y', 'PV', 'PMT', 'FV')

    FIN_ACTIONS = ('CPT', 'P/Y', 'BGN', 'CFj', 'Nj', 'NPV', 'IRR', 'P1', 'P2',
                   'BAL', 'PRN', 'INT', 'SL', 'SYD', 'DB', 'EFF', 'NOM', 'Clear All')

    @staticmethod
    def _annuity_factor(i, n):
        """((1+i)^n - 1) / i, with the i -> 0 limit handled."""
        if abs(i) < 1e-12:
            return n
        if 1 + i <= 0:
            raise FinanceError(_("Rate out of range"))
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
            raise FinanceError(_("No solution"))
        roots = []
        for a, b in brackets:
            if a == b:
                roots.append(a)
                continue
            fa = f(a)
            for step in range(200):
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
            raise FinanceError(_("P/Y must be positive"))
        return self.tvm['I/Y'] / (100 * self.periods_per_year)

    def compute_tvm(self, key):
        n, pv, pmt, fv = (self.tvm[k] for k in ('N', 'PV', 'PMT', 'FV'))
        b = 1 if self.begin_mode else 0
        py = self.periods_per_year
        if py <= 0:
            raise FinanceError(_("P/Y must be positive"))

        if key == 'I/Y':
            if n <= 0:
                raise FinanceError(_("N must be positive"))

            def equation(i):
                growth = (1 + i) ** n
                return pv * growth + pmt * (1 + i * b) * self._annuity_factor(i, n) + fv
            return self._find_root(equation) * py * 100

        i = self.periodic_rate()
        if 1 + i <= 0:
            raise FinanceError(_("Rate out of range"))
        growth = (1 + i) ** n
        annuity = (1 + i * b) * self._annuity_factor(i, n)

        if key == 'FV':
            return -(pv * growth + pmt * annuity)
        if key == 'PV':
            return -(fv + pmt * annuity) / growth
        if key == 'PMT':
            if annuity == 0:
                raise FinanceError(_("N must not be 0"))
            return -(pv * growth + fv) / annuity
        if key == 'N':
            if abs(i) < 1e-12:
                if pmt == 0:
                    raise FinanceError(_("PMT must not be 0"))
                return -(pv + fv) / pmt
            a = pmt * (1 + i * b) / i
            numerator, denominator = a - fv, a + pv
            if denominator == 0 or numerator / denominator <= 0:
                raise FinanceError(_("No solution"))
            return math.log(numerator / denominator) / math.log(1 + i)
        raise FinanceError(_("Unknown key"))

    def expanded_cash_flows(self):
        flows = []
        for amount, count in self.cash_flows:
            if len(flows) + int(count) > MAX_PERIODS:    # check before building the list
                raise FinanceError(_("Too many cash flows"))
            flows.extend([amount] * int(count))
        return flows

    def compute_npv(self, rate_percent):
        flows = self.expanded_cash_flows()
        if not flows:
            raise FinanceError(_("Enter cash flows with CFj"))
        r = float(rate_percent) / 100      # Financial works in ordinary floats (15 digits)
        if 1 + r <= 0:
            raise FinanceError(_("Rate out of range"))
        return sum(cf / (1 + r) ** t for t, cf in enumerate(flows))

    def compute_irr(self):
        flows = self.expanded_cash_flows()
        if len(flows) < 2 or not (any(c > 0 for c in flows) and any(c < 0 for c in flows)):
            raise FinanceError(_("IRR needs inflows and outflows"))
        return self._find_root(lambda r: sum(c / (1 + r) ** t for t, c in enumerate(flows))) * 100

    def compute_amortization(self):
        if self.amort_p1 is None or self.amort_p2 is None:
            raise FinanceError(_("Set P1 and P2 first"))
        p1, p2 = self.amort_p1, self.amort_p2
        if p1 < 1 or p2 < p1:
            raise FinanceError(_("P2 must be at least P1"))
        if p2 > MAX_PERIODS:
            raise FinanceError(_("Too many periods"))
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
            raise FinanceError(_("Set N to the asset life"))
        if year < 1 or year > math.ceil(life):
            raise FinanceError(_("Year must be within the asset life"))
        if method == 'SL':
            return (cost - salvage) / life
        if method == 'SYD':
            n = int(life)
            if n != life:
                raise FinanceError(_("SYD needs a whole-number life"))
            return (cost - salvage) * (n - year + 1) / (n * (n + 1) / 2)
        # declining balance: I/Y holds the declining percent (200 = double declining)
        factor = self.tvm['I/Y'] / 100
        if factor <= 0:
            raise FinanceError(_("Set I/Y to the declining % (e.g. 200)"))
        if year > MAX_PERIODS:
            raise FinanceError(_("Too many periods"))
        book = cost
        depreciation = 0.0
        for year_number in range(int(year)):
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
            raise FinanceError(_("Enter a whole number >= {minimum}").format(minimum=minimum))
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
                raise FinanceError(_("P/Y must be positive"))
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
                raise FinanceError(_("Enter a cash flow first"))
            self.cash_flows.append([float(value), 1])
            self.show_result(value, echo=True)
        elif label == 'Nj':
            if not self.cash_flows:
                raise FinanceError(_("Enter a cash flow with CFj first"))
            count = self.entered_count()
            if count > MAX_PERIODS:
                raise FinanceError(_("Nj can be at most {count}").format(count=MAX_PERIODS))
            self.cash_flows[-1][1] = count
            self.show_result(count, echo=True)
        elif label == 'NPV':
            rate = self.typed_value()
            if rate is None:
                raise FinanceError(_("Enter the discount rate % first"))
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
            # Translators: a history line for depreciation, e.g. "SL yr 3" (year 3)
            record = _("{method} yr {year}").format(method=label, year=year)
            self.show_result(self.compute_depreciation(label, year), record=record)
        elif label in ('EFF', 'NOM'):
            rate = self.entered_value()
            rate = None if rate is None else float(rate)
            m = self.periods_per_year
            if rate is None:
                raise FinanceError(_("Enter a rate % first"))
            if m <= 0:
                raise FinanceError(_("P/Y must be positive"))
            if label == 'EFF':
                if 1 + rate / 100 / m <= 0:
                    raise FinanceError(_("Rate out of range"))
                result = ((1 + rate / 100 / m) ** m - 1) * 100
            else:
                if 1 + rate / 100 <= 0:
                    raise FinanceError(_("Rate out of range"))
                result = m * ((1 + rate / 100) ** (1 / m) - 1) * 100
            self.show_result(result, record=label)
