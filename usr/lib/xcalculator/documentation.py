# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Help → Documentation and Keyboard Shortcuts: the pages, and the window that shows them."""
import gi
import re
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
from i18n import N_, _


# Help → Keyboard Shortcuts: (group, [(accelerator, what it does)]), in two columns like Xed
SHORTCUTS_PAGE = "shortcuts"


SHORTCUT_COLUMNS = (
    ((_("Windows"), (("<Control>n", _("Open a new window")),
                     ("<Control>w", _("Close the window")),
                     ("<Control>q", _("Quit Xcalculator")))),
     (_("Modes"), (("<Control><Alt>b", _("Switch to Basic")),
                   ("<Control><Alt>s", _("Switch to Scientific")),
                   ("<Control><Alt>f", _("Switch to Financial")),
                   ("<Control><Alt>p", _("Switch to Programmer")),
                   ("<Control><Alt>u", _("Switch to Unit Converter")),
                   ("<Control><Alt>c", _("Switch to Currency Converter")))),
     (_("Help"), (("F1", _("Open the documentation")),
                  ("<Control>F1", _("Show the keyboard shortcuts")))),
     (_("Printing"), (("<Control>p", _("Print the history")),
                      ("<Shift><Control>p", _("Preview the printout"))))),
    ((_("Copy and Paste"), (("<Control>c", _("Copy the display, or the highlighted part")),
                            ("<Control>x", _("Cut the highlighted part")),
                            ("<Control>v", _("Paste a number or calculation")),
                            ("<Control>a", _("Highlight everything in the display")))),
     (_("Text Size"), (("<Control>equal", _("Larger text")),
                       ("<Control>minus", _("Smaller text")),
                       ("<Control>0", _("Normal text size")))),
     (_("Basic"), (("<Control>r", _("Square root (√)")),)),
     (_("Scientific"), (("<Control>r", _("Square root (²√x)")),
                        ("<Control>i", _("Reciprocal (1/x)")))),
     (_("Programmer"), (("<Control>h", _("Switch to HEX")),
                        ("<Control>d", _("Switch to DEC")),
                        ("<Control>o", _("Switch to OCT")),
                        ("<Control>b", _("Switch to BIN"))))),
)


LIST_ITEM_RE = re.compile(r'^  (•|\d+\.) (.*)$')     # "  • text" and "  1. text" in the pages below


def section_heading(title):
    """A heading one step bigger than "Numbers" and smaller than the page title, like General."""
    return f'<span size="110%"><b>{GLib.markup_escape_text(title)}</b></span>'


