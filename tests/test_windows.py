"""Tests for the Windows backend, on any system: a stand-in answers for Windows (win32.py)."""

import pytest
from PIL import Image

from wallframe import windows
from wallframe.daemons import Output
from wallframe.windows import Desktop, Wallpaper, desktop_places, names, registry_key

GUID = "{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"


@pytest.fixture(autouse=True)
def blanks_stay_out_of_your_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(windows, "DATA_DIR", str(tmp_path / "data"))


def device(code, uid):
    return rf"\\?\DISPLAY#{code}#5&1a2b3c&0&UID{uid}#{GUID}"


DELL, LG, SIDE = device("DEL40F3", 4352), device("GSM5B7F", 4353), device("DEL40F3", 4354)


class FakeWindows:
    """Answers like win32.System for a desk of `screens`, keeping what is set."""

    def __init__(self, screens, pictures=None, edids=None, focused=None, accent=None):
        self._screens, self.pictures = screens, dict(pictures or {})
        self.edids, self._focused, self._accent = edids or {}, focused, accent
        self.set = []

    def screens(self):
        return list(self._screens)

    def focused(self):
        return self._focused

    def edid(self, key):
        return self.edids.get(key, b"")

    def accent(self):
        return self._accent

    def dark(self):
        return True

    def already_open(self):
        return True

    def wallpaper(self, path):
        if path not in self.pictures:
            raise OSError(None, "unknown monitor")
        return self.pictures[path]

    def set_wallpaper(self, path, image):
        self.set.append((path, image))
        self.pictures[path] = image


def edid_of(width_mm, height_mm, name=""):
    data = bytearray(128)
    data[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    data[54:56] = b"\x01\x1d"
    data[66], data[67] = width_mm & 0xFF, height_mm & 0xFF
    data[68] = (width_mm >> 8) << 4 | height_mm >> 8
    if name:
        data[72:77] = b"\x00\x00\x00\xfc\x00"
        data[77:90] = (name.encode() + b"\n").ljust(13, b" ")
    return bytes(data)


def test_monitors_are_named_by_their_model_code_and_told_apart_by_their_order():
    assert names([SIDE, LG, DELL]) == {DELL: "DEL40F3", SIDE: "DEL40F3-2", LG: "GSM5B7F"}


def test_a_device_path_of_another_shape_still_gets_a_name_fit_for_a_file():
    assert names(["odd path"]) == {"odd path": "Monitor"}


def test_the_edid_is_under_the_monitors_instance_in_the_registry():
    assert registry_key(DELL) == (r"SYSTEM\CurrentControlSet\Enum\DISPLAY\DEL40F3"
                                  r"\5&1a2b3c&0&UID4352\Device Parameters")
    assert registry_key("odd path") is None


def test_monitors_with_the_same_scale_keep_their_places():
    screens = [windows.Screen(DELL, (0, 0, 1920, 1080), 1.0),
               windows.Screen(LG, (1920, 0, 1920, 1080), 1.0)]
    assert desktop_places(screens, names([DELL, LG])) == {
        "DEL40F3": (0, 0, 1920, 1080), "GSM5B7F": (1920, 0, 1920, 1080)}


def test_mixed_scales_give_logical_places_that_still_touch():
    """A 4K at 150% beside a 1080p at 100%, lined up by their bottoms. Windows puts the
    1080p at x=3840, in physical pixels; at 1920 logical it would leave a gap."""
    screens = [windows.Screen(DELL, (0, 0, 3840, 2160), 1.5),
               windows.Screen(LG, (3840, 1080, 1920, 1080), 1.0)]
    assert desktop_places(screens, names([DELL, LG])) == {
        "DEL40F3": (0, 0, 2560, 1440), "GSM5B7F": (2560, 360, 1920, 1080)}


def test_a_monitor_left_of_the_main_one_has_negative_places():
    screens = [windows.Screen(DELL, (0, 0, 1920, 1080), 1.0),
               windows.Screen(LG, (-2560, 0, 2560, 1440), 1.25)]
    places = desktop_places(screens, names([DELL, LG]))
    assert places["GSM5B7F"] == (-2048, 0, 2048, 1152)
    assert places["DEL40F3"] == (0, 0, 1920, 1080)  # touching, tops lined up


def test_no_monitors_have_no_places():
    assert desktop_places([], {}) == {}


def test_outputs_are_the_monitors_in_physical_pixels(tmp_path):
    picture = tmp_path / "sea.jpg"
    picture.write_bytes(b"")
    system = FakeWindows([(DELL, (0, 0, 3840, 2160), 1.5)], {DELL: str(picture)})
    assert Wallpaper(system).outputs() == [Output("DEL40F3", 3840, 2160, str(picture))]


def test_a_monitor_with_a_color_or_a_picture_that_is_gone_can_still_be_framed(tmp_path):
    system = FakeWindows([(LG, (0, 0, 1920, 1080), 1.0), (SIDE, (1920, 0, 1080, 1920), 1.0)],
                         {LG: "", SIDE: str(tmp_path / "gone.jpg")})
    first, second = Wallpaper(system).outputs()
    with Image.open(first.image) as picture:
        assert picture.size == (1920, 1080)
    with Image.open(second.image) as picture:
        assert picture.size == (1080, 1920)


def test_a_monitor_the_shell_does_not_know_is_left_out(tmp_path):
    system = FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0)])
    assert Wallpaper(system).outputs() == []


