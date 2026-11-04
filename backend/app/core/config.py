from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Local runs read the repository-level .env; container runs receive env vars
# from the platform and the missing file is harmless.
load_dotenv(Path.cwd() / ".env")
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


# OpenAI-compatible endpoints with a free tier. A preset supplies the base URL
# and model, and reads its key from <NAME>_API_KEY / <NAME>_TOKEN, so switching
# provider is a single LLM_PROVIDER line.
LLM_PRESETS: dict[str, tuple[str, str]] = {
    "modelscope": ("https://api-inference.modelscope.cn/v1", "Qwen/Qwen3.5-35B-A3B"),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
}


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str


def _provider_key(env: Mapping[str, str], name: str) -> str:
    for suffix in ("API_KEY", "TOKEN"):
        value = env.get(f"{name.upper()}_{suffix}", "").strip()
        if value:
            return value
    return ""


def build_llm_chain(env: Mapping[str, str]) -> tuple[LLMProvider, ...]:
    """Primary provider plus optional fallbacks, resolved from the environment.

    `LLM_PROVIDER` selects a preset; explicit `LLM_BASE_URL` / `LLM_MODEL` still
    override it. `LLM_FALLBACKS` lists presets with their own key, so a
    rate-limited free tier degrades to the next endpoint instead of failing.
    """

    name = env.get("LLM_PROVIDER", "").strip().lower()
    preset = LLM_PRESETS.get(name)
    base_url = env.get("LLM_BASE_URL", "").strip() or (preset[0] if preset else "")
    api_key = env.get("LLM_API_KEY", "").strip()
    if not api_key and preset:
        api_key = _provider_key(env, name)
    model = env.get("LLM_MODEL", "").strip()
    if not model:
        model = preset[1] if preset else "deepseek-chat"

    chain: list[LLMProvider] = []
    seen: set[tuple[str, str]] = set()
    if base_url and api_key:
        chain.append(LLMProvider(name or "custom", base_url, api_key, model))
        seen.add((base_url, model))
    for raw in env.get("LLM_FALLBACKS", "").split(","):
        fallback = raw.strip().lower()
        if fallback not in LLM_PRESETS:
            continue
        fallback_base, fallback_model = LLM_PRESETS[fallback]
        fallback_base = (
            env.get(f"{fallback.upper()}_BASE_URL", "").strip() or fallback_base
        )
        fallback_model = (
            env.get(f"{fallback.upper()}_MODEL", "").strip() or fallback_model
        )
        fallback_key = _provider_key(env, fallback)
        if not fallback_key or (fallback_base, fallback_model) in seen:
            continue
        chain.append(
            LLMProvider(fallback, fallback_base, fallback_key, fallback_model)
        )
        seen.add((fallback_base, fallback_model))
    return tuple(chain)


_LLM_CHAIN = build_llm_chain(os.environ)
_LLM_PRIMARY = _LLM_CHAIN[0] if _LLM_CHAIN else None


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Margin")
    app_env: str = os.getenv("APP_ENV", "development")
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    data_dir: Path = _env_path("DATA_DIR", "./data")
    upload_dir: Path = _env_path("UPLOAD_DIR", "./data/uploads")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "120"))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "2000"))
    parse_concurrency: int = int(os.getenv("PARSE_CONCURRENCY", "2"))
    docling_max_pages: int = int(os.getenv("DOCLING_MAX_PAGES", "60"))
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "80"))

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://margin:margin@localhost:5432/margin"
    )
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "margin_chunks")
    valkey_url: str = os.getenv("VALKEY_URL", "redis://localhost:6379/0")
    grobid_url: str = os.getenv("GROBID_URL", "http://localhost:8070")

    llm_provider: str = _LLM_PRIMARY.name if _LLM_PRIMARY else ""
    llm_base_url: str = _LLM_PRIMARY.base_url if _LLM_PRIMARY else ""
    llm_api_key: str = _LLM_PRIMARY.api_key if _LLM_PRIMARY else ""
    llm_model: str = (
        _LLM_PRIMARY.model if _LLM_PRIMARY else os.getenv("LLM_MODEL", "deepseek-chat")
    )
    llm_chain: tuple[LLMProvider, ...] = _LLM_CHAIN
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    # OpenAI-compatible embedding endpoint used by the optional hybrid-search
    # vector leg; the leg stays off unless EMBEDDING_BASE_URL is set.
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if item.strip()
    )

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_chain)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
