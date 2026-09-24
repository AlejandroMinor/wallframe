import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import render  # noqa: E402
from .framing import BLUR_RANGE, FILLS, MAX_ZOOM  # noqa: E402

APP_ID = "io.github.AlejandroMinor.wallframe"
MARGIN = 60  # canvas space around the frame, to see what is left out
ZOOM_STEP = 1.1
FLASH_MS = 3000  # how long status bar messages stay
KEY_ACTIONS = {"h": "mirror", "v": "flip", "r": "rotate", "0": "reset", "KP_0": "reset"}
DISCARD_KEY = "d"
ZOOM_KEYS = {"plus": ZOOM_STEP, "equal": ZOOM_STEP, "KP_Add": ZOOM_STEP,
             "minus": 1 / ZOOM_STEP, "KP_Subtract": 1 / ZOOM_STEP}
ARROW_KEYS = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
HELP_KEYS = ("question", "F1")
# What the help panel lists: (section, [(keys, action)]).
SHORTCUTS = [
    ("Move and zoom", [
        ("Drag  ·  Arrows", "Move (Shift: bigger steps)"),
        ("Scroll  ·  +  −", "Zoom"),
        ("C", "Center, keeping the zoom"),
    ]),
    ("Image", [
        ("H", "Mirror"),
        ("V", "Flip upside down"),
        ("R", "Rotate 90°"),
        ("0", "Reset to the original image, centered"),
        ("D", "Discard changes since the last Apply"),
    ]),
    ("Background (zoomed out, Blur fill)", [
        ("B", "Move the background instead of the image"),
    ]),
    ("Window", [
        ("Tab", "Next monitor"),
        ("G", "Rule-of-thirds grid"),
        ("Enter", "Apply to the marked monitors"),
        ("?  ·  F1", "Show these shortcuts"),
        ("Esc", "Close a panel, or the window"),
    ]),
]
NUDGE = 5            # monitor pixels per arrow key press
NUDGE_SHIFT = 50     # with Shift held
# GTK's own theme leaves these classes uncolored on labels; the named colors
# still come from the user's theme.
STYLE = """
label.accent { color: @accent_color; }
label.success { color: @success_color; }
label.warning { color: @warning_color; }
label.error { color: @error_color; }
"""


def run(monitors, daemon, start, focused):
    """Opens the editor on monitors[start] and returns the exit status."""
    app = Gtk.Application(application_id=APP_ID)
    app.connect("startup", lambda _app: add_style())
    app.connect("activate", lambda _app: Window(app, monitors, daemon, start, focused).present())
    return app.run([])


def add_style():
    provider = Gtk.CssProvider()
    provider.load_from_string(STYLE)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


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


def pinned_popover(title, content):
    """A popover that stays open while you work, with a title and a close button.

    It does not close on clicks elsewhere, so you can keep dragging on the
    canvas with it open; its close button, its menu button or Esc close it.
    """
    popover = Gtk.Popover(autohide=False)
    heading = Gtk.Label(xalign=0, hexpand=True)
    heading.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    close = icon_button("window-close-symbolic", "Close (Esc)", popover.popdown)
    close.add_css_class("flat")
    header = Gtk.Box(spacing=6)
    header.append(heading)
    header.append(close)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=6,
                  margin_bottom=12, margin_start=12, margin_end=6)
    box.append(header)
    box.append(content)
    popover.set_child(box)
    return popover


