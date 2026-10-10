"""The parts of the window that are pure logic: what a failed Apply reports, what
Copy says it did, and which keys reach the editor at all.

They are called on a stand-in for the window, so this needs GTK but not a
display; it is skipped when GTK is missing, like the rest of the editor.
"""

import os

import pytest

pytest.importorskip("gi")  # only the window needs GTK
from PIL import Image  # noqa: E402

from wallframe import span, upscalers  # noqa: E402
from wallframe.commands import Cancel  # noqa: E402
from wallframe.daemons import Daemon, Output  # noqa: E402
from wallframe.layouts import Layouts  # noqa: E402
from wallframe.monitor import Monitor  # noqa: E402
from wallframe.state import Store  # noqa: E402
from wallframe.window import NUDGE, NUDGE_SHIFT, Window  # noqa: E402
from gi.repository import Gdk, Gtk  # noqa: E402

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


class Bar:
    """Stands in for the progress bar, which only records what it is told."""
    def __init__(self):
        self.shown, self.text, self.visible = None, None, None

    def set_fraction(self, fraction):
        self.shown = fraction

    def set_text(self, text):
        self.text = text

    def set_visible(self, visible):
        self.visible = visible


class StandIn:
    """Enough of a Window for the real methods to run on it, with no display.

    Only the GTK widgets and the status bar are faked. Anything else falls
    through to the real Window, so the code under test is the real code.
    """

    def __init__(self, monitors, daemon=None, index=0, span=None):
        self.monitors, self.daemon, self.index = monitors, daemon, index
        self.span = span  # None as when the desktop does not say where the monitors are
        self.views = monitors + ([span] if span else [])
        self.fill_button = Widget()
        self.help_button = Widget()
        self.copy_button = Widget()
        self.move_backdrop = Widget()
        self.grid_button = Widget()
        self.layouts_button = Widget()
        self.arrange_button = Widget()
        self.dragged = self.held = None
        self.layouts = (Layouts(os.path.join(monitors[0].store.directory, "layouts"))
                        if monitors else None)
        self.positions = {}
        self.upscaler = None  # as without Upscayl installed
        self.upscaling = {}
        self.flashed, self.reported = [], []
        self.applying = None
        self.busy = []  # every set_busy() call, to see the window paused and resumed
        self.closed = False

    def __getattr__(self, name):
        """The real properties and methods: self.monitor, self.edit, self.moving..."""
        return getattr(Window, name).__get__(self)

    def refresh(self):
        pass

    def select(self, index):
        self.index = index

    def get_focus(self):
        return None

    def in_background(self, work, then):
        """At once: the tests check what happened right after the call."""
        then(work())

    def set_busy(self, what):
        self.applying = what
        self.busy.append(what)

    def fill_layouts(self):
        pass

    def flash(self, text, style):
        self.flashed.append((style, text))

    def report(self, message, detail):
        self.reported.append((message, detail))

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


def test_copying_the_fill_only_leaves_the_picture(tmp_path):
    a, b = wallpaper(tmp_path, "a.png"), wallpaper(tmp_path, "b.png")
    target = monitor_on(tmp_path, "DP-1", 90, 160, a)
    other = monitor_on(tmp_path, "DP-2", 90, 160, b)
    other.framing.fill, other.framing.fill_color = "color", "#123456"
    target.framing.zoom_at(0.5, 0, 0)      # zoomed out, so the fill is on screen
    window = StandIn([target, other], index=0)

    Window.copy_settings(window, other, everything=False)
    assert window.flashed[0][1] == "Copied the fill from DP-2"
    assert (target.framing.fill, target.framing.fill_color) == ("color", "#123456")
    assert target.image == a                            # it did not bring the picture over


def test_copying_everything_brings_another_picture(tmp_path):
    a, b = wallpaper(tmp_path, "a.png"), wallpaper(tmp_path, "b.png")
    target = monitor_on(tmp_path, "DP-1", 90, 160, a)
    other = monitor_on(tmp_path, "HDMI-A-1", 160, 90, b)  # another shape, too
    window = StandIn([target, other], index=0)

    Window.copy_settings(window, other)
    assert target.image == b and target.touched
    assert window.flashed[0][1] == "Copied everything from HDMI-A-1"