def test_set_image_shows_the_crop_on_that_monitor_only(tmp_path):
    system = FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0), (LG, (1920, 0, 1920, 1080), 1.0)],
                         {DELL: "", LG: ""})
    shell = Wallpaper(system)
    crop = tmp_path / "crop.png"
    shell.set_image("GSM5B7F", str(crop))
    assert system.set == [(LG, str(crop))]


def test_the_desktop_says_what_windows_says_of_the_dark_mode_and_a_running_wallframe():
    desktop = Desktop(FakeWindows([]))
    assert desktop.dark() and desktop.already_open()


def test_set_image_on_a_monitor_that_is_gone_raises():
    shell = Wallpaper(FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0)], {DELL: ""}))
    with pytest.raises(OSError, match="no monitor named HDMI"):
        shell.set_image("HDMI", "/crop.png")


def test_info_names_the_focused_monitor_its_models_and_places():
    system = FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0), (LG, (1920, 0, 1920, 1080), 1.0)],
                         edids={registry_key(DELL): edid_of(527, 296, "DELL P2419H")},
                         focused=LG.upper())  # written another way than the shell does
    info = Desktop(system).info()
    assert info.focused == "GSM5B7F"
    assert info.models == {"DEL40F3": "DELL P2419H", "GSM5B7F": ""}  # "": its EDID has none
    assert info.positions == {"DEL40F3": (0, 0, 1920, 1080), "GSM5B7F": (1920, 0, 1920, 1080)}


def test_sizes_come_from_the_edids_windows_keeps():
    system = FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0), (LG, (1920, 0, 1920, 1080), 1.0)],
                         edids={registry_key(DELL): edid_of(527, 296)})
    assert Desktop(system).sizes() == {"DEL40F3": (527, 296)}


def test_wallframe_opens_without_a_picture_on_any_monitor():
    """A color was enough to stop it at "No image wallpaper found."."""
    system = FakeWindows([(DELL, (0, 0, 1920, 1080), 1.0)], {DELL: ""})
    assert Desktop(system).wallpaper() is not None


def test_there_is_no_wallpaper_to_frame_without_monitors():
    assert Desktop(FakeWindows([])).wallpaper() is None


@pytest.mark.parametrize("value, css", [
    (0xFFD77800, "rgb(0, 120, 215)"),  # Windows' own blue, stored as 0xAABBGGRR
    (None, None),
])
def test_the_accent_is_read_as_abgr(value, css):
    assert Desktop(FakeWindows([], accent=value)).accent() == css


def test_windows_is_only_reachable_on_windows(monkeypatch):
    monkeypatch.setattr(windows.sys, "platform", "linux")
    assert not Desktop(FakeWindows([])).reachable()
    monkeypatch.setattr(windows.sys, "platform", "win32")
    assert Desktop(FakeWindows([])).reachable()
