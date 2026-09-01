"""为「测试数据」提交包生成 D/I/K 三组画像的端到端完整输入输出样例。

用法：后端已在本机 8000 端口运行（python main.py）时执行：
    python submission_test_data/_build/generate_samples.py

行为：读取 data/evaluation/learner_profiles.json 中的画像 D/I/K，
      组装成 POST /api/generate 的扁平入参（三种资源形态全开），
      逐个调用后端，把完整响应原样落盘到
      submission_test_data/_build/raw_samples.json。

注意：后端按自身 .env 配置决定演示/真实模式，本脚本不做任何改写。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"
ENDPOINT = "http://localhost:8000/api/generate"
TARGET_IDS = ["profile-d-zero-basis", "profile-i-skilled-engineer", "profile-k-over-confident"]
RESOURCE_TYPES = ["lecture", "guide", "quiz"]  # 定制讲义 / 实操指南 / 分阶测试题


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_payload(profile_input: dict) -> dict:
    """把画像 input（learner_profiles.json 结构）拍平成 GenerateRequest 入参。"""
    pretest = profile_input.get("pretest_results", [])
    # 只保留 GenerateRequest 需要的键，避免多余字段（completed_at 等）混入
    pretest_clean = []
    for p in pretest:
        pretest_clean.append(
            {
                "test_name": p.get("test_name", ""),
                "total_score": p.get("total_score", 0),
                "max_score": p.get("max_score", 0),
                "topic_scores": p.get("topic_scores", {}),
            }
        )
    return {
        "name": profile_input.get("name", "匿名学习者"),
        "education_level": profile_input.get("education_level", "high_school"),
        "major": profile_input.get("major", ""),
        "school": profile_input.get("school", ""),
        "work_years": profile_input.get("work_years", 0),
        "industry": profile_input.get("industry", ""),
        "positions": profile_input.get("positions", []),
        "skills_used": profile_input.get("skills_used", []),
        "pretest_results": pretest_clean,
        "learning_goal": profile_input.get("learning_goal", ""),
        "resource_types": RESOURCE_TYPES,
    }


def post(payload: dict, timeout: float = 600.0):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(raw)


def main() -> int:
    profiles = {p["id"]: p for p in load_json(PROFILES_PATH)["profiles"]}
    missing = [pid for pid in TARGET_IDS if pid not in profiles]
    if missing:
        print("画像缺失:", missing)
        return 2

    out = {"meta": {"endpoint": ENDPOINT, "resource_types": RESOURCE_TYPES}, "samples": []}
    for pid in TARGET_IDS:
        prof = profiles[pid]
        payload = build_payload(prof["input"])
        print(f"→ 生成 {prof['id']} ({prof['label']}) ...")
        try:
            status, resp = post(payload)
        except urllib.error.URLError as exc:
            print(f"  调用失败: {exc.reason}")
            return 1
        print(f"  HTTP {status} | status={resp.get('status')} | "
              f"resources={len(resp.get('resources', []))} | audit={len(resp.get('audit', []))}")
        out["samples"].append(
            {
                "profile_id": prof["id"],
                "label": prof["label"],
                "input": prof["input"],
                "request": payload,
                "http_status": status,
                "response": resp,
            }
        )

    dest = Path(__file__).parent / "raw_samples.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已保存 {len(out['samples'])} 组样例 → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
