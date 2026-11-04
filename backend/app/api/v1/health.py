from __future__ import annotations

import importlib.util
import socket
import sys
from urllib.parse import urlparse

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import HealthResponse
from app.services.indexing import get_index
from app.services.llm import probe as probe_llm

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    capabilities = {
        "llm": settings.llm_configured,
        "docling": _module_available("docling"),
        "paddleocr": _module_available("paddleocr"),
        "rapidocr": _module_available("rapidocr_onnxruntime"),
        "pypdfium2": _module_available("pypdfium2"),
        "grobid": _port_open(settings.grobid_url),
        "qdrant": _port_open(settings.qdrant_url),
        "langgraph": _module_available("langgraph"),
        "networkx": _module_available("networkx"),
    }
    parsing_ready = any(
        capabilities[name]
        for name in ("docling", "paddleocr", "rapidocr", "pypdfium2")
    )
    ok = parsing_ready and capabilities["networkx"]
    degraded = [name for name, ready in capabilities.items() if not ready]
    llm_provider, llm_latency = probe_llm() if settings.llm_configured else (None, None)
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version="0.1.0",
        capabilities=capabilities,
        degraded=degraded,
        index_chunks=get_index().count(),
        llm_provider=llm_provider,
        llm_latency_ms=llm_latency,
        memory_rss_mb=_rss_mb(),
    )


def _rss_mb() -> float | None:
    """Process RSS in MB; ctypes on Windows, /proc on POSIX, else None."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if not psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            ):
                return None
            return round(counters.WorkingSetSize / 1024 / 1024, 1)
        with open("/proc/self/statm", encoding="utf-8") as handle:
            pages = int(handle.read().split()[1])
        return round(pages * 4096 / 1024 / 1024, 1)
    except Exception:
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _port_open(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.3):
            return True
    except OSError:
        return False
