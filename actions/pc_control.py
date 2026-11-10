"""MAYERA - PC control (v3.1, user-picked "PC Control pack").

MAYERA can operate Golu's own Windows PC by voice:

  * open_app(app)     - open an allowlisted app (Chrome, Notepad, ...)
  * close_app(app)    - close an allowlisted app (never Explorer,
                        never MAYERA/Python itself)
  * set_volume(...)   - volume up / down / mute via media keys
  * type_text(text)   - paste-type dictated text into the window in
                        front (clipboard + Ctrl+V, works for Hindi too)
  * take_screenshot() - save a PNG of the screen to Pictures and open it

Safety by design: only the fixed allowlists below can ever run - the
model cannot invent commands, and there is deliberately NO shutdown /
restart / delete-anything tool (a misheard word must never cost work).
Everything OS-specific is injectable, so the logic is fully testable
off-Windows; on non-Windows every action returns a clean "sirf
Windows par" result instead of failing.
"""

import datetime
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

# alias -> target passed to Windows `start`
OPEN_APPS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "my computer": "explorer",
    "wordpad": "write",
    "task manager": "taskmgr",
    "settings": "ms-settings:",
    "control panel": "control",
    "snipping tool": "snippingtool",
    "camera": "microsoft.windows.camera:",
}

# alias -> process image name for taskkill. Explorer is NOT here on
# purpose (closing it kills the taskbar/desktop), and neither is
# anything MAYERA herself runs on.
CLOSE_APPS = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "wordpad": "write.exe",
    "snipping tool": "SnippingTool.exe",
    "camera": "WindowsCamera.exe",
}

_VOLUME_KEYS = {"mute": 0xAD, "up": 0xAF, "down": 0xAE}

# Keys JARVIS may press by voice (fixed allowlist). The letter keys
# double as YouTube controls: k = play/pause, f = fullscreen,
# m = mute, j/l = seek back/forward.
_PRESS_KEYS = {
    "enter": 0x0D, "space": 0x20, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "backspace": 0x08,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "k": 0x4B, "f": 0x46, "m": 0x4D, "j": 0x4A, "l": 0x4C,
}


def _default_runner(cmd):
    # subprocess.Popen (v3.13, user's spec): launching an app must
    # never block - the window-appear poll in open_app is what waits,
    # so a slow Windows 11 Notepad cannot stall the voice loop.
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _default_volume(action, steps):
    """Press the hardware volume keys (works everywhere on Windows)."""
    import ctypes
    user32 = ctypes.windll.user32
    code = _VOLUME_KEYS[action]
    presses = 1 if action == "mute" else steps
    for _ in range(presses):
        user32.keybd_event(code, 0, 0, 0)
        user32.keybd_event(code, 0, 2, 0)  # KEYEVENTF_KEYUP


def _ctypes_clipboard_get():
    """Current clipboard text via ctypes, or None if not text."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    if not user32.OpenClipboard(0):
        return None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _ctypes_clipboard_set(text):
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    data = text.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(0):
        raise OSError("clipboard busy")
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(13, handle)  # CF_UNICODETEXT
    finally:
        user32.CloseClipboard()


def _ctrl_v():
    import ctypes
    user32 = ctypes.windll.user32
    for vk, flags in ((0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)):
        user32.keybd_event(vk, 0, flags, 0)  # Ctrl down, V down, V up, Ctrl up


def _default_typer(text):
    """Paste-type via the clipboard + Ctrl+V - never simulated
    keystrokes, so Hindi/Hinglish and special characters work
    (pyautogui.write cannot type them).

    v3.13 (user's spec): pyperclip + pyautogui are used when they
    are installed, with the pure-ctypes path as fallback, and the
    user's PREVIOUS clipboard content is preserved and restored
    afterwards - JARVIS must not silently eat what he had copied.
    """
    previous = None
    have_previous = False
    try:
        import pyperclip
        try:
            previous = pyperclip.paste()
            have_previous = isinstance(previous, str)
        except Exception:  # noqa: BLE001 - clipboard may hold non-text
            have_previous = False
        pyperclip.copy(text)
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.hotkey("ctrl", "v")
        except ImportError:
            _ctrl_v()
    except ImportError:
        try:
            previous = _ctypes_clipboard_get()
            have_previous = previous is not None
        except Exception:  # noqa: BLE001
            have_previous = False
        _ctypes_clipboard_set(text)
        _ctrl_v()
    if have_previous:
        time.sleep(0.25)  # let the paste land before restoring
        try:
            import pyperclip
            pyperclip.copy(previous)
        except ImportError:
            try:
                _ctypes_clipboard_set(previous)
            except Exception:  # noqa: BLE001 - restore is best-effort
                pass


def _default_focuser(image, timeout):
    """Wait for a window of the given process image (e.g. 'notepad.exe')
    to exist, bring it to the foreground, and report whether it ended
    up in front. v3.10: open_app used to return the instant the
    launcher fired, so a following type_text pasted into whatever
    window still had focus (usually the browser) and the text was
    lost - his 'Notepad khulta hai, likhta nahi' bug."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    target = (image or "").lower()
    if not target:
        return False
    deadline = time.monotonic() + max(0.2, float(timeout or 0))
    found = [None]
    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)):
                if buf.value.lower().endswith(target):
                    found[0] = hwnd
                    return False
            return True
        finally:
            kernel32.CloseHandle(handle)

    while time.monotonic() <= deadline:
        found[0] = None
        user32.EnumWindows(enum_proc(_cb), 0)
        if found[0]:
            user32.SetForegroundWindow(found[0])
            time.sleep(0.12)
            if user32.GetForegroundWindow() == found[0]:
                return True
            user32.SetForegroundWindow(found[0])
            time.sleep(0.12)
            return user32.GetForegroundWindow() == found[0]
        time.sleep(0.1)
    return False


