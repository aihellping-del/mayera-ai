"""JARVIS - UI serving + opening helpers (v3.16 project structure).

The web UI (the Rainbow Flow HUD, Settings drawer, Diagnostics)
lives in the `dashboard/` folder. It is mounted at the SAME web
address as before (/static/...) so saved pages and links keep
working - only the folder on disk changed its name.

Opening (v3.18, user's ask): the UI no longer opens as a tab in
his everyday browser. On Windows it launches Chrome or Edge in
--app mode - JARVIS gets its OWN window (no tabs, no address bar,
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


def _app_browser():
    """Find a Chromium browser for --app mode: (name, exe) or
    (None, None). Chrome first, then Edge (every Windows 11 PC has
    Edge, so this almost always succeeds)."""
    if not sys.platform.startswith("win"):
        return None, None
    env = os.environ
    candidates = [
        ("chrome", "chrome", [
            Path(env.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(env.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(env.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]),
        ("edge", "msedge", [
            Path(env.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(env.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]),
    ]
    for name, which_name, paths in candidates:
        for path in paths:
            try:
                if path.is_file():
                    return name, str(path)
            except OSError:
                continue
        found = shutil.which(which_name)
        if found:
            return name, found
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
        if mode.startswith("app:"):
            print("  UI apni alag dashboard window me khula hai "
                  "(browser tab nahi bana).", flush=True)
    threading.Timer(delay, _open).start()
