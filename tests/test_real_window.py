"""The real window, built and driven: what the stand-in used elsewhere cannot show.

test_window.py calls the window's methods on a stand-in that never runs __init__, so a
widget that hides a method, a menu pointing at a missing action or a button that is not
there pass unseen. These tests build the window itself, so they need a display, and are
skipped without one. The file dialog and the clipboard are replaced; nothing of yours is
touched.
"""

import pytest

pytest.importorskip("gi")
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

from test_span import two_monitors  # noqa: E402
from wallframe import span  # noqa: E402
from wallframe.layouts import Layouts  # noqa: E402
from wallframe.window import Window  # noqa: E402

if not Gtk.init_check():
    pytest.skip("the real window needs a display", allow_module_level=True)

SIZES = {"DP-1": (500, 250), "DP-2": (500, 250)}


class Daemon:
    def outputs(self):
        return []

    def set_image(self, *_args):
        pass


class Clipboard:
    def __init__(self):
        self.set = False

    def set_content(self, _provider):
        self.set = True


def in_window(tmp_path, body, with_span=True):
    """Builds the real window (not shown), runs body(window), and gives back what it raised."""
    monitors, positions = two_monitors(tmp_path, right=(400, 200))
    across = span.make(monitors, positions, sizes=SIZES) if with_span else None
    start = 2 if with_span else 0
    failure = []

    def activate(app):
        try:
            window = Window(app, monitors, Daemon(), start, "DP-1", None,
                            Layouts(str(tmp_path / "layouts")), positions, across)
            window.refresh()
            body(window)
        except Exception as error:  # noqa: BLE001 - handed back to the test
            failure.append(error)
        app.quit()

    app = Gtk.Application(application_id="io.github.AlejandroMinor.wallframe.tests",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    app.run([])
    if failure:
        raise failure[0]


def leave_empty_space(window):
    framing = window.monitor.framing
    framing.zoom, framing.x, framing.y = framing.fit_zoom * 0.5, 100, 40
    window.refresh()


def test_the_window_builds_with_and_without_the_span(tmp_path):
    for name, with_span in (("with", True), ("without", False)):
        (tmp_path / name).mkdir()
        in_window(tmp_path / name, lambda window: None, with_span=with_span)


def test_every_export_action_works_and_writes_its_files(tmp_path):
    saved, clipboard = {}, Clipboard()

    def body(window):
        leave_empty_space(window)

        def ask(_title, name, write, done):              # the file dialog, answered at once
            path = str(tmp_path / name)
            write(path)
            saved[name] = done(path)

        window.ask_export = ask
        window.get_clipboard = lambda: clipboard
        window.export_picture()
        window.export_for_ai()
        window.copy_fill_prompt()

    in_window(tmp_path, body)
    assert set(saved) == {"wallframe-span.png", "wallframe-fill-span.png"}
    assert (tmp_path / "wallframe-fill-span-mask.png").exists()
    assert "#00ff00" in saved["wallframe-fill-span.png"] and clipboard.set


def test_nothing_to_fill_is_said_and_nothing_is_written(tmp_path):
    flashed = []

    def body(window):
        window.flash = lambda text, style: flashed.append((style, text))
        window.ask_export = lambda *args: pytest.fail("nothing should be asked")
        window.export_for_ai()                           # the picture covers the monitors
        window.copy_fill_prompt()

    in_window(tmp_path, body)
    assert [style for style, _text in flashed] == ["warning", "warning"]


def test_the_menus_point_at_actions_that_exist(tmp_path):
    def entries(menu):
        return {menu.get_item_link(i, "section").get_item_attribute_value(j, "action").get_string()
                for i in range(menu.get_n_items())
                for j in range(menu.get_item_link(i, "section").get_n_items())}

    def body(window):
        wanted = entries(window.export_button.get_menu_model())
        wanted |= entries(window.desk_button.get_menu_model())
        assert {f"win.{name}" for name in window.list_actions()} == wanted

    in_window(tmp_path, body)


def test_the_desk_tools_are_only_on_the_span_and_work_without_arranging(tmp_path):
    def body(window):
        assert window.spanning and window.desk_button.get_visible()
        assert not window.arranging                       # they do not need the arranging mode
        window.select(0)
        window.refresh()
        assert not window.desk_button.get_visible()       # on a monitor: nothing to calibrate
        window.select(window.views.index(window.span))
        window.refresh()
        assert window.desk_button.get_visible()
        window.calibrate()
        assert window.monitor.image.endswith("calibration.png")

    in_window(tmp_path, body)


def test_a_desk_can_be_saved_from_its_tab(tmp_path):
    def body(window):
        window.arrangement_name.set_text("Desk")
        window.save_arrangement()
        assert [name for name, _entry in window.arrangements.named(["DP-1", "DP-2"])] == ["Desk"]

    in_window(tmp_path, body)


def test_without_a_span_there_are_no_desk_tools(tmp_path):
    def body(window):
        assert not window.desk_button.get_visible()
        window.calibrate()                                # nothing to put it on: no error

    in_window(tmp_path, body, with_span=False)


def test_reset_to_default_puts_the_desk_back(tmp_path):
    def body(window):
        defaults = dict(window.span.default)
        window.span.set_yaw("DP-1", 25)
        window.span.set_pitch("DP-2", 10)
        window.span.move_monitor("DP-2", 300, 40)
        window.reset_desk()
        assert not window.span.yaws and not window.span.pitches
        assert window.span.places == defaults

    in_window(tmp_path, body)

