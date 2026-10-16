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
        except BaseException as error:  # noqa: BLE001 - handed back, pytest.fail included
            failure.append(error)
        app.quit()

    app = Gtk.Application(application_id="io.github.AlejandroMinor.wallframe.tests",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    app.run([])
    if failure:
        raise failure[0]


def leave_empty_space(window):
    """Zooms the picture out to half its fitting size, off center: most of it is empty."""
    framing = window.monitor.framing
    framing.zoom, framing.x, framing.y = framing.fit_zoom * 0.5, 100, 40
    window.refresh()


def test_the_window_builds_with_and_without_the_span(tmp_path):
    for name, with_span in (("with", True), ("without", False)):
        (tmp_path / name).mkdir()
        in_window(tmp_path / name, lambda window: None, with_span=with_span)


def test_every_export_action_works_and_writes_its_files(tmp_path):
    saved, clipboard, asked = {}, Clipboard(), []

    def body(window):
        leave_empty_space(window)

        def ask(_title, name, write, done):              # the file dialog, answered at once
            path = str(tmp_path / name)
            write(path)
            saved[name] = done(path)

        window.ask_export = ask
        window.confirm = lambda message, detail, go, then: (asked.append(message), then())
        window.get_clipboard = lambda: clipboard
        window.export_picture()
        window.export_for_ai()
        window.copy_fill_prompt()

    in_window(tmp_path, body)
    names = sorted(saved)
    assert len(names) == 2 and names[0].startswith("wallframe-export-fill-span-")
    assert names[1].startswith("wallframe-export-span-")   # each ends with its date and time
    assert (tmp_path / (names[0][:-4] + "-mask.png")).exists()
    assert asked == ["The empty space is blurred"]       # the fill is blur: it said so first
    assert "area" in saved[names[0]] and clipboard.set


def test_a_blurred_fill_asks_first_and_cancelling_exports_nothing(tmp_path):
    asked = []

    def body(window):
        leave_empty_space(window)
        window.ask_export = lambda *args: pytest.fail("cancelled: nothing should be exported")
        window.confirm = lambda message, detail, go, then: asked.append((message, detail, go))
        window.export_for_ai()                           # confirm never calls then(): cancel

    in_window(tmp_path, body)
    message, detail, go = asked[0]
    assert message == "The empty space is blurred" and go == "Continue"
    assert "least present in your picture" in detail and "% of the picture is empty" in detail


def test_mostly_empty_space_warns_with_how_much(tmp_path):
    asked, flashed = [], []

    def body(window):
        leave_empty_space(window)
        window.monitor.framing.fill = "color"
        window.monitor.framing.fill_color = "#ff00ff"
        window.confirm = lambda message, detail, go, then: (asked.append(message), then())
        window.ask_export = lambda title, name, write, done: flashed.append(done(name))
        window.export_for_ai()

    in_window(tmp_path, body)
    assert len(asked) == 1 and asked[0].endswith("% of the picture is empty space")
    assert int(asked[0].split("%")[0]) > 50
    assert "%)" in flashed[0]                            # the saved notice says it too


def test_a_fill_color_that_is_not_in_the_picture_exports_without_asking(tmp_path):
    exported = []

    def body(window):
        framing = window.monitor.framing                 # a thin empty border: no notice
        framing.zoom = framing.min_zoom * 0.9
        framing.center()
        window.monitor.framing.fill = "color"
        window.monitor.framing.fill_color = "#ff00ff"    # the test picture has no magenta
        window.confirm = lambda *args: pytest.fail("nothing to warn about")
        window.ask_export = lambda title, name, write, done: exported.append(name)
        window.export_for_ai()

    in_window(tmp_path, body)
    assert len(exported) == 1 and exported[0].startswith("wallframe-export-fill-span-")


def test_a_fill_color_like_the_picture_warns(tmp_path):
    asked = []

    def body(window):
        leave_empty_space(window)
        window.monitor.framing.fill = "color"
        window.monitor.framing.fill_color = "#000080"    # the test picture has this navy
        window.confirm = lambda message, detail, go, then: asked.append(message)
        window.export_for_ai()

    in_window(tmp_path, body)
    assert asked == ["The fill color is close to colors in your picture"]


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

