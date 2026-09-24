import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import render  # noqa: E402
from .framing import MAX_ZOOM  # noqa: E402

APP_ID = "io.github.AlejandroMinor.wallframe"
MARGIN = 60  # canvas space around the frame, to see what is left out
ZOOM_STEP = 1.1
KEY_ACTIONS = {"h": "mirror", "v": "flip", "r": "rotate", "0": "reset", "KP_0": "reset"}


def run(monitors, daemon, start, focused):
    """Opens the editor on monitors[start] and returns the exit status."""
    app = Gtk.Application(application_id=APP_ID)
    app.connect("activate", lambda _app: Window(app, monitors, daemon, start, focused).present())
    return app.run([])


def to_surface(img):
    """Wraps a PIL image as a cairo surface for drawing."""
    img = img.convert("RGBA")
    # cairo's ARGB32 is premultiplied BGRA in memory on little-endian machines.
    data = bytearray(img.tobytes("raw", "BGRa"))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32,
                                              img.width, img.height, img.width * 4)


def icon_button(icon, tooltip, callback, toggle=False):
    button = (Gtk.ToggleButton if toggle else Gtk.Button)(
        icon_name=icon, tooltip_text=tooltip, focusable=False)
    button.connect("toggled" if toggle else "clicked", lambda _b: callback())
    return button