# Help → Documentation: (page name, the mode it explains or None, paragraphs of Pango markup).
# The name is translated when shown; it also picks the page, so it stays in English here.
HELP_PAGES = (
    (N_("Getting Started"), None, (
        # Translators: the Documentation pages are Pango markup: keep <b>…</b> and &amp; &lt; &gt; as they are
        _("Xcalculator has six modes. Pick one from the <b>Mode</b> menu:\n"
          "  • <b>Basic</b> for everyday sums.\n"
          "  • <b>Scientific</b> for powers, roots, trigonometry, logarithms, and more.\n"
          "  • <b>Financial</b> for loans, savings, cash flows, and depreciation.\n"
          "  • <b>Programmer</b> for hexadecimal, binary, and bitwise work.\n"
          "  • <b>Unit Converter</b> for lengths, weights, temperatures, and more.\n"
          "  • <b>Currency Converter</b> for exchange rates from the European Central Bank."),
        _("<b>Typing</b>\n"
          "Click the buttons or use the keyboard. Click in the display or use the arrow keys to move the cursor. Typed text, Backspace, and Delete all work at the cursor position. Highlighted text is replaced by what you type."),
        _("<b>The history</b>\n"
          "Every answer is added to the history above the display. Click an answer to use it in your next calculation, or click a calculation to bring it back. <b>View → Clear History</b> empties it, and <b>File → Print</b> prints it like an adding-machine tape. The history is saved as you go; see Preferences to show it again the next time Xcalculator opens."),
        _("<b>Long numbers</b>\n"
          "An answer too wide for the window is shown in scientific notation, like 3.7×10²⁰. Widen the window to see it in full. Copy and the history always keep the full number."),
        _("<b>Copy and paste</b>\n"
          "<b>Edit → Copy</b> copies the display. <b>Edit → Paste</b> pastes a number or a simple calculation."),
        _("<b>Window size and text size</b>\n"
          "Stretch the history taller and every mode keeps that height. Each mode remembers its own width. <b>View → Larger Font</b>, <b>Smaller Font</b>, and <b>Reset Font Size</b> change the text size, and <b>View → Reset View</b> returns to the original window size."),
        _("<b>Preferences</b>\n"
          "<b>Edit → Preferences</b> sets decimal places, thousands separators, angle units, and more. Also choose which modes appear in the Mode menu."),
    )),
    (N_("Basic"), "Basic", (
        _("The everyday keypad. Every other mode builds on it."),
        _("  <b>Clear</b>  start again\n"
          "  <b>√</b>  square root of the number you just typed, or of the answer: 9 √ = 3\n"
          "  <b>%</b>  percent: 50% = 0.5, and 200 × 15% = 30\n"
          "  <b>±</b>  change the sign of the number you are typing\n"
          "  <b>=</b>  work out the answer (or press Enter)\n"
          "  <b>⌫</b>  at the right end of the display (and on the keypad in the other modes): delete the character before the cursor"),
        _("Multiplication and division are done before addition and subtraction, so 2 + 3 × 4 = 14."),
        _("<b>Typing with the keyboard</b>\n"
          "  <b>0–9</b>, <b>.</b>  numbers\n"
          "  <b>+  -  *  /</b>  add, subtract, multiply, divide\n"
          "  <b>%</b>  percent\n"
          "  <b>Enter</b> or <b>=</b>  work out the answer\n"
          "  <b>Backspace</b>  delete before the cursor;  <b>Delete</b>  delete after it\n"
          "  <b>Escape</b>  clear\n"
          "  <b>← →  Home  End</b>  move the cursor;  hold <b>Shift</b> to highlight"),
        _("The other modes use these keys too; each mode's page lists what it adds or changes. For the Ctrl shortcuts, see the Keyboard page."),
    )),
    (N_("Scientific"), "Scientific", (
        _("Everything in Basic, plus:"),
        _("<b>Powers and roots</b>\n"
          "  <b>x²</b>, <b>x³</b>, <b>xʸ</b>  powers;  <b>eˣ</b>, <b>10ˣ</b>  powers of e and 10\n"
          "  <b>²√x</b>, <b>³√x</b>, <b>ʸ√x</b>  square, cube, and y-th roots;  <b>1/x</b>  reciprocal\n"
          "  <b>EE</b>  times ten to the power: 3 EE 5 = 300000"),
        _("<b>Trigonometry</b>\n"
          "  <b>sin</b>, <b>cos</b>, <b>tan</b>, and the hyperbolic <b>sinh</b>, <b>cosh</b>, <b>tanh</b>\n"
          "  <b>2nd</b>  switches these buttons to their inverses (sin⁻¹ and so on)\n"
          "  <b>Rad</b> / <b>Deg</b>  switches between radians and degrees. Degrees are used until you switch."),
        _("<b>Logarithms and constants</b>\n"
          "  <b>ln</b>  natural logarithm;  <b>log₁₀</b>  base-10 logarithm\n"
          "  <b>π</b>, <b>e</b>  the constants;  <b>Rand</b>  a random number between 0 and 1\n"
          "  <b>x!</b>  factorial: 5! = 120"),
        _("<b>More functions</b>\n"
          "  <b>|x|</b>  absolute value: |−5| = 5\n"
          "  <b>nCr</b>  combinations, when order doesn't matter: 5 nCr 2 = 10\n"
          "  <b>nPr</b>  permutations, when order matters: 5 nPr 2 = 20\n"
          "  <b>round</b>  to the nearest whole number: round(2.5) = 3\n"
          "  <b>mod</b>  the remainder: 17 mod 5 = 2\n"
          "  <b>f(x)</b>  a menu of more functions, each with a short explanation"),
        _("<b>Memory</b>\n"
          "  <b>M+</b> adds the display to the memory, <b>M−</b> subtracts it, <b>MR</b> recalls it, and <b>MC</b> clears it."),
        _("<b>Keyboard</b>\n"
          "All of Basic's keys work here too, plus:\n"
          "  <b>^</b>  power;  <b>( )</b>  parentheses;  <b>!</b>  factorial;  <b>e</b>  the constant e;  <b>p</b>  π"),
    )),
    (N_("Financial"), "Financial", (
        _("The lines under the display always show the values stored so far."),
        _("<b>Loans and savings (time value of money)</b>\n"
          "The five keys <b>N</b>, <b>I/Y</b>, <b>PV</b>, <b>PMT</b>, and <b>FV</b> are the number of payments, the yearly interest rate in percent, the present value, the payment, and the future value.\n"
          "  1. Type a number and press a key to store it. Press a key on its own to see what it holds.\n"
          "  2. Store four of the five.\n"
          "  3. Press <b>CPT</b>, then the fifth key, to work it out.\n"
          "Money you receive is positive and money you pay out is negative. For a loan of 20,000, store PV = 20000, and the payment PMT comes out negative.\n"
          "  <b>P/Y</b>  payments per year (12 to start); type a number and press P/Y to change it\n"
          "  <b>BGN</b>  switches between payments at the end of each period (END) and the beginning (BGN)"),
        _("<b>Cash flows</b>\n"
          "  <b>CFj</b>  type an amount and press CFj; the first one is the starting amount, usually an investment entered as negative\n"
          "  <b>Nj</b>  type a count and press Nj to repeat the last cash flow that many times\n"
          "  <b>NPV</b>  type the discount rate in percent and press NPV for the net present value\n"
          "  <b>IRR</b>  the internal rate of return"),
        _("<b>Loan schedule (amortization)</b>\n"
          "With the loan stored, type a payment number and press <b>P1</b>, then another and press <b>P2</b>.\n"
          "  <b>BAL</b>  the balance left after payment P2\n"
          "  <b>PRN</b>, <b>INT</b>  the principal and the interest paid from P1 to P2"),
        _("<b>Depreciation</b>\n"
          "Store the asset's life in years as N, its cost as PV, and its salvage value as FV. Type a year and press <b>SL</b> (straight line), <b>SYD</b> (sum of the years' digits), or <b>DB</b> (declining balance; store the declining percent, such as 200, as I/Y)."),
        _("<b>Interest rates</b>\n"
          "  <b>EFF</b>  type a nominal yearly rate for the effective yearly rate, compounding P/Y times a year\n"
          "  <b>NOM</b>  the reverse"),
        _("<b>Business</b>\n"
          "  <b>Mrgn</b>  profit margin: cost Mrgn price, then =. 60 Mrgn 100 = 40 (percent)\n"
          "  <b>Δ%</b>  percent change: old Δ% new, then =. 80 Δ% 100 = 25 (percent)"),
        _("<b>Clear All</b> erases every stored financial value."),
        _("Financial answers are worked out to about 15 significant digits, whatever the decimal places setting: far more than money needs."),
        _("<b>Keyboard</b>\n"
          "All of Basic's keys work here too, plus <b>( )</b> for parentheses. The financial keys (N, PMT, CPT, and so on) are on the buttons only."),
    )),
    (N_("Programmer"), "Programmer", (
        _("Programmer mode works with whole numbers stored in a fixed number of bits, the way a computer does."),
        _("<b>Number bases (HEX, DEC, OCT, BIN)</b>\n"
          "Click a base to type and show numbers in it. The number on screen is converted when you switch. The lines under the display always show the current value in all four bases."),
        _("<b>Word size (QWORD / DWORD / WORD / BYTE)</b>\n"
          "The number of bits: 64, 32, 16, or 8. Numbers are signed: in BYTE the range is -128 to 127, and 127 + 1 wraps around to -128. In HEX, OCT, and BIN you see the raw bits, so -1 in BYTE shows as FF."),
        _("<b>Bitwise operators</b>\n"
          "AND, OR, and XOR compare two numbers bit by bit. NOT flips every bit of the next number. NAND and NOR are NOT AND and NOT OR. Example: in BIN, 1100 AND 1010 = 1000."),
        _("<b>Shifts</b>\n"
          "&lt;&lt; moves bits left (each step doubles the number); &gt;&gt; moves them right (each step halves it)."),
        _("<b>Arithmetic</b>\n"
          "+, −, × work as usual. ÷ drops the remainder and mod gives it: 17 ÷ 5 = 3 and 17 mod 5 = 2."),
        _("<b>Order of operations (first to last)</b>\n"
          "NOT and minus sign, then × ÷ mod, then + −, then &lt;&lt; &gt;&gt;, then AND, then XOR, then OR. Use parentheses when unsure."),
        _("<b>Try it</b>\n"
          "1. Click HEX, type FF, press =. The lines below show DEC 255.\n"
          "2. Click BYTE (cycle the word size) and DEC 255 becomes -1.\n"
          "3. Click BIN and try 1100 XOR 1010 =."),
        # xgettext: no-python-format
        _("<b>Keyboard</b>\n"
          "All of Basic's keys work here too (except the decimal point: whole numbers only), plus:\n"
          "  <b>a–f</b>  hex digits\n"
          "  <b>&amp; | ^ ~</b>  AND, OR, XOR, NOT\n"
          "  <b>&lt; &gt;</b>  shift left and right\n"
          "  <b>( )</b>  parentheses\n"
          "Two keys mean something different here: ^ is XOR (not power) and % is mod (not percent)."),
        _("Hover over any button for a short explanation."),
    )),
    (N_("Unit Converter"), "Unit Converter", (
        _("  1. Pick a category: Angle, Area, Density, Digital Storage, Energy, Length, Mass, Pressure, Speed, Temperature, Time, or Volume.\n"
          "  2. Pick a unit beside each box.\n"
          "  3. Type a number in either box. The other box converts as you type; the box with the green outline is the one you are typing in."),
        _("The line under the boxes shows the formula used. ≈ means the number in it is rounded."),
        _("  <b>Capture</b> (or Enter)  saves the conversion to the history\n"
          "  <b>±</b>  makes the number negative, for temperatures below zero"),
        _("Click a captured line in the history to bring back that conversion: its category, both units, and the number."),
        _("Conversions use the official definitions (for example, 1 inch is exactly 2.54 cm) and are shown with the decimal places set in Preferences. The converter remembers your category and the units you chose in each."),
        _("<b>Keyboard</b>\n"
          "Basic's number, Backspace, Delete, Escape, and cursor keys work here too. Two keys work differently:\n"
          "  <b>-</b>  makes the number negative (like ±)\n"
          "  <b>Enter</b> or <b>=</b>  Capture\n"
          "The other operator keys (+ * / %) do nothing here, since the converter has no operators."),
    )),

    (N_("Currency Converter"), "Currency Converter", (
        _("Converts between the euro and about 30 other currencies, using the European Central Bank's reference rates. The bank publishes new rates once a day on working days."),
        _("<b>Getting the rates</b>\n"
          "Xcalculator doesn't go online until you ask it to. The first time, click <b>Download Rates</b>. After that the button reads <b>Refresh Rates</b>: click it whenever you want the latest rates. The rates are kept in ~/.cache/xcalculator, so the converter also works offline, with the last rates it downloaded. The line under the boxes always says how old they are."),
        _("<b>Converting</b>\n"
          "  1. Pick a currency beside each box. The first time it's US Dollar and Euro; after that, the pair you used last.\n"
          "  2. Type an amount in either box. The other box converts as you type.\n"
          "Each currency is shown with its own decimal places: two for dollars and euros, none for yen. The line under the boxes gives the rate both ways."),
        _("  <b>⇅ Swap</b>  exchanges the two currencies; the amount in the top box stays\n"
          "  <b>Capture</b> (or Enter)  saves the conversion to the history; click the line later to bring it back\n"
          "  <b>±</b>  makes the amount negative"),
        _("<b>Auto Refresh</b>\n"
          "Click <b>Auto Refresh</b> (or switch on <b>Refresh rates automatically</b> in Preferences) to refresh the rates by themselves: every 3 days to start, and you can choose 1 to 30 days in Preferences. It can be switched on once you have downloaded rates."),
        _("Normally rates refresh only while Xcalculator is open. With <b>Also when Xcalculator is closed</b> switched on in Preferences, a small scheduled job checks once a day, even when Xcalculator isn't running, and refreshes rates that are older than your number of days. If the computer was off, it checks a few minutes after you next log in; with no internet connection it tries again the next day. Switching either setting off stops it."),
        _("These are reference rates, the middle of the market. A bank or a card usually charges a little more."),
        _("<b>Keyboard</b>\n"
          "The same keys as the Unit Converter: numbers, Backspace, Delete, Escape, and the cursor keys; <b>-</b> makes the amount negative and <b>Enter</b> or <b>=</b> captures."),
    )),
    (N_("Preferences"), None, (
        _("Open <b>Edit → Preferences</b>. Changes take effect at once. <b>Reset to Defaults</b> puts every preference back the way it was the first time; it doesn't touch the saved history."),
        section_heading(_("General")),
        _("<b>Numbers</b>\n"
          "  • <b>Decimal places:</b> Rounds answers to 0–50 decimal places (default 10). Uses high-precision math from the python3-mpmath package, which is installed with Xcalculator (falls back to 15 places if it's missing). Very small answers keep their digits instead of rounding to 0, and switch to scientific notation if they don't fit. Changing it re-shows the answer on screen; lines already in the history keep their digits.\n"
          "  • <b>Show all decimal places:</b> Pads answers with trailing zeros (with 2 places, 19.5 becomes 19.50). Useful for tracking currency.\n"
          "  • <b>Thousands separators:</b> 1234567 shows as 1,234,567 in answers, history, and the printout. Not used while typing or in Programmer mode. Copy retains plain digits."),
        _("<b>Scientific</b>\n"
          "  • <b>Angle units:</b> Sets degrees or radians for sin, cos, and tan. The Rad/Deg button in Scientific changes the same setting."),
        _("<b>Programmer</b>\n"
          "  • <b>Word size</b> and <b>Starting number base:</b> For Programmer mode; its buttons change the same settings."),
        _("<b>Currency Converter</b>\n"
          "  • <b>Refresh rates automatically:</b> The same setting as the Auto Refresh button. It can be switched on once rates have been downloaded.\n"
          "  • <b>Refresh interval in days:</b> How often rates refresh: every 1 to 30 days (default 3).\n"
          "  • <b>Also when Xcalculator is closed:</b> Also refreshes in the background, once a day, even when Xcalculator isn't running (default off)."),
        _("<b>History</b>\n"
          "  • <b>Keep history after closing:</b> Restores history upon launch. Continuously logs the last 500 lines to ~/.config/xcalculator/history.json. <b>View → Clear History</b> only empties the window.\n"
          "  • <b>Delete Saved History:</b> Clears the history and deletes the file."),
        section_heading(_("Modes")),
        _("Switch off unused modes to hide them from the Mode menu. At least one mode stays on."),
    )),
    (N_("Keyboard"), None, SHORTCUTS_PAGE),     # drawn with key caps, like Xed's shortcuts window
)


