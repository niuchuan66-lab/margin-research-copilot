"""Offline parsing CLI: `python -m app.workers.parse_cli path/to/paper.pdf`."""

from __future__ import annotations

import argparse
import json

from app.services.parsing import parse_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a PDF and print a block summary")
    parser.add_argument("pdf", help="path to a PDF file")
    parser.add_argument("--blocks", type=int, default=10, help="blocks to print")
    args = parser.parse_args()

    parsed = parse_pdf(args.pdf)
    summary = {
        "pages": parsed.pages,
        "engine": parsed.parse_engine,
        "blocks": len(parsed.blocks),
        "references": len(parsed.references),
        "sample": [
            {
                "page": block.page,
                "kind": block.kind.value,
                "bbox": block.bbox,
                "text": block.text[:240],
            }
            for block in parsed.blocks[: args.blocks]
        ],
        "metadata": parsed.metadata,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
