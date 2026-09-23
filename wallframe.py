#!/usr/bin/env python3
"""Drag and zoom the wallpaper inside each monitor's frame, then apply it.

Shows the image each monitor is displaying, with that monitor's frame on top.
Pick the monitor from the row of buttons (or Tab), drag to move, scroll to
zoom around the pointer (or use the slider). The toolbar mirrors, flips,
turns, resets and toggles a rule-of-thirds grid; every button has a key
(H, V, R, 0, G), shown in its tooltip. Apply (Enter) writes the monitors you
touched and keeps the window open; Esc closes it.

The result is cropped to the exact output size and handed to awww (or swww)
for that monitor only.

    wallframe.py [MONITOR]
"""

import json
import os
import re
import subprocess
import sys
import time

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from PIL import Image  # noqa: E402

APP_ID = "io.github.AlejandroMinor.wallframe"
# Not ~/.cache: the crop is the wallpaper itself, and awww reloads it from this
# path on every login, so a cache cleaner would leave the monitor blank.
OUT_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                       "wallframe")
# Crop -> source image and framing, so reopening resumes from the original
# instead of cropping the crop again.
STATE = os.path.join(OUT_DIR, "state.json")
PREVIEW_MAX = 2048   # longest side of the on-screen copy; the crop uses the original
MARGIN = 60          # canvas space around the frame, to see what is left out
ZOOM_STEP = 1.1
MAX_ZOOM = 8.0       # relative to the zoom that just covers the monitor


