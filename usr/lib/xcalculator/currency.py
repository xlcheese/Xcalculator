# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Currency Converter mode: exchange rates from the European Central Bank.

Nothing is downloaded until the person clicks Download Rates. After that, rates are
refreshed when they click Refresh Rates, or automatically every few days if they switch
Auto Refresh on: while Xcalculator is open, and also when it's closed if they choose that
in Preferences (a systemd user timer runs "xcalculator --refresh-rates" once a day)."""
import gettext
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from gi.repository import GLib
from i18n import N_, _, ngettext
from config import APP_VERSION, CONFIG_FILE
from engine import DECIMAL_RE

# the bank's reference rates, published once a day on working days (about 4 pm in Frankfurt);
# XCALCULATOR_RATES_URL lets the tests use a local copy instead
RATES_URL = os.environ.get("XCALCULATOR_RATES_URL",
                           "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml")
RATES_DIR = os.path.join(GLib.get_user_cache_dir(), "xcalculator")      # ~/.cache/xcalculator
RATES_FILE = os.path.join(RATES_DIR, "rates.json")
MAX_RATES_SIZE = 200000                     # bytes; the real file is about 2 kB
CURRENCY = "Currency"                       # the converter's "category" in this mode
CURRENCY_START = ("USD", "EUR")             # the first time; then the last pair used
DEFAULT_INTERVAL = 3                        # days between automatic refreshes
MAX_INTERVAL = 30
CHECK_SECONDS = 3600                        # while open: look once an hour whether rates are due
MESSAGE_SECONDS = 6                         # how long "Auto refresh on" and the like stay up
TIMER = "xcalculator-rates.timer"           # the systemd user timer for refreshing when closed
TIMER_FOLDERS = ("/usr/lib/systemd/user", "/usr/local/lib/systemd/user",
                 os.path.join(GLib.get_user_data_dir(), "systemd", "user"))

# The European Central Bank's currencies (and the euro), offered before any rates are downloaded.
# After that, the list comes from the bank's own file.
BANK_CURRENCIES = ("AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "IDR",
                   "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON",
                   "SEK", "SGD", "THB", "TRY", "USD", "ZAR")
# Currency names come from the iso-codes package (in every Linux Mint), already translated
# into over 160 languages: the official ISO 4217 names, such as "Yen" and "Pound Sterling".
ISO_4217_FILE = "/usr/share/iso-codes/json/iso_4217.json"
# decimal places each currency is written with (ISO 4217); all the others use 2
CURRENCY_DECIMALS = {"JPY": 0, "KRW": 0, "ISK": 0}
CODE_RE = re.compile(r'[A-Z]{3}')


# ---------------------------------------------------------------------------
# The rates: reading the bank's file, keeping a copy, downloading
# ---------------------------------------------------------------------------

def parse_rates(text):
    """The bank's XML: (date, {code: units per euro as an exact Fraction}), with the euro."""
    date = re.search(r'''time=['"](\d{4}-\d{2}-\d{2})['"]''', text)
    pairs = re.findall(r'''currency=['"]([A-Z]{3})['"]\s+rate=['"](\d+(?:\.\d+)?)['"]''', text)
    rates = {code: Fraction(rate) for code, rate in pairs if Fraction(rate) > 0}
    if not date or len(rates) < 5 or "USD" not in rates:
        raise ValueError("not the European Central Bank's rates file")
    datetime.strptime(date.group(1), "%Y-%m-%d")    # a real date
    rates["EUR"] = Fraction(1)
    return date.group(1), rates


