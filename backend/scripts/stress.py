"""Concurrency stress probe for the Margin backend.

Drives N parse jobs in parallel (semaphore should keep only PARSE_CONCURRENCY
running), fires M /qa/ask requests concurrently, reports latency P95 and the
RSS delta from /api/v1/health, then deletes the uploaded papers.

Usage (from backend/):
  python scripts/stress.py --url http://127.0.0.1:8000 --pdf data/uploads/xxxx.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx

API_PREFIX = "/api/v1"


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


async def _upload(client: httpx.AsyncClient, pdf: Path) -> str | None:
    try:
        with pdf.open("rb") as handle:
            response = await client.post(
                f"{API_PREFIX}/papers",
                files={"file": (pdf.name, handle, "application/pdf")},
            )
        if response.status_code != 201:
            print(f"  upload failed: HTTP {response.status_code} {response.text[:200]}")
            return None
        return response.json()["paper"]["id"]
    except httpx.HTTPError as exc:
        print(f"  upload failed: {exc}")
        return None


async def _parse_one(
    client: httpx.AsyncClient, paper_id: str, timeout: float
) -> tuple[str, float, str]:
    started = time.perf_counter()
    response = await client.post(f"{API_PREFIX}/papers/{paper_id}/parse")
    response.raise_for_status()
    seen_queued = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = await client.get(f"{API_PREFIX}/papers/{paper_id}/parse-status")
        status.raise_for_status()
        payload = status.json()
        if payload["status"] in {"queued", "running"}:
            seen_queued = seen_queued or payload["status"] == "queued"
            if payload["status"] == "queued":
                await asyncio.sleep(0.5)
                continue
        else:
            break
        await asyncio.sleep(1.0)
    else:
        return paper_id, time.perf_counter() - started, f"timeout after {timeout}s"
    payload = status.json()
    elapsed = time.perf_counter() - started
    note = ("queued-then-ran" if seen_queued else "ran-directly") + f" ({payload['status']})"
    if payload["status"] != "done":
        note += f" error={payload.get('error', '')[:120]}"
    return paper_id, elapsed, note


async def _qa_one(
    client: httpx.AsyncClient, question: str, paper_ids: list[str]
) -> float | None:
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{API_PREFIX}/qa/ask",
            json={"question": question, "paper_ids": paper_ids, "top_k": 4},
            timeout=180,
        )
        if response.status_code != 200:
            print(f"  qa failed: HTTP {response.status_code} {response.text[:160]}")
            return None
        return time.perf_counter() - started
    except httpx.HTTPError as exc:
        print(f"  qa failed: {exc}")
        return None


async def _rss_mb(client: httpx.AsyncClient) -> float | None:
    try:
        response = await client.get(f"{API_PREFIX}/health")
        response.raise_for_status()
        return response.json().get("memory_rss_mb")
    except httpx.HTTPError:
        return None


async def _delete(client: httpx.AsyncClient, paper_id: str) -> None:
    try:
        await client.delete(f"{API_PREFIX}/papers/{paper_id}")
    except httpx.HTTPError as exc:
        print(f"  cleanup {paper_id} failed: {exc}")


async def _run(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"PDF not found: {pdf}", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(base_url=args.url.rstrip("/"), timeout=120) as client:
        before = await _rss_mb(client)
        print(f"health before: rss={before} MB")

        print(f"uploading {args.parses} copies of {pdf.name} ...")
        uploads = await asyncio.gather(*(_upload(client, pdf) for _ in range(args.parses)))
        paper_ids = [pid for pid in uploads if pid]
        if len(paper_ids) < args.parses:
            print(f"only {len(paper_ids)}/{args.parses} uploads succeeded", file=sys.stderr)
            return 1
        print(f"uploaded: {', '.join(paper_ids)}")

        print(f"starting {len(paper_ids)} concurrent parses (timeout {args.parse_timeout}s) ...")
        parse_started = time.perf_counter()
        results = await asyncio.gather(
            *(_parse_one(client, pid, args.parse_timeout) for pid in paper_ids)
        )
        parse_wall = time.perf_counter() - parse_started
        parse_failed = [row for row in results if "done" not in row[2]]
        for paper_id, elapsed, note in results:
            print(f"  parse {paper_id}: {elapsed:.1f}s {note}")
        print(
            f"parse wall time: {parse_wall:.1f}s for {len(results)} papers "
            f"(concurrency cap {args.expected_concurrency})"
        )
        if parse_failed:
            print(f"{len(parse_failed)} parses did not finish as done", file=sys.stderr)
            return 1

        print(f"firing {args.qas} concurrent /qa/ask requests ...")
        qa_latencies = [
            latency
            for latency in await asyncio.gather(
                *(_qa_one(client, args.question, paper_ids) for _ in range(args.qas))
            )
            if latency is not None
        ]
        if qa_latencies:
            print(
                f"qa latencies: n={len(qa_latencies)} "
                f"mean={statistics.mean(qa_latencies):.1f}s "
                f"p50={statistics.median(qa_latencies):.1f}s "
                f"p95={_p95(qa_latencies):.1f}s "
                f"max={max(qa_latencies):.1f}s"
            )
        else:
            print("all qa requests failed", file=sys.stderr)
            return 1

        after = await _rss_mb(client)
        print(f"health after: rss={after} MB")
        if before is not None and after is not None:
            print(f"rss delta: {after - before:+.1f} MB")

        print(f"cleaning up {len(paper_ids)} uploaded papers ...")
        await asyncio.gather(*(_delete(client, pid) for pid in paper_ids))
        print("cleanup done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--parses", type=int, default=5)
    parser.add_argument("--qas", type=int, default=20)
    parser.add_argument("--parse-timeout", type=float, default=300)
    parser.add_argument("--expected-concurrency", type=int, default=2)
    parser.add_argument(
        "--question",
        default="这篇文章的主要方法是什么？",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
