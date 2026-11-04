"""OpenAI-compatible chat helper with an ordered provider chain.

The first configured provider is the primary; `LLM_FALLBACKS` appends further
endpoints (typically free tiers). A 429, timeout or outage therefore degrades
to the next provider instead of dropping straight to the extractive fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _payload(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> str | None:
    if not settings.llm_chain:
        return None
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        for provider in settings.llm_chain:
            try:
                response = await client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=_payload(provider.model, messages, temperature, max_tokens),
                )
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                return payload["choices"][0]["message"]["content"]
            except Exception as exc:
                logger.warning(
                    "LLM provider %s (%s) failed: %s",
                    provider.name,
                    provider.model,
                    exc,
                )
    return None


def probe(timeout: float = 4.0) -> tuple[str | None, float | None]:
    """One-token round trip through the chain within a total time budget.

    Returns the provider that answered and its latency in milliseconds; both
    are None when every provider is unreachable.
    """

    if not settings.llm_chain:
        return None, None
    per_attempt = max(1.0, timeout / len(settings.llm_chain))
    with httpx.Client(timeout=per_attempt) as client:
        for provider in settings.llm_chain:
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {provider.api_key}"},
                    json=_payload(
                        provider.model,
                        [{"role": "user", "content": "ping"}],
                        0.0,
                        1,
                    ),
                )
                response.raise_for_status()
                return provider.name, round((time.perf_counter() - started) * 1000, 1)
            except Exception:
                continue
    return None, None