def download_rates():
    """Download today's rates and keep a copy. Raises OSError or ValueError on failure."""
    request = urllib.request.Request(RATES_URL, headers={"User-Agent": f"Xcalculator/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read(MAX_RATES_SIZE).decode("utf-8", "replace")
    date, rates = parse_rates(text)
    data = {"date": date, "downloaded": time.time(), "rates": {c: str(r) for c, r in rates.items()}}
    os.makedirs(RATES_DIR, exist_ok=True)
    temporary = RATES_FILE + ".new"
    with open(temporary, "w") as f:
        json.dump(data, f)
    os.replace(temporary, RATES_FILE)       # never a half-written file, even if two run at once
    return data


def load_rates():
    """The rates downloaded last time, or None."""
    try:
        with open(RATES_FILE) as f:
            data = json.load(f)
        rates = {c: Fraction(r) for c, r in data["rates"].items() if CODE_RE.fullmatch(c)}
        datetime.strptime(data["date"], "%Y-%m-%d")
        if len(rates) < 5 or not all(r > 0 for r in rates.values()):
            return None
        return {"date": data["date"], "downloaded": float(data["downloaded"]),
                "rates": {c: str(r) for c, r in rates.items()}}
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


def rates_due(data, interval):
    """True when there are no rates, or they were downloaded `interval` days ago or more."""
    return data is None or time.time() - data["downloaded"] >= interval * 86400 - 600


def convert_currency(value, rates, from_code, to_code):
    return value * Fraction(rates[to_code]) / Fraction(rates[from_code])


def currency_decimals(code):
    return CURRENCY_DECIMALS.get(code, 2)


def format_money(value, code):
    """An amount with the currency's own decimal places: 92.30 dollars, 5000 yen."""
    with localcontext() as ctx:
        ctx.prec = 80
        amount = Decimal(value.numerator) / Decimal(value.denominator)
        rounded = amount.quantize(Decimal(1).scaleb(-currency_decimals(code)), rounding=ROUND_HALF_UP)
    text = format(rounded, 'f')
    return text.lstrip("-") if rounded == 0 else text      # no "-0.00"


def format_rate(value):
    """A rate to five significant digits: 0.92340, 1.0830, 151.23."""
    with localcontext() as ctx:
        ctx.prec = 40
        rate = Decimal(value.numerator) / Decimal(value.denominator)
        return format(rate.quantize(Decimal(1).scaleb(rate.adjusted() - 4), rounding=ROUND_HALF_UP), 'f')


def rates_date_text(data):
    # Translators: the date of the exchange rates, in Python's strftime format
    # (%b month, %d day, %Y year), e.g. "Oct 28, 2026"
    return datetime.strptime(data["date"], "%Y-%m-%d").strftime(_("%b %d, %Y"))


def currency_name(code):
    """The currency's ISO 4217 name in the person's language, or just its code."""
    if CurrencyNames.names is None:
        CurrencyNames.load()
    name = CurrencyNames.names.get(code)
    return CurrencyNames.translation.gettext(name) if name else code


class CurrencyNames:
    names = None                            # code -> English ISO name, read the first time
    translation = gettext.NullTranslations()

    @classmethod
    def load(cls):
        try:
            with open(ISO_4217_FILE) as f:
                cls.names = {row["alpha_3"]: row["name"] for row in json.load(f)["4217"]}
        except (OSError, ValueError, KeyError, TypeError):
            cls.names = {}                  # no iso-codes: the codes alone
        cls.translation = gettext.translation("iso_4217", fallback=True)


class Rates:
    """The rates every window shares, and whether a download is under way."""
    data = None                             # what load_rates() / download_rates() return
    loaded = False
    downloading = False
    failed = False                          # the last download didn't work

    @classmethod
    def get(cls):
        if not cls.loaded:
            cls.data, cls.loaded = load_rates(), True
        return cls.data


# ---------------------------------------------------------------------------
# Refreshing when Xcalculator is closed: a systemd user timer
# ---------------------------------------------------------------------------

background_refresh_requested = None     # what this program last asked systemd for


def background_refresh_available():
    """The timer is installed with the package; running from the source folder it isn't."""
    return any(os.path.exists(os.path.join(folder, TIMER)) for folder in TIMER_FOLDERS)


def set_background_refresh(enabled):
    """Switch the daily background check on or off for this person (no password needed)."""
    global background_refresh_requested
    if not background_refresh_available() or enabled == background_refresh_requested:
        return
    background_refresh_requested = enabled
    command = ["systemctl", "--user", "enable" if enabled else "disable", "--now", TIMER]

    def run():
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Couldn't change the rates timer: {error}")
    threading.Thread(target=run, daemon=True).start()


def refresh_from_command_line():
    """"xcalculator --refresh-rates", run once a day by the timer: refresh rates that are due.
    It does nothing unless the person switched on both automatic and background refresh."""
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    except (OSError, ValueError):
        return 0
    interval = config.get("currency_interval", DEFAULT_INTERVAL)
    interval = interval if isinstance(interval, int) and 1 <= interval <= MAX_INTERVAL else DEFAULT_INTERVAL
    if not (config.get("currency_auto") is True and config.get("currency_background") is True):
        return 0
    if load_rates() is None or rates_due(load_rates(), interval):
        try:
            download_rates()
        except (OSError, ValueError) as error:  # no connection: the timer tries again tomorrow
            print(f"Couldn't refresh the exchange rates: {error}")
    return 0


# ---------------------------------------------------------------------------
# The Currency Converter's own buttons and messages
# ---------------------------------------------------------------------------

class CurrencyMode:
    """The Currency Converter: the Unit Converter's two boxes, with currencies and rates."""

    CURRENCY_TOOLTIPS = {
        'Swap': N_("Exchange the two currencies"),
        'Auto Refresh': N_("Refresh the exchange rates automatically. Change how often in Edit → Preferences."),
        'Refresh Rates': N_("Download today's rates from the European Central Bank"),
    }

    def currency_window_ready(self):
        """Called once from the window: settings, and the hourly look at whether rates are due."""
        self.currency_message = ""
        self.currency_message_timer = 0
        source = GLib.timeout_add_seconds(CHECK_SECONDS, self.currency_check)
        self.connect("destroy", lambda *args: GLib.source_remove(source))

    def currency_check(self):
        if self.current_mode == "Currency Converter" and self.currency_auto \
                and Rates.get() is not None and rates_due(Rates.get(), self.currency_interval):
            self.start_rates_download()
        return True

    def currency_units(self):
        """(name, code, None) for each currency the menus offer, by name."""
        data = Rates.get()
        codes = data["rates"] if data else BANK_CURRENCIES
        return sorted(((currency_name(c), c, None) for c in codes), key=lambda unit: unit[0].casefold())

    def currency_entered(self):
        """The Currency Converter has just been shown."""
        self.currency_refresh_buttons()
        if self.currency_auto and Rates.get() is not None and rates_due(Rates.get(), self.currency_interval):
            self.start_rates_download()

    def currency_refresh_buttons(self):
        """Download Rates or Refresh Rates; Auto Refresh and Capture wait for the first rates."""
        have_rates = Rates.get() is not None
        refresh = self.buttons.get('Refresh Rates')
        if refresh:
            refresh.set_label(_("Refresh Rates") if have_rates else _("Download Rates"))
            context = refresh.get_style_context()
            (context.remove_class if have_rates else context.add_class)("suggested-action")
            refresh.set_sensitive(not Rates.downloading)
        auto = self.buttons.get('Auto Refresh')
        if auto:
            self.syncing_widgets = True
            auto.set_active(self.currency_auto)
            self.syncing_widgets = False
            auto.set_sensitive(have_rates)
        capture = self.buttons.get('Capture')
        if capture:
            capture.set_sensitive(have_rates)

    def currency_action(self, label):
        if label == 'Swap':
            self.currency_swap()
        elif label == 'Auto Refresh':
            self.set_currency_auto(not self.currency_auto)
            self.show_currency_message(self.auto_refresh_message())
        elif label == 'Refresh Rates':
            self.start_rates_download()
        elif label in ('Capture', '=') and Rates.get() is None:
            pass                            # nothing to capture yet
        else:
            self.converter_action(label)

    def currency_swap(self):
        """⇅ Swap: exchange the two currencies; the amount in the top box stays."""
        amount = self.expression if self.conv_active == 0 else self.conv_result_full
        pair = self.conv_units[CURRENCY]
        self.conv_units[CURRENCY] = [pair[1], pair[0]]
        self.conv_use_box(0)
        self.expression = amount if DECIMAL_RE.fullmatch(amount) else ""
        self.token_stack = []
        self.conv_set_category(CURRENCY)
        self.update_display()
        self.display.grab_focus_without_selecting()
        self.save_window_settings()

    def auto_refresh_message(self):
        if not self.currency_auto:
            return _("Auto refresh off.")
        days = self.currency_interval
        if self.currency_background and background_refresh_available():
            return ngettext("Auto refresh on, every day, also when Xcalculator is closed.",
                            "Auto refresh on, every {days} days, also when Xcalculator is closed.",
                            days).format(days=days) + "\n" + _("Change how often in Edit → Preferences.")
        return ngettext("Auto refresh on, every day while Xcalculator is open.",
                        "Auto refresh on, every {days} days while Xcalculator is open.",
                        days).format(days=days) + "\n" + _("Change how often in Edit → Preferences.")

    def show_currency_message(self, text):
        """Show a message under the boxes for a few seconds, then the rates again."""
        self.currency_message = text
        if self.currency_message_timer:
            GLib.source_remove(self.currency_message_timer)
        self.currency_message_timer = GLib.timeout_add_seconds(MESSAGE_SECONDS, self.end_currency_message)
        self.conv_refresh()

    def end_currency_message(self):
        self.currency_message, self.currency_message_timer = "", 0
        self.conv_refresh()
        return False

    def currency_convert(self, value, from_code, to_code):
        """The other box's amount and the line under the boxes, for conv_refresh."""
        data = Rates.get()
        top, bottom = self.conv_units[CURRENCY]     # the rate line always reads top to bottom
        if data is None or from_code not in data["rates"] or to_code not in data["rates"]:
            return "", self.two_lines(self.currency_status(None, top, bottom))
        amount = "" if value is None else format_money(convert_currency(value, data["rates"], from_code, to_code), to_code)
        return amount, self.two_lines(self.currency_status(data, top, bottom))

    @staticmethod
    def two_lines(text):
        """Every message under the boxes takes two lines, so the boxes never jump up and down."""
        return text if "\n" in text else text + "\n"

    def currency_status(self, data, from_code, to_code):
        if self.currency_message:
            return self.currency_message
        if Rates.downloading:
            return _("Downloading exchange rates from the European Central Bank…")
        if data is None:
            if Rates.failed:
                return (_("Couldn't reach the European Central Bank.") + "\n"
                        + _("Check the internet connection, then click Download Rates again."))
            return (_("Exchange rates come from the European Central Bank, once a day.") + "\n"
                    + _("Click Download Rates to get today's rates."))
        rates = data["rates"]
        line = "{one} {a} = {rate} {b}    {one} {b} = {back} {a}".format(
            one=1, a=from_code, b=to_code,
            rate=format_rate(convert_currency(Fraction(1), rates, from_code, to_code)),
            back=format_rate(convert_currency(Fraction(1), rates, to_code, from_code)))
        if Rates.failed:
            return line + "\n" + _("Couldn't download new rates. Using the rates from {date}.").format(
                date=rates_date_text(data))
        return line + "\n" + _("European Central Bank rates, {date}").format(date=rates_date_text(data))

    def start_rates_download(self):
        """Download new rates without freezing the window; every open window then updates."""
        if Rates.downloading:
            return
        Rates.downloading = True
        windows = [self] + self.other_calculators()
        for window in windows:
            window.currency_update_screen()

        def work():
            try:
                result = download_rates()
            except (OSError, ValueError) as error:
                print(f"Couldn't download the exchange rates: {error}")
                result = None
            GLib.idle_add(done, result)

        def done(result):
            Rates.downloading = False
            Rates.failed = result is None
            if result is not None:
                Rates.data, Rates.loaded = result, True
            for window in [self] + self.other_calculators():
                window.currency_update_screen(new_rates=result is not None)
            return False
        threading.Thread(target=work, daemon=True).start()

    def currency_update_screen(self, new_rates=False):
        self.sync_preferences()             # its Auto Refresh switch waits for the first rates
        if self.current_mode != "Currency Converter":
            return
        if new_rates:
            self.conv_set_category(CURRENCY)    # the menus may have gained currencies
        self.currency_refresh_buttons()
        self.conv_refresh()

