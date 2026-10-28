# Xcalculator: a calculator for Linux Mint and the Cinnamon desktop.
# Copyright (C) 2026 Wesley Hayslip
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Type 5318008 and press = : the calculator turns upside down for a few seconds."""
import gi
import math
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from printing import cairo


FLIP_TRIGGER = "5318008"


FLIP_TURN_SECONDS = 0.6   # time to spin over (and back)


FLIP_HOLD_SECONDS = 5.0   # time spent upside down


class UpsideDown:
    """The 5318008 easter egg (needs cairo, package python3-gi-cairo)."""

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
