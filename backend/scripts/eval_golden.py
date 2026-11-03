"""Golden-set retrieval evaluation over the parsed corpus in data/eval.

Usage (from backend/):
  python -m scripts.eval_golden                 # score the golden set
  python -m scripts.eval_golden --verify        # print top-5 chunk texts to audit gold pages
  python -m scripts.eval_golden --list-papers   # list ready papers in the store
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

# The embeddable interpreter runs isolated and ignores PYTHONPATH; make the
# app package importable regardless of how this script is launched.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(REPO_DIR / "data" / "eval"))
    parser.add_argument(
        "--golden", default=str(BACKEND_DIR / "tests" / "data" / "golden_qa.json")
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--list-papers", action="store_true")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="use the old overlap-only search for an A/B comparison",
    )
    args = parser.parse_args()

    os.environ.setdefault("DATA_DIR", args.data_dir)
    os.environ.setdefault("UPLOAD_DIR", str(Path(args.data_dir) / "uploads"))

    from app.services.indexing import InMemoryIndex, index_paper
    from app.services.qa import retrieve_hits
    from app.store import paper_store

    if args.legacy:
        InMemoryIndex.search_hybrid = InMemoryIndex.search  # type: ignore[method-assign]

    ready = [paper for paper in paper_store.list() if paper.status.value == "ready"]
    if args.list_papers:
        for paper in ready:
            print(f"{paper.id}  {paper.filename}  pages={paper.pages}  blocks={len(paper.blocks)}")
        return 0

    by_filename: dict[str, str] = {}
    for paper in ready:
        by_filename[paper.filename] = paper.id
        index_paper(paper)

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    hit_count = 0
    rows: list[tuple[bool, str, str, list[int], list[int]]] = []
    for entry in golden:
        paper_id = by_filename.get(entry["paper"])
        if paper_id is None:
            print(f"SKIP {entry['paper']}: not found in store", file=sys.stderr)
            continue
        question = entry["question"]
        gold_pages = [int(page) for page in entry.get("pages") or [entry["page"]]]
        hits = retrieve_hits(question, paper_ids=[paper_id], top_k=args.top_k)
        pages = [chunk.page for chunk, _ in hits]
        ok = any(page in gold_pages for page in pages)
        hit_count += int(ok)
        if args.verify:
            for chunk, _score in hits:
                snippet = " ".join(chunk.text.split())[:90]
                print(f"  p{chunk.page:>3}  {snippet}")
        rows.append((ok, entry["paper"], question, gold_pages, pages))
        if args.verify:
            print()

    for ok, paper, question, gold_pages, pages in rows:
        mark = "OK  " if ok else "MISS"
        print(f"{mark} gold {gold_pages}  top-{args.top_k} {pages}  [{paper}] {question}")

    rate = hit_count / len(rows) if rows else 0.0
    print(f"\nTop-{args.top_k} page hit rate: {hit_count}/{len(rows)} = {rate:.1%}")
    return 0 if rate >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