def describe(monitor):
    """Model, size and orientation, as shown in tooltips and the status bar."""
    orientation = "vertical" if monitor.portrait else "horizontal"
    return [monitor.model, f"{monitor.width}x{monitor.height}", orientation]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, monitors, daemon, start, focused):
        super().__init__(application=app, title="wallframe")
        self.monitors, self.daemon, self.index = monitors, daemon, start
        self.previews = {}    # monitor name -> (image, mirror and rotation, cairo surface)
        self.show_grid = True
        self.syncing = False  # set while code moves the zoom slider
        self.asking = False   # set while wallpaper-change questions are on screen
        self.postponed = set()  # (monitor, image) questions closed with Esc
        self.flash_timer = None

        # Size against the monitor the window opens on; without knowing which,
        # the smallest one, so it fits wherever it lands.
        opens_on = next((m for m in monitors if m.name == focused),
                        min(monitors, key=lambda m: m.width * m.height))
        self.set_default_size(int(min(1200, opens_on.width * 0.8)),
                              int(min(850, opens_on.height * 0.7)))

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self.draw)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.build_top_bar())
        box.append(self.area)
        box.append(self.build_bottom_bar())
        self.set_child(box)
        self.connect_input()
        # Coming back to the window is when a wallpaper changed elsewhere shows up.
        self.connect("notify::is-active", self.on_active)
        self.select(start)

    def build_top_bar(self):
        """Monitor buttons on the left, tools and Apply on the right."""
        # A dot on a button marks the monitors Apply will write. The row scrolls
        # sideways rather than widening the window past a portrait screen.
        self.buttons = []
        picker = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        for i, monitor in enumerate(self.monitors):
            content = Gtk.Box(spacing=6)
            content.append(Gtk.Image(
                icon_name="phone-symbolic" if monitor.portrait else "video-display-symbolic"))
            button_name = Gtk.Label()
            content.append(button_name)
            button = Gtk.ToggleButton(focusable=False, child=content)
            button.name_label = button_name
            if self.buttons:
                button.set_group(self.buttons[0])
            button.connect("toggled", self.on_pick, i)
            button.set_tooltip_text(" · ".join(filter(None, describe(monitor))) + "  (Tab)")
            picker.append(button)
            self.buttons.append(button)
        row = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True,
                                 propagate_natural_height=True, child=picker)

        tools = Gtk.Box(spacing=6)
        for icon, tip, action in (
                ("object-flip-horizontal-symbolic", "Mirror (H)", "mirror"),
                ("object-flip-vertical-symbolic", "Flip upside down (V)", "flip"),
                ("object-rotate-right-symbolic", "Rotate 90° (R)", "rotate"),
                ("edit-undo-symbolic", "Reset to the original image, centered (0)", "reset")):
            tools.append(icon_button(icon, tip, lambda action=action: self.edit(action)))
        self.grid_button = icon_button("view-grid-symbolic", "Rule-of-thirds grid (G)",
                                       self.on_grid_button, toggle=True)
        self.grid_button.set_active(self.show_grid)
        tools.append(self.grid_button)
        apply_button = Gtk.Button(label="Apply", tooltip_text="Apply the marked monitors (Enter)",
                                  focusable=False, margin_start=6)
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", lambda _b: self.apply())
        tools.append(apply_button)

        top = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        top.append(row)
        top.append(tools)
        return top

    def build_bottom_bar(self):
        """What is being edited on the left, zoom on the right."""
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.zoom_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                   100, MAX_ZOOM * 100, 5)
        self.zoom_scale.set_draw_value(False)
        self.zoom_scale.set_size_request(180, -1)
        self.zoom_scale.set_focusable(False)
        self.zoom_scale.connect("value-changed", self.on_zoom_scale)
        self.zoom_label = Gtk.Label(width_chars=5, xalign=1)
        bottom = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        bottom.append(self.label)
        bottom.append(Gtk.Image(icon_name="zoom-in-symbolic", tooltip_text="Zoom (scroll)"))
        bottom.append(self.zoom_scale)
        bottom.append(self.zoom_label)
        return bottom

    def connect_input(self):
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        self.area.add_controller(drag)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.on_scroll)
        self.area.add_controller(scroll)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: setattr(self, "pointer", (x, y)))
        self.area.add_controller(motion)
        self.pointer = (0, 0)

        # Capture phase: otherwise Tab moves widget focus before reaching us.
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

    @property
    def monitor(self):
        return self.monitors[self.index]

    def preview(self, monitor):
        """The monitor's preview surface, rebuilt when the image, mirror or rotation change."""
        framing = monitor.framing
        key = (monitor.image, framing.flip_h, framing.flip_v, framing.rotation)
        cached = self.previews.get(monitor.name)
        if not cached or cached[0] != key:
            cached = self.previews[monitor.name] = (key, to_surface(monitor.preview()))
        return cached[1]

    def frame(self):
        """Returns (scale, fx, fy): canvas pixels per monitor pixel, frame origin."""
        monitor = self.monitor
        aw, ah = self.area.get_width(), self.area.get_height()
        scale = min((aw - 2 * MARGIN) / monitor.width, (ah - 2 * MARGIN) / monitor.height)
        return scale, (aw - monitor.width * scale) / 2, (ah - monitor.height * scale) / 2

    def draw(self, _area, cr, aw, ah):
        monitor = self.monitor
        framing = monitor.framing
        scale, fx, fy = self.frame()
        cr.set_source_rgb(0.08, 0.08, 0.08)
        cr.paint()

        # The whole image, at its current position relative to the frame.
        preview = self.preview(monitor)
        cr.save()
        cr.translate(fx + framing.x * scale, fy + framing.y * scale)
        image_scale = framing.zoom * scale * framing.image_w / preview.get_width()
        cr.scale(image_scale, image_scale)
        cr.set_source_surface(preview, 0, 0)
        cr.paint()
        cr.restore()

        # Dim everything outside the frame: that part will not be shown.
        fw, fh = monitor.width * scale, monitor.height * scale
        cr.set_source_rgba(0, 0, 0, 0.65)
        cr.rectangle(0, 0, aw, ah)
        cr.rectangle(fx, fy, fw, fh)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)  # fill the ring around the frame only
        cr.fill()

        if self.show_grid:
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.set_line_width(1)
            for k in (1, 2):
                cr.move_to(fx + fw * k / 3, fy)
                cr.line_to(fx + fw * k / 3, fy + fh)
                cr.move_to(fx, fy + fh * k / 3)
                cr.line_to(fx + fw, fy + fh * k / 3)
            cr.stroke()

        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(2)
        cr.rectangle(fx, fy, fw, fh)
        cr.stroke()

    def select(self, index):
        self.index = index
        self.buttons[index].set_active(True)
        self.refresh()

    def on_pick(self, button, index):
        if button.get_active() and index != self.index:
            self.select(index)

    def refresh(self):
        """Syncs the bars with the current monitor and redraws."""
        for monitor, button in zip(self.monitors, self.buttons):
            button.name_label.set_label(f"● {monitor.name}" if monitor.touched else monitor.name)
        monitor = self.monitor
        framing = monitor.framing
        pct = round(framing.relative_zoom * 100)
        self.syncing = True
        self.zoom_scale.set_value(pct)
        self.syncing = False
        self.zoom_label.set_label(f"{pct}%")
        details = describe(monitor) + [
            "mirrored" if framing.flip_h else "",
            "flipped" if framing.flip_v else "",
            f"rotated {framing.rotation}°" if framing.rotation else ""]
        self.label.set_markup(f"<b>{GLib.markup_escape_text(monitor.name)}</b>   "
                              + GLib.markup_escape_text("  ·  ".join(filter(None, details))))
        self.area.queue_draw()

    def edit(self, action):
        self.monitor.edit(action)
        self.refresh()

    def on_grid_button(self):
        self.show_grid = self.grid_button.get_active()
        self.area.queue_draw()

    def on_zoom_scale(self, scale):
        if self.syncing:
            return
        monitor = self.monitor
        # Zoom around the frame's center, as there is no pointer to anchor to.
        monitor.framing.zoom_at(scale.get_value() / 100 / monitor.framing.relative_zoom,
                          monitor.width / 2, monitor.height / 2)
        self.refresh()

    def on_drag_begin(self, _gesture, _x, _y):
        self.drag_origin = (self.monitor.framing.x, self.monitor.framing.y)

    def on_drag_update(self, _gesture, dx, dy):
        scale, _, _ = self.frame()
        self.monitor.framing.move_to(self.drag_origin[0] + dx / scale,
                                     self.drag_origin[1] + dy / scale)
        self.refresh()

    def on_scroll(self, _controller, _dx, dy):
        scale, fx, fy = self.frame()
        px, py = (self.pointer[0] - fx) / scale, (self.pointer[1] - fy) / scale
        self.monitor.framing.zoom_at(ZOOM_STEP ** -dy, px, py)
        self.refresh()
        return True

    def on_key(self, _controller, keyval, _code, _state):
        key = Gdk.keyval_name(Gdk.keyval_to_lower(keyval))
        if key == "Escape":
            self.close()
        elif key == "Tab" and len(self.monitors) > 1:
            self.select((self.index + 1) % len(self.monitors))
        elif key in ("Return", "KP_Enter"):
            self.apply()
        elif key in KEY_ACTIONS:
            self.edit(KEY_ACTIONS[key])
        elif key == "g":
            self.grid_button.set_active(not self.grid_button.get_active())
        else:
            return False
        return True

    def on_active(self, _window, _prop):
        if self.is_active() and not self.asking:
            self.sync_with_daemon(ask_postponed=False)

    def apply(self):
        """Checks for wallpapers changed elsewhere first, so none is overwritten unasked."""
        if not self.asking:
            self.sync_with_daemon(then=self.apply_touched)

    def apply_touched(self):
        touched = [m for m in self.monitors if m.touched]
        if not touched:
            self.flash("Nothing to apply")
            return
        for monitor in touched:
            monitor.apply(self.daemon)
        self.refresh()
        self.flash("Applied")

    def sync_with_daemon(self, then=None, ask_postponed=True):
        """Reloads monitors whose wallpaper changed elsewhere; asks about edited ones.

        `then` runs once every question is answered, and not at all if one is dismissed.
        """
        current = {output.name: output for output in self.daemon.outputs()}
        conflicts, reloaded = [], []
        for monitor in self.monitors:
            output = current.get(monitor.name)
            if not output or not monitor.changed(output.image):
                continue
            if monitor.touched or not render.is_still_image(output.image):
                if ask_postponed or (monitor.name, output.image) not in self.postponed:
                    conflicts.append((monitor, output))
            else:
                monitor.load(output)
                reloaded.append(monitor.name)
        self.refresh()
        if reloaded:
            self.flash(f"New wallpaper loaded on {', '.join(reloaded)}")
        self.ask_next(conflicts, then)

    def ask_next(self, conflicts, then):
        """Asks about each conflict in turn, then runs `then`."""
        if not conflicts:
            self.asking = False
            if then:
                then()
            return
        self.asking = True
        monitor, output = conflicts[0]
        loadable = render.is_still_image(output.image)
        dialog = Gtk.AlertDialog(
            message=f"{monitor.name} has a new wallpaper",
            detail="Your changes on this monitor are for the previous image."
                   if loadable else
                   "It is animated or a video, so wallframe cannot edit it.",
            buttons=["Load new wallpaper" if loadable else "Keep the new wallpaper",
                     "Keep editing (Apply will replace it)"],
            default_button=0)

        def answered(dialog, result):
            try:
                choice = dialog.choose_finish(result)
            except GLib.Error:  # closed with Esc: ask again on Apply, apply nothing now
                self.postponed.add((monitor.name, output.image))
                self.asking = False
                return
            if choice == 1:
                monitor.ignored = output.image
            elif loadable:
                monitor.load(output)
            else:
                monitor.ignored = output.image
                monitor.discard_edit()
            self.refresh()
            self.ask_next(conflicts[1:], then)

        dialog.choose(self, None, answered)

    def flash(self, text):
        """Shows a short message in the status bar, then restores it."""
        self.label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        if self.flash_timer:
            GLib.source_remove(self.flash_timer)  # a newer message gets its full time
        self.flash_timer = GLib.timeout_add(1500, self.restore_status)

    def restore_status(self):
        self.flash_timer = None
        self.refresh()
        return False  # run once; True would repeat every 1500 ms