def run(cmd):
    """Returns the command's stdout, or "" when it is missing or fails."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    except OSError:
        return ""


def notify(message):
    """Reports a fatal problem on stderr and, when available, as a notification."""
    print(f"wallframe: {message}", file=sys.stderr)
    run(["notify-send", "wallframe", message])


def daemon_outputs():
    """Returns (daemon, [(name, width, height, image)]) for outputs showing an image.

    awww is the continuation of swww and both answer `query` the same way, so
    whichever daemon is running wins.
    """
    for daemon in ("awww", "swww"):
        found = []
        for line in run([daemon, "query"]).splitlines():
            m = re.match(r"^: ([^:]+): (\d+)x(\d+),.*image: (.+)$", line)
            if m:
                found.append((m[1], int(m[2]), int(m[3]), m[4]))
        if found:
            return daemon, found
    return None, []


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def compositor_outputs():
    """Returns (focused name, {name: model}) from Hyprland or sway, else (None, {})."""
    for cmd in (["hyprctl", "monitors", "-j"], ["swaymsg", "-t", "get_outputs"]):
        try:
            outputs = json.loads(run(cmd) or "[]")
        except ValueError:
            continue
        if outputs:
            focused = next((o.get("name") for o in outputs if o.get("focused")), None)
            return focused, {o.get("name"): display_model(o) for o in outputs}
    return None, {}


def display_model(output):
    """Make and model, without repeating the make when the model already has it.

    EDID makes are noisy ("ASUSTek COMPUTER INC", "NZXT (PNP same EDID)_") while
    models usually start with the brand ("ASUS VA24E"), so only the make's
    first word is kept, and only when neither already contains the other
    (ASUSTek / ASUS).
    """
    make = (output.get("make") or "").split()
    model = (output.get("model") or "").strip()
    if not make or not model:
        return model or " ".join(make[:1])
    brand, first = make[0].lower(), model.split()[0].lower()
    if brand in model.lower() or first in brand:
        return model
    return f"{make[0]} {model}"


def to_surface(img):
    """Wraps a PIL image as a cairo surface for drawing."""
    img = img.convert("RGBA")
    # cairo's ARGB32 is premultiplied BGRA in memory on little-endian machines.
    data = bytearray(img.tobytes("raw", "BGRa"))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32,
                                              img.width, img.height, img.width * 4)


class Target:
    """One monitor: its size, the image and where that image sits on it.

    Positions are in monitor pixels: the image is drawn at (x, y) scaled by
    `zoom`, so the monitor shows the image region starting at (-x/zoom, -y/zoom).
    img_w and img_h are the size after mirroring and rotating.
    """

    def __init__(self, name, width, height, shown, state):
        saved = state.get(name, {})
        resume = saved.get("crop") == shown and os.path.exists(saved.get("source", ""))
        image = saved["source"] if resume else shown
        self.name, self.width, self.height, self.image = name, width, height, image
        self.flip_h = saved.get("flip_h", False) if resume else False
        self.flip_v = saved.get("flip_v", False) if resume else False
        self.rotation = saved.get("rotation", 0) if resume else 0  # degrees clockwise
        with Image.open(image) as img:
            img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
            self.thumb = img.convert("RGBA")
        self.refresh()
        self.recentre()
        if resume:
            self.zoom = self.min_zoom * saved["zoom"]
            self.x, self.y = saved["x"], saved["y"]
            self.clamp()
        # What the monitor shows right now; the dot marks any difference from it.
        self.applied = self.framing()

    def framing(self):
        """The edit as comparable values, rounded so float noise is not a change."""
        return (self.flip_h, self.flip_v, self.rotation,
                round(self.zoom / self.min_zoom, 4), round(self.x, 1), round(self.y, 1))

    @property
    def touched(self):
        return self.framing() != self.applied

    def transform(self, img):
        """Applies the mirror and rotation, in the same order for preview and crop."""
        if self.flip_h:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if self.flip_v:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        # PIL rotates counter-clockwise.
        steps = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
        return img.transpose(steps[self.rotation]) if self.rotation else img

    def refresh(self):
        """Rebuilds the preview and the transformed size after a flip or turn."""
        with Image.open(self.image) as img:
            w, h = img.size
        if self.rotation in (90, 270):
            w, h = h, w
        self.img_w, self.img_h = w, h
        self.preview = to_surface(self.transform(self.thumb))
        self.preview_scale = self.preview.get_width() / self.img_w
        self.min_zoom = max(self.width / w, self.height / h)

    def recentre(self):
        """Covers the monitor, centred: the framing the daemon's crop starts from."""
        self.zoom = self.min_zoom
        self.x = (self.width - self.img_w * self.zoom) / 2
        self.y = (self.height - self.img_h * self.zoom) / 2

    def mirror(self, horizontal):
        """Flips the image in place, so the frame shows the same part mirrored."""
        if horizontal:
            self.flip_h = not self.flip_h
            self.x = self.width - self.img_w * self.zoom - self.x
        else:
            self.flip_v = not self.flip_v
            self.y = self.height - self.img_h * self.zoom - self.y
        self.refresh()

    def rotate(self):
        """Turns 90 degrees clockwise; the proportions change, so it recentres."""
        self.rotation = (self.rotation + 90) % 360
        self.refresh()
        self.recentre()

    def reset(self):
        """Back to the starting framing: centred, no mirror, no rotation."""
        self.flip_h = self.flip_v = False
        self.rotation = 0
        self.refresh()
        self.recentre()

    @property
    def orientation(self):
        return "vertical" if self.height > self.width else "horizontal"

    @property
    def icon(self):
        return "phone-symbolic" if self.height > self.width else "video-display-symbolic"

    def clamp(self):
        """Keeps the image covering the whole monitor, so no bars show."""
        self.zoom = min(max(self.zoom, self.min_zoom), self.min_zoom * MAX_ZOOM)
        self.x = min(0, max(self.x, self.width - self.img_w * self.zoom))
        self.y = min(0, max(self.y, self.height - self.img_h * self.zoom))

    def zoom_at(self, factor, px, py):
        """Zooms keeping the monitor point (px, py) over the same image spot."""
        old = self.zoom
        self.zoom *= factor
        self.clamp()
        k = self.zoom / old
        self.x = px - (px - self.x) * k
        self.y = py - (py - self.y) * k
        self.clamp()

    def render(self):
        """Crops the original image to this framing, at native output size."""
        left, top = -self.x / self.zoom, -self.y / self.zoom
        box = (left, top, left + self.width / self.zoom, top + self.height / self.zoom)
        os.makedirs(OUT_DIR, exist_ok=True)
        # The daemon caches by path, so a reused name would bring back the old crop.
        for old in os.listdir(OUT_DIR):
            if old.startswith(self.name + "-") and old.endswith(".png"):
                os.remove(os.path.join(OUT_DIR, old))
        path = os.path.join(OUT_DIR, f"{self.name}-{int(time.time())}.png")
        with Image.open(self.image) as img:
            self.transform(img.convert("RGB")).resize(
                (self.width, self.height), Image.LANCZOS, box=box).save(path)
        state = load_state()
        state[self.name] = {"crop": path, "source": self.image,
                            "zoom": self.zoom / self.min_zoom, "x": self.x, "y": self.y,
                            "flip_h": self.flip_h, "flip_v": self.flip_v,
                            "rotation": self.rotation}
        with open(STATE, "w") as f:
            json.dump(state, f, indent=2)
        return path