def describe(monitor):
    """Model, size and orientation, as shown in tooltips and the status bar."""
    orientation = "vertical" if monitor.portrait else "horizontal"
    return [monitor.model, f"{monitor.width}x{monitor.height}", orientation]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, monitors, daemon, start, focused):
        super().__init__(application=app, title="wallframe")
        self.monitors, self.daemon, self.index = monitors, daemon, start
        self.previews = {}    # monitor name -> (image, mirror and rotation, cairo surface)
        self.backgrounds = {}  # monitor name -> (image, transform and fill, cairo surface)
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
        self.discard_button = icon_button("document-revert-symbolic",
                                          "Discard changes since the last Apply (D)", self.discard)
        tools.append(self.discard_button)
        self.grid_button = icon_button("view-grid-symbolic", "Rule-of-thirds grid (G)",
                                       self.on_grid_button, toggle=True)
        self.grid_button.set_active(self.show_grid)
        tools.append(self.grid_button)
        self.apply_button = Gtk.Button(label="Apply", focusable=False, margin_start=6,
                                       tooltip_text="Apply the marked monitors (Enter)")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda _b: self.apply())
        tools.append(self.apply_button)

        top = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        top.append(row)
        top.append(tools)
        return top

    def build_bottom_bar(self):
        """What is being edited on the left, fill and zoom on the right."""
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)

        # Only shown below 100%, when the image leaves gaps to fill.
        self.fill_button = Gtk.MenuButton(popover=self.build_fill_popover(), focusable=False,
                                          tooltip_text="What fills the space around the image")

        self.zoom_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                   100, MAX_ZOOM * 100, 5)
        self.zoom_scale.set_draw_value(False)
        self.zoom_scale.set_size_request(180, -1)
        self.zoom_scale.set_focusable(False)
        self.zoom_scale.connect("value-changed", self.on_zoom_scale)
        self.zoom_label = Gtk.Label(width_chars=5, xalign=1)
        self.help_button = Gtk.MenuButton(icon_name="input-keyboard-symbolic", focusable=False,
                                          tooltip_text="Keyboard shortcuts (?)",
                                          popover=self.build_help_popover())
        self.help_button.add_css_class("flat")
        bottom = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=6, margin_end=12)
        bottom.append(self.help_button)
        bottom.append(self.label)
        bottom.append(self.fill_button)
        zoom_out = icon_button("zoom-out-symbolic", "Zoom out (-)",
                               lambda: self.zoom_centered(1 / ZOOM_STEP))
        zoom_in = icon_button("zoom-in-symbolic", "Zoom in (+)",
                              lambda: self.zoom_centered(ZOOM_STEP))
        for button in (zoom_out, zoom_in):
            button.add_css_class("flat")
        bottom.append(zoom_out)
        bottom.append(self.zoom_scale)
        bottom.append(zoom_in)
        bottom.append(self.zoom_label)
        return bottom

    def build_help_popover(self):
        """Every mouse action and key, grouped, from SHORTCUTS."""
        grid = Gtk.Grid(row_spacing=6, column_spacing=18)
        row = 0
        for section, entries in SHORTCUTS:
            title = Gtk.Label(xalign=0, margin_top=0 if row == 0 else 8)
            title.set_markup(f"<b>{GLib.markup_escape_text(section)}</b>")
            grid.attach(title, 0, row, 2, 1)
            row += 1
            for keys, action in entries:
                key_label = Gtk.Label(label=keys, xalign=1)
                key_label.add_css_class("monospace")
                grid.attach(key_label, 0, row, 1, 1)
                grid.attach(Gtk.Label(label=action, xalign=0), 1, row, 1, 1)
                row += 1
        return pinned_popover("Keyboard shortcuts", grid)

    def build_fill_popover(self):
        """Fill kind, blur strength, background moving and color, in one panel."""
        self.fill_choice = Gtk.DropDown.new_from_strings(["Blur", "Color"])
        self.fill_choice.set_tooltip_text("What fills the space around the image")
        self.fill_choice.set_focusable(False)
        self.fill_choice.connect("notify::selected", self.on_fill_choice)
        # Not modal: compositors like Hyprland dim the parent of a modal dialog,
        # and the eyedropper would then pick the dimmed colors.
        self.fill_color = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(with_alpha=False, modal=False), focusable=False)
        self.fill_color.connect("notify::rgba", self.on_fill_color)
        self.blur_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, *BLUR_RANGE, 8)
        self.blur_scale.set_draw_value(False)
        self.blur_scale.set_size_request(180, -1)
        self.blur_scale.set_focusable(False)
        self.blur_scale.set_tooltip_text("Blur strength")
        self.blur_scale.connect("value-changed", self.on_blur_scale)
        # Checked, dragging and zooming move the blurred background instead of the image.
        self.move_backdrop = Gtk.CheckButton(label="Move background (B)", focusable=False)
        self.move_backdrop.connect("toggled", self.on_move_backdrop)

        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        self.blur_label = Gtk.Label(label="Strength", xalign=0)
        self.color_label = Gtk.Label(label="Color", xalign=0)
        for row, (label, control) in enumerate((
                (Gtk.Label(label="Fill", xalign=0), self.fill_choice),
                (self.blur_label, self.blur_scale),
                (self.color_label, self.fill_color))):
            grid.attach(label, 0, row, 1, 1)
            grid.attach(control, 1, row, 1, 1)
        grid.attach(self.move_backdrop, 0, 3, 2, 1)
        return pinned_popover("Around the image", grid)

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

    @property
    def backdrop_visible(self):
        """True when the blurred background shows, so there is something to move."""
        framing = self.monitor.framing
        return framing.fill == "blur" and not framing.covers

    @property
    def moving(self):
        """What dragging and zooming act on: the image, or the blurred background behind it."""
        if self.move_backdrop.get_active() and self.backdrop_visible:
            return self.monitor.framing.backdrop
        return self.monitor.framing

    def preview(self, monitor):
        """The monitor's preview surface, rebuilt when the image, mirror or rotation change."""
        framing = monitor.framing
        key = (monitor.image, framing.flip_h, framing.flip_v, framing.rotation)
        cached = self.previews.get(monitor.name)
        if not cached or cached[0] != key:
            cached = self.previews[monitor.name] = (key, to_surface(monitor.preview()))
        return cached[1]

    def background(self, monitor):
        """The fill behind a smaller image, at half the monitor size; rebuilt when it changes."""
        framing = monitor.framing
        key = (monitor.image, framing.flip_h, framing.flip_v, framing.rotation,
               framing.fill, framing.fill_color, framing.blur, framing.backdrop.key())
        cached = self.backgrounds.get(monitor.name)
        if not cached or cached[0] != key:
            size = (max(1, monitor.width // 2), max(1, monitor.height // 2))
            surface = to_surface(render.background(monitor.preview(), framing, size))
            cached = self.backgrounds[monitor.name] = (key, surface)
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

        if not framing.covers:
            # The fill, inside the frame only, behind the image.
            background = self.background(monitor)
            cr.save()
            cr.translate(fx, fy)
            fill_scale = scale * monitor.width / background.get_width()
            cr.scale(fill_scale, fill_scale)
            cr.set_source_surface(background, 0, 0)
            cr.paint()
            cr.restore()

        # The whole image, at its current position relative to the frame.
        preview = self.preview(monitor)
        cr.save()
        cr.translate(fx + framing.x * scale, fy + framing.y * scale)
        image_scale = framing.zoom * scale * framing.image_w / preview.get_width()
        cr.scale(image_scale, image_scale)
        cr.set_source_surface(preview, 0, 0)
        # While the background moves, the image fades so the background shows through,
        # and a dashed outline keeps its place visible.
        moving_backdrop = self.moving is not framing
        cr.paint_with_alpha(0.35 if moving_backdrop else 1)
        cr.restore()
        if moving_backdrop:
            cr.save()
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(1.5)
            cr.set_dash([6, 4])
            cr.rectangle(fx + framing.x * scale, fy + framing.y * scale,
                         framing.image_w * framing.zoom * scale,
                         framing.image_h * framing.zoom * scale)
            cr.stroke()
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
        self.move_backdrop.set_active(False)  # each monitor starts by moving its image
        self.refresh()

    def on_pick(self, button, index):
        if button.get_active() and index != self.index:
            self.select(index)

    def refresh(self):
        """Syncs the bars with the current monitor and redraws."""
        for monitor, button in zip(self.monitors, self.buttons):
            button.name_label.set_label(f"● {monitor.name}" if monitor.touched else monitor.name)
        self.apply_button.set_sensitive(any(m.touched for m in self.monitors))
        self.discard_button.set_sensitive(self.monitor.touched)
        monitor = self.monitor
        framing = monitor.framing
        moving = self.moving
        pct = round(moving.relative_zoom * 100)
        self.syncing = True
        # The lowest zoom depends on the monitor, the rotation and what is being moved.
        self.zoom_scale.set_range(moving.lowest_zoom / moving.min_zoom * 100, MAX_ZOOM * 100)
        self.zoom_scale.set_value(pct)
        self.fill_choice.set_selected(FILLS.index(framing.fill))
        rgba = Gdk.RGBA()
        rgba.parse(framing.fill_color)
        self.fill_color.set_rgba(rgba)
        self.blur_scale.set_value(framing.blur)
        self.syncing = False
        blur = framing.fill == "blur"
        if self.move_backdrop.get_active() and not self.backdrop_visible:
            self.move_backdrop.set_active(False)  # nothing left to move: back to the image
        self.fill_button.set_visible(not framing.covers)
        self.fill_button.set_label(f"Fill: {'Blur' if blur else 'Color'}")
        for widget in (self.blur_label, self.blur_scale, self.move_backdrop):
            widget.set_visible(blur)
        for widget in (self.color_label, self.fill_color):
            widget.set_visible(not blur)
        self.zoom_label.set_label(f"{pct}%")
        details = describe(monitor) + [
            "moving the background" if self.moving is not framing else "",
            "mirrored" if framing.flip_h else "",
            "flipped" if framing.flip_v else "",
            f"rotated {framing.rotation}°" if framing.rotation else ""]
        if not self.flash_timer:  # a message on screen keeps the bar until it ends
            self.label.set_markup(f"<b>{GLib.markup_escape_text(monitor.name)}</b>   "
                                  + GLib.markup_escape_text("  ·  ".join(filter(None, details))))
        self.area.queue_draw()

    def edit(self, action):
        self.monitor.edit(action)
        self.refresh()

    def discard(self):
        """Back to what the monitor shows now, dropping this session's changes on it."""
        if self.monitor.touched:
            self.monitor.discard_edit()
            self.move_backdrop.set_active(False)
            self.refresh()
            self.flash(f"Changes to {self.monitor.name} discarded", "accent")

    def on_grid_button(self):
        self.show_grid = self.grid_button.get_active()
        self.area.queue_draw()

    def on_zoom_scale(self, scale):
        if not self.syncing:
            self.zoom_centered(scale.get_value() / 100 / self.moving.relative_zoom)

    def zoom_centered(self, factor):
        """Zooms around the frame's center, for the slider and buttons that have no pointer."""
        monitor = self.monitor
        self.moving.zoom_at(factor, monitor.width / 2, monitor.height / 2)
        self.refresh()

    def on_fill_choice(self, dropdown, _prop):
        if not self.syncing:
            self.monitor.framing.fill = FILLS[dropdown.get_selected()]
            self.refresh()

    def on_fill_color(self, button, _prop):
        if not self.syncing:
            rgba = button.get_rgba()
            self.monitor.framing.fill_color = "#{:02x}{:02x}{:02x}".format(
                *(round(channel * 255) for channel in (rgba.red, rgba.green, rgba.blue)))
            self.refresh()

    def toggle_backdrop(self):
        """The B key: switches between moving the image and its background, when there is one."""
        if self.move_backdrop.get_active() or self.backdrop_visible:
            self.move_backdrop.set_active(not self.move_backdrop.get_active())
        elif self.monitor.framing.covers:
            self.flash("Zoom out below 100% to move the background", "warning")
        else:
            self.flash("Only the Blur fill has a background to move", "warning")

    def on_move_backdrop(self, button):
        self.refresh()
        if button.get_active():
            self.flash("Moving the background · press B to move the image", "accent")
        else:
            self.flash("Moving the image", "accent")

    def on_blur_scale(self, scale):
        if not self.syncing:
            self.monitor.framing.blur = round(scale.get_value())
            self.refresh()

    def on_drag_begin(self, _gesture, _x, _y):
        self.drag_origin = (self.moving.x, self.moving.y)
        if self.moving is not self.monitor.framing and not self.moving.can_move:
            self.flash("Zoom in the background to move it", "warning")

    def on_drag_update(self, _gesture, dx, dy):
        scale, _, _ = self.frame()
        self.moving.move_to(self.drag_origin[0] + dx / scale, self.drag_origin[1] + dy / scale)
        self.refresh()

    def on_scroll(self, _controller, _dx, dy):
        scale, fx, fy = self.frame()
        px, py = (self.pointer[0] - fx) / scale, (self.pointer[1] - fy) / scale
        self.moving.zoom_at(ZOOM_STEP ** -dy, px, py)
        self.refresh()
        return True

    def on_key(self, _controller, keyval, _code, state):
        key = Gdk.keyval_name(Gdk.keyval_to_lower(keyval))
        open_panel = next((b for b in (self.fill_button, self.help_button) if b.get_active()),
                          None)
        if key == "Escape" and open_panel:
            open_panel.popdown()  # Esc closes the panel, not the whole window
        elif key in HELP_KEYS:
            self.help_button.set_active(not self.help_button.get_active())
        elif key == "Escape":
            self.close()
        elif key == "Tab" and len(self.monitors) > 1:
            self.select((self.index + 1) % len(self.monitors))
        elif key in ("Return", "KP_Enter"):
            self.apply()
        elif key in KEY_ACTIONS:
            self.edit(KEY_ACTIONS[key])
        elif key == DISCARD_KEY:
            self.discard()
        elif key == "g":
            self.grid_button.set_active(not self.grid_button.get_active())
        elif key == "b":
            self.toggle_backdrop()
        elif key == "c":
            self.moving.center()
            self.refresh()
        elif key in ZOOM_KEYS:
            self.zoom_centered(ZOOM_KEYS[key])
        elif key in ARROW_KEYS:
            step = NUDGE_SHIFT if state & Gdk.ModifierType.SHIFT_MASK else NUDGE
            dx, dy = ARROW_KEYS[key]
            self.moving.move_to(self.moving.x + dx * step, self.moving.y + dy * step)
            self.refresh()
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
            self.flash("Nothing to apply", "warning")
            return
        failed = []
        for monitor in touched:
            try:
                monitor.apply(self.daemon)
            except OSError as error:  # the others still apply
                reason = "image not found" if isinstance(error, FileNotFoundError) else (
                    error.strerror or str(error))
                failed.append(f"{monitor.name}: {reason}")
        self.move_backdrop.set_active(False)  # back to moving the image
        self.refresh()
        if failed:
            self.flash(f"Could not apply {'; '.join(failed)}", "error")
        else:
            self.flash("Applied", "success")

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
            self.flash(f"New wallpaper loaded on {', '.join(reloaded)}", "success")
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

    def flash(self, text, style):
        """Shows a short message in the status bar, then restores it.

        `style` is a GTK style class ("accent", "success", "warning" or "error"),
        so the color comes from the user's theme.
        """
        self.label.set_css_classes([style])
        self.label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        if self.flash_timer:
            GLib.source_remove(self.flash_timer)  # a newer message gets its full time
        self.flash_timer = GLib.timeout_add(FLASH_MS, self.restore_status)

    def restore_status(self):
        self.flash_timer = None
        self.label.set_css_classes([])
        self.refresh()
        return False  # run once; True would repeat the timer
