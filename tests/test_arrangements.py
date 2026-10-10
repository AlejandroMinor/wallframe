import pytest

from test_span import two_monitors
from wallframe import span
from wallframe.arrangements import Arrangements


def stood(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    return span.make(monitors, positions)


def test_an_arrangement_is_kept_by_name_and_for_these_monitors(tmp_path):
    saved = Arrangements(str(tmp_path / "data"))
    assert saved.load() == {} and saved.named(["DP-1", "DP-2"]) == []
    whole = stood(tmp_path)
    whole.move_monitor("DP-2", 230, 15)
    whole.set_yaw("DP-2", 35)
    saved.save("Desk", whole.arrangement())
    saved.save("Other", {"monitors": ["HDMI-A-1", "DP-1"], "places": {}, "yaws": {}})
    assert [name for name, _entry in saved.named(["DP-2", "DP-1"])] == ["Desk"]
    saved.delete("Desk")
    saved.delete("Nothing")                                  # no error for a missing one
    assert saved.named(["DP-1", "DP-2"]) == []


def test_an_unreadable_file_is_an_empty_list(tmp_path):
    saved = Arrangements(str(tmp_path))
    (tmp_path / "arrangements.json").write_text("not json")
    assert saved.load() == {}
    (tmp_path / "arrangements.json").write_text("[1, 2]")
    assert saved.load() == {}


def test_bringing_one_back_stands_the_monitors_and_keeps_the_picture(tmp_path):
    whole = stood(tmp_path)
    whole.move_monitor("DP-2", 230, 15)
    whole.set_yaw("DP-2", -20)
    entry = whole.arrangement()
    whole.reset_places()                                     # as a moved monitor would leave it
    assert whole.places["DP-2"][:2] != (230, 15) and not whole.yaws
    assert whole.use_arrangement(entry) is True
    assert whole.places["DP-2"][:2] == (230, 15)
    assert whole.yaws == {"DP-2": -20}
    assert whole.touched                                     # waits for Apply
    assert whole.use_arrangement({"monitors": ["X", "Y"], "places": {}}) is False
    assert whole.use_arrangement({"monitors": ["DP-1", "DP-2"]}) is False  # nothing to place


@pytest.mark.parametrize("entry", [None, {}, {"monitors": 3}])
def test_a_broken_entry_is_refused(tmp_path, entry):
    assert stood(tmp_path).use_arrangement(entry) is False
