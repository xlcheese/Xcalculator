# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Printing the history as a calculator tape (Print and Print Preview share this)."""
import gi
from datetime import datetime
gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo
from i18n import _

# The 5318008 easter egg and printing need cairo (package python3-gi-cairo).
# Without it the calculator works normally; those two are skipped or greyed out.
try:
    gi.require_foreign('cairo')
    import cairo
except ImportError:
    cairo = None


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
    # Translators: the date and time printed at the top of the tape, in Python's strftime format
    # (%b month, %d day, %Y year, %I hour, %M minute, %p AM/PM).
    return _("Xcalculator  ·  {date}").format(date=printed_at.strftime(_("%b %d, %Y  %I:%M %p")))


def _page_text(page, pages):
    return _("Page {page} of {pages}").format(page=page, pages=pages)


def paginate_tape(new_layout, entries, page_width, page_height, printed_at):
    """Split the history into pages: a list of lists of entry numbers."""
    column = min(TAPE_WIDTH, page_width)
    header = _tape_layout(new_layout, _tape_header_text(printed_at), column, size_scale=0.8).get_pixel_size()[1]
    footer = _tape_layout(new_layout, _page_text(1, 1), column, size_scale=0.8).get_pixel_size()[1]
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
    footer = _tape_layout(new_layout, _page_text(page_number + 1, len(pages)), column, size_scale=0.8,
                          align=Pango.Alignment.CENTER)
    show(footer, page_height - footer.get_pixel_size()[1], gray=0.35)


class PrintPreview(Gtk.Window):
    """File → Print Preview: each page drawn the way Print will draw it."""
    SCALE = 0.75                            # preview pixels per point

    def __init__(self, calculator, entries, page_setup):
        super().__init__(title=_("Print Preview - Xcalculator"), transient_for=calculator, destroy_with_parent=True)
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
        self.back.set_tooltip_text(_("Previous page"))
        self.back.connect("clicked", lambda b: self.go(-1))
        self.forward = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        self.forward.set_tooltip_text(_("Next page"))
        self.forward.connect("clicked", lambda b: self.go(1))
        self.page_label = Gtk.Label()
        print_button = Gtk.Button(label=_("Print…"))
        print_button.connect("clicked", self.on_print)
        close_button = Gtk.Button(label=_("Close"))
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
        self.page_label.set_text(_page_text(self.page + 1, len(self.pages)))
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


def points_layout_maker(cr):
    """new_layout() for drawing on an ordinary cairo surface where 1 unit = 1 point."""
    context = PangoCairo.create_context(cr)
    PangoCairo.context_set_resolution(context, 72)
    return lambda: Pango.Layout.new(context)


class TapePrinting:
    """File → Print and Print Preview."""

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
        operation.set_job_name(_("Xcalculator tape"))
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
            self.show_message(_("Printing failed"), error.message)
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
