"""Check the configured LLM without printing the API key.

Run from `backend/`:

    python check_llm.py
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.llm import chat


async def main() -> None:
    print(f"base_url   : {settings.llm_base_url or '(empty)'}")
    print(f"model      : {settings.llm_model or '(empty)'}")
    print(f"configured : {settings.llm_configured}")
    if not settings.llm_configured:
        print("LLM_API_KEY is empty; the backend will use the extractive fallback.")
        return
    answer = await chat(
        [{"role": "user", "content": "用一句中文确认你已连通，不要展开。"}],
        max_tokens=80,
    )
    print(f"answer     : {answer or '(call failed; check key/base_url/network)'}")


if __name__ == "__main__":
    asyncio.run(main())
