"""JARVIS - UI serving + opening helpers (v3.16 project structure).

The web UI (the Rainbow Flow HUD, Settings drawer, Diagnostics)
lives in the `dashboard/` folder. It is mounted at the SAME web
address as before (/static/...) so saved pages and links keep
working - only the folder on disk changed its name.

Opening (v3.18, user's ask): the UI no longer opens as a tab in
his everyday browser. On Windows it launches Chrome in
--app mode (v3.30: Chrome only, per his order) - JARVIS gets its OWN window (no tabs, no address bar,
its own taskbar button), like a small dashboard app. It is still
the same page underneath, so the mic permission and device choices
saved in that browser carry over. MAYERA_NO_APP_UI=1 forces the
old open-in-a-tab behaviour.
"""

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi.staticfiles import StaticFiles

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard"


def mount_dashboard(app):
    """Serve dashboard/ at /static (URL kept for compatibility)."""
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)),
              name="static")
    return app


def _chrome_from_registry():
    """Chrome's real path from the Windows App Paths registry
    (the same place `start chrome` looks) - finds installs
    outside the standard folders (v3.30)."""
    try:
        import winreg
    except ImportError:
        return None
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
    ]
    for hive, subkey in keys:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
            if value and Path(value).is_file():
                return str(value)
        except OSError:
            continue
    return None


