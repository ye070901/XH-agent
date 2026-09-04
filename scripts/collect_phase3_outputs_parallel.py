"""并发采集 Phase 3 原始输出（真实 LLM 模式）。

与 collect_phase3_outputs.py 相同，但用线程池并发调用 /api/generate，
用于 74 个 case 的批量真实采样。输出格式与串行版完全一致。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Windows 控制台默认 cp950，print 中文会崩；强制 utf-8 输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases_k1k7_70.json"


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


def collect_one(case: dict[str, Any], endpoint: str, timeout: float) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    payload = dict(case["input"])
    error = None
    try:
        status, response = post_json(endpoint, payload, timeout)
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
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=360.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        print(f"Refusing to overwrite existing output: {args.output}")
        return 2
    dataset = load_json(args.cases)
    cases = list(dataset.get("cases", []))
    endpoint = args.base_url.rstrip("/") + "/api/generate"
    print(f"Collecting {len(cases)} raw outputs from {endpoint} with {args.workers} workers.")

    records_by_id: dict[str, dict[str, Any]] = {}
    started_all = time.perf_counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def flush(snapshot: dict[str, dict[str, Any]]) -> None:
        """增量落盘：每完成一个 case 就写一次，崩了也不丢已采集结果。"""
        ordered = [snapshot[case["id"]] for case in cases if case["id"] in snapshot]
        result = {
            "meta": {
                "name": "Phase 3 raw pipeline outputs (K1-K7 70, parallel re-collection)",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "endpoint": endpoint,
                "source_cases": str(args.cases),
                "record_count": len(ordered),
                "evaluated": False,
            },
            "records": ordered,
        }
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(collect_one, case, endpoint, args.timeout): case["id"] for case in cases
        }
        done = 0
        for future in as_completed(futures):
            case_id = futures[future]
            record = future.result()
            records_by_id[case_id] = record
            done += 1
            elapsed = (time.perf_counter() - started_all) / 60.0
            flush(records_by_id)
            print(
                f"[{done}/{len(cases)}] {case_id}: HTTP {record['http_status']}, "
                f"{record['elapsed_ms']:.0f} ms (elapsed {elapsed:.1f} min)"
            )

    records = [records_by_id[case["id"]] for case in cases]
    failed = sum(not 200 <= record["http_status"] < 300 for record in records)
    total_min = (time.perf_counter() - started_all) / 60.0
    print(
        f"Saved {len(records)} raw records to {args.output}; HTTP failures: {failed}; "
        f"total {total_min:.1f} min."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