def test_the_fill_message_also_says_it_only_shows_when_zoomed_out(tmp_path):
    target = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path, "a.png"))
    other = monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))
    window = StandIn([target, other], index=0)          # the target still covers the monitor

    Window.copy_settings(window, other, everything=False)
    assert window.flashed[0][1] == "Copied the fill from DP-2; it shows when zoomed out"


# --- Upscale: the panel says which picture it is on, and how far along it is


def test_one_picture_running_says_it_keeps_the_window_usable(tmp_path):
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))])
    window.ai_pictures = 1
    assert Window.ai_busy_text(window) == "Runs in the background: you can keep editing."


def test_several_pictures_are_counted(tmp_path):
    """Monitors with different pictures upscale one after another; say which is which."""
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path, "a.png")),
                      monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))])
    window.ai_step, window.ai_pictures = 2, 3
    assert Window.ai_busy_text(window) == "Picture 2 of 3 · you can keep editing"


def test_the_bar_starts_over_and_then_follows_the_percentage(tmp_path):
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))])
    window.ai_progress = Bar()
    Window.ai_step_started(window, 2, 3)
    assert (window.ai_progress.shown, window.ai_progress.text) == (0.0, "2 / 3")
    Window.ai_step_advanced(window, 62.5)
    assert (window.ai_progress.shown, window.ai_progress.text) == (0.625, "62%")


def test_cancel_stops_only_the_upscale_of_these_monitors(tmp_path):
    """Monitors sharing a run stop together; another monitor's run keeps going."""
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path)),
                      monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path)),
                      monitor_on(tmp_path, "DP-3", 90, 160, wallpaper(tmp_path))])
    shared, other = Cancel(), Cancel()
    window.upscaling = {"DP-1": shared, "DP-2": shared, "DP-3": other}
    window.ai_all = Widget(active=False)
    Window.on_ai_run(window)                            # the Upscale button, now Cancel
    assert shared.requested and not other.requested


def test_closing_the_window_stops_every_upscale(tmp_path):
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))])
    first, second = Cancel(), Cancel()
    window.upscaling = {"DP-1": first, "DP-2": second}
    assert Window.cancel_upscales(window, window.upscaling) is False   # still closes
    assert first.requested and second.requested


def test_a_cancelled_upscale_keeps_the_pictures_already_done(tmp_path):
    a = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path, "a.png"))
    b = monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))
    window = StandIn([a, b])
    window.upscaling = {"DP-1": Cancel(), "DP-2": Cancel()}
    done = wallpaper(tmp_path, "a-upscaled.png", size=(800, 400))
    Window.upscaled(window, [a, b], {a.original: done}, {}, 2, cancelled=True)
    assert window.upscaling == {}
    assert a.image == done and b.image == b.original
    assert window.flashed == [("warning", "Upscale cancelled")]


def test_the_upscale_panel_really_builds(tmp_path, monkeypatch):
    """Builds it with the arguments it is really constructed with.

    A bad argument there only shows up as a TypeError inside the activate
    handler, and GTK then keeps running with no window and no clue why.
    """
    monkeypatch.setattr(upscalers, "_MODEL_DIRS", (str(tmp_path / "models"),))
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "upscayl-standard-4x.param").write_text("")

    class Panel:
        monitors, upscaler = [object()], upscalers.Upscaler("upscayl-ncnn",
                                                           str(tmp_path / "models"))

        def __getattr__(self, name):
            """The real methods, so the signals it connects are the real ones."""
            return getattr(Window, name).__get__(self)

    panel = Panel()
    assert Window.build_ai_popover(panel) is not None
    for name in ("ai_model", "ai_scale", "ai_run", "ai_progress", "ai_status"):
        assert getattr(panel, name) is not None, name


# --- Layouts: one click shows a saved set on the monitors and in the editor


class RecordingDaemon:
    def __init__(self):
        self.shown = {}

    def set_image(self, output, path):
        self.shown[output] = path


def test_a_layout_applies_at_once_and_comes_back_as_saved(tmp_path):
    a, b = wallpaper(tmp_path, "a.png"), wallpaper(tmp_path, "b.png")
    left = monitor_on(tmp_path, "DP-1", 90, 160, a)
    right = monitor_on(tmp_path, "DP-2", 160, 90, a)
    daemon = RecordingDaemon()
    window = StandIn([left, right], daemon)
    left.edit("mirror")
    saved = window.layouts.save("Mirrored", window.monitors)
    left.use_image(b)
    left.edit("rotate")
    Window.apply_touched(window)

    Window.activate_layout(window, saved)
    assert left.image == a and left.framing.flip_h and left.framing.rotation == 0
    assert not left.touched                              # applied, not left pending
    assert daemon.shown["DP-1"] == left.shown
    assert "DP-2" not in daemon.shown                    # unchanged, so not rewritten
    assert window.flashed[-1] == ("success", "Switched to Mirrored")


