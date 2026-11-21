import os
import sys

GIGABYTE = 1 << 30
DEFAULT_RESERVE = 2 * GIGABYTE
MINIMUM_BUDGET = GIGABYTE // 2


def _windows_memory_status():
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status


def total_memory_bytes() -> int:
    """Installed physical memory, in bytes."""
    if sys.platform == "win32":
        return int(_windows_memory_status().total_physical)
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def available_memory_bytes() -> int:
    """Physical memory the OS can still hand out right now, in bytes."""
    if sys.platform == "win32":
        return int(_windows_memory_status().available_physical)
    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")


def safe_cache_budget(configured: int, used: int, available: int, reserve: int = DEFAULT_RESERVE,
                      minimum: int = MINIMUM_BUDGET) -> int:
    """Cache size that keeps `reserve` bytes free for the system, capped at the configured size."""
    return max(minimum, min(configured, used + available - reserve))
