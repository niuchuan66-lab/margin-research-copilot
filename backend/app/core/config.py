from __future__ import annotations

import os
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


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Margin")
    app_env: str = os.getenv("APP_ENV", "development")
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    data_dir: Path = _env_path("DATA_DIR", "./data")
    upload_dir: Path = _env_path("UPLOAD_DIR", "./data/uploads")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "120"))
    docling_max_pages: int = int(os.getenv("DOCLING_MAX_PAGES", "60"))
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "80"))

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://margin:margin@localhost:5432/margin"
    )
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "margin_chunks")
    valkey_url: str = os.getenv("VALKEY_URL", "redis://localhost:6379/0")
    grobid_url: str = os.getenv("GROBID_URL", "http://localhost:8070")

    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
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
        return bool(self.llm_base_url and self.llm_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
