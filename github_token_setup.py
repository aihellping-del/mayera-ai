"""MAYERA - save the GitHub token for a PRIVATE update repo, once.

Only needed when the update repository (aihellping-del/mayera-ai) is
private. The token is stored next to this file as gh_token.dat,
encrypted with Windows DPAPI - the same protection as the Gemini key
in key.dat: tied to this Windows account, never plain text, useless
on another PC. Run it again to replace the token; delete gh_token.dat
to forget it. The token itself is created by the user on GitHub
(Settings -> Developer settings -> Fine-grained tokens) with
read-only access to just the mayera-ai repository.
"""

import base64
import ctypes
import getpass
import sys
from ctypes import wintypes
from pathlib import Path

_TOKEN_FILE = Path(__file__).resolve().parent / "gh_token.dat"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(data: bytes):
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        in_blob = _DataBlob(len(data), ctypes.cast(
            buf, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DataBlob()
        if not crypt32.CryptProtectData(
                ctypes.byref(in_blob), "MAYERA-GitHub", None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


def main():
    if sys.platform != "win32":
        print("Ye sirf Windows par chalta hai.")
        return 1
    print()
    print(" GitHub token ek baar save karein (private repo ke liye).")
    print(" Token chipa hua rahega - paste karke Enter dabayein.")
    print()
    token = getpass.getpass(" GitHub token: ").strip()
    if not token:
        print(" Khali token - kuch save nahi hua.")
        return 1
    blob = _protect(token.encode("utf-8"))
    if blob is None:
        print(" Token encrypt nahi ho paya - save nahi hua.")
        return 1
    try:
        _TOKEN_FILE.write_text(base64.b64encode(blob).decode("ascii"))
    except OSError:
        print(" File save nahi ho payi.")
        return 1
    print()
    print(" Ho gaya! Token is PC par surakshit save hai.")
    print(" Ab MAYERA private repo se bhi khud update ho jayegi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
