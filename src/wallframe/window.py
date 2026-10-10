import os
import threading

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import calibration, render, upscalers  # noqa: E402
from .commands import Cancel, Cancelled  # noqa: E402
from .framing import BLUR_RANGE, FILLS, MAX_ZOOM  # noqa: E402
from .arrangements import Arrangements  # noqa: E402
from .layouts import Layouts  # noqa: E402
from .monitor import Snapshot  # noqa: E402

APP_ID = "io.github.AlejandroMinor.wallframe"
# wallframe's own icons, for what the icon theme has no symbol for.
ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
MARGIN = 60  # canvas space around the frame, to see what is left out
ZOOM_STEP = 1.1
FLASH_MS = 3000  # how long status bar messages stay
KEY_ACTIONS = {"h": "mirror", "v": "flip", "r": "rotate", "0": "reset", "KP_0": "reset"}
DISCARD_KEY = "d"
ZOOM_KEYS = {"plus": ZOOM_STEP, "equal": ZOOM_STEP, "KP_Add": ZOOM_STEP,
             "minus": 1 / ZOOM_STEP, "KP_Subtract": 1 / ZOOM_STEP}
ARROW_KEYS = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
# While arranging, comma and period turn the selected monitor toward you; Shift makes
# them semicolon and colon, for bigger steps.
YAW_KEYS = {"comma": -1, "period": 1, "semicolon": -5, "colon": 5}
HELP_KEYS = ("question", "F1")
UPSCALE_TOOLTIP = "Enlarge a low-resolution image with AI (Upscayl)"
# What the help panel lists: (section, [(keys, action)]). Each key is drawn as a
# key cap; the mouse gestures in MOUSE are plain text, so the two never look alike.
SHORTCUTS = [
    ("Move and zoom", [
        (("Drag", "← ↑ ↓ →"), "Move the image (Shift: bigger steps)"),
        (("Scroll", "+", "−"), "Zoom"),
        (("C",), "Center, keeping the zoom"),
    ]),
    ("Image", [
        (("H",), "Mirror"),
        (("V",), "Flip upside down"),
        (("R",), "Rotate 90°"),
        (("0",), "Reset to the original image, centered"),
        (("O",), "Open another image, or drop one on the canvas"),
        (("D",), "Discard changes since the last Apply"),
    ]),
    ("Background (zoomed out, Blur fill)", [
        (("B",), "Move the background instead of the image"),
    ]),
    ("Span", [
        (("M",), "Arrange the monitors as they stand on your desk"),
        (("Click",), "While arranging: select a monitor; the arrows then move it by 1 mm "
                     "(Shift: 10 mm), not the image"),
        ((",", "."), "While arranging: turn the selected monitor by 1° (Shift: 5°), toward you "
                     "or, with a negative angle, away"),
        (("0",), "While arranging: back to their real sizes and places"),
        (("H", "V", "R"), "Not while arranging: finish with M first"),
    ]),
    ("Window", [
        (("Tab",), "Next monitor, or the span across all of them"),
        (("G",), "Grid: rule of thirds (in the span, also of the whole picture); "
                 "centimeters of the desk while arranging"),
        (("Enter",), "Apply to the marked monitors"),
        (("?", "F1"), "Show these shortcuts"),
        (("Esc",), "Close a panel, or the window"),
    ]),
]
MOUSE = {"Drag", "Scroll", "Click"}
SNAP = 10            # canvas pixels within which a dragged monitor meets another's edge
SELECTED = (0.25, 0.6, 1.0)  # the monitor being arranged: its frame and name tag
NUDGE = 5            # monitor pixels per arrow key press
NUDGE_SHIFT = 50     # with Shift held
ARRANGE_MM = 1       # millimeters per arrow key press while arranging, with real sizes
ARRANGE_MM_SHIFT = 10
# GTK's own theme leaves these classes uncolored on labels; the named colors
# still come from the user's theme.
STYLE = """
label.accent { color: @accent_color; }
label.success { color: @success_color; }
label.warning { color: @warning_color; }
label.error { color: @error_color; }
button.active-layout { box-shadow: inset 0 0 0 2px @accent_color; }
label.keycap {
  font-family: monospace;
  font-size: 0.9em;
  padding: 1px 7px;
  border-radius: 5px;
  border: 1px solid alpha(currentColor, 0.25);
  border-bottom-width: 2px;
  background: alpha(currentColor, 0.08);
}
"""


def run(monitors, daemon, start, focused, upscaler=None, layouts=None, positions=None,
        span=None):
    """Opens the editor on monitors[start], or on the span when start is past them,
    and returns the exit status."""
    app = Gtk.Application(application_id=APP_ID)
    app.connect("startup", lambda _app: add_style())
    app.connect("activate", lambda _app: Window(app, monitors, daemon, start, focused,
                                                upscaler, layouts, positions, span).present())
    return app.run([])


