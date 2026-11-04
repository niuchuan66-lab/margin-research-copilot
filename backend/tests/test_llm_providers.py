"""Provider chain resolution and failover, without network or real keys."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import LLM_PRESETS, LLMProvider, build_llm_chain
from app.services import llm


def test_preset_uses_its_own_key() -> None:
    chain = build_llm_chain(
        {"LLM_PROVIDER": "modelscope", "MODELSCOPE_API_KEY": "ms-test"}
    )

    assert len(chain) == 1
    provider = chain[0]
    assert provider.name == "modelscope"
    assert provider.base_url == LLM_PRESETS["modelscope"][0]
    assert provider.model == LLM_PRESETS["modelscope"][1]
    assert provider.api_key == "ms-test"


def test_explicit_base_and_model_override_preset() -> None:
    chain = build_llm_chain(
        {
            "LLM_PROVIDER": "zhipu",
            "ZHIPU_API_KEY": "z-test",
            "LLM_BASE_URL": "https://gateway.example/v1",
            "LLM_MODEL": "custom-model",
        }
    )

    assert chain[0].base_url == "https://gateway.example/v1"
    assert chain[0].model == "custom-model"


def test_generic_key_works_without_provider() -> None:
    chain = build_llm_chain(
        {"LLM_BASE_URL": "https://api.example/v1", "LLM_API_KEY": "k"}
    )

    assert chain[0].name == "custom"
    assert chain[0].model == "deepseek-chat"


def test_fallbacks_need_their_own_key_and_keep_order() -> None:
    chain = build_llm_chain(
        {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "d",
            "LLM_FALLBACKS": "zhipu, modelscope, unknown",
            "ZHIPU_API_KEY": "z",
        }
    )

    assert [provider.name for provider in chain] == ["deepseek", "zhipu"]


def test_missing_keys_mean_unconfigured() -> None:
    assert build_llm_chain({}) == ()
    assert build_llm_chain({"LLM_PROVIDER": "modelscope"}) == ()


class _Response:
    def __init__(self, content: str = "ok") -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


def _fake_settings(providers: tuple[LLMProvider, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        llm_chain=providers,
        llm_timeout=5.0,
        llm_configured=bool(providers),
    )


@pytest.mark.asyncio
async def test_chat_falls_back_to_next_provider(monkeypatch) -> None:
    providers = (
        LLMProvider("primary", "https://primary.example/v1", "k1", "m1"),
        LLMProvider("backup", "https://backup.example/v1", "k2", "m2"),
    )
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def post(self, url: str, **kwargs: Any) -> _Response:
            calls.append(url)
            if "primary" in url:
                raise httpx.ConnectError("down")
            return _Response()

    monkeypatch.setattr(llm, "settings", _fake_settings(providers))
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    assert await llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert calls == [
        "https://primary.example/v1/chat/completions",
        "https://backup.example/v1/chat/completions",
    ]


@pytest.mark.asyncio
async def test_chat_returns_none_when_every_provider_fails(monkeypatch) -> None:
    providers = (LLMProvider("only", "https://only.example/v1", "k", "m"),)

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def post(self, url: str, **kwargs: Any) -> _Response:
            raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(llm, "settings", _fake_settings(providers))
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    assert await llm.chat([{"role": "user", "content": "hi"}]) is None


@pytest.mark.asyncio
async def test_chat_without_providers_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(llm, "settings", _fake_settings(()))

    assert await llm.chat([{"role": "user", "content": "hi"}]) is None
