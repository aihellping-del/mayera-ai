"""MAYERA - auto updater.

Runs once at startup (from START_MAYERA.bat, before the server). It
checks the update channel (a GitHub repository with only the program's
own code - no keys, no memories) for a newer version:

    version.txt   -> the latest version number
    manifest.txt  -> the list of program files in that version

If a newer version exists, the listed files are downloaded and copied
over the local ones. Hard safety rules:

  * .venv, mayera_memory.db (memories/settings), key.dat (the saved
    API key) and gh_token.dat (the saved GitHub token) are NEVER
    touched, even if a manifest listed them.
  * version.txt is written LAST, only after every file copied fine.
  * Any failure (no internet, server down, ...) prints one short line
    and exits quietly - an update problem must NEVER stop MAYERA
    from starting.
  * Set MAYERA_NO_UPDATE=1 to skip the check entirely.

Public or private repo - both work:

  * Public repo: no token needed, downloads just work.
  * Private repo: the updater sends a read-only GitHub token, taken
    from the MAYERA_GH_TOKEN environment variable, or from
    gh_token.dat next to this file (the token encrypted with Windows
    DPAPI, exactly like key.dat - set it once with GITHUB_TOKEN.bat).
    The token is NEVER part of the update channel itself.
"""

import base64
import ctypes
import hashlib
import os
import sys
import tempfile
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

REPO = "aihellping-del/mayera-ai"
BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
ROOT = Path(__file__).resolve().parent.parent  # core/ -> project root
TIMEOUT = 6  # seconds - never keep the user waiting

NEVER_TOUCH = {"mayera_memory.db", "key.dat", "gh_token.dat"}
NEVER_TOUCH_DIRS = {".venv", "__pycache__"}
_TOKEN_FILE = ROOT / "gh_token.dat"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _unprotect(data: bytes):
    """Windows DPAPI decrypt; None on any other platform/failure."""
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        in_blob = _DataBlob(len(data), ctypes.cast(
            buf, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DataBlob()
        if not crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


def _load_github_token():
    env = (os.environ.get("MAYERA_GH_TOKEN") or "").strip()
    if env:
        return env
    try:
        raw = _TOKEN_FILE.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    plain = _unprotect(blob)
    if plain is None:
        return None
    try:
        token = plain.decode("utf-8").strip()
    except Exception:
        return None
    return token or None


def _fetch(path, token=None):
    headers = {"User-Agent": "MAYERA-Updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(RAW + "/" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _parse_checksums(text):
    """checksums.txt: '<sha256>  <path>' per line -> {path: hash}.
    (v3.31.1: right after a release, GitHub's CDN can serve a MIX
    of new and cached-old files - version.txt fresh, a code file
    stale - which produced a half-updated install. Verifying
    every file's hash makes a mixed download abort instead.)"""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].strip()] = parts[0].lower()
    return out


def _fetch_verified(rel, expected_hash, token=None):
    """Fetch one file; when a checksum is known, retry a few
    times while the served bytes don't match (CDN settling),
    then give up - the caller aborts the whole update and the
    old version keeps running untouched."""
    attempts = 4 if expected_hash else 1
    last_error = None
    for attempt in range(attempts):
        data = _fetch(rel, token)
        if not data:
            raise ValueError(f"empty download: {rel}")
        if not expected_hash:
            return data
        digest = hashlib.sha256(data).hexdigest()
        if digest == expected_hash:
            return data
        last_error = ValueError(f"checksum mismatch: {rel}")
        if attempt + 1 < attempts:
            time.sleep(2)
    raise last_error


def _version_tuple(text):
    try:
        return tuple(int(p) for p in text.strip().split(".") if p != "")
    except Exception:
        return (0,)


def _local_version():
    try:
        return (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def _is_safe(rel_path):
    parts = Path(rel_path).parts
    if any(p in NEVER_TOUCH_DIRS for p in parts):
        return False
    if parts and parts[-1] in NEVER_TOUCH:
        return False
    if ".." in parts or os.path.isabs(rel_path):
        return False
    return True


def main():
    if os.environ.get("MAYERA_NO_UPDATE") == "1":
        return 0
    token = _load_github_token()
    try:
        remote_version = _fetch(
            "version.txt", token).decode("utf-8").strip()
    except Exception:
        print("  (Update check nahi ho paya - JARVIS waise hi chalega.)")
        return 0

    local_version = _local_version()
    if _version_tuple(remote_version) <= _version_tuple(local_version):
        return 0  # already up to date - stay silent

    print(f"  Naya JARVIS update mil gaya: v{remote_version} "
          f"(aapke paas v{local_version} hai). Laga raha hu...")
    try:
        manifest = _fetch("manifest.txt", token).decode("utf-8")
        files = [ln.strip() for ln in manifest.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        try:
            checksums = _parse_checksums(
                _fetch("checksums.txt", token).decode("utf-8"))
        except Exception:
            checksums = {}  # older channel without checksums
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            staged = []
            for rel in files:
                if not _is_safe(rel) or rel == "version.txt":
                    continue
                data = _fetch_verified(rel, checksums.get(rel), token)
                dest = tmp / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                staged.append(rel)
            # every download succeeded -> now copy over, version last
            for rel in staged:
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((tmp / rel).read_bytes())
            (ROOT / "version.txt").write_text(
                remote_version + "\n", encoding="utf-8")
        print(f"  Update ho gaya! JARVIS ab v{remote_version} hai.")
    except Exception:
        print("  (Update beech me ruk gaya - purana JARVIS hi chalega. "
              "Agli baar phir try hogi.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
