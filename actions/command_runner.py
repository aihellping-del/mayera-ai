"""Run CMD commands and Python code - WITH PERMISSION (v3.32).

From the user's ULTRA FAST spec §3/§9: 'Execute CMD commands
with permission controls. Write and run Python code.' and
'Never execute arbitrary dangerous commands without
authorization.'

The permission control is structural, not a prompt suggestion:
  * EVERY run goes through the confirmation callback first -
    the on-screen Haan/Nahi card shows the EXACT command or
    code. No callback wired, or a 'no' = nothing executes.
  * A small catastrophic denylist is refused OUTRIGHT, approval
    or not: disk formatting, shutdown/restart, recursive delete
    of system folders, registry Run-key writes, adding user
    accounts, diskpart/bcdedit. (His rulebook: some things are
    not JARVIS's to do at all.)
  * Runs are confined: working directory is his home folder,
    60-second timeout (the process is killed past it), output
    captured and truncated before it reaches the model.
  * Python runs with the SAME interpreter JARVIS itself runs
    on (his .venv), from a temp file that is deleted after.

Synchronous by design (subprocess) - the executor runs it on a
thread, so the voice conversation never blocks on it.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 60
MAX_OUTPUT = 1500

_DENY_PATTERNS = [
    r"\bformat\s+[a-z]:",                       # format C:
    r"\bshutdown\b",                            # shutdown /s ...
    r"\brestart-computer\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\breg\s+(delete|add)\b",                  # registry edits
    r"\bnet\s+user\s+\S+\s+/add",               # new user account
    r"(del|erase)\s+.*[\\/](windows|program files)",
    r"(rd|rmdir)\s+/s",                         # recursive rmdir
    r"remove-item\s+.*(-recurse|windows)",      # PS recursive wipe
    r"rm\s+-rf\s+/",                            # unix-style root wipe
    r"\bmkfs\b",
    r"cipher\s+/w",                             # disk wipe pass
]
_DENY = [re.compile(p, re.IGNORECASE) for p in _DENY_PATTERNS]


def denied_pattern(text):
    """The matched catastrophic pattern, or None."""
    for pattern in _DENY:
        if pattern.search(text or ""):
            return pattern.pattern
    return None


def _default_runner(argv_or_shell, cwd, timeout):
    """Run and return (exit_code, combined_output). Raises
    subprocess.TimeoutExpired past the limit (subprocess.run
    kills the child before raising)."""
    proc = subprocess.run(
        argv_or_shell, shell=isinstance(argv_or_shell, str),
        cwd=str(cwd), timeout=timeout, capture_output=True,
        text=True, errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


class CommandRunner:
    def __init__(self, home=None, runner=None, timeout=TIMEOUT_SECONDS):
        self._home = Path(home) if home else Path.home()
        self._runner = runner or _default_runner
        self._timeout = timeout

    def _gate(self, text, confirm, kind):
        """Denylist -> confirm card -> (ok, early_result)."""
        if not (text or "").strip():
            return False, {"status": "error",
                           "message": f"{kind} khaali hai"}
        hit = denied_pattern(text)
        if hit:
            return False, {
                "status": "error",
                "message": "ye command kabhi nahi chalega - ye PC ko "
                           "nuksaan pahuncha sakta hai (band list me "
                           "hai). Golu ko saaf bata do."}
        approved = False
        if confirm is not None:
            approved = bool(confirm(
                f"Ye {kind} chalaun? Tumhari Haan ke bina nahi "
                f"chalega:\n{text}"))
        if not approved:
            return False, {"status": "cancelled",
                           "message": f"{kind} NAHI chalaya - "
                                      "confirmation nahi mili"}
        return True, None

    def _finish(self, argv_or_shell):
        try:
            code, out = self._runner(argv_or_shell, self._home,
                                     self._timeout)
        except subprocess.TimeoutExpired:
            return {"status": "error",
                    "message": f"command {self._timeout} second me "
                               "pura nahi hua - rok diya gaya"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error",
                    "message": f"command chal nahi paya "
                               f"({exc.__class__.__name__})"}
        return {"status": "done", "exit_code": code,
                "output": (out or "").strip()[-MAX_OUTPUT:],
                "note": "output ka aakhiri hissa hai; exit_code 0 "
                        "matlab command safal raha"}

    def run_command(self, command, confirm=None):
        ok, early = self._gate(command, confirm, "CMD command")
        if not ok:
            return early
        return self._finish((command or "").strip())

    def run_python(self, code, confirm=None):
        ok, early = self._gate(code, confirm, "Python code")
        if not ok:
            return early
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".py", delete=False,
                    encoding="utf-8") as fh:
                fh.write(code)
                tmp = fh.name
            return self._finish([sys.executable, tmp])
        finally:
            if tmp:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass
