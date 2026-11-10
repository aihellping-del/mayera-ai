"""JARVIS - one-time setup (Python version of INSTALL.bat).

Run once after unzipping:

    python setup.py

It creates the .venv virtual environment next to this file and
installs everything from requirements.txt into it. After that,
start JARVIS with START_JARVIS.bat. Safe to run again - an
existing .venv is reused, not recreated.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python():
    if sys.platform.startswith("win"):
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def main():
    print("JARVIS setup chal raha hai...")
    if not venv_python().exists():
        print("  .venv ban raha hai...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)],
                       check=True)
    py = str(venv_python())
    print("  Packages install ho rahe hain (thoda samay lagega)...")
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"],
                   check=False)
    result = subprocess.run(
        [py, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if result.returncode != 0:
        print("  Kuch packages nahi lage - net check karke phir chalao.")
        return 1
    print("  Setup ho gaya! Ab START_JARVIS.bat chalao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
