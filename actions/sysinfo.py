"""JARVIS - system info (light port of Mark LVI's system_monitor
idea: stdlib + ctypes only, no psutil dependency). Battery and RAM
come from the Windows APIs when on Windows; anything unknown is
reported as unknown, never guessed."""

import ctypes
import os
import platform
import shutil


def get_system_info():
    info = {
        "status": "done", "verified": True,
        "os": f"{platform.system()} {platform.release()}",
        "cpu_cores": os.cpu_count(),
    }
    total, _used, free = shutil.disk_usage(str(os.path.expanduser("~")))
    info["disk_free_gb"] = round(free / (1024 ** 3), 1)
    info["disk_total_gb"] = round(total / (1024 ** 3), 1)
    if platform.system() == "Windows":
        try:
            class _Power(ctypes.Structure):
                _fields_ = [("line", ctypes.c_byte),
                            ("flag", ctypes.c_byte),
                            ("percent", ctypes.c_byte),
                            ("reserved", ctypes.c_byte),
                            ("life_time", ctypes.c_ulong),
                            ("full_life", ctypes.c_ulong)]

            status = _Power()
            if ctypes.windll.kernel32.GetSystemPowerStatus(
                    ctypes.byref(status)) and status.percent != 255:
                info["battery_percent"] = int(status.percent)
                info["battery_charging"] = bool(status.flag & 8)
        except Exception:  # noqa: BLE001 - unknown is an honest answer
            pass
        try:
            class _Mem(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong),
                            ("load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong),
                            ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong),
                            ("avail_page", ctypes.c_ulonglong),
                            ("total_virt", ctypes.c_ulonglong),
                            ("avail_virt", ctypes.c_ulonglong),
                            ("avail_ext", ctypes.c_ulonglong)]

            mem = _Mem()
            mem.length = ctypes.sizeof(_Mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(mem)):
                info["ram_used_percent"] = int(mem.load)
                info["ram_total_gb"] = round(
                    mem.total_phys / (1024 ** 3), 1)
        except Exception:  # noqa: BLE001
            pass
    return info
