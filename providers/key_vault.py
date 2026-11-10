"""MAYERA - saved API key vault (Windows DPAPI).

The user chose "save it once": the Gemini API key is stored on THIS PC
only, encrypted with Windows DPAPI (CryptProtectData), which ties the
encryption to the user's own Windows account:

  * key.dat holds ONLY the encrypted blob (base64) - never plain text.
  * Only the same Windows user on the same PC can decrypt it.
  * Copying key.dat to another PC/account is useless - it won't open.
  * Deleting key.dat (or running KEY_CHANGE.bat) forgets the key.

On non-Windows systems the vault is unavailable and every function
fails soft (None / False), so MAYERA behaves exactly as before.
"""

import base64
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

_KEY_FILE = Path(__file__).resolve().parent.parent / "key.dat"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def vault_available():
    return sys.platform == "win32"


def has_saved_key():
    return _KEY_FILE.exists()


def _protect(data: bytes):
    if not vault_available():
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        in_blob = _DataBlob(len(data), ctypes.cast(
            buf, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DataBlob()
        if not crypt32.CryptProtectData(
                ctypes.byref(in_blob), "MAYERA", None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


def _unprotect(data: bytes):
    if not vault_available():
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


def save_key(key) -> bool:
    blob = _protect((key or "").strip().encode("utf-8"))
    if blob is None:
        return False
    try:
        _KEY_FILE.write_text(base64.b64encode(blob).decode("ascii"))
        return True
    except OSError:
        return False


def load_key():
    try:
        raw = _KEY_FILE.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return None  # corrupt file -> behave as if no key saved
    plain = _unprotect(blob)
    if plain is None:
        return None  # different user/PC, or tampered
    try:
        key = plain.decode("utf-8").strip()
    except Exception:
        return None
    return key or None


def delete_key() -> bool:
    try:
        _KEY_FILE.unlink()
        return True
    except OSError:
        return False
