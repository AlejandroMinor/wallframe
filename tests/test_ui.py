"""The window shown on screen and walked through like a person would, one step at a time.

Skipped unless asked for with -m ui, since a window opens on your desktop. Nothing is applied
and nothing of yours is touched. Set WALLFRAME_UI_SHOTS to a folder to keep a picture of the
window after each step.
"""

import os

import pytest

pytest.importorskip("gi")
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from test_real_window import SIZES, Daemon  # noqa: E402
from test_span import two_monitors  # noqa: E402
from wallframe import config, span  # noqa: E402
from wallframe.layouts import Layouts  # noqa: E402
from wallframe.window import Window  # noqa: E402

pytestmark = pytest.mark.ui

if not Gtk.init_check():
    pytest.skip("the window needs a display", allow_module_level=True)

PAUSE = 400     # ms between steps, enough to follow them by eye


def press(window, name, times=1, shift=False):
    state = Gdk.ModifierType.SHIFT_MASK if shift else 0
    for _ in range(times):
        window.on_key(None, Gdk.keyval_from_name(name), 0, state)


def photograph(window, path):
    """Saves the window, as last drawn, to `path` (popovers are separate and left out)."""
    snapshot = Gtk.Snapshot()
    content = window.get_child()
    Gtk.WidgetPaintable.new(content).snapshot(snapshot, content.get_width(), content.get_height())
    node = snapshot.to_node()
    if node:
        window.get_renderer().render_texture(node, None).save_to_png(path)


def walk(tmp_path, steps):
    """Shows the window on the span and runs each (name, step) after a pause; a step that
    raises fails the test."""
    monitors, positions = two_monitors(tmp_path, right=(400, 200))
    across = span.make(monitors, positions, sizes=SIZES)
    shots = os.environ.get("WALLFRAME_UI_SHOTS")
    failure = []

    def activate(app):
        window = Window(app, monitors, Daemon(), 2, "DP-1", None,
                        Layouts(str(tmp_path / "layouts")), positions, across)
        window.present()

        def run(index):
            if shots and index:  # the previous step, drawn during the pause
                photograph(window, os.path.join(shots, f"{index:02}-{steps[index - 1][0]}.png"))
            if index == len(steps) or failure:
                app.quit()
                return False
            name, step = steps[index]
            try:
                step(window)
                window.refresh()
            except Exception as error:  # noqa: BLE001 - handed back to the test
                failure.append(AssertionError(f"step {name!r}: {error!r}"))
            GLib.timeout_add(PAUSE, run, index + 1)
            return False

        GLib.timeout_add(PAUSE, run, 0)

    app = Gtk.Application(application_id="io.github.AlejandroMinor.wallframe.ui",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    app.run([])
    if failure:
        raise failure[0]


def test_arranging_the_desk_with_the_keys(tmp_path):
    def arrange(window):
        press(window, "m")
        assert window.arranging

    def turn(window):
        press(window, "period", 25)
        assert window.span.yaws[window.selected] == 25

    def tilt_and_move(window):
        window.selected = "DP-2"
        before = dict(window.span.places)["DP-2"]
        press(window, "greater", 10)
        press(window, "Right", 12, shift=True)
        assert window.span.pitches["DP-2"] == 10 and window.span.places["DP-2"] != before

    def back_to_the_picture(window):
        window.arrange_button.set_active(False)
        assert not window.arranging

    walk(tmp_path, [("span", lambda window: None), ("arranging", arrange), ("turned", turn),
                    ("tilted-and-moved", tilt_and_move), ("picture", back_to_the_picture)])


def test_every_panel_opens_and_closes(tmp_path):
    def open_menu(button):
        def step(window):
            getattr(window, button).popup()
            assert getattr(window, button).get_popover().get_visible()
        return step

    def close_menu(button):
        return lambda window: getattr(window, button).popdown()

    def side(page):
        """Opens the side panel on `page` with its button, or closes it with Esc."""
        def step(window):
            if page:
                button = window.gallery_button if page == "wallpapers" else window.layouts_button
                button.set_active(True)
                assert window.side_stack.get_visible_child_name() == page
            else:
                press(window, "Escape")
            assert window.side_panel.get_visible() == bool(page)
        return step

    def narrower(window):
        window.split.set_position(window.split.get_width() - 1)  # as narrow as it goes

    def reopened(window):
        narrow = config.panel_width(None)            # kept when the panel closed
        assert narrow < 400                          # one column of pictures fits
        window.split.set_position(window.split.get_width() - 500)
        window.side_placed = False                   # as in a new window: read from the file
        window.gallery_button.set_active(True)
        assert window.split.get_width() - window.split.get_position() == narrow
        press(window, "Escape")

    def desk_tab(window):
        window.side_stack.set_visible_child_name("desk")
        assert window.layouts_button.get_active() and not window.gallery_button.get_active()

    def grid(window):
        before = window.grid_button.get_active()
        press(window, "g")
        assert window.grid_button.get_active() != before

    steps = [("export-menu", open_menu("export_button")), ("closed", close_menu("export_button")),
             ("desk-tools", open_menu("desk_button")), ("closed", close_menu("desk_button")),
             ("layouts", side("layouts")), ("desk-tab", desk_tab),
             ("wallpapers", side("wallpapers")), ("narrower", narrower), ("closed", side(None)),
             ("reopened", reopened),
             ("fill", open_menu("fill_button")), ("closed", close_menu("fill_button")),
             ("help", open_menu("help_button")), ("closed", close_menu("help_button")),
             ("settings", open_menu("settings_button")), ("closed", close_menu("settings_button")),
             ("grid", grid)]
    walk(tmp_path, steps)