def test_a_layout_with_a_missing_picture_still_applies_the_rest(tmp_path):
    gone = wallpaper(tmp_path, "gone.png")
    left = monitor_on(tmp_path, "DP-1", 90, 160, gone)
    right = monitor_on(tmp_path, "DP-2", 90, 160, wallpaper(tmp_path, "b.png"))
    window = StandIn([left, right], RecordingDaemon())
    right.edit("mirror")
    saved = window.layouts.save("Two", window.monitors)
    os.remove(gone)
    right.edit("mirror")

    Window.activate_layout(window, saved)
    assert right.framing.flip_h and window.daemon.shown.keys() == {"DP-2"}
    assert left.image == gone and not left.touched       # left as it was
    assert window.flashed[-1] == ("error", "Could not load all of Two")
    assert window.reported == [("Could not load all of Two",
                                f"DP-1: image not found\n{gone}\n\n"
                                "The other monitors switched.")]


def test_a_picture_that_is_not_an_image_changes_nothing(tmp_path):
    picture = wallpaper(tmp_path, "a.png")
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, picture)
    window = StandIn([monitor], UntouchableDaemon())
    monitor.edit("mirror")
    saved = window.layouts.save("Broken", [monitor])
    monitor.edit("mirror")
    with open(picture, "w") as f:
        f.write("not an image any more")

    Window.activate_layout(window, saved)
    assert not monitor.framing.flip_h and not monitor.touched
    message, detail = window.reported[0]
    assert detail.startswith("DP-1: ") and picture in detail


def test_a_layout_from_other_monitors_says_so(tmp_path):
    window = StandIn([monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))],
                     UntouchableDaemon())
    other = StandIn([monitor_on(tmp_path, "HDMI-A-1", 90, 160, wallpaper(tmp_path))])
    saved = window.layouts.save("Elsewhere", other.monitors)
    Window.activate_layout(window, saved)
    assert window.flashed[-1] == ("warning", "Elsewhere has none of these monitors")


def test_the_layout_on_the_monitors_is_the_one_marked(tmp_path):
    a, b = wallpaper(tmp_path, "a.png"), wallpaper(tmp_path, "b.png")
    left = monitor_on(tmp_path, "DP-1", 90, 160, a)
    right = monitor_on(tmp_path, "DP-2", 160, 90, a)
    window = StandIn([left, right], RecordingDaemon())
    first = window.layouts.save("First", window.monitors)
    left.open_image(b)
    second = window.layouts.save("Second", window.monitors)
    assert Window.shows_layout(window, first)          # applied is still First
    assert not Window.shows_layout(window, second)     # Second is only in the editor

    Window.activate_layout(window, second)
    assert Window.shows_layout(window, second) and not Window.shows_layout(window, first)
    left.edit("rotate")                                 # an edit not applied yet
    assert Window.shows_layout(window, second)         # the monitors still show it
    Window.apply_touched(window)
    assert not Window.shows_layout(window, second)


def test_the_window_pauses_while_it_applies(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor], RecordingDaemon())
    saved = window.layouts.save("Desk", [monitor])
    monitor.edit("mirror")
    Window.activate_layout(window, saved)
    assert window.busy == ["Desk", None]                # paused, then resumed


