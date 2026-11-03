"""Entry point that works with both normal Python and the embeddable build.

    cd backend
    python check_llm.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def run() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app.workers.llm_check import main

    asyncio.run(main())


if __name__ == "__main__":
    run()