def add_style():
    """The status bar colors and wallframe's own icons, once per display."""
    display = Gdk.Display.get_default()
    provider = Gtk.CssProvider()
    provider.load_from_string(STYLE)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Gtk.IconTheme.get_for_display(display).add_search_path(ICONS_DIR)
    # Found there too, so the windows have it even without the desktop file linked.
    Gtk.Window.set_default_icon_name(APP_ID)


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
    """Model, size and orientation, as shown in tooltips and the status bar.

    For the span, the number of monitors and the size of the whole desktop.
    """
    orientation = "vertical" if monitor.portrait else "horizontal"
    return [monitor.model, f"{monitor.width}x{monitor.height}", orientation]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, monitors, daemon, start, focused, upscaler=None, layouts=None,
                 positions=None, span=None):
        super().__init__(application=app, title="wallframe")
        self.monitors, self.daemon, self.index = monitors, daemon, start
        # One picture across every monitor (see span.py); None when the desktop
        # does not say where they are. It is edited like one more monitor, last.
        self.span = span
        self.views = monitors + ([span] if span else [])
        self.layouts = layouts or Layouts()
        self.positions = positions or {}  # monitor name -> place on the desktop, for previews
        self.upscaler = upscaler  # None when Upscayl is not installed
        self.upscaling = {}       # monitor name -> the Cancel of its running upscale
        self.ai_step, self.ai_pictures = 0, 0  # picture being upscaled, of how many
        self.previews = {}    # monitor name -> (image, mirror and rotation, cairo surface)
        self.backgrounds = {}  # monitor name -> (image, transform and fill, cairo surface)
        self.show_grid = True
        self.syncing = False  # set while code moves the zoom slider
        self.asking = False   # set while wallpaper-change questions are on screen
        self.postponed = set()  # (monitor, image) questions closed with Esc
        self.flash_timer = None
        self.applying = None  # what is being applied off the main thread, e.g. "Work"
        self.dragged = None   # the span's monitor being dragged into place, by name
        self.selected = None  # the span's monitor the arrow keys move while arranging, by name
        self.held = None      # the canvas's (scale, origin) while it is dragged

        # Size against the monitor the window opens on; without knowing which,
        # the smallest one, so it fits wherever it lands.
        opens_on = next((m for m in monitors if m.name == focused),
                        min(monitors, key=lambda m: m.width * m.height))
        self.set_default_size(int(min(1200, opens_on.width * 0.8)),
                              int(min(850, opens_on.height * 0.7)))

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self.draw)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.top_bar = self.build_top_bar()
        box.append(self.top_bar)
        box.append(self.area)
        box.append(self.build_bottom_bar())
        self.set_child(box)
        self.connect_input()
        # Coming back to the window is when a wallpaper changed elsewhere shows up.
        self.connect("notify::is-active", self.on_active)
        # Upscayl is a separate program and would outlive the window, still on the GPU.
        self.connect("close-request", lambda _w: self.cancel_upscales(self.upscaling))
        self.select(start)

    def build_top_bar(self):
        """Monitor buttons on the left, tools and Apply on the right."""
        # A dot on a button marks the monitors Apply will write. The row scrolls
        # sideways rather than widening the window past a portrait screen.
        self.buttons = []
        picker = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        for i, monitor in enumerate(self.views):
            content = Gtk.Box(spacing=6)
            icon = ("video-joined-displays-symbolic" if monitor is self.span
                    else "phone-symbolic" if monitor.portrait else "video-display-symbolic")
            content.append(Gtk.Image(icon_name=icon))
            button_name = Gtk.Label()
            content.append(button_name)
            button = Gtk.ToggleButton(focusable=False, child=content)
            button.name_label = button_name
            if self.buttons:
                button.set_group(self.buttons[0])
            button.connect("toggled", self.on_pick, i)
            about = " · ".join(filter(None, describe(monitor)))
            if monitor is self.span:
                about = f"One picture across all monitors · {about}"
            button.set_tooltip_text(about + "  (Tab)")
            picker.append(button)
            self.buttons.append(button)
        row = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True,
                                 propagate_natural_height=True, child=picker)

        tools = Gtk.Box(spacing=6)
        tools.append(icon_button("document-open-symbolic",
                                 "Open another image (O), or drop one",
                                 self.choose_image))
        for icon, tip, action in (
                ("object-flip-horizontal-symbolic", "Mirror (H)", "mirror"),
                ("object-flip-vertical-symbolic", "Flip upside down (V)", "flip"),
                ("object-rotate-right-symbolic", "Rotate 90° (R)", "rotate"),
                ("edit-undo-symbolic", "Reset to the original image, centered (0)", "reset")):
            tools.append(icon_button(icon, tip, lambda action=action: self.edit(action)))
        # wallframe's own icon: the icon theme has none for "make the picture bigger".
        self.ai_button = Gtk.MenuButton(icon_name="wallframe-upscale-symbolic", focusable=False,
                                        tooltip_text=UPSCALE_TOOLTIP,
                                        popover=self.build_ai_popover())
        tools.append(self.ai_button)
        self.discard_button = icon_button("document-revert-symbolic",
                                          "Discard changes since the last Apply (D)", self.discard)
        tools.append(self.discard_button)
        # Lists the other monitors each time it opens, since it depends on the current one.
        self.copy_button = Gtk.MenuButton(icon_name="edit-copy-symbolic", focusable=False,
                                          tooltip_text="Copy settings from another monitor",
                                          popover=Gtk.Popover(),
                                          visible=len(self.monitors) > 1)
        self.copy_button.set_create_popup_func(self.fill_copy_menu)
        tools.append(self.copy_button)
        # Only in the span: dragging moves the monitors' frames instead of the image.
        self.arrange_button = icon_button("preferences-desktop-display-symbolic",
                                          "Arrange the monitors as they stand on your desk (M)",
                                          self.on_arrange, toggle=True)
        self.arrange_button.set_visible(False)
        tools.append(self.arrange_button)
        self.calibrate_button = icon_button("preferences-system-symbolic",
                                            "Put a calibration image on the span, to line the monitors up",
                                            self.calibrate)
        self.calibrate_button.set_visible(False)
        tools.append(self.calibrate_button)
        self.arrangements = Arrangements(self.monitors[0].store.directory)
        self.arrangements_button = Gtk.MenuButton(
            icon_name="document-save-symbolic", focusable=False,
            tooltip_text="Save how the monitors stand, or bring back a saved one",
            popover=self.build_arrangements_popover())
        self.arrangements_button.set_visible(False)
        tools.append(self.arrangements_button)
        self.grid_button = icon_button("view-grid-symbolic", "Rule-of-thirds grid (G)",
                                       self.on_grid_button, toggle=True)
        self.grid_button.set_active(self.show_grid)
        tools.append(self.grid_button)
        self.layouts_button = Gtk.MenuButton(icon_name="user-bookmarks-symbolic",
                                             focusable=False, margin_start=6,
                                             tooltip_text="Layouts: save and switch wallpapers",
                                             popover=self.build_layouts_popover())
        tools.append(self.layouts_button)
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
        self.spinner = Gtk.Spinner(visible=False)  # while Apply or a layout works
        bottom.append(self.spinner)
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
            title = Gtk.Label(xalign=0, margin_top=0 if row == 0 else 14, margin_bottom=2)
            title.set_markup(f"<b>{GLib.markup_escape_text(section)}</b>")
            title.add_css_class("dim-label")
            grid.attach(title, 0, row, 2, 1)
            row += 1
            for keys, action in entries:
                cell = Gtk.Box(spacing=4, halign=Gtk.Align.START)
                for key in keys:
                    label = Gtk.Label(label=key)
                    label.add_css_class("dim-label" if key in MOUSE else "keycap")
                    cell.append(label)
                grid.attach(cell, 0, row, 1, 1)
                grid.attach(Gtk.Label(label=action, xalign=0), 1, row, 1, 1)
                row += 1
        return pinned_popover("Keyboard shortcuts", grid)

    def build_ai_popover(self):
        """Upscale with Upscayl, switch between original and upscaled, compare at 1:1.

        Without Upscayl it says how to install it, since the button would do nothing.
        """
        if not self.upscaler:
            text = Gtk.Label(label=upscalers.INSTALL_HELP, xalign=0, wrap=True,
                             max_width_chars=48)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.append(text)
            box.append(Gtk.LinkButton(uri=upscalers.RELEASES_URL, label="Upscayl releases",
                                      halign=Gtk.Align.START))
            return pinned_popover("Upscale with AI", box)

        self.ai_model = Gtk.DropDown.new_from_strings(
            [label for _model, label in self.upscaler.models])
        self.ai_scale = Gtk.DropDown.new_from_strings([f"×{s}" for s in upscalers.SCALES])
        for dropdown in (self.ai_model, self.ai_scale):
            dropdown.set_focusable(False)
        # Monitors showing the same picture share one upscale; the label says how many run.
        self.ai_all = Gtk.CheckButton(focusable=False, visible=len(self.monitors) > 1)
        self.ai_all.connect("toggled", lambda _b: self.refresh_ai())
        self.ai_run = Gtk.Button(label="Upscale", focusable=False)
        self.ai_run.add_css_class("suggested-action")
        self.ai_run.connect("clicked", lambda _b: self.on_ai_run())

        # Which copy the monitor uses; switching back undoes the upscaling.
        self.ai_original = Gtk.ToggleButton(label="Original", focusable=False, hexpand=True)
        self.ai_upscaled = Gtk.ToggleButton(label="Upscaled", focusable=False, hexpand=True,
                                            group=self.ai_original)
        self.ai_original.connect("toggled", self.on_ai_choice)
        self.ai_choice = Gtk.Box(css_classes=["linked"])
        self.ai_choice.append(self.ai_original)
        self.ai_choice.append(self.ai_upscaled)
        self.ai_compare = Gtk.Button(label="Compare 1:1", focusable=False)
        self.ai_compare.connect("clicked", lambda _b: self.open_compare())
        self.ai_status = Gtk.Label(xalign=0, wrap=True, max_width_chars=36)
        self.ai_status.add_css_class("dim-label")
        self.ai_progress = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER)
        self.ai_progress.set_size_request(180, -1)
        self.ai_progress.set_visible(False)

        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        self.ai_use_label = Gtk.Label(label="Use", xalign=0)
        for row, (label, control) in enumerate((
                (Gtk.Label(label="Model", xalign=0), self.ai_model),
                (Gtk.Label(label="Scale", xalign=0), self.ai_scale),
                (None, self.ai_all),
                (None, self.ai_run),
                (None, self.ai_progress),
                (self.ai_use_label, self.ai_choice),
                (None, self.ai_compare),
                (None, self.ai_status))):
            if label:
                grid.attach(label, 0, row, 1, 1)
            grid.attach(control, 1, row, 1, 1)
        return pinned_popover("Upscale with AI", grid)

    def build_arrangements_popover(self):
        """Names for where the monitors stand and how they are turned: kept apart from
        the pictures, so a calibration is done once and brought back when a monitor moves."""
        self.arrangement_name = Gtk.Entry(placeholder_text="Name", hexpand=True)
        self.arrangement_name.connect("activate", lambda _e: self.save_arrangement())
        save = Gtk.Button(label="Save current", focusable=False)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda _b: self.save_arrangement())
        row = Gtk.Box(spacing=6)
        row.append(self.arrangement_name)
        row.append(save)
        self.arrangement_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(row)
        box.append(self.arrangement_list)
        popover = pinned_popover("Desk arrangements", box)
        popover.connect("show", lambda _p: self.fill_arrangements())
        return popover

    def fill_arrangements(self):
        """One row per arrangement saved for these monitors: its name brings it back."""
        while child := self.arrangement_list.get_first_child():
            self.arrangement_list.remove(child)
        saved = self.arrangements.named([m.name for m in self.monitors])
        if not saved:
            empty = Gtk.Label(label="None yet. Saving one keeps the places and the angle\n"
                                    "of every monitor, apart from any picture.", xalign=0)
            empty.add_css_class("dim-label")
            self.arrangement_list.append(empty)
        for name, entry in saved:
            angles = ", ".join(f"{n} {a:+d}°" for n, a in sorted(entry.get("yaws", {}).items()))
            use = Gtk.Button(label=name, focusable=False, hexpand=True, halign=Gtk.Align.FILL,
                             tooltip_text=angles or "No monitor turned")
            use.connect("clicked", lambda _b, name=name, entry=entry: self.use_arrangement(
                name, entry))
            remove = icon_button("user-trash-symbolic", "Delete this arrangement",
                                 lambda name=name: self.delete_arrangement(name))
            remove.add_css_class("flat")
            line = Gtk.Box(spacing=6)
            line.append(use)
            line.append(remove)
            self.arrangement_list.append(line)

    def save_arrangement(self):
        name = self.arrangement_name.get_text().strip()
        if not name:
            self.flash("Give the arrangement a name", "warning")
            return
        try:
            self.arrangements.save(name, self.span.arrangement())
        except OSError as error:
            self.flash(f"Could not save the arrangement: {error.strerror or error}", "error")
            return
        self.arrangement_name.set_text("")
        self.fill_arrangements()
        self.flash(f"Arrangement “{name}” saved", "success")

    def use_arrangement(self, name, entry):
        if self.span.use_arrangement(entry):
            self.refresh()
            self.flash(f"Arrangement “{name}” · Apply to put it on the monitors", "accent")
        else:
            self.flash(f"“{name}” is for other monitors", "warning")

    def delete_arrangement(self, name):
        try:
            self.arrangements.delete(name)
        except OSError as error:
            self.flash(f"Could not delete it: {error.strerror or error}", "error")
        self.fill_arrangements()

    def build_layouts_popover(self):
        """Save what the monitors show, and switch to a saved layout with one click."""
        self.layout_name = Gtk.Entry(placeholder_text="Name", hexpand=True)
        self.layout_name.connect("activate", lambda _e: self.save_layout())
        save = Gtk.Button(label="Save current", focusable=False)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda _b: self.save_layout())
        row = Gtk.Box(spacing=6)
        row.append(self.layout_name)
        row.append(save)
        self.layout_list = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                                       max_children_per_line=2, min_children_per_line=1,
                                       row_spacing=6, column_spacing=6, homogeneous=True)
        self.layout_empty = Gtk.Label(label="No layouts yet. Saving one keeps the picture\n"
                                            "and framing of every monitor.", xalign=0)
        self.layout_empty.add_css_class("dim-label")
        scroll = Gtk.ScrolledWindow(child=self.layout_list, max_content_height=460,
                                    propagate_natural_height=True,
                                    propagate_natural_width=True,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for widget in (row, self.layout_empty, scroll):
            box.append(widget)
        self.fill_layouts()
        return pinned_popover("Layouts", box)

    def fill_layouts(self):
        """One card per layout: click it to apply, ⋯ to rename, update, copy or delete."""
        self.layout_list.remove_all()
        layouts = self.layouts.all()
        self.layout_empty.set_visible(not layouts)
        for layout in layouts:
            picture = Gtk.Picture.new_for_filename(layout.preview)
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_size_request(170, 76)
            name = Gtk.Label(label=layout.name, ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=18)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            content.append(picture)
            content.append(name)
            active = self.shows_layout(layout)
            if active:  # what the monitors show: the card says so, in the accent color
                name.set_label(f"✓ {layout.name}")
                name.add_css_class("accent")
            card = Gtk.Button(child=content, focusable=False,
                              tooltip_text="On the monitors now · click to apply it again"
                              if active else "Apply to the monitors now")
            card.add_css_class("flat")
            if active:
                card.add_css_class("active-layout")
            card.connect("clicked", lambda _b, layout=layout: self.activate_layout(layout))
            menu = Gtk.MenuButton(icon_name="view-more-symbolic", focusable=False,
                                  tooltip_text="Rename, update, duplicate or delete",
                                  halign=Gtk.Align.END, valign=Gtk.Align.START,
                                  popover=self.build_layout_menu(layout))
            menu.add_css_class("flat")
            overlay = Gtk.Overlay(child=card)
            overlay.add_overlay(menu)
            self.layout_list.append(overlay)

    def build_layout_menu(self, layout):
        """The ⋯ menu of one layout; its name is edited in place, Enter renames."""
        rename = Gtk.Entry(text=layout.name)
        rename.connect("activate",
                       lambda entry: self.layout_action(self.layouts.rename, layout,
                                                        entry.get_text().strip() or layout.name))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.append(rename)
        for label, action in (
                ("Save current here", lambda: self.layout_action(
                    self.layouts.update, layout, self.monitors, self.positions,
                    self.layout_span())),
                ("Duplicate", lambda: self.layout_action(self.layouts.duplicate, layout)),
                ("Delete…", lambda: self.confirm_delete_layout(layout))):
            button = Gtk.Button(label=label, focusable=False)
            button.get_child().set_xalign(0)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, action=action: action())
            box.append(button)
        return Gtk.Popover(child=box)

    def layout_action(self, action, layout, *args):
        """Runs a change on the layouts folder, then lists them again."""
        try:
            action(layout, *args)
        except OSError as error:
            self.flash(f"Could not change {layout.name}: {error.strerror or error}", "error")
        self.fill_layouts()

    def confirm_delete_layout(self, layout):
        dialog = Gtk.AlertDialog(message=f"Delete {layout.name}?",
                                 detail="The pictures stay where they are.",
                                 buttons=["Cancel", "Delete"], cancel_button=0)

        def answered(dialog, result):
            try:
                if dialog.choose_finish(result) == 1:
                    self.layout_action(self.layouts.delete, layout)
            except GLib.Error:  # closed with Esc
                pass

        dialog.choose(self, None, answered)

    def save_layout(self):
        name = self.layout_name.get_text().strip() or f"Layout {len(self.layouts.all()) + 1}"
        try:
            self.layouts.save(name, self.monitors, self.positions, self.layout_span())
        except OSError as error:
            self.flash(f"Could not save the layout: {error.strerror or error}", "error")
            return
        self.layout_name.set_text("")
        self.set_focus(None)  # the keys go back to the editor
        self.fill_layouts()
        self.flash(f"Saved {name}", "success")

    def layout_span(self):
        """The span a layout saved now keeps: the one being edited, or the one the
        monitors show, untouched; None when they show pictures of their own."""
        if self.spanning:
            return self.span
        span = self.span
        if span and span.live and not span.touched and not any(m.touched for m in self.monitors):
            return span
        return None

    def activate_layout(self, layout):
        """Shows the layout on the monitors right away, and in the editor.

        Monitors it does not know keep what they show; edits waiting for Apply on
        the monitors it does know are replaced by it. A picture that cannot be
        loaded leaves its monitor as it was, and a dialog says why and where the
        picture was, since a path does not fit in the status bar. A layout saved
        from the span also brings the span back to the editor, and opens it.
        """
        jobs = [(m, layout.monitors[m.name]) for m in self.monitors if m.name in layout.monitors]
        if not jobs:
            self.flash(f"{layout.name} has none of these monitors", "warning")
            return

        def done(failed):
            self.after_layout(layout)
            if failed:
                self.flash(f"Could not load all of {layout.name}", "error")
                self.report(f"Could not load all of {layout.name}",
                            "\n\n".join(failed) + "\n\nThe other monitors switched.")
            else:
                self.flash(f"Switched to {layout.name}", "success")

        self.apply_monitors(jobs, layout.name, done)

    def after_layout(self, layout):
        """Puts the layout's span in the editor, when it has one for these monitors;
        a layout without one leaves the span, which the monitors no longer show."""
        span, saved = self.span, layout.span
        if not span or not saved or set(saved["monitors"]) != set(span.places):
            if self.spanning:
                self.select(0)
            return
        # The monitors just read the same picture: their thumbnail saves reading it again.
        thumb = next((m.thumb for m in self.monitors if m.image == saved["source"]), None)
        try:
            span.take(saved, thumb)
        except OSError:
            return  # its picture is gone; the monitors that could, switched
        span.mark_applied()
        self.remember_span()
        self.select(self.views.index(span))

    def remember_span(self):
        try:
            self.monitors[0].store.remember_span(self.span.snapshot())
        except OSError as error:
            self.flash(f"Could not save the span: {error.strerror or error}", "error")

    def shows_layout(self, layout):
        """True when every monitor the layout knows shows what it saved, as applied."""
        known = [m for m in self.monitors if m.name in layout.monitors]
        return bool(known) and all(m.shows(layout.monitors[m.name]) for m in known)

    def report(self, message, detail):
        """An error with more to say than the status bar holds."""
        Gtk.AlertDialog(message=message, detail=detail).show(self)

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
        drag.connect("drag-end", self.on_drag_end)
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

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.area.add_controller(drop)

    @property
    def monitor(self):
        """What is being edited: a monitor, or the span."""
        return self.views[self.index]

    @property
    def spanning(self):
        return self.span is not None and self.monitor is self.span

    @property
    def arranging(self):
        """True while dragging moves the span's monitors instead of the image."""
        return self.spanning and self.arrange_button.get_active()

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
        """Returns (scale, fx, fy): canvas pixels per monitor pixel, frame origin.

        While a monitor of the span is dragged, the desk holds still on the canvas,
        though the box around the monitors grows or shrinks under the pointer.
        """
        monitor = self.monitor
        if self.held:
            scale, ox, oy = self.held
            return scale, ox + monitor.left * scale, oy + monitor.top * scale
        aw, ah = self.area.get_width(), self.area.get_height()
        scale = min((aw - 2 * MARGIN) / monitor.width, (ah - 2 * MARGIN) / monitor.height)
        return scale, (aw - monitor.width * scale) / 2, (ah - monitor.height * scale) / 2

    def draw(self, _area, cr, aw, ah):
        """The image over its frames: one per monitor, so several for the span."""
        monitor = self.monitor
        framing = monitor.framing
        scale, fx, fy = self.frame()
        frames = [(name, fx + x * scale, fy + y * scale, w * scale, h * scale)
                  for name, x, y, w, h in monitor.frames()]
        cr.set_source_rgb(0.08, 0.08, 0.08)
        cr.paint()

        if not framing.covers:
            # The fill, inside the frames only, behind the image.
            background = self.background(monitor)
            cr.save()
            for _name, x, y, w, h in frames:
                cr.rectangle(x, y, w, h)
            cr.clip()
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
        cr.paint_with_alpha(0.35 if moving_backdrop or self.arranging else 1)
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

        # Dim everything outside the frames: that part will not be shown.
        cr.set_source_rgba(0, 0, 0, 0.65)
        cr.rectangle(0, 0, aw, ah)
        for _name, x, y, w, h in frames:
            cr.rectangle(x, y, w, h)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)  # fill around the frames only
        cr.fill()

        if self.show_grid:
            self.draw_grid(cr, frames, scale, fx, fy)

        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(3 if self.arranging else 2)
        for _name, x, y, w, h in frames:
            cr.rectangle(x, y, w, h)
        cr.stroke()
        chosen = next((f for f in frames if self.arranging and f[0] == self.selected), None)
        if chosen:  # the monitor the arrow keys move
            _name, x, y, w, h = chosen
            cr.set_source_rgba(*SELECTED, 0.25)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_source_rgba(*SELECTED, 1)
            cr.set_line_width(5)
            cr.rectangle(x, y, w, h)
            cr.stroke()
        if len(frames) > 1:
            self.draw_names(cr, frames)

    def draw_grid(self, cr, frames, scale, fx, fy):
        """The rule of thirds of each monitor. In the span, also the thirds of the whole
        picture, which run on across the monitors, and while arranging, the desk's real
        centimeters, numbered like the calibration picture."""
        spanning = self.spanning
        cr.save()
        if spanning:  # lines that cross the monitors show only where a monitor is
            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
            for _name, x, y, w, h in frames:
                cr.rectangle(x, y, w, h)
            cr.clip()
        if self.arranging and self.span.units_per_mm:
            self.draw_centimeters(cr, frames, scale, fx, fy)
        else:
            cr.set_source_rgba(1, 1, 1, 0.15 if spanning else 0.3)
            cr.set_line_width(1)
            for _name, x, y, w, h in frames:
                for k in (1, 2):
                    cr.move_to(x + w * k / 3, y)
                    cr.line_to(x + w * k / 3, y + h)
                    cr.move_to(x, y + h * k / 3)
                    cr.line_to(x + w, y + h * k / 3)
            cr.stroke()
            if spanning:
                width, height = self.span.width * scale, self.span.height * scale
                cr.set_source_rgba(1, 0.84, 0.4, 0.65)
                cr.set_line_width(1.5)
                for k in (1, 2):
                    cr.move_to(fx + width * k / 3, fy)
                    cr.line_to(fx + width * k / 3, fy + height)
                    cr.move_to(fx, fy + height * k / 3)
                    cr.line_to(fx + width, fy + height * k / 3)
                cr.stroke()
        cr.restore()

    def draw_centimeters(self, cr, frames, scale, fx, fy):
        """A line every centimeter of the real desk, thick every five, from the box's corner."""
        span = self.span
        per_cm = 10 * span.units_per_mm * scale  # canvas pixels
        width, height = span.width * scale, span.height * scale
        cr.set_font_size(10)
        for k in range(int(max(width, height) / per_cm) + 1):
            major = k % 5 == 0
            cr.set_source_rgba(1, 1, 1, 0.4 if major else 0.1)
            cr.set_line_width(1.5 if major else 1)
            at = k * per_cm
            cr.move_to(fx + at, fy)
            cr.line_to(fx + at, fy + height)
            cr.move_to(fx, fy + at)
            cr.line_to(fx + width, fy + at)
            cr.stroke()
            if not major:
                continue
            cr.set_source_rgba(1, 1, 1, 0.8)
            for _name, x, y, w, h in frames:
                if x <= fx + at <= x + w:
                    cr.move_to(fx + at + 3, y + 40)
                    cr.show_text(str(k))
                if y <= fy + at <= y + h:
                    cr.move_to(x + 4, fy + at - 3)
                    cr.show_text(str(k))

    def draw_names(self, cr, frames):
        """Each monitor's name in the corner of its frame, on a dark tag; the selected one's is lit."""
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        for name, x, y, _w, _h in frames:
            yaw = self.span.yaws.get(name, 0) if self.spanning else 0
            tag = f"{name}  {yaw:+d}°" if yaw else name  # the angle it is turned, when it is
            extents = cr.text_extents(tag)
            lit = self.arranging and name == self.selected
            cr.set_source_rgba(*(SELECTED + (1,) if lit else (0, 0, 0, 0.6)))
            cr.rectangle(x + 6, y + 6, extents.x_advance + 12, 20)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.move_to(x + 12, y + 20)
            cr.show_text(tag)

    def select(self, index):
        self.index = index
        self.buttons[index].set_active(True)
        self.move_backdrop.set_active(False)  # each monitor starts by moving its image
        self.arrange_button.set_active(False)
        self.refresh()

    def on_pick(self, button, index):
        if button.get_active() and index != self.index:
            self.select(index)

    def refresh(self):
        """Syncs the bars with the current monitor and redraws."""
        for monitor, button in zip(self.views, self.buttons):
            button.name_label.set_label(f"● {monitor.name}" if monitor.touched else monitor.name)
        self.apply_button.set_sensitive(bool(self.pending()))
        self.discard_button.set_sensitive(self.monitor.touched)
        # The span has no other monitor to copy from: it is all of them.
        self.copy_button.set_visible(len(self.monitors) > 1 and not self.spanning)
        self.arrange_button.set_visible(self.spanning)
        self.calibrate_button.set_visible(self.arranging)
        self.arrangements_button.set_visible(self.arranging)
        self.refresh_ai()
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
            ("real sizes" if monitor.real_sizes else "desktop sizes") if self.spanning else "",
            (f"Arranging {self.selected}{self.yaw_text()}{self.gap_text()} · M to finish"
             if self.arranging else "Moving the picture · M to arrange")
            if self.spanning else "",
            "moving the background" if self.moving is not framing else "",
            "upscaling…" if monitor.name in self.upscaling else "",
            "upscaled" if monitor.image != monitor.original else "",
            "mirrored" if framing.flip_h else "",
            "flipped" if framing.flip_v else "",
            f"rotated {framing.rotation}°" if framing.rotation else ""]
        if self.applying:  # until it is over, whatever else flashed
            self.label.set_css_classes(["accent"])
            self.label.set_markup(
                f"<b>{GLib.markup_escape_text(f'Applying {self.applying}…')}</b>")
        elif not self.flash_timer:  # a message on screen keeps the bar until it ends
            self.label.set_markup(f"<b>{GLib.markup_escape_text(monitor.name)}</b>   "
                                  + GLib.markup_escape_text("  ·  ".join(filter(None, details))))
        self.area.queue_draw()

    def yaw_text(self):
        """" +40°" when the selected monitor is turned."""
        degrees = self.span.yaws.get(self.selected, 0)
        return f" {degrees:+d}°" if degrees else ""

    def gap_text(self):
        """" · gap 12 mm to left and 14 mm to right" for the selected monitor."""
        span = self.span
        if not span.units_per_mm:
            return ""
        near = [f"{round(distance / span.units_per_mm)} mm to {side}"
                for side, (_other, distance) in sorted(span.gaps(self.selected).items())]
        return f" · gap {' and '.join(near)}" if near else ""

    def edit(self, action):
        if self.arranging:
            if action == "reset":
                self.span.reset_places()
                self.flash("The monitors are back to their real sizes and places", "accent")
                self.refresh()
            else:
                self.flash("Finish arranging first (M)", "warning")
            return  # mirror and rotate would move the picture under the monitors unseen
        self.monitor.edit(action)
        self.refresh()

    def on_arrange(self):
        if self.syncing:
            return
        if self.arranging:
            self.selected = self.selected or self.span.monitors[0].name
            self.flash("Drag a monitor or select it and use the arrows · M to finish", "accent")
        else:
            self.selected = None
        self.refresh()

    def calibrate(self):
        """Puts the calibration picture on the span, marked for Apply."""
        if not self.arranging:
            return
        path = os.path.join(self.monitors[0].store.directory, calibration.FILE)
        try:
            calibration.make(self.span, path)
            self.span.open_image(path)
        except OSError as error:
            self.flash(f"Could not make the calibration image: {error.strerror or error}",
                       "error")
            return
        self.move_backdrop.set_active(False)
        self.refresh()
        self.flash("Calibration image · Apply it, then move the monitors until the lines meet",
                   "accent")

    def fill_copy_menu(self, menu_button):
        """One row per other monitor, with the picture it shows: copy all of it, or the fill."""
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        heading = Gtk.Label(xalign=0, margin_bottom=2)
        heading.set_markup(f"<b>Copy to {GLib.markup_escape_text(self.monitor.name)} from</b>")
        grid.attach(heading, 0, 0, 2, 1)
        row = 1
        for source in self.monitors:
            if source is self.monitor:
                continue
            name = Gtk.Label(xalign=0)
            name.set_markup(f"<b>{GLib.markup_escape_text(source.name)}</b>")
            same = source.original == self.monitor.original
            picture = Gtk.Label(label="same picture" if same else os.path.basename(source.image),
                                xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE,
                                max_width_chars=24)
            picture.add_css_class("dim-label")
            about = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            about.append(name)
            about.append(picture)
            choices = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
            for label, tip, everything in (
                    ("Everything", "The picture, mirror, rotation, zoom, position and fill",
                     True),
                    ("Fill only", "Blur or color around a smaller image", False)):
                button = Gtk.Button(label=label, tooltip_text=tip, focusable=False)
                button.connect("clicked", lambda _b, source=source, everything=everything:
                               self.copy_settings(source, everything))
                choices.append(button)
            grid.attach(about, 0, row, 1, 1)
            grid.attach(choices, 1, row, 1, 1)
            row += 1
        menu_button.get_popover().set_child(grid)

    def copy_settings(self, source, everything=True):
        self.copy_button.popdown()
        target = self.monitor
        target.copy_from(source, everything)
        self.move_backdrop.set_active(False)
        self.refresh()
        if everything:
            self.flash(f"Copied everything from {source.name}", "accent")
        elif target.framing.covers:
            self.flash(f"Copied the fill from {source.name}; it shows when zoomed out", "accent")
        else:
            self.flash(f"Copied the fill from {source.name}", "accent")

    def refresh_ai(self):
        """Syncs the AI panel with the current monitor."""
        if not self.upscaler:
            return
        monitor = self.monitor
        # A clock on the toolbar button while any upscale runs, seen with the panel closed.
        busy = bool(self.upscaling)
        self.ai_button.set_icon_name("preferences-system-time-symbolic" if busy
                                     else "wallframe-upscale-symbolic")
        self.ai_button.set_tooltip_text("Upscaling…" if busy else UPSCALE_TOOLTIP)
        running = any(m.name in self.upscaling for m in self.upscale_targets())
        # While it runs, the same button stops it.
        self.ai_run.set_label("Cancel" if running else "Upscale")
        self.ai_run.set_css_classes(["destructive-action" if running else "suggested-action"])
        self.ai_progress.set_visible(running)
        self.ai_all.set_visible(len(self.monitors) > 1 and not self.spanning)
        pictures = len({m.original for m in self.monitors})
        self.ai_all.set_label("All monitors · same picture, upscaled once" if pictures == 1
                              else f"All monitors · {pictures} pictures, one after another")
        has_copy = monitor.upscaled is not None
        for widget in (self.ai_use_label, self.ai_choice, self.ai_compare):
            widget.set_visible(has_copy)
        self.syncing = True
        using_copy = monitor.image == monitor.upscaled
        (self.ai_upscaled if using_copy else self.ai_original).set_active(True)
        self.syncing = False
        self.ai_status.set_label(
            self.ai_busy_text() if running else
            "Upscaling always starts from the original." if has_copy else "")

    def ai_busy_text(self):
        """What the panel says while it works: which picture, of how many."""
        if self.ai_pictures > 1:
            return f"Picture {self.ai_step} of {self.ai_pictures} · you can keep editing"
        return "Runs in the background: you can keep editing."

    def ai_step_started(self, step, total):
        """Puts the bar back to the start and names the picture that begins."""
        self.ai_step, self.ai_pictures = step, total
        self.ai_progress.set_fraction(0)
        self.ai_progress.set_text(f"{step} / {total}")
        self.refresh_ai()
        return False  # run once

    def ai_step_advanced(self, done):
        """The share of the image Upscayl has finished, from the percentage it prints."""
        self.ai_progress.set_fraction(done / 100)
        self.ai_progress.set_text(f"{done:.0f}%")
        return False  # run once

    def on_ai_run(self):
        """Upscale, or cancel the upscale that is running for these monitors."""
        targets = [m.name for m in self.upscale_targets() if m.name in self.upscaling]
        if targets:
            self.cancel_upscales(targets)
        else:
            self.upscale()

    def cancel_upscales(self, names):
        """Stops the upscales running for these monitors; the rest keep going.

        Monitors that share a run stop together: it is one Upscayl for all of them.
        """
        for cancel in {self.upscaling[name] for name in names}:
            cancel()
        return False  # let the window close

    def upscale_targets(self):
        """The monitors an Upscale click covers: this one, or all of them; or the span."""
        if self.spanning or not self.ai_all.get_active():
            return [self.monitor]
        return self.monitors

    def upscale(self):
        """Enlarges the targets' original images with AI, off the main thread.

        It takes seconds on a GPU and more without one, so the window stays usable
        and the result lands when it is ready, even if another monitor is selected.
        Each different picture runs once, one after another; monitors that show
        the same picture share the result. The panel counts the pictures and shows
        the percentage Upscayl reports, so the wait is visibly a wait.
        """
        targets = self.upscale_targets()
        model = self.upscaler.models[self.ai_model.get_selected()][0]
        scale = upscalers.SCALES[self.ai_scale.get_selected()]
        originals = list(dict.fromkeys(m.original for m in targets))  # distinct, in order
        cancel = Cancel()
        self.upscaling.update((m.name, cancel) for m in targets)
        self.ai_step_started(1, len(originals))
        self.refresh()
        names = ", ".join(m.name for m in targets)
        self.flash(f"Upscaling {names} ×{scale}…", "accent")

        def report(line):
            done = upscalers.percent(line)
            if done is not None:
                GLib.idle_add(self.ai_step_advanced, done)

        def work():
            results, errors = {}, {}
            for step, original in enumerate(originals, start=1):
                GLib.idle_add(self.ai_step_started, step, len(originals))
                try:
                    results[original] = self.upscaler.upscale(original, model, scale, report,
                                                              cancel)
                except OSError as failure:
                    errors[original] = failure
                except Cancelled:
                    break
            GLib.idle_add(self.upscaled, targets, results, errors, scale, cancel.requested)

        threading.Thread(target=work, daemon=True).start()

    def upscaled(self, targets, results, errors, scale, cancelled=False):
        """Back on the main thread with the upscaled copies, and what failed.

        Pictures finished before a cancel are kept: they took as long as any other.
        Waits while something is applied, since that reads the monitors it changes.
        """
        if self.applying:
            GLib.timeout_add(200, self.upscaled, targets, results, errors, scale, cancelled)
            return False
        for monitor in targets:
            self.upscaling.pop(monitor.name, None)
            if monitor.original in results:
                monitor.use_upscaled(results[monitor.original])
        self.refresh()
        if cancelled:
            self.flash("Upscale cancelled", "warning")
            return False
        failed = [m.name for m in targets if m.original in errors]
        if failed:
            error = next(iter(errors.values()))
            self.flash(f"Could not upscale {', '.join(failed)}: {error.strerror or error}",
                       "error")
        else:
            names = ", ".join(m.name for m in targets)
            self.flash(f"Upscaled {names} ×{scale} · compare it, then Apply", "success")
        return False  # run once

    def on_ai_choice(self, _button, *_args):
        if self.syncing:
            return
        if self.ai_original.get_active():
            self.monitor.use_original()
        else:
            self.monitor.use_upscaled()
        self.refresh()

    def open_compare(self):
        from .compare import CompareWindow  # it imports this module
        CompareWindow(self, self.monitor).present()

    def discard(self):
        """Back to what the monitor shows now, dropping this session's changes on it."""
        if self.monitor.touched:
            self.monitor.discard_edit()
            self.move_backdrop.set_active(False)
            self.refresh()
            self.flash(f"Changes to {self.monitor.name} discarded", "accent")

    def choose_image(self):
        """Asks for a picture, starting in the folder of the one shown now."""
        images = Gtk.FileFilter(name="Images")
        images.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog = Gtk.FileDialog(title=f"Open an image for {self.monitor.name}",
                                filters=filters, default_filter=images, modal=False,
                                initial_folder=Gio.File.new_for_path(
                                    os.path.dirname(self.monitor.original)))
        monitor = self.monitor  # the one it was opened for, even if Tab moves on

        def chosen(dialog, result):
            try:
                path = dialog.open_finish(result).get_path()
            except GLib.Error:  # cancelled
                return
            self.open_image(monitor, path)

        dialog.open(self, None, chosen)

    def on_drop(self, _target, files, _x, _y):
        paths = [f.get_path() for f in files.get_files() if f.get_path()]
        if not paths:
            return False
        self.open_image(self.monitor, paths[0])
        return True

    def open_image(self, monitor, path):
        """Puts `path` on `monitor` in the editor, marked for Apply."""
        try:
            monitor.open_image(path)
        except OSError as error:
            self.flash(f"Cannot open {os.path.basename(path)}: {error.strerror or error}",
                       "error")
            return
        if monitor is self.monitor:
            self.move_backdrop.set_active(False)
        self.refresh()
        self.flash(f"{os.path.basename(path)} on {monitor.name} · frame it, then Apply",
                   "accent")

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

    def on_drag_begin(self, _gesture, x, y):
        if self.arranging:
            self.begin_arranging(x, y)
            return
        self.drag_origin = (self.moving.x, self.moving.y)
        if self.moving is not self.monitor.framing and not self.moving.can_move:
            self.flash("Zoom in the background to move it", "warning")

    def begin_arranging(self, x, y):
        """Picks the span's monitor under (x, y) on the canvas, to drag it."""
        scale, fx, fy = self.frame()
        span = self.span
        under = [(name, fx + mx * scale, fy + my * scale, w * scale, h * scale)
                 for name, mx, my, w, h in span.frames()]
        name = next((name for name, left, top, w, h in reversed(under)
                     if left <= x <= left + w and top <= y <= top + h), None)
        self.dragged = name
        if not name:
            self.flash("Drag one of the monitors", "warning")
            return
        self.selected = name
        self.held = (scale, fx - span.left * scale, fy - span.top * scale)
        self.drag_origin = span.places[name][:2]

    def on_drag_end(self, _gesture, _dx, _dy):
        if self.dragged:
            self.dragged, self.held = None, None
            self.span.settle()
            self.refresh()

    def on_drag_update(self, _gesture, dx, dy):
        if self.arranging:
            if self.dragged:
                scale = self.held[0]
                x, y = self.span.snap(self.dragged, self.drag_origin[0] + dx / scale,
                                      self.drag_origin[1] + dy / scale, SNAP / scale)
                self.span.move_monitor(self.dragged, x, y)
                self.refresh()
            return
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
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            # Left to the desktop: Ctrl+D would discard the framing and Ctrl+H mirror it.
            return False
        if self.applying:
            return True  # nothing edits the monitors while they are being applied
        key = Gdk.keyval_name(Gdk.keyval_to_lower(keyval))
        if isinstance(self.get_focus(), Gtk.Editable) and key != "Escape":
            return False  # typing a layout's name: H, R or Enter are letters, not actions
        open_panel = next((b for b in (self.fill_button, self.help_button, self.layouts_button,
                                       self.arrangements_button)
                           if b.get_active()), None)
        if key == "Escape" and open_panel:
            open_panel.popdown()  # Esc closes the panel, not the whole window
        elif key in HELP_KEYS:
            self.help_button.set_active(not self.help_button.get_active())
        elif key == "Escape":
            self.close()
        elif key == "Tab" and len(self.views) > 1:
            self.select((self.index + 1) % len(self.views))
        elif key in ("Return", "KP_Enter"):
            self.apply()
        elif key in KEY_ACTIONS:
            self.edit(KEY_ACTIONS[key])
        elif key == DISCARD_KEY:
            self.discard()
        elif key == "o":
            self.choose_image()
        elif key == "g":
            self.grid_button.set_active(not self.grid_button.get_active())
        elif key == "b":
            self.toggle_backdrop()
        elif key == "m" and self.spanning:
            self.arrange_button.set_active(not self.arrange_button.get_active())
        elif key == "c":
            self.moving.center()
            self.refresh()
        elif key in ZOOM_KEYS:
            self.zoom_centered(ZOOM_KEYS[key])
        elif key in YAW_KEYS and self.arranging:
            self.span.set_yaw(self.selected, self.span.yaws.get(self.selected, 0)
                              + YAW_KEYS[key])
            self.refresh()
        elif key in ARROW_KEYS:
            shifted = bool(state & Gdk.ModifierType.SHIFT_MASK)
            step = NUDGE_SHIFT if shifted else NUDGE
            dx, dy = ARROW_KEYS[key]
            if self.arranging:
                if self.span.units_per_mm:  # millimeters on the desk, not span units
                    step = (ARRANGE_MM_SHIFT if shifted else ARRANGE_MM) * self.span.units_per_mm
                x, y = self.span.places[self.selected][:2]
                self.span.move_monitor(self.selected, x + dx * step, y + dy * step)
                self.span.settle()
                self.refresh()
                return True
            self.moving.move_to(self.moving.x + dx * step, self.moving.y + dy * step)
            self.refresh()
        else:
            return False
        return True

    def on_active(self, _window, _prop):
        if self.is_active() and not self.asking and not self.applying:
            self.sync_with_daemon(ask_postponed=False)

    def apply(self):
        """Checks for wallpapers changed elsewhere first, so none is overwritten unasked."""
        if not self.asking:
            self.sync_with_daemon(then=self.apply_touched)

    def pending(self):
        """What Apply writes: the edited monitors, or in the span, the span when
        the monitors do not show it as it is."""
        if self.spanning:
            span = self.span
            return [span] if span.touched or not span.live else []
        return [m for m in self.monitors if m.touched]

    def apply_touched(self):
        if not self.pending():
            self.flash("Nothing to apply", "warning")
            return
        if self.spanning:
            self.apply_span()
            return
        touched = self.pending()

        def done(failed):
            if failed:
                self.flash(f"Could not apply {'; '.join(failed)}", "error")
            else:
                self.flash("Applied", "success")

        self.apply_monitors([(m, None) for m in touched], "the changes", done)

    def apply_span(self):
        """Gives each monitor its piece of the span; a monitor that shows its piece
        already is left alone."""
        span = self.span

        def done(failed):
            span.mark_applied()
            self.remember_span()
            self.refresh()
            if failed:
                self.flash(f"Could not apply {'; '.join(failed)}", "error")
            else:
                self.flash("Applied across all monitors", "success")

        self.apply_monitors(span.pieces(), "the span", done)

    def apply_monitors(self, jobs, what, done):
        """Applies each (monitor, layout entry, Snapshot, or None for its own edits)
        off the main thread.

        Reading the pictures and cropping them takes a second or two per monitor,
        so the window pauses with a spinner instead of freezing, and nothing edits
        the monitors until it is over. done(failed) runs back on the main thread,
        with one line per monitor that failed; a layout's picture that cannot be
        read also gives the path where it was.
        """
        self.set_busy(what)

        def work():
            """The slow part, which reads the monitors and changes none of them."""
            results = []  # (monitor, snapshot, crop path, error, picture that failed to load)
            for monitor, entry in jobs:
                try:
                    snapshot = (entry if isinstance(entry, Snapshot)
                                else monitor.read_snapshot(entry) if entry else None)
                except OSError as error:  # gone or unreadable: the other monitors still apply
                    results.append((monitor, None, None, error, entry["source"]))
                    continue
                image, framing = ((snapshot.source, snapshot.framing) if snapshot
                                  else (monitor.image, monitor.framing))
                if snapshot and not monitor.touched and (image, framing.key()) == (
                        monitor.applied_image, monitor.applied):
                    results.append((monitor, snapshot, None, None, None))  # shows it already
                    continue
                try:
                    results.append((monitor, snapshot, monitor.make_crop(image, framing),
                                    None, None))
                except OSError as error:
                    results.append((monitor, snapshot, None, error, None))
            return results

        def finish(results):
            failed = []
            for monitor, snapshot, path, error, picture in results:
                if snapshot:
                    monitor.take(snapshot)
                try:
                    if error:
                        raise error
                    if path:
                        monitor.show(self.daemon, path)
                except OSError as failure:
                    reason = ("image not found" if isinstance(failure, FileNotFoundError)
                              else failure.strerror or str(failure))
                    failed.append(f"{monitor.name}: {reason}"
                                  + (f"\n{picture}" if picture else ""))
            self.set_busy(None)
            self.move_backdrop.set_active(False)  # back to moving the image
            if self.upscaler:
                in_use = {p for m in self.views for p in (m.image, m.upscaled) if p}
                self.upscaler.clean(in_use | self.monitors[0].store.images_in_use()
                                    | self.layouts.images_in_use())
            self.refresh()
            self.fill_layouts()  # marks the card of what the monitors show now
            done(failed)

        self.in_background(work, finish)

    def in_background(self, work, then):
        """Runs work() on another thread, then then(its result) back on the main one."""
        def run():
            result = work()
            GLib.idle_add(lambda: then(result) and False)  # False: run once

        threading.Thread(target=run, daemon=True).start()

    def set_busy(self, what):
        """Pauses the editor while `what` is applied, or resumes it with None."""
        self.applying = what
        self.top_bar.set_sensitive(not what)
        self.area.set_sensitive(not what)
        self.spinner.set_visible(bool(what))
        self.spinner.set_spinning(bool(what))
        self.refresh()

    def sync_with_daemon(self, then=None, ask_postponed=True):
        """Reloads monitors whose wallpaper changed elsewhere; asks about edited ones.

        `then` runs once every question is answered, and not at all if one is dismissed.
        """
        current = {output.name: output for output in self.daemon.outputs()}
        conflicts, reloaded = [], []
        # An edited span would replace every monitor's wallpaper, so it asks too.
        span_edited = self.spanning and self.span.touched
        for monitor in self.monitors:
            output = current.get(monitor.name)
            if not output or not monitor.changed(output.image):
                continue
            if monitor.touched or span_edited or not render.is_still_image(output.image):
                if ask_postponed or (monitor.name, output.image) not in self.postponed:
                    conflicts.append((monitor, output))
            else:
                monitor.load(output)
                reloaded.append(monitor)
        if reloaded and self.span and not span_edited:
            self.span.follow(reloaded[0])  # the span shows what the monitors do now
        self.refresh()
        if reloaded:
            self.flash(f"New wallpaper loaded on {', '.join(m.name for m in reloaded)}",
                       "success")
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
        detail = ("It is animated or a video, so wallframe cannot edit it." if not loadable
                  else "Your changes on this monitor are for the previous image."
                  if monitor.touched else "Applying the span would replace it.")
        dialog = Gtk.AlertDialog(
            message=f"{monitor.name} has a new wallpaper",
            detail=detail,
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
            # Kept, the new wallpaper must survive: an Apply of the span would cover it.
            keep = choice != 1 and self.spanning
            self.ask_next(conflicts[1:], None if keep else then)

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