def test_keys_do_nothing_while_it_applies(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    window.applying = "Desk"
    for name in ("h", "r", "Return", "Escape"):
        assert key(window, name) is True                # taken, and dropped
    assert not monitor.touched and not window.closed


def test_typing_a_layout_name_does_not_edit_the_image(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    window.get_focus = lambda: Gtk.Entry().get_delegate()
    for name in ("h", "r", "Return", "Tab", "0"):
        assert key(window, name) is False
    assert not monitor.touched


def test_the_layouts_panel_really_builds(tmp_path):
    """With a real layout in it, so the cards and their menus are built too."""
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    window.layouts.save("Desk", [monitor])
    monitor.edit("mirror")
    window.layouts.save("Mirrored", [monitor])
    monitor.edit("mirror")                              # the monitor shows Desk
    assert Window.build_layouts_popover(window) is not None
    Window.fill_layouts(window)                         # the stand-in skips it elsewhere
    cards = [child.get_child().get_child() for child in window.layout_list]
    assert len(cards) == 2 and not window.layout_empty.get_visible()
    assert [card.has_css_class("active-layout") for card in cards] == [True, False]


# --- Open: another picture for a monitor, from the dialog or a dropped file


def test_an_opened_image_waits_for_apply(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor], UntouchableDaemon())
    other = wallpaper(tmp_path, "beach.png")
    Window.open_image(window, monitor, other)
    assert monitor.image == other and monitor.touched
    assert window.flashed == [("accent", "beach.png on DP-1 · frame it, then Apply")]


def test_a_file_that_is_not_an_image_says_so(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    Window.open_image(window, monitor, str(notes))
    assert not monitor.touched
    assert window.flashed == [("error",
                               "Cannot open notes.txt: not an image wallframe can read")]


# --- Keys: Ctrl and Alt belong to the desktop


def test_control_and_alt_are_left_to_the_desktop(tmp_path):
    monitor = monitor_on(tmp_path, "DP-1", 90, 160, wallpaper(tmp_path))
    window = StandIn([monitor])
    for name in ("d", "h", "v", "r", "b", "c", "g", "o", "0", "plus", "minus",
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


# --- The span: one picture across every monitor


def spanning(tmp_path, daemon=None):
    """A window on the span of two monitors side by side, sharing one store."""
    picture = wallpaper(tmp_path, "wide.png", (400, 100))
    left = monitor_on(tmp_path, "DP-1", 200, 100, picture)
    right = monitor_on(tmp_path, "DP-2", 200, 100, picture)
    places = {"DP-1": (0, 0, 200, 100), "DP-2": (200, 0, 200, 100)}
    across = span.make([left, right], places)
    return StandIn([left, right], daemon or RecordingDaemon(), index=2, span=across)


def test_the_span_gives_every_monitor_its_piece(tmp_path):
    window = spanning(tmp_path)
    window.span.edit("mirror")
    assert Window.pending(window) == [window.span]
    Window.apply_touched(window)
    assert window.daemon.shown.keys() == {"DP-1", "DP-2"}
    assert window.span.live and not window.span.touched
    assert window.monitors[0].store.span()["flip_h"]          # remembered for next time
    assert window.flashed[-1] == ("success", "Applied across all monitors")
    Window.apply_touched(window)
    assert window.flashed[-1] == ("warning", "Nothing to apply")


def test_a_span_not_on_the_monitors_can_be_applied_unedited(tmp_path):
    window = spanning(tmp_path)
    assert not window.span.touched and not window.span.live
    assert Window.pending(window) == [window.span]


def test_editing_one_monitor_leaves_the_span(tmp_path):
    window = spanning(tmp_path)
    Window.apply_touched(window)
    window.index = 0
    window.monitors[0].edit("mirror")
    Window.apply_touched(window)
    assert not window.span.live
    window.index = 2
    assert Window.pending(window) == [window.span]          # Apply puts it back


def test_a_layout_saved_from_the_span_brings_it_back(tmp_path):
    window = spanning(tmp_path)
    window.span.framing.zoom_at(1.5, 300, 50)
    saved = window.layouts.save("Wide", window.monitors, window.positions,
                                Window.layout_span(window))
    assert saved.span
    Window.apply_touched(window)
    window.index = 0
    window.monitors[0].edit("mirror")
    Window.apply_touched(window)
    window.span.edit("rotate")                               # an edit the layout drops

    Window.activate_layout(window, saved)
    assert window.monitor is window.span and window.span.live
    assert window.span.framing.rotation == 0 and not window.span.touched
    assert Window.shows_layout(window, saved)


def test_a_layout_without_a_span_leaves_the_span_view(tmp_path):
    window = spanning(tmp_path)
    window.index = 0
    plain = window.layouts.save("Plain", window.monitors)
    assert plain.span is None
    window.index = 2
    window.monitors[0].edit("mirror")
    Window.activate_layout(window, plain)
    assert window.index == 0


def test_tab_reaches_the_span_after_the_monitors(tmp_path):
    window = spanning(tmp_path)
    window.index = 1
    assert key(window, "Tab") is True and window.monitor is window.span
    assert key(window, "Tab") is True and window.index == 0
