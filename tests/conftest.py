import pytest


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
