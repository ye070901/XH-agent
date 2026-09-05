"""可断点续传的 Phase 3 原始输出采集器（eval / demo 双模式）。

与 collect_phase3_outputs.py 的唯一区别：
  - 每个 case 完成后立即把 records 写回输出文件（checkpoint），进程被杀最多丢当前 1 例；
  - 重启时自动跳过已完成的 case_id，续跑剩余；
  - 输出格式完全兼容 collect_phase3_outputs.py，可直接喂 run_phase3_evaluation.py。

Run:
    python scripts/collect_resumable.py --case-ids data/evaluation/runs/stratified_sample_ids.json \
        --mode eval --output data/evaluation/runs/phase3_raw_outputs_eval_sample.json
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


def write_checkpoint(
    output: Path,
    records: list[dict[str, Any]],
    endpoint: str,
    source_cases: str,
    target_count: int,
) -> None:
    doc = {
        "meta": {
            "name": "Phase 3 raw pipeline outputs (resumable)",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "source_cases": source_cases,
            "record_count": len(records),
            "target_count": target_count,
            "complete": len(records) >= target_count,
            "evaluated": False,
        },
        "records": records,
    }
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--case-ids",
        type=Path,
        required=True,
        help="分层采样 id 清单 JSON（含 positive_case_ids / negative_case_ids）",
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--mode", choices=["demo", "eval"], default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_json(args.cases)
    all_cases = {c["id"]: c for c in dataset.get("cases", [])}
    ids_doc = load_json(args.case_ids)
    target = list(ids_doc.get("positive_case_ids", [])) + list(ids_doc.get("negative_case_ids", []))

    # 断点续传：读已有 checkpoint 中已完成的 case_id
    done_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    if args.output.exists():
        prev = load_json(args.output)
        records = [r for r in prev.get("records", []) if r.get("case_id")]
        done_ids = {r.get("case_id") for r in records if r.get("case_id")}

    remaining = [cid for cid in target if cid not in done_ids]
    endpoint = args.base_url.rstrip("/") + "/api/generate"
    print(
        f"目标 {len(target)} / 已完成 {len(done_ids)} / 剩余 {len(remaining)}",
        flush=True,
    )
    if not remaining:
        print("无剩余，全部已完成")
        return 0

    failed = 0
    for index, cid in enumerate(remaining, start=1):
        case = all_cases.get(cid)
        if case is None:
            print(f"[skip] 未知 case {cid}", flush=True)
            continue
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        payload = dict(case.get("input") or {})
        if args.mode is not None:
            payload["audit_mode"] = args.mode

        record: dict[str, Any] = {
            "case_id": cid,
            "kind": case.get("kind"),
            "profile_id": case.get("profile_id"),
            "started_at": started_at,
        }
        try:
            status, response = post_json(endpoint, payload, args.timeout)
        except urllib.error.URLError as exc:
            status = 0
            response = None
            record["transport_error"] = str(exc.reason)
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        record["http_status"] = status
        record["response"] = response
        if not 200 <= status < 300:
            failed += 1

        records.append(record)
        write_checkpoint(args.output, records, endpoint, str(args.cases), len(target))
        print(
            f"[{index}/{len(remaining)}] {cid}: HTTP {status}, "
            f"{record['elapsed_ms']:.0f} ms (累计 {len(records)}/{len(target)})",
            flush=True,
        )

    print(f"完成：累计 {len(records)}/{len(target)}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
