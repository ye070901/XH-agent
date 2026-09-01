"""Call the running /api/generate endpoint and save unmodified Phase 3 outputs.

The collector performs no scoring.  Depending on backend configuration this
may invoke a paid LLM, so the command prints the target and requires an explicit
output path.  No API keys or request headers are written to the output file.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw_text": raw}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw_text": raw}
        return exc.code, parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["demo", "eval"],
        default=None,
        help=(
            "双模式隔离：向请求体注入 audit_mode 字段（demo=演示交付全部分级 / "
            "eval=能力评测仅LLM原生判定）。不传则不注入（保持基线行为）。"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        print(f"Refusing to overwrite existing output: {args.output}")
        return 2
    dataset = load_json(args.cases)
    cases = list(dataset.get("cases", []))
    if args.case_id:
        selected = set(args.case_id)
        cases = [case for case in cases if case.get("id") in selected]
        missing = selected - {case.get("id") for case in cases}
        if missing:
            print("Unknown case id(s): " + ", ".join(sorted(missing)))
            return 2
    if args.limit is not None:
        if args.limit < 1:
            print("--limit must be at least 1")
            return 2
        cases = cases[: args.limit]

    endpoint = args.base_url.rstrip("/") + "/api/generate"
    print(
        f"Collecting {len(cases)} raw outputs from {endpoint}. "
        "The backend may use demo mode or a paid LLM according to its own configuration."
    )
    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        payload = dict(case["input"])
        if args.mode is not None:
            payload["audit_mode"] = args.mode  # 双模式隔离：注入评测模式
        try:
            status, response = post_json(endpoint, payload, args.timeout)
            error = None
        except urllib.error.URLError as exc:
            status = 0
            response = None
            error = str(exc.reason)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        record = {
            "case_id": case["id"],
            "kind": case["kind"],
            "profile_id": case["profile_id"],
            "started_at": started_at,
            "elapsed_ms": elapsed_ms,
            "http_status": status,
            "response": response,
        }
        if error:
            record["transport_error"] = error
        records.append(record)
        print(f"[{index}/{len(cases)}] {case['id']}: HTTP {status}, {elapsed_ms:.0f} ms")

    result = {
        "meta": {
            "name": "Phase 3 raw pipeline outputs",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "source_cases": str(args.cases),
            "record_count": len(records),
            "evaluated": False,
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    failed = sum(not 200 <= record["http_status"] < 300 for record in records)
    print(f"Saved {len(records)} raw records to {args.output}; HTTP failures: {failed}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
