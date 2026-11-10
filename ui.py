"""JARVIS - UI serving helpers (v3.16 project structure).

The web UI (the Rainbow Flow HUD, Settings drawer, Diagnostics)
lives in the `dashboard/` folder. It is mounted at the SAME web
address as before (/static/...) so saved pages and links keep
working - only the folder on disk changed its name.
"""

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


def open_ui_later(url, delay=1.2):
    """Open the UI in the default browser shortly after startup."""
    threading.Timer(delay, lambda: webbrowser.open(url)).start()
