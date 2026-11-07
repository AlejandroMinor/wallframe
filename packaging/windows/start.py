"""What wallframe.exe runs, beside app/. pythonw has no console, so a crash at the start
would leave nothing on the screen: it says so in a box."""

import ctypes
import os
import runpy
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
try:
    runpy.run_module("wallframe", run_name="__main__", alter_sys=True)
except Exception:  # noqa: BLE001 - there is no one else to tell
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), "wallframe could not start",
                                     0x10)
    sys.exit(1)
