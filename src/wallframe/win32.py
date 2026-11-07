"""What windows.py asks of Windows itself, through ctypes: no package beyond Python's own.

Only imported on Windows. It does no thinking: windows.py names the monitors,
places them and decides what to show, and is tested with a stand-in for this.

The monitors come from EnumDisplayMonitors, in physical pixels because the
process is per-monitor DPI aware (see aware). Each one's device path, like
\\\\?\\DISPLAY#DEL40F3#5&1a2b3c&0&UID4352#{e6f07b5f-...}, is how the shell's
IDesktopWallpaper knows it, and also where its EDID is in the registry.
"""

import ctypes
import os
import uuid
import winreg
from contextlib import contextmanager
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore")
shell32 = ctypes.WinDLL("shell32")
ole32 = ctypes.WinDLL("ole32")

# The shell's wallpaper object and its interface (shobjidl_core.h).
CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
IID_IDESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
# Its methods, by place in the vtable after IUnknown's three.
_SET_WALLPAPER, _GET_WALLPAPER, _GET_PATH_AT, _GET_PATH_COUNT = 3, 4, 5, 6
_GET_POSITION, _SET_POSITION = 11, 10
_DWPOS_FILL, _DWPOS_SPAN = 4, 5
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2

_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_MDT_EFFECTIVE_DPI = 0
_MONITOR_DEFAULTTONEAREST = 2
_EDD_GET_DEVICE_INTERFACE_NAME = 1
_DISPLAY_DEVICE_ACTIVE = 1
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
# How the taskbar knows wallframe from any other Python, and the installer's shortcuts too.
APP_USER_MODEL_ID = "AlejandroMinor.wallframe"
_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_held = []  # the mutex of the running wallframe, which ends with the process


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
_WINDOWENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC,
                                       wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.EnumWindows.argtypes = [_WINDOWENUMPROC, wintypes.LPARAM]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                    ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
shcore.GetDpiForMonitor.restype = ctypes.HRESULT
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long  # read by hand: S_FALSE also needs CoUninitialize
ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.HRESULT
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


def aware():
    """Asks for physical pixels on every monitor, whatever its scale.

    Without it, Windows hands a scaled-down, blurry desktop to the process and
    sizes in a made-up 96 DPI, and the crops would not match the monitors.
    It must come before any window, so before GTK opens one; it fails harmlessly
    when the awareness is already set (by the manifest, or by GTK itself).
    """
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
    except AttributeError:  # before Windows 10 1703
        pass
    shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def no_session_bus():
    """Tells GLib there is no session bus. Windows has none, so showing a window would
    start gdbus.exe to be one, which nothing here uses, outlives wallframe for a moment,
    and has been seen to leave GTK waiting for good."""
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "disabled:")


def _open_window():
    """wallframe's window, by title and GDK's window class, or None: a folder or a
    browser tab can be called wallframe too."""
    found = []

    def look(handle, _data):
        title, kind = ctypes.create_unicode_buffer(16), ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(handle, title, 16)
        user32.GetClassNameW(handle, kind, 64)
        if title.value == "wallframe" and kind.value.lower().startswith("gdk"):
            found.append(handle)
            return False
        return True

    user32.EnumWindows(_WINDOWENUMPROC(look), 0)
    return found[0] if found else None


def _guid(text):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


@contextmanager
def _desktop_wallpaper():
    """The shell's IDesktopWallpaper, made for this one use on this thread.

    A COM object belongs to the thread that made it, and wallframe asks from
    the main thread and from workers, so each use makes its own.
    """
    initialized = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED) >= 0
    pointer = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(_guid(CLSID_DESKTOP_WALLPAPER), None, _CLSCTX_ALL,
                               _guid(IID_IDESKTOP_WALLPAPER), ctypes.byref(pointer))
        yield pointer
    finally:
        if pointer:
            _call(pointer, 2, ctypes.c_ulong)  # IUnknown::Release
        if initialized:
            ole32.CoUninitialize()


def _call(pointer, index, restype, *args):
    """Calls method `index` of a COM object; `args` are (ctypes type, value) pairs.

    With HRESULT as the result type, ctypes raises OSError on a failure.
    """
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *(kind for kind, _value in args))(
        vtable[index])
    return method(pointer, *(value for _kind, value in args))