def icon_button(icon, tooltip, callback, toggle=False):
    button = (Gtk.ToggleButton if toggle else Gtk.Button)(
        icon_name=icon, tooltip_text=tooltip, focusable=False)
    button.connect("toggled" if toggle else "clicked", lambda _b: callback())
    return button


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, daemon, targets, start, focused):
        super().__init__(application=app, title="wallframe")
        self.daemon, self.targets, self.index = daemon, targets, start
        self.show_grid = True
        self.syncing = False  # set while code moves the zoom slider

        # Size against the monitor the window opens on; without knowing which,
        # the smallest one, so it fits wherever it lands.
        home = next((t for t in targets if t.name == focused),
                    min(targets, key=lambda t: t.width * t.height))
        self.set_default_size(int(min(1200, home.width * 0.8)),
                              int(min(850, home.height * 0.7)))

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self.draw)

        # Top bar: monitors on the left, tools and Apply on the right.
        # One button per monitor; a dot marks the ones Apply will write. The row
        # scrolls sideways rather than widening the window past a portrait screen.
        self.buttons = []
        picker = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        for i, t in enumerate(targets):
            content = Gtk.Box(spacing=6)
            content.append(Gtk.Image(icon_name=t.icon))
            button_name = Gtk.Label()
            content.append(button_name)
            button = Gtk.ToggleButton(focusable=False, child=content)
            button.name_label = button_name
            if self.buttons:
                button.set_group(self.buttons[0])
            button.connect("toggled", self.on_pick, i)
            button.set_tooltip_text(" · ".join(filter(None, (
                t.model, f"{t.width}x{t.height}", t.orientation))) + "  (Tab)")
            picker.append(button)
            self.buttons.append(button)
        row = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True,
                                 propagate_natural_height=True, child=picker)

        tools = Gtk.Box(spacing=6)
        for icon, tip, action in (
                ("object-flip-horizontal-symbolic", "Mirror (H)", lambda: self.transform("mirror")),
                ("object-flip-vertical-symbolic", "Flip upside down (V)", lambda: self.transform("flip")),
                ("object-rotate-right-symbolic", "Rotate 90° (R)", lambda: self.transform("rotate")),
                ("edit-undo-symbolic", "Reset to the original image, centred (0)", lambda: self.transform("reset"))):
            tools.append(icon_button(icon, tip, action))
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

        # Bottom bar: what is being edited on the left, zoom on the right.
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)  # Pango.EllipsizeMode.END
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

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(top)
        box.append(self.area)
        box.append(bottom)
        self.set_child(box)

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

        self.select(start)

    @property
    def target(self):
        return self.targets[self.index]

    def frame(self):
        """Returns (scale, fx, fy): canvas pixels per monitor pixel, frame origin."""
        t = self.target
        aw, ah = self.area.get_width(), self.area.get_height()
        scale = min((aw - 2 * MARGIN) / t.width, (ah - 2 * MARGIN) / t.height)
        return scale, (aw - t.width * scale) / 2, (ah - t.height * scale) / 2

    def draw(self, _area, cr, aw, ah):
        t = self.target
        scale, fx, fy = self.frame()
        cr.set_source_rgb(0.08, 0.08, 0.08)
        cr.paint()

        # The whole image, at its current position relative to the frame.
        cr.save()
        cr.translate(fx + t.x * scale, fy + t.y * scale)
        s = t.zoom * scale / t.preview_scale
        cr.scale(s, s)
        cr.set_source_surface(t.preview, 0, 0)
        cr.paint()
        cr.restore()

        # Dim everything outside the frame: that part will not be shown.
        fw, fh = t.width * scale, t.height * scale
        cr.set_source_rgba(0, 0, 0, 0.65)
        cr.rectangle(0, 0, aw, ah)
        cr.rectangle(fx, fy, fw, fh)
        cr.set_fill_rule(1)  # even-odd: fill the ring around the frame only
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
        for t, button in zip(self.targets, self.buttons):
            mark = "● " if t.touched else ""
            button.name_label.set_label(f"{mark}{t.name}")
        t = self.target
        pct = round(t.zoom / t.min_zoom * 100)
        self.syncing = True
        self.zoom_scale.set_value(pct)
        self.syncing = False
        self.zoom_label.set_label(f"{pct}%")
        details = [t.model, f"{t.width}x{t.height}", t.orientation,
                   "mirrored" if t.flip_h else "", "flipped" if t.flip_v else "",
                   f"rotated {t.rotation}°" if t.rotation else ""]
        self.label.set_markup(f"<b>{GLib.markup_escape_text(t.name)}</b>   "
                              + GLib.markup_escape_text("  ·  ".join(filter(None, details))))
        self.area.queue_draw()

    def transform(self, action):
        t = self.target
        if action == "mirror":
            t.mirror(horizontal=True)
        elif action == "flip":
            t.mirror(horizontal=False)
        elif action == "rotate":
            t.rotate()
        else:
            t.reset()
        self.refresh()

    def on_grid_button(self):
        self.show_grid = self.grid_button.get_active()
        self.area.queue_draw()

    def on_zoom_scale(self, scale):
        if self.syncing:
            return
        t = self.target
        # Zoom around the frame's centre, as there is no pointer to anchor to.
        t.zoom_at(scale.get_value() / 100 * t.min_zoom / t.zoom, t.width / 2, t.height / 2)
        self.refresh()

    def on_drag_begin(self, _gesture, _x, _y):
        self.drag_origin = (self.target.x, self.target.y)

    def on_drag_update(self, _gesture, dx, dy):
        scale, _, _ = self.frame()
        t = self.target
        t.x = self.drag_origin[0] + dx / scale
        t.y = self.drag_origin[1] + dy / scale
        t.clamp()
        self.refresh()

    def on_scroll(self, _controller, _dx, dy):
        scale, fx, fy = self.frame()
        px, py = (self.pointer[0] - fx) / scale, (self.pointer[1] - fy) / scale
        self.target.zoom_at(ZOOM_STEP ** -dy, px, py)
        self.refresh()
        return True

    def on_key(self, _controller, keyval, _code, _state):
        key = Gdk.keyval_name(Gdk.keyval_to_lower(keyval))
        actions = {"h": "mirror", "v": "flip", "r": "rotate", "0": "reset", "KP_0": "reset"}
        if key == "Escape":
            self.close()
        elif key == "Tab" and len(self.targets) > 1:
            self.select((self.index + 1) % len(self.targets))
        elif key in ("Return", "KP_Enter"):
            self.apply()
        elif key in actions:
            self.transform(actions[key])
        elif key == "g":
            self.grid_button.set_active(not self.grid_button.get_active())
        else:
            return False
        return True

    def apply(self):
        if not any(t.touched for t in self.targets):
            self.flash("Nothing to apply")
            return
        for t in self.targets:
            if not t.touched:
                continue
            subprocess.run([self.daemon, "img", "-o", t.name, "--resize", "no",
                            "--transition-type", "fade", "--transition-duration", "0.4",
                            t.render()])
            t.applied = t.framing()
        self.refresh()
        self.flash("Applied")

    def flash(self, text):
        """Shows a short confirmation in the status bar, then restores it."""
        self.label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        GLib.timeout_add(1500, lambda: self.refresh() or False)


def main():
    daemon, outputs = daemon_outputs()
    if not outputs:
        notify("No image wallpaper found.")
        return 1

    state = load_state()
    targets = []
    for name, width, height, image in outputs:
        try:
            with Image.open(image) as img:
                if getattr(img, "is_animated", False):
                    continue  # a single cropped frame would freeze the animation
            targets.append(Target(name, width, height, image, state))
        except OSError:
            continue  # not an image (video wallpaper)
    if not targets:
        notify("Animated and video wallpapers cannot be adjusted.")
        return 1

    focused, models = compositor_outputs()
    for t in targets:
        t.model = models.get(t.name, "")
    wanted = sys.argv[1] if len(sys.argv) > 1 else focused
    start = next((i for i, t in enumerate(targets) if t.name == wanted), 0)

    app = Gtk.Application(application_id=APP_ID)
    app.connect("activate", lambda a: Window(a, daemon, targets, start, focused).present())
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