def _make_fast_capturer():
    """Fast in-memory screen capture via mss + Pillow (v3.22).

    The PowerShell screenshot path costs ~1 s per capture on his
    laptop, and screen vision pays it on EVERY look/click (his log:
    click_on_screen took 7.9 s end to end). mss grabs in tens of
    milliseconds. Both packages are optional (requirements since
    v3.13); if either is missing this returns None and the proven
    PowerShell path is used instead.
    """
    try:
        import mss
        from PIL import Image
    except Exception:  # noqa: BLE001 - optional dependency
        return None

    def _grab():
        import io
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    return _grab


def _default_dialog_dismisser(image):
    """Dismiss ONE stale-session error dialog of the given app, if
    it is showing (v3.17.1). Windows 11 Notepad restores the last
    session's tabs on every open; a tab whose file was moved or
    deleted makes it pop a modal 'The system cannot find the path
    specified.' box - which then sits in front of the editor and
    eats the text JARVIS tries to type (his 2026-11-10 screenshot).

    Deliberately surgical: the window must be a standard dialog
    (class #32770) owned by the app's process AND carry a static
    text containing 'cannot find the path'. Save prompts and every
    other dialog are never touched. Pressing Enter activates the
    dialog's default button (OK). Returns True if one was dismissed.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        target = (image or "").lower()
        if not target:
            return False
        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        hit = [None]

        def _process_matches(hwnd):
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return False
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return False
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = ctypes.c_ulong(260)
                return bool(
                    kernel32.QueryFullProcessImageNameW(
                        handle, 0, buf, ctypes.byref(size))
                    and buf.value.lower().endswith(target))
            finally:
                kernel32.CloseHandle(handle)

        def _has_path_error_text(hwnd):
            found = [False]

            def _child(child, _lp):
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(child, cls, 64)
                if cls.value == "Static":
                    txt = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(child, txt, 512)
                    if "cannot find the path" in txt.value.lower():
                        found[0] = True
                        return False
                return True

            user32.EnumChildWindows(hwnd, enum_proc(_child), 0)
            return found[0]

        def _cb(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value != "#32770":
                return True
            if _process_matches(hwnd) and _has_path_error_text(hwnd):
                hit[0] = hwnd
                return False
            return True

        user32.EnumWindows(enum_proc(_cb), 0)
        if not hit[0]:
            return False
        user32.SetForegroundWindow(hit[0])
        time.sleep(0.05)
        user32.keybd_event(0x0D, 0, 0, 0)      # Enter down (default = OK)
        user32.keybd_event(0x0D, 0, 2, 0)      # Enter up
        time.sleep(0.1)
        return True
    except Exception:  # noqa: BLE001 - best-effort, never fatal
        return False


def _default_title_focuser(title_part, timeout):
    """focus_window's OS layer (v3.13, user's spec): find a window
    whose TITLE contains title_part (e.g. 'Notepad'), restore it if
    minimized, activate it, wait ~0.5s, verify it is in front.
    pygetwindow is tried first (the spec's stack); the ctypes
    EnumWindows path is the fallback when it is not installed."""
    target = (title_part or "").strip().lower()
    if not target:
        return False
    deadline = time.monotonic() + max(0.5, float(timeout or 0))
    try:
        import pygetwindow as gw
        while time.monotonic() <= deadline:
            for win in gw.getAllWindows():
                if target in (win.title or "").lower():
                    try:
                        if win.isMinimized:
                            win.restore()
                        win.activate()
                    except Exception:  # noqa: BLE001 - try next window
                        continue
                    time.sleep(0.5)
                    if win.isActive:
                        return True
            time.sleep(0.3)
        return False
    except ImportError:
        pass
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found = [None]

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if target in buf.value.lower():
            found[0] = hwnd
            return False
        return True

    while time.monotonic() <= deadline:
        found[0] = None
        user32.EnumWindows(enum_proc(_cb), 0)
        if found[0]:
            if user32.IsIconic(found[0]):
                user32.ShowWindow(found[0], 9)  # SW_RESTORE
            user32.SetForegroundWindow(found[0])
            time.sleep(0.5)
            if user32.GetForegroundWindow() == found[0]:
                return True
        time.sleep(0.3)
    return False


def _default_clicker_at(x, y, button, double):
    """Move to absolute (x, y) and click there (v3.13 click tool)."""
    import ctypes
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    _default_clicker(button, double)


def _default_screenshot(path):
    """Capture the primary screen to a PNG via PowerShell/.NET -
    no third-party dependency needed."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
        f"$b.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png)"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   timeout=25, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _default_mover(direction, percent):
    """Move the mouse by a percent of the screen (or to the centre).
    Returns the new (x, y) position."""
    import ctypes

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.windll.user32
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    pt = _Point()
    user32.GetCursorPos(ctypes.byref(pt))
    x, y = pt.x, pt.y
    if direction == "center":
        x, y = width // 2, height // 2
    else:
        if direction == "left":
            x -= int(width * percent / 100)
        elif direction == "right":
            x += int(width * percent / 100)
        elif direction == "up":
            y -= int(height * percent / 100)
        elif direction == "down":
            y += int(height * percent / 100)
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    user32.SetCursorPos(x, y)
    return (x, y)


def _default_clicker(button, double):
    import ctypes
    import time
    user32 = ctypes.windll.user32
    down, up = ((0x0002, 0x0004) if button == "left"
                else (0x0008, 0x0010))

    def _once():
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)

    _once()
    if double:
        time.sleep(0.09)
        _once()


