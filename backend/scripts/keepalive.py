"""Keepalive probe for the Margin demo — stdlib only, safe for Task Scheduler.

Usage:
  python scripts/keepalive.py --once                    # single probe, exit code = health
  python scripts/keepalive.py --interval 600            # loop forever, probe every 600s
  python scripts/keepalive.py --url http://127.0.0.1:8000/api/v1/health

Exit codes: 0 healthy, 1 unhealthy, 2 alert (3 consecutive failures).

schtasks example (every 10 minutes):
  schtasks /Create /SC MINUTE /MO 10 /TN MarginKeepalive /TR "<python> -X utf8 keepalive.py --once"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://niuchuanbo-margin-research-copilot.ms.show/api/v1/health"


def probe(url: str, timeout: float = 15.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "margin-keepalive/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = payload.get("status")
            if status not in {"ok", "degraded"}:
                return False, f"unexpected status {status!r}"
            return True, f"status={status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--max-failures", type=int, default=3)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    failures = 0
    while True:
        healthy, detail = probe(args.url)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if healthy:
            failures = 0
            print(f"[{stamp}] OK   {args.url} ({detail})", flush=True)
            if args.once:
                return 0
        else:
            failures += 1
            print(
                f"[{stamp}] FAIL {args.url} ({detail}) "
                f"consecutive={failures}/{args.max_failures}",
                file=sys.stderr,
                flush=True,
            )
            if args.once:
                return 1
            if failures >= args.max_failures:
                print(
                    f"[{stamp}] ALERT Margin demo down: {args.url} "
                    f"failed {failures} times in a row",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
        time.sleep(max(args.interval, 10))


if __name__ == "__main__":
    raise SystemExit(main())