class System:
    """Windows as windows.Desktop needs it. Paths are device paths, as above."""

    def screens(self):
        """[(device path, (x, y, width, height) in physical pixels, scale)] for every
        monitor that shows part of the desktop. A mirrored pair is one monitor."""
        handles = []
        callback = _MONITORENUMPROC(lambda handle, _dc, _rect, _data: handles.append(handle)
                                    or True)
        user32.EnumDisplayMonitors(None, None, callback, 0)
        spelled = {path.lower(): path for path in self._shell_paths()}
        found = []
        for handle in handles:
            info = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
            if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                continue
            path = self._device_path(info.szDevice)
            if not path:
                continue
            path = spelled.get(path.lower(), path)  # the shell's own spelling
            rect = info.rcMonitor
            found.append((path, (rect.left, rect.top, rect.right - rect.left,
                                 rect.bottom - rect.top), self._scale(handle)))
        return found

    @staticmethod
    def _shell_paths():
        """The device paths as IDesktopWallpaper writes them; [] when it cannot say."""
        paths = []
        try:
            with _desktop_wallpaper() as shell:
                count = wintypes.UINT()
                _call(shell, _GET_PATH_COUNT, ctypes.HRESULT,
                      (ctypes.POINTER(wintypes.UINT), ctypes.byref(count)))
                for index in range(count.value):
                    text = ctypes.c_void_p()
                    _call(shell, _GET_PATH_AT, ctypes.HRESULT, (wintypes.UINT, index),
                          (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(text)))
                    paths.append(ctypes.wstring_at(text.value))
                    ole32.CoTaskMemFree(text)
        except OSError:
            pass
        return paths

    @staticmethod
    def _device_path(adapter):
        """The device path of the first active monitor on `adapter` (\\\\.\\DISPLAY1)."""
        device = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
        index = 0
        while user32.EnumDisplayDevicesW(adapter, index, ctypes.byref(device),
                                         _EDD_GET_DEVICE_INTERFACE_NAME):
            if device.StateFlags & _DISPLAY_DEVICE_ACTIVE and device.DeviceID:
                return device.DeviceID
            index += 1
        return None

    @staticmethod
    def _scale(handle):
        x, y = wintypes.UINT(), wintypes.UINT()
        try:
            shcore.GetDpiForMonitor(handle, _MDT_EFFECTIVE_DPI, ctypes.byref(x), ctypes.byref(y))
        except OSError:
            return 1.0
        return x.value / 96 or 1.0

    def focused(self):
        """The device path of the monitor under the mouse, where the user just clicked."""
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        handle = user32.MonitorFromPoint(point, _MONITOR_DEFAULTTONEAREST)
        info = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
        if not handle or not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return None
        return self._device_path(info.szDevice)

    @staticmethod
    def edid(key):
        """The EDID kept under the registry `key` (see windows.registry_key), or b""."""
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as opened:
                value, _kind = winreg.QueryValueEx(opened, "EDID")
        except OSError:
            return b""
        return bytes(value)

    @staticmethod
    def already_open():
        """True when wallframe is running already, whose window comes forward. Otherwise
        this process holds the mutex that says so, until it ends."""
        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(None, False, f"Local\\{APP_USER_MODEL_ID}")
        if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
            _held.append(mutex)
            return False
        window = _open_window()
        if window:
            if user32.IsIconic(window):
                user32.ShowWindow(window, _SW_RESTORE)
            user32.SetForegroundWindow(window)
        return True

    @staticmethod
    def dark():
        """True when the user chose the dark mode for apps."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as opened:
                return winreg.QueryValueEx(opened, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False

    @staticmethod
    def accent():
        """Windows' accent color as 0xAABBGGRR, or None when it cannot be read."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\DWM") as opened:
                value, _kind = winreg.QueryValueEx(opened, "AccentColor")
        except OSError:
            return None
        return value

    @staticmethod
    def wallpaper(path):
        """The picture the monitor at `path` shows, or "" for a color or a slideshow
        that names none. Raises OSError when the shell does not know the monitor."""
        with _desktop_wallpaper() as shell:
            text = ctypes.c_void_p()
            _call(shell, _GET_WALLPAPER, ctypes.HRESULT,
                  (wintypes.LPCWSTR, path), (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(text)))
            try:
                return ctypes.wstring_at(text.value) if text.value else ""
            finally:
                ole32.CoTaskMemFree(text)

    @staticmethod
    def set_wallpaper(path, image):
        """Shows `image` on the monitor at `path`. Raises OSError when the shell cannot.

        Span, the one fit that ignores each monitor's own picture, is changed to
        Fill; with a crop of the monitor's exact size, every other fit shows it
        untouched, so the user's choice stays.
        """
        with _desktop_wallpaper() as shell:
            position = ctypes.c_int()
            _call(shell, _GET_POSITION, ctypes.HRESULT,
                  (ctypes.POINTER(ctypes.c_int), ctypes.byref(position)))
            if position.value == _DWPOS_SPAN:
                _call(shell, _SET_POSITION, ctypes.HRESULT, (ctypes.c_int, _DWPOS_FILL))
            _call(shell, _SET_WALLPAPER, ctypes.HRESULT,
                  (wintypes.LPCWSTR, path), (wintypes.LPCWSTR, image))
