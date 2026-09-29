"""The parts of the window that are pure logic: what a failed Apply reports, what
Copy says it did, and which keys reach the editor at all.

They are called on a stand-in for the window, so this needs GTK but not a
display; it is skipped when GTK is missing, like the rest of the editor.
"""

import os

import pytest

pytest.importorskip("gi")  # only the window needs GTK
from PIL import Image  # noqa: E402

from wallframe.daemons import Daemon, Output  # noqa: E402
from wallframe.monitor import Monitor  # noqa: E402
from wallframe.state import Store  # noqa: E402
from wallframe.window import NUDGE, NUDGE_SHIFT, Window  # noqa: E402
from gi.repository import Gdk  # noqa: E402

NO_DAEMON = "wallframe-no-existe-este-programa"


class UntouchableDaemon:
    """For tests that must fail before reaching the daemon: never the real awww,
    which would change the wallpaper on the machine running the tests."""

    def set_image(self, output, path):
        raise AssertionError(f"the daemon was reached for {output}")


class Widget:
    """Stands in for the buttons and menus these methods touch."""

    def __init__(self, active=False):
        self.active = active

    def get_active(self):
        return self.active

    def set_active(self, active):
        self.active = active

    def popdown(self):
        self.active = False


class StandIn:
    """Enough of a Window for the real methods to run on it, with no display.

    Only the GTK widgets and the status bar are faked. Anything else falls
    through to the real Window, so the code under test is the real code.
    """

    def __init__(self, monitors, daemon=None, index=0):
        self.monitors, self.daemon, self.index = monitors, daemon, index
        self.fill_button = Widget()
        self.help_button = Widget()
        self.copy_button = Widget()
        self.move_backdrop = Widget()
        self.grid_button = Widget()
        self.upscaler = None  # as without Upscayl installed
        self.upscaling = set()
        self.flashed = []
        self.closed = False

    def __getattr__(self, name):
        """The real properties and methods: self.monitor, self.edit, self.moving..."""
        return getattr(Window, name).__get__(self)

    def refresh(self):
        pass

    def flash(self, text, style):
        self.flashed.append((style, text))

    def close(self):
        self.closed = True


def wallpaper(tmp_path, name="wallpaper.png", size=(400, 200)):
    path = tmp_path / name
    Image.new("RGB", size).save(path)
    return str(path)


def monitor_on(tmp_path, name, width, height, image, data="data"):
    return Monitor(Output(name, width, height, image), Store(tmp_path / data))


def key(window, name, state=0):
    """Presses a key on the window; returns what on_key did with it."""
    return Window.on_key(window, None, Gdk.keyval_from_name(name), 0, state)


# --- Apply: what a failure says, and what it leaves behind


def test_a_daemon_that_is_gone_is_not_blamed_on_the_image(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    monitor.edit("rotate")
    window = StandIn([monitor], Daemon(NO_DAEMON))
    Window.apply_touched(window)
    style, text = window.flashed[0]
    assert style == "error"
    assert "could not be started" in text
    assert "image not found" not in text        # the image is right there


def test_a_missing_wallpaper_says_so(tmp_path):
    image = wallpaper(tmp_path)
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, image)
    monitor.edit("rotate")
    os.remove(image)
    window = StandIn([monitor], UntouchableDaemon())
    Window.apply_touched(window)
    assert window.flashed[0][1] == "Could not apply DP-1: image not found"


def test_a_failed_monitor_stays_pending_and_the_others_still_apply(tmp_path):
    image = wallpaper(tmp_path)
    first = monitor_on(tmp_path, "DP-1", 90, 160, image)
    second = monitor_on(tmp_path, "DP-2", 90, 160, image)
    first.edit("rotate")
    second.edit("mirror")

    class OnlyOneWorks:
        def set_image(self, output, path):
            if output == "DP-1":
                raise OSError(None, "awww failed: unknown output: DP-1")

    window = StandIn([first, second], OnlyOneWorks())
    Window.apply_touched(window)
    assert "DP-1" in window.flashed[0][1]
    assert first.touched                      # it did not apply
    assert not second.touched                 # and it did
    assert os.path.exists(second.shown)


# --- Copy: it brings more than the message used to say


def test_copying_from_the_same_shape_says_it_copied_everything(tmp_path):
    image = wallpaper(tmp_path, size=(4000, 2000))
    target = monitor_on(tmp_path, "DP-1", 1080, 1920, image)
    source = monitor_on(tmp_path, "DP-3", 1440, 2560, image)   # same 9:16, bigger
    source.edit("rotate")
    source.framing.flip_h = True
    window = StandIn([target, source], index=0)

    Window.copy_settings(window, source)
    assert window.flashed[0][1] == "Copied everything from DP-3"
    assert "position and fill" not in window.flashed[0][1]
    # And it really did bring the mirror and the rotation, not only the position.
    assert (target.framing.flip_h, target.framing.rotation) == (True, 90)


def test_copying_from_another_image_says_only_the_fill_came(tmp_path):
    target = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path, "a.png"))
    other = monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))
    other.framing.fill, other.framing.fill_color = "color", "#123456"
    target.framing.zoom_at(0.5, 0, 0)      # zoomed out, so the fill is on screen
    window = StandIn([target, other], index=0)

    Window.copy_settings(window, other)
    assert window.flashed[0][1] == "Copied the fill from DP-2 (different image)"
    assert "everything" not in window.flashed[0][1]
    assert (target.framing.fill, target.framing.fill_color) == ("color", "#123456")
    assert not target.framing.rotation                  # it did not bring the image over


def test_the_fill_message_also_says_it_only_shows_when_zoomed_out(tmp_path):
    target = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path, "a.png"))
    other = monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))
    window = StandIn([target, other], index=0)          # the target still covers the monitor

    Window.copy_settings(window, other)
    assert window.flashed[0][1] == "Copied the fill from DP-2; it shows when zoomed out"


# --- Keys: Ctrl and Alt belong to the desktop


def test_control_and_alt_are_left_to_the_desktop(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    for name in ("d", "h", "v", "r", "b", "c", "g", "0", "plus", "minus",
                 "Left", "Right", "Tab", "Return"):
        for mask in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.ALT_MASK):
            assert key(window, name, mask) is False, f"{name} with modifiers got through"
    assert not monitor.touched and not window.closed and not window.flashed


def test_the_same_keys_work_without_modifiers(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    assert key(window, "h") is True
    assert monitor.framing.flip_h                        # the mirror really happened
    assert key(window, "Escape") is True
    assert window.closed


def test_shift_still_takes_bigger_steps(tmp_path):
    plain = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path), "a")
    shifted = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path), "b")
    for monitor, state in ((plain, 0), (shifted, Gdk.ModifierType.SHIFT_MASK)):
        assert key(StandIn([monitor]), "Right", state) is True
    # A right nudge grows x, and Shift grows it by the difference between the steps.
    assert shifted.framing.x - plain.framing.x == NUDGE_SHIFT - NUDGE