class HelpWindow(Gtk.Window):
    """Help → Documentation: one page per topic, picked from a list on the left."""

    def __init__(self, calculator):
        super().__init__(title=_("Help - Xcalculator"), transient_for=calculator, destroy_with_parent=True)
        self.set_default_size(860, 700)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.page_for_mode = {}
        for name, mode, paragraphs in HELP_PAGES:
            title = _(name)
            if paragraphs == SHORTCUTS_PAGE:
                self.stack.add_titled(self.build_shortcuts_page(), name, title)
                continue
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.add(self.build_text_page(title, paragraphs))
            self.stack.add_titled(scroller, name, title)
            if mode:
                self.page_for_mode[mode] = name
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
    def text_label(markup):
        label = Gtk.Label(xalign=0)
        label.set_markup(markup)
        label.set_line_wrap(True)
        label.set_selectable(True)
        label.set_max_width_chars(70)
        return label

    def build_text_page(self, title, paragraphs):
        """A page of paragraphs. List items ("  • text", "  1. text") get their own row, so
        a long item wraps under its own text instead of under the bullet."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.set_margin_start(24); page.set_margin_end(24); page.set_margin_top(18); page.set_margin_bottom(24)
        page.pack_start(self.text_label(f"<big><b>{GLib.markup_escape_text(title)}</b></big>"), False, False, 0)
        for paragraph in paragraphs:
            lines = paragraph.split("\n")
            if not all(self.valid_markup(line) for line in lines):
                page.pack_start(self.text_label(paragraph), False, False, 0)     # markup across lines
                continue
            block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for line in lines:
                item = LIST_ITEM_RE.match(line)
                if item:
                    row = Gtk.Box(spacing=6)
                    row.set_margin_start(12)
                    marker = self.text_label(item.group(1))
                    marker.set_valign(Gtk.Align.START)
                    marker.set_selectable(False)
                    row.pack_start(marker, False, False, 0)
                    row.pack_start(self.text_label(item.group(2)), True, True, 0)
                    block.pack_start(row, False, False, 0)
                elif line.startswith("  "):                 # an indented line, such as a key and what it does
                    label = self.text_label(line[2:])
                    label.set_margin_start(12)
                    block.pack_start(label, False, False, 0)
                else:
                    block.pack_start(self.text_label(line), False, False, 0)
            page.pack_start(block, False, False, 0)
        return page

    @staticmethod
    def valid_markup(text):
        try:
            Pango.parse_markup(text, -1, "\0")
            return True
        except GLib.Error:
            return False

    @staticmethod
    def build_shortcuts_page():
        """Shortcut keys drawn as key caps (Ctrl + N), in groups and two columns, like Xed."""
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<big><b>{GLib.markup_escape_text(_('Keyboard Shortcuts'))}</b></big>")
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
