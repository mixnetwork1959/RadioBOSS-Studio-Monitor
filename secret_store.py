from __future__ import annotations

"""Small Windows DPAPI wrapper used for RadioBOSS credentials.

The public Studio Monitor is a Windows application.  On Windows, passwords are
encrypted for the current Windows account by CryptProtectData.  A reversible
base64 fallback is kept only so developers can run the source on other systems;
the settings dialog clearly reports the active storage mode.
"""

import base64
import ctypes
from ctypes import wintypes
import os


DPAPI_PREFIX = "dpapi:"
PORTABLE_PREFIX = "portable:"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    return blob, buffer


def storage_description() -> str:
    if os.name == "nt":
        return "Protected by Windows for the current user"
    return "Portable development mode (not encrypted)"


def protect_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""

    raw = text.encode("utf-8")
    if os.name != "nt":
        return PORTABLE_PREFIX + base64.b64encode(raw).decode("ascii")

    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "RadioBOSS Studio Monitor",
        None,
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()

    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del in_buffer
    return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if text.startswith(PORTABLE_PREFIX):
        try:
            return base64.b64decode(text[len(PORTABLE_PREFIX):]).decode("utf-8")
        except Exception:
            return ""
    if not text.startswith(DPAPI_PREFIX):
        # Backward compatibility for old, flat Studio Monitor configs.
        return text
    if os.name != "nt":
        return ""

    try:
        encrypted = base64.b64decode(text[len(DPAPI_PREFIX):])
        in_blob, in_buffer = _blob_from_bytes(encrypted)
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)
        ):
            return ""
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(out_blob.pbData)
            del in_buffer
    except Exception:
        return ""
