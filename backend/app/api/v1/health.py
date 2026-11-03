from __future__ import annotations

import importlib.util
import socket
from urllib.parse import urlparse

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import HealthResponse

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
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version="0.1.0",
        capabilities=capabilities,
        degraded=degraded,
    )


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