def _default_scroller(direction, amount):
    import ctypes
    delta = 120 * amount * (1 if direction == "up" else -1)
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, delta, 0)  # MOUSEEVENTF_WHEEL


def _default_keyer(key):
    import ctypes
    vk = _PRESS_KEYS[key]
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


class PcController:
    def __init__(self, is_windows=None, runner=None, volumer=None,
                 typer=None, shooter=None, opener=None, home=None,
                 mover=None, clicker=None, scroller=None, keyer=None,
                 focuser=None, sleeper=None, bytes_capturer=None,
                 title_focuser=None, clicker_at=None,
                 dialog_dismisser=None):
        self._win = (sys.platform.startswith("win")
                     if is_windows is None else is_windows)
        self._runner = runner or _default_runner
        self._volumer = volumer or _default_volume
        self._typer = typer or _default_typer
        self._shooter = shooter or _default_screenshot
        self._opener = opener or webbrowser.open
        self._home = Path(home) if home else Path.home()
        self._mover = mover or _default_mover
        self._clicker = clicker or _default_clicker
        self._scroller = scroller or _default_scroller
        self._keyer = keyer or _default_keyer
        self._focuser = focuser or _default_focuser
        self._sleep = sleeper or time.sleep
        self._bytes_capturer = (bytes_capturer
                                if bytes_capturer is not None
                                else _make_fast_capturer())
        self._title_focuser = title_focuser or _default_title_focuser
        self._clicker_at = clicker_at or _default_clicker_at
        self._dialog_dismisser = (dialog_dismisser
                                  or _default_dialog_dismisser)
        self._last_open = None  # (process image, monotonic time)
        # pyautogui FAILSAFE (v3.13, user's spec): slamming the mouse
        # into a screen corner aborts pyautogui actions. Best-effort -
        # pyautogui is optional, the ctypes paths do not need it.
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
        except Exception:  # noqa: BLE001 - optional dependency
            pass

    def _guard(self):
        if not self._win:
            return {"status": "unsupported",
                    "message": "PC control sirf Windows par chalta hai."}
        return None

    @staticmethod
    def _norm(app):
        return " ".join((app or "").strip().lower().split())

    # ------------------------------------------------------------------
    def open_app(self, app):
        blocked = self._guard()
        if blocked:
            return blocked
        target = OPEN_APPS.get(self._norm(app))
        if target is None:
            return {"status": "error",
                    "message": f"'{app}' meri list me nahi hai. List: "
                               + ", ".join(sorted(set(OPEN_APPS)))}
        self._runner(["cmd", "/c", "start", "", target])
        # v3.10: WAIT for the app's window to actually come to the
        # front before reporting success - otherwise a following
        # type_text pastes into the wrong window and the text is lost.
        image = CLOSE_APPS.get(self._norm(app))
        focused = False
        if image:
            # v3.17.1: clear the app's stale-session error dialog
            # first (Windows 11 Notepad restoring a tab whose file
            # is gone pops 'The system cannot find the path
            # specified.' in front of the editor). Keep dismissing
            # while dialogs keep appearing - several stale tabs can
            # queue several boxes - capped at ~3 s; the normal case
            # (no dialog) costs a single quick check.
            self._dismiss_stale_dialogs(image)
            # v3.13: poll up to ~8s (user's spec) - the focuser
            # returns the moment the window is in front, so a fast
            # app costs nothing; a slow Windows 11 Notepad (which
            # can take several seconds on first open) is no longer
            # reported ready before its window even exists.
            focused = bool(self._focuser(image, 8.0))
            if not focused:
                # A late dialog can also be why focus failed.
                self._dismiss_stale_dialogs(image)
                focused = bool(self._focuser(image, 2.0))
            self._last_open = (image, time.monotonic())
        return {"status": "opened", "app": app, "focused": focused}

    def _dismiss_stale_dialogs(self, image):
        """Dismiss queued stale-session dialogs of this app (see
        _default_dialog_dismisser for how narrow the match is)."""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                dismissed = bool(self._dialog_dismisser(image))
            except Exception:  # noqa: BLE001 - best-effort
                return
            if not dismissed:
                return
            time.sleep(0.15)

    def close_app(self, app):
        blocked = self._guard()
        if blocked:
            return blocked
        image = CLOSE_APPS.get(self._norm(app))
        if image is None:
            return {"status": "error",
                    "message": f"'{app}' ko band karna meri list me nahi "
                               "hai (Explorer aur JARVIS khud kabhi band "
                               "nahi hote)."}
        self._runner(["taskkill", "/IM", image, "/F"])
        return {"status": "closed", "app": app}

    def set_volume(self, action, steps=3):
        blocked = self._guard()
        if blocked:
            return blocked
        action = (action or "").strip().lower()
        if action not in _VOLUME_KEYS:
            return {"status": "error",
                    "message": "action 'up', 'down' ya 'mute' hona chahiye"}
        try:
            steps = max(1, min(20, int(steps)))
        except (TypeError, ValueError):
            steps = 3
        self._volumer(action, steps)
        return {"status": "ok", "action": action, "steps": steps}

    def focus_window(self, title_part):
        """Bring the window whose title contains title_part (e.g.
        'Notepad') to the front: restore if minimized, activate,
        verify. Retries a few times (v3.13, user's spec). Returns
        True/False - callers must treat False as 'do not type'."""
        blocked = self._guard()
        if blocked:
            return False
        title_part = (title_part or "").strip()
        if not title_part:
            return False
        for _attempt in range(3):
            try:
                if self._title_focuser(title_part, 2.0):
                    return True
            except Exception:  # noqa: BLE001 - a failed try is a retry
                pass
            self._sleep(0.3)
        return False

    def type_text(self, text, window_title=None):
        blocked = self._guard()
        if blocked:
            return blocked
        text = (text or "").strip()
        if not text:
            return {"status": "error", "message": "khaali text"}
        if len(text) > 2000:
            text = text[:2000]
        # v3.13: when a target window is named (the spec's
        # type_text(text, window_title='Notepad')), focus THAT
        # window by title first - and if it cannot be focused, do
        # NOT paste at all: pasting into the wrong window is exactly
        # the 'Notepad khulta hai, likhta nahi / text gayab' bug.
        if window_title:
            if not self.focus_window(window_title):
                return {"status": "error",
                        "message": f"'{window_title}' window saamne "
                                   "nahi la paya - text nahi likha, "
                                   "galat window me chala jata."}
            self._sleep(0.25)
            self._typer(text)
            return {"status": "typed", "chars": len(text),
                    "focused_window": window_title}
        # v3.10: if an app was opened a moment ago, RE-FOCUS its
        # window first and let focus settle, then paste.
        refocused = False
        if self._last_open:
            image, when = self._last_open
            if time.monotonic() - when <= 25:
                refocused = bool(self._focuser(image, 1.5))
                self._sleep(0.25)
        self._typer(text)
        return {"status": "typed", "chars": len(text),
                "refocused": refocused}

    # ------------------------------------------------------------------
    # Mouse + keys (v3.4): he points with his voice - "mouse upar le
    # jao", "click karo", "neeche scroll karo" - and drives YouTube
    # with k (play/pause), f (fullscreen), j/l (seek).
    # ------------------------------------------------------------------
    def mouse_move(self, direction, percent=20):
        blocked = self._guard()
        if blocked:
            return blocked
        direction = (direction or "").strip().lower()
        if direction not in ("up", "down", "left", "right", "center"):
            return {"status": "error",
                    "message": "direction up/down/left/right/center ho"}
        try:
            percent = max(1, min(90, int(percent)))
        except (TypeError, ValueError):
            percent = 20
        pos = self._mover(direction, percent)
        return {"status": "moved", "direction": direction,
                "percent": percent, "position": list(pos) if pos else None}

    def mouse_click(self, button="left", double=False):
        blocked = self._guard()
        if blocked:
            return blocked
        button = (button or "left").strip().lower()
        if button not in ("left", "right"):
            return {"status": "error", "message": "button left/right ho"}
        self._clicker(button, bool(double))
        return {"status": "clicked", "button": button,
                "double": bool(double)}

    def mouse_scroll(self, direction="down", amount=3):
        blocked = self._guard()
        if blocked:
            return blocked
        direction = (direction or "down").strip().lower()
        if direction not in ("up", "down"):
            return {"status": "error", "message": "direction up/down ho"}
        try:
            amount = max(1, min(20, int(amount)))
        except (TypeError, ValueError):
            amount = 3
        self._scroller(direction, amount)
        return {"status": "scrolled", "direction": direction,
                "amount": amount}

    def click(self, x, y, button="left", double=False):
        """Move to absolute screen point (x, y) and click there
        (v3.13, user's spec names: click(x, y)). Coordinates must
        come from a look_at_screen check first - never blind."""
        blocked = self._guard()
        if blocked:
            return blocked
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return {"status": "error", "message": "x, y number hone chahiye"}
        if x < 0 or y < 0 or x > 10000 or y > 10000:
            return {"status": "error", "message": "x, y screen ke bahar hain"}
        button = (button or "left").strip().lower()
        if button not in ("left", "right"):
            return {"status": "error", "message": "button left/right ho"}
        self._clicker_at(x, y, button, bool(double))
        return {"status": "clicked", "x": x, "y": y,
                "button": button, "double": bool(double)}

    def scroll(self, amount):
        """Scroll by a signed amount (v3.13, user's spec name:
        scroll(amount)): positive = down, negative = up."""
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return {"status": "error", "message": "amount number ho"}
        if amount == 0:
            return {"status": "error", "message": "amount 0 hai"}
        direction = "down" if amount > 0 else "up"
        return self.mouse_scroll(direction, abs(amount))

    def press_key(self, key):
        blocked = self._guard()
        if blocked:
            return blocked
        key = (key or "").strip().lower()
        if key not in _PRESS_KEYS:
            return {"status": "error",
                    "message": "ye key meri list me nahi hai: "
                               + ", ".join(sorted(set(_PRESS_KEYS)))}
        self._keyer(key)
        return {"status": "pressed", "key": key}

    def take_screenshot(self):
        blocked = self._guard()
        if blocked:
            return blocked
        folder = self._home / "Pictures"
        if not folder.is_dir():
            folder = self._home
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"JARVIS-screenshot-{stamp}.png"
        self._shooter(str(path))
        try:
            self._opener(path.as_uri())
        except Exception:  # noqa: BLE001 - opening it is a bonus
            pass
        return {"status": "saved", "path": str(path)}

    def capture_png(self):
        """Capture the screen as PNG BYTES, in memory only (v3.12).

        Unlike take_screenshot this saves nothing to Pictures and
        opens nothing - it exists so JARVIS can LOOK at the screen
        (mayera/screen_vision.py) when Golu asks what is on it, or
        to check a click/type result. The default path reuses the
        PowerShell shooter via a temp file that is deleted at once.
        """
        blocked = self._guard()
        if blocked:
            return blocked
        if self._bytes_capturer is not None:
            try:
                data = self._bytes_capturer()
                if data:
                    return {"status": "ok", "png": data}
            except Exception:  # noqa: BLE001 - fall through to the
                pass             # proven PowerShell path below
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            self._shooter(tmp)
            with open(tmp, "rb") as fh:
                data = fh.read()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return {"status": "ok", "png": data}
