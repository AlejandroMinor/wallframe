import pytest

from wallframe import commands, config, gallery


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    """Never the user's own config.ini, whose post_command would run in the tests,
    nor their thumbnail cache."""
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config" / "config.ini"))
    monkeypatch.setattr(gallery, "CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def no_message_box(monkeypatch):
    """On Windows, notify() opens a box that waits for a click no one gives."""
    boxes = []
    monkeypatch.setattr(commands, "message_box", boxes.append)
    return boxes


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: shows the window on screen; run with -m ui")


def pytest_collection_modifyitems(config, items):
    """On-screen tests run only when asked for with -m ui."""
    if "ui" in (config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="shows the window on screen; run with -m ui")
    for item in items:
        if "ui" in item.keywords:
            item.add_marker(skip)
