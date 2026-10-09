"""Tests for the Plasma backend: no plasmashell, no D-Bus, no kscreen-doctor runs.

Its scripts are JavaScript for plasmashell; where node is installed they run
for real against a stand-in for Plasma's scripting API, so what is tested is
the script itself and not only the Python that writes it.
"""

import json
import shutil
import subprocess

import pytest

from wallframe import plasma
from wallframe.daemons import Output
from wallframe.plasma import Plasma, kscreen_outputs


def kscreen(*outputs):
    """`kscreen-doctor -j` output with these outputs, in the fields wallframe reads."""
    return json.dumps({"outputs": [dict({"connected": True, "enabled": True, "scale": 1,
                                         "rotation": 1, "currentModeId": "1"}, **o)
                                   for o in outputs]})


def output(name, x, y, width, height, **extra):
    return dict({"name": name, "pos": {"x": x, "y": y},
                 "modes": [{"id": "0", "size": {"width": 640, "height": 480}},
                           {"id": "1", "size": {"width": width, "height": height}}]}, **extra)


# A 4K screen at 200% on the left and a 1080p one turned upright on its right.
DESK = kscreen(output("DP-1", 0, 0, 3840, 2160, scale=2),
               output("HDMI-A-1", 1920, 0, 1920, 1080, rotation=8))


def test_kscreen_gives_logical_places_and_pixel_sizes():
    assert kscreen_outputs(DESK) == {"DP-1": (0, 0, 1920, 1080, 3840, 2160),
                                     "HDMI-A-1": (1920, 0, 1080, 1920, 1080, 1920)}


def test_kscreen_skips_screens_that_are_off_or_unplugged():
    text = kscreen(output("DP-1", 0, 0, 1920, 1080),
                   output("DP-2", 1920, 0, 1920, 1080, enabled=False),
                   output("DP-3", 0, 0, 1920, 1080, connected=False))
    assert list(kscreen_outputs(text)) == ["DP-1"]


def test_kscreen_that_says_nothing_gives_nothing():
    assert kscreen_outputs("") == {} and kscreen_outputs("not json") == {}


def answering(desktops):
    """An evaluate() that answers the query with these desktops, recording each script."""
    def evaluate(script):
        evaluate.scripts.append(script)
        return "set" if "writeConfig" in script else json.dumps(desktops)
    evaluate.scripts = []
    return evaluate


DESKTOPS = [
    {"screen": 1, "x": 1920, "y": 0, "width": 1080, "height": 1920,
     "image": "file:///home/me/My%20Pictures/tall.png"},
    {"screen": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
     "image": "file:///home/me/wide.jpg"},
]


def test_screens_are_named_by_kscreen_and_measured_in_pixels():
    shell = Plasma(answering(DESKTOPS), lambda: kscreen_outputs(DESK))
    assert shell.outputs() == [Output("DP-1", 3840, 2160, "/home/me/wide.jpg"),
                               Output("HDMI-A-1", 1080, 1920, "/home/me/My Pictures/tall.png")]
    assert shell.screens == {"DP-1": 0, "HDMI-A-1": 1}


def test_without_kscreen_the_screens_still_work_by_number():
    shell = Plasma(answering(DESKTOPS[1:]), dict)
    assert shell.outputs() == [Output("Screen-1", 1920, 1080, "/home/me/wide.jpg")]


def test_a_slideshow_or_a_color_is_not_a_picture_to_frame():
    shell = Plasma(answering([dict(DESKTOPS[1], plugin="org.kde.slideshow", image="")]),
                   lambda: kscreen_outputs(DESK))
    assert shell.outputs() == []
    assert shell.screens == {"DP-1": 0}           # but the screen is known, to set one


def package(root, name, *sizes):
    """A wallpaper package under root/wallpapers: one picture at several sizes."""
    images = root / "wallpapers" / name / "contents" / "images"
    images.mkdir(parents=True)
    for size in sizes:
        (images / f"{size}.png").write_bytes(b"")
    return root / "wallpapers" / name


@pytest.fixture
def wallpapers(tmp_path, monkeypatch):
    """A home with the default package, Next, and nothing shared."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "nowhere"))
    package(tmp_path, "Next", "5120x2880", "1440x2960", "7680x2160", "1920x1080")
    return tmp_path


def test_a_fresh_desktop_shows_the_default_package(wallpapers):
    """Plasma names no picture until one is chosen: the theme's default shows."""
    landscape = plasma.picture({"image": ""}, 3840, 2160)
    portrait = plasma.picture({"image": ""}, 1080, 1920)
    next_images = wallpapers / "wallpapers" / "Next" / "contents" / "images"
    assert landscape == str(next_images / "5120x2880.png")   # 16:9, the largest one
    assert portrait == str(next_images / "1440x2960.png")    # the upright one


def test_a_package_can_be_named_by_folder_url_or_name(wallpapers):
    mountain = package(wallpapers, "Mountain", "3840x2160")
    expected = str(mountain / "contents" / "images" / "3840x2160.png")
    for image in ("Mountain", mountain.as_uri() + "/", str(mountain)):
        assert plasma.picture({"image": image}, 1920, 1080) == expected


def test_a_missing_package_is_no_picture(wallpapers):
    assert plasma.picture({"image": "Gone"}, 1920, 1080) == ""


def test_no_plasmashell_reads_as_no_daemon():
    def gone(script):
        raise OSError(None, "Plasma refused it: The name is not activatable")
    assert Plasma(gone, dict).outputs() == []


