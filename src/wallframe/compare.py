import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import render  # noqa: E402
from .window import icon_button, to_surface  # noqa: E402

VIEW_MAX = (900, 560)  # the part of the monitor shown, in real monitor pixels
HANDLE = 14            # how close to the line a drag grabs it instead of the image


def clamp(value, low, high):
    return min(max(value, low), high)


class CompareWindow(Gtk.Window):
    """The original and the upscaled copy side by side, at real monitor pixels.

    Both are rendered exactly as Apply would render them, so what differs here
    is what would differ on the monitor. A line splits them: drag it to compare,
    drag anywhere else to look at another part of the monitor.
    """

    def __init__(self, parent, monitor):
        # Not modal: Hyprland and others dim the parent of a modal window.
        super().__init__(transient_for=parent, modal=False,
                         title=f"Compare 1:1 · {monitor.name}")
        self.monitor = monitor
        self.view_w, self.view_h = (min(monitor.width, VIEW_MAX[0]),
                                    min(monitor.height, VIEW_MAX[1]))
        self.split = self.view_w / 2
        # Top left corner of the view, in monitor pixels; starts at the center.
        self.offset = ((monitor.width - self.view_w) / 2, (monitor.height - self.view_h) / 2)
        self.surfaces = None  # (original, upscaled), once rendered

        self.area = Gtk.DrawingArea(content_width=self.view_w, content_height=self.view_h)
        self.area.set_draw_func(self.draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        self.area.add_controller(drag)

        # Compositors like Hyprland give it no title bar, so it brings its own, with
        # the close button where every window has it; Esc closes it too.
        title = Gtk.Label(xalign=0, hexpand=True)
        title.set_markup(f"<b>Compare 1:1 · {GLib.markup_escape_text(monitor.name)}</b>")
        close = icon_button("window-close-symbolic", "Close (Esc)", self.close)
        close.add_css_class("flat")
        top = Gtk.Box(spacing=6, margin_top=4, margin_bottom=4, margin_start=12, margin_end=6)
        top.append(title)
        top.append(close)
        self.hint = Gtk.Label(label="Rendering both at full size…", margin_top=6,
                              margin_bottom=6)
        self.hint.add_css_class("dim-label")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(top)
        box.append(self.area)
        box.append(self.hint)
        self.set_child(box)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.set_resizable(False)
        threading.Thread(target=self.render_both, daemon=True).start()

    def render_both(self):
        """Off the main thread: a full-size render takes a moment on a big upscaled copy."""
        monitor = self.monitor
        images = [render.compose(path, monitor.framing_for(path))
                  for path in (monitor.original, monitor.upscaled)]
        GLib.idle_add(self.rendered, images)

    def rendered(self, images):
        self.surfaces = [to_surface(image) for image in images]
        self.hint.set_label("Drag the line to compare · drag the image to look around")
        self.area.queue_draw()
        return False  # run once

    def draw(self, _area, cr, width, height):
        cr.set_source_rgb(0.08, 0.08, 0.08)
        cr.paint()
        if not self.surfaces:
            return
        left, top = self.offset
        for surface, x, w in ((self.surfaces[0], 0, self.split),
                              (self.surfaces[1], self.split, width - self.split)):
            cr.save()
            cr.rectangle(x, 0, w, height)
            cr.clip()
            cr.set_source_surface(surface, -left, -top)
            cr.paint()
            cr.restore()

        # The dividing line, with a round handle in the middle.
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(2)
        cr.move_to(self.split, 0)
        cr.line_to(self.split, height)
        cr.stroke()
        cr.arc(self.split, height / 2, 9, 0, 6.2832)
        cr.fill()

        self.draw_tag(cr, "Original", 10, align_right=False)
        self.draw_tag(cr, "Upscaled", width - 10, align_right=True)

    @staticmethod
    def draw_tag(cr, text, x, align_right):
        """A small label on a dark box, readable over any image."""
        cr.set_font_size(13)
        extents = cr.text_extents(text)
        left = x - extents.width - 12 if align_right else x
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.rectangle(left, 10, extents.width + 12, 22)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.move_to(left + 6, 26)
        cr.show_text(text)

    def on_key(self, _controller, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def on_drag_begin(self, _gesture, x, _y):
        self.moving_split = abs(x - self.split) <= HANDLE
        self.drag_start = self.split if self.moving_split else self.offset

    def on_drag_update(self, _gesture, dx, dy):
        monitor = self.monitor
        if self.moving_split:
            self.split = clamp(self.drag_start + dx, 0, self.view_w)
        else:
            left, top = self.drag_start  # dragging the image right shows what is to its left
            self.offset = (clamp(left - dx, 0, monitor.width - self.view_w),
                           clamp(top - dy, 0, monitor.height - self.view_h))
        self.area.queue_draw()