def _app_browser():
    """Find Chrome for --app mode: ('chrome', exe) or (None, None).
    CHROME ONLY (v3.30, user's order: 'bas Chrome hi use kare') -
    no Edge fallback; when Chrome is missing the caller falls
    back to a normal browser tab instead."""
    if not sys.platform.startswith("win"):
        return None, None
    found = _chrome_from_registry()
    if found:
        return "chrome", found
    env = os.environ
    paths = [
        Path(env.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in paths:
        try:
            if path.is_file():
                return "chrome", str(path)
        except OSError:
            continue
    found = shutil.which("chrome")
    if found:
        return "chrome", found
    return None, None


def open_ui(url, finder=None, popen=None, browser_open=None):
    """Open the UI; returns 'app:chrome' | 'app:edge' | 'tab'."""
    if os.environ.get("MAYERA_NO_APP_UI") != "1":
        name, exe = (finder or _app_browser)()
        if exe:
            try:
                (popen or subprocess.Popen)(
                    [exe, f"--app={url}", "--window-size=1120,840"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                return f"app:{name}"
            except Exception:  # noqa: BLE001 - fall through to a tab
                pass
    (browser_open or webbrowser.open)(url)
    return "tab"


def open_ui_later(url, delay=1.2):
    """Open the UI shortly after startup (app window by default)."""
    def _open():
        mode = open_ui(url)
        _hud_mode["mode"] = mode
        if mode.startswith("app:"):
            print("  UI apni alag dashboard window me khula hai "
                  "(browser tab nahi bana).", flush=True)
            # v3.36.1: badi window khulte hi minimize - screen
            # par sirf robot dikhe (window band NAHI hoti).
            if auto_minimize_enabled():
                threading.Thread(target=_minimize_hud_at_launch,
                                 daemon=True).start()
    threading.Timer(delay, _open).start()


# ------------------------------------------------------------------
# Robot Dost (v3.36): kone wali chhoti robot window.
#
# Owner ki pasand ka chhota robot (dashboard/robot.html) ek alag
# chhoti Chrome --app window me screen ke neeche-dayein kone me
# rehta hai aur JARVIS ki haalat (bol/sun/soch) par react karta
# hai. Ye sirf ek chehra hai - mic/audio badi HUD ke paas hi
# rehte hain. MAYERA_NO_ROBOT=1 se band. Har nakami sirf log
# hoti hai; robot ki wajah se JARVIS kabhi nahi rukta.
# ------------------------------------------------------------------

ROBOT_W = 280
ROBOT_H = 330
ROBOT_MARGIN = 12
ROBOT_TASKBAR = 48          # Windows taskbar ki jagah chhod kar
ROBOT_TITLE = "JARVIS Robot Dost"


def robot_window_pos(screen_w, screen_h, win_w=ROBOT_W, win_h=ROBOT_H):
    """Bottom-right position (x, y), screen ke andar hi clamped."""
    x = max(0, screen_w - win_w - ROBOT_MARGIN)
    y = max(0, screen_h - win_h - ROBOT_MARGIN - ROBOT_TASKBAR)
    return x, y


def _screen_size():
    """Primary screen ka size (w, h) ya None (fail-soft)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return (int(user32.GetSystemMetrics(0)),
                int(user32.GetSystemMetrics(1)))
    except Exception:  # noqa: BLE001 - size na mile to position skip
        return None


def _find_window_by_title(title_part, exact=None):
    """Title me `title_part` wali pehli dikhai dene wali window
    ka handle ya None. Sirf Windows; har galti par None.
    `exact` diya ho to pehle FindWindowW se poora title match
    try hota hai (robot ke liye); warna sirf EnumWindows wala
    substring match - HUD dhoondhte waqt robot window galti se
    kabhi nahi milti."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        if exact:
            hwnd = user32.FindWindowW(None, exact)
            if hwnd:
                return hwnd
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                            wintypes.LPARAM)
        def _cb(h, _lp):
            try:
                if not user32.IsWindowVisible(h):
                    return True
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                if title_part in buf.value:
                    found.append(h)
                    return False
            except Exception:  # noqa: BLE001
                pass
            return True

        user32.EnumWindows(_cb, 0)
        return found[0] if found else None
    except Exception:  # noqa: BLE001
        return None


def _pin_robot_topmost():
    """Robot window ko always-on-top karne ki koshish (best
    effort, background thread). Window milne tak ~10s retry;
    na mile ya API fail ho to chup-chaap chhod do - robot
    bina topmost ke bhi chalega."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        import time as _time
        user32 = ctypes.windll.user32
        HWND_TOPMOST = -1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        for _ in range(14):
            hwnd = _find_window_by_title("Robot Dost",
                                         exact=ROBOT_TITLE)
            if hwnd:
                ok = user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                if ok:
                    print("  Robot Dost: window sabse upar (topmost) "
                          "set ho gayi.", flush=True)
                return
            _time.sleep(0.7)
    except Exception:  # noqa: BLE001 - topmost na ho to bhi theek
        pass


def open_robot(url, finder=None, popen=None, pin=None):
    """Robot window kholo; returns 'off' | 'skip' | 'app:chrome'.
    Tab kabhi nahi khulta - robot sirf --app window me rehta hai,
    Chrome na mile to robot chup-chaap skip ho jata hai."""
    if os.environ.get("MAYERA_NO_ROBOT") == "1":
        return "off"
    if os.environ.get("MAYERA_NO_APP_UI") == "1":
        return "skip"
    name, exe = (finder or _app_browser)()
    if not exe:
        return "skip"
    args = [exe, f"--app={url}",
            f"--window-size={ROBOT_W},{ROBOT_H}"]
    size = _screen_size()
    if size:
        x, y = robot_window_pos(size[0], size[1])
        args.append(f"--window-position={x},{y}")
    try:
        (popen or subprocess.Popen)(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - robot fail = JARVIS fail nahi
        return "skip"
    if pin is None:
        threading.Thread(target=_pin_robot_topmost,
                         daemon=True).start()
    else:
        pin()
    return f"app:{name}"


def open_robot_later(base_url, delay=2.5):
    """Startup ke thodi der baad robot window (fail-soft)."""
    def _open():
        try:
            mode = open_robot(base_url.rstrip("/") +
                              "/static/robot.html")
            if mode.startswith("app:"):
                print("  Robot Dost kone wali window me aa gaya "
                      "hai.", flush=True)
        except Exception:  # noqa: BLE001
            pass
    threading.Timer(delay, _open).start()


# ------------------------------------------------------------------
# HUD auto-minimize (v3.36.1): badi window screen se HIDE ho,
# band NAHI. Owner ki order: "Badi window hata do - sirf robot
# dikhe". Lekin HUD page hi voice client hai (mic, WebSocket,
# audio, START button sab usi me hai) - use band karna matlab
# JARVIS ki awaaz band aur robot ko status milna band. Isliye
# window khulti hai, phir minimize ho jati hai; page neeche
# chalti rehti hai, robot kone me dikhta rehta hai. Owner
# taskbar se HUD wapas laa kar START dabata hai; call active
# hote hi window ek baar phir minimize ho jati hai (usi call
# me dobara restore kare to phir nahi ladte). MAYERA_NO_
# AUTO_MINIMIZE=1 par purana vyavhaar (window khuli rehti
# hai). Tab mode (MAYERA_NO_APP_UI=1) me minimize bilkul
# nahi - uski apni Chrome window ko haath nahi lagate. Har
# ctypes nakami sirf log hoti hai, startup kabhi nahi rukta.
# ------------------------------------------------------------------

HUD_TITLE_PART = "Voice Companion"   # HUD title: "JARVIS AI — Voice Companion"
ACTIVE_CALL_STATES = frozenset(
    {"connected", "listening", "speaking", "thinking", "muted"})
# "muted" bhi call ke beech ki hi haalat hai (mic band kiya),
# isliye active mani jati hai - warna har mute toggle par
# watcher call khatm samajh kar dobara minimize kar deta.

_hud_mode = {"mode": None}   # open_ui_later asal mode yahan note karta hai


def auto_minimize_enabled(env=None):
    """MAYERA_NO_AUTO_MINIMIZE=1 ya tab mode ho to band."""
    env = os.environ if env is None else env
    return (env.get("MAYERA_NO_AUTO_MINIMIZE") != "1"
            and env.get("MAYERA_NO_APP_UI") != "1")


def _show_window_minimize(hwnd):
    """ShowWindow(SW_MINIMIZE); ho gaya to True (fail-soft)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        SW_MINIMIZE = 6
        return bool(ctypes.windll.user32.ShowWindow(hwnd,
                                                    SW_MINIMIZE))
    except Exception:  # noqa: BLE001
        return False


def minimize_hud_window(finder=None, show=None):
    """HUD window ko dhoondh kar minimize karo; safal to True."""
    hwnd = (finder or _find_window_by_title)(HUD_TITLE_PART)
    if not hwnd:
        return False
    return bool((show or _show_window_minimize)(hwnd))


def _minimize_hud_retries(tries=3, pause=0.4, finder=None,
                          show=None, sleep=None):
    """Chhota retry loop - window milte hi minimize."""
    import time as _time
    sleep = sleep or _time.sleep
    for i in range(tries):
        if minimize_hud_window(finder=finder, show=show):
            return True
        if i + 1 < tries:
            sleep(pause)
    return False


def _minimize_hud_at_launch(finder=None, show=None, sleep=None):
    """Launch ke baad HUD dikhte hi EK baar minimize (~10s
    retry). Background thread se chalta hai; na mile to
    chup-chaap chhod do - JARVIS waise hi chalega."""
    if _minimize_hud_retries(tries=14, pause=0.7, finder=finder,
                             show=show, sleep=sleep):
        print("  Badi window neeche minimize ho gayi hai - "
              "screen par sirf Robot Dost dikhega. START dabane "
              "ke liye taskbar se JARVIS window wapas laayein.",
              flush=True)
        return True
    return False


class HudMinimizeWatcher:
    """Status aaine ko poll karke, call active hone par HUD
    ko us call me EK baar minimize karta hai.

    Niyam: idle/connecting se active (connected/listening/
    speaking/thinking/muted) me jaana = nayi call - ek baar
    minimize. Call ke beech owner window wapas laaye to
    dobara minimize NAHI (us se ladna nahi hai). Call khatm
    (idle/error) par ghadi reset, taaki agli call par phir
    ek baar minimize ho. Idle rehte hue kabhi minimize nahi
    (settings ke liye window khuli reh sakti hai)."""

    def __init__(self, status_getter, minimize, enabled=None):
        self._get = status_getter
        self._minimize = minimize
        self._enabled = enabled or (lambda: True)
        self._in_call = False
        self._minimized_this_call = False

    def step(self):
        """Ek poll; is step me minimize kiya to True."""
        try:
            state = self._get()
        except Exception:  # noqa: BLE001 - status na mile to chup
            return False
        if state in ACTIVE_CALL_STATES:
            if self._in_call:
                return False        # call chal rahi hai, ladna nahi
            self._in_call = True
            if self._minimized_this_call or not self._enabled():
                return False
            self._minimized_this_call = True
            try:
                return bool(self._minimize())
            except Exception:  # noqa: BLE001 - minimize fail = log only
                return False
        # active nahi (idle/connecting/error/...): call khatm
        self._in_call = False
        self._minimized_this_call = False
        return False

    def run(self, interval=0.5, stop=None):
        import time as _time
        while stop is None or not stop.is_set():
            self.step()
            _time.sleep(interval)


def start_hud_minimize_watcher(status_getter, minimize=None,
                               interval=0.5):
    """Call par HUD minimize karne wala background watcher
    shuru karo. Opt-out/tab mode me None (kuch nahi chalta).
    Watcher sirf tab minimize karta hai jab HUD asal me
    --app window me khuli ho (open_ui_later ka note kiya
    mode) - tab mode me uski Chrome window ko haath nahi
    lagta, chahe Chrome dhoondhne me nakami hui ho."""
    if not auto_minimize_enabled():
        return None
    watcher = HudMinimizeWatcher(
        status_getter,
        minimize or (lambda: _minimize_hud_retries(tries=3)),
        enabled=lambda: (_hud_mode["mode"] or "").startswith("app:"))
    threading.Thread(target=watcher.run,
                     kwargs={"interval": interval},
                     daemon=True).start()
    return watcher