def test_set_image_sends_the_path_safely():
    """A quote in a file name must not end the JavaScript string."""
    evaluate = answering(DESKTOPS)
    shell = Plasma(evaluate, lambda: kscreen_outputs(DESK))
    shell.set_image("HDMI-A-1", '/tmp/it\'s "mine".png')
    script = evaluate.scripts[-1]
    assert "desktop.screen != 1" in script
    line = next(line for line in script.splitlines() if '"Image"' in line)
    assert line.strip() == 'desktop.writeConfig("Image", "file:///tmp/it%27s%20%22mine%22.png");'


def test_set_image_on_an_unknown_screen_fails_clearly():
    shell = Plasma(answering(DESKTOPS), lambda: kscreen_outputs(DESK))
    with pytest.raises(OSError) as failed:
        shell.set_image("DP-9", "/tmp/crop.png")
    assert failed.value.strerror == "Plasma has no desktop on DP-9"


def test_plasma_gives_positions_for_the_layout_previews(monkeypatch):
    monkeypatch.setattr(plasma, "run", lambda cmd: DESK)
    info = plasma.Desktop().info()
    assert info.positions == {"DP-1": (0, 0, 1920, 1080), "HDMI-A-1": (1920, 0, 1080, 1920)}
    assert info.focused is None


def test_plasma_sets_the_wallpaper_itself(monkeypatch):
    monkeypatch.setattr(plasma.Plasma, "outputs", lambda self: [Output("DP-1", 1, 1, "/a")])
    assert isinstance(plasma.Desktop().wallpaper(), Plasma)
    monkeypatch.setattr(plasma.Plasma, "outputs", lambda self: [])   # no plasmashell
    assert plasma.Desktop().wallpaper() is None


# --- The scripts themselves, run by node against a stand-in for plasmashell

STAND_IN = r"""
const state = JSON.parse(require("fs").readFileSync(0, "utf8"));
const printed = [];
function print(text) { printed.push(String(text)); }
function currentActivity() { return state.activity; }
function screenGeometry(screen) { return state.screens[screen]; }
function desktopsForActivity(id) {
    return state.desktops.filter(d => d.activity === id).map(d => ({
        get screen() { return d.screen; },
        get wallpaperPlugin() { return d.plugin; },
        set wallpaperPlugin(plugin) { d.plugin = plugin; },
        currentConfigGroup: [],
        readConfig(key, fallback) {
            const group = d.config[this.currentConfigGroup.join("/")] || {};
            return key in group ? group[key] : fallback;
        },
        writeConfig(key, value) {
            const name = this.currentConfigGroup.join("/");
            (d.config[name] = d.config[name] || {})[key] = value;
        },
    }));
}
eval(state.script);
console.log(JSON.stringify({printed: printed.join("\n"), desktops: state.desktops}));
"""
GROUP = "Wallpaper/org.kde.image/General"


class StandInPlasma:
    """plasmashell's scripting, played by node: it keeps the desktops between scripts."""

    def __init__(self):
        self.state = {
            "activity": "work",
            "screens": [{"left": 0, "top": 0, "width": 1920, "height": 1080},
                        {"left": 1920, "top": 0, "width": 1080, "height": 1920}],
            "desktops": [
                {"activity": "work", "screen": 0, "plugin": "org.kde.image",
                 "config": {GROUP: {"Image": "file:///home/me/wide.jpg"}}},
                {"activity": "work", "screen": 1, "plugin": "org.kde.slideshow", "config": {}},
                {"activity": "work", "screen": -1, "plugin": "org.kde.image", "config": {}},
                {"activity": "play", "screen": 0, "plugin": "org.kde.image",
                 "config": {GROUP: {"Image": "file:///home/me/game.png"}}},
            ]}

    def __call__(self, script):
        done = subprocess.run(["node", "-e", STAND_IN], text=True, capture_output=True,
                              input=json.dumps(dict(self.state, script=script)), check=True)
        reply = json.loads(done.stdout)
        self.state["desktops"] = reply["desktops"]
        return reply["printed"]


needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node runs the scripts")


@needs_node
def test_the_query_script_reads_each_screen_of_the_current_activity():
    shell = Plasma(StandInPlasma(), lambda: kscreen_outputs(DESK))
    assert shell.outputs() == [Output("DP-1", 3840, 2160, "/home/me/wide.jpg")]
    assert shell.screens == {"DP-1": 0, "HDMI-A-1": 1}  # the slideshow screen is known


@needs_node
def test_the_set_script_turns_a_slideshow_into_the_crop():
    stand_in = StandInPlasma()
    shell = Plasma(stand_in, lambda: kscreen_outputs(DESK))
    shell.set_image("HDMI-A-1", "/home/me/.local/share/wallframe/HDMI-A-1-1.png")
    tall = stand_in.state["desktops"][1]
    assert tall["plugin"] == "org.kde.image"
    assert tall["config"][GROUP] == {
        "Image": "file:///home/me/.local/share/wallframe/HDMI-A-1-1.png", "FillMode": 2}
    play = stand_in.state["desktops"][3]
    assert play["config"][GROUP]["Image"] == "file:///home/me/game.png"  # another activity
    # And reading it back finds the crop, which is how wallframe resumes from it.
    assert Output("HDMI-A-1", 1080, 1920,
                  "/home/me/.local/share/wallframe/HDMI-A-1-1.png") in shell.outputs()
