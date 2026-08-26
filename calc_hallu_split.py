import json
import csv

data_path = r"./data/evaluation/runs/phase3_raw_outputs.json"

with open(data_path, "r", encoding="utf-8") as f:
    root = json.load(f)

cases = root["records"]
total_cases = len(cases)
print(f"总共读取case数量： {total_cases}\n")

total_hallucination = 0
total_unverifiable = 0
sum_case_hallu_rate = 0.0
valid_case_rate = 0

csv_rows = []

for idx, case in enumerate(cases):
    resp = case.get("response", {})
    audit_list = resp.get("audit", [])

    hallu_cnt = 0
    unveri_cnt = 0
    hallu_rate = None

    if isinstance(audit_list, list) and len(audit_list) >= 1:
        audit_obj = audit_list[0]
        if isinstance(audit_obj, dict):
            # ⚠️ 重点修正：count字段嵌套在 fact_check子字典！
            fact_check = audit_obj.get("fact_check", {})
            hallu_cnt = fact_check.get("hallucination_count", 0)
            unveri_cnt = fact_check.get("unverifiable_count", 0)
            hallu_rate = audit_obj.get("hallucination_rate")

    total_hallucination += hallu_cnt
    total_unverifiable += unveri_cnt

    if hallu_rate is not None:
        sum_case_hallu_rate += hallu_rate
        valid_case_rate += 1

    csv_rows.append({
        "case_idx": idx,
        "hallucination_count": hallu_cnt,
        "unverifiable_count": unveri_cnt,
        "hallucination_rate": hallu_rate
    })
    #打印前10个case调试，case0现在应该输出 hallu_cnt=1, unveri=1, rate=0.25
    if idx < 10:
        print(f"case[{idx}]: hallu_cnt={hallu_cnt}, unveri={unveri_cnt}, rate={hallu_rate}")

out_csv = "hallucination_stats.csv"
with open(out_csv, "w", encoding="utf-8", newline="") as fcsv:
    writer = csv.DictWriter(fcsv, fieldnames=["case_idx","hallucination_count","unverifiable_count","hallucination_rate"])
    writer.writeheader()
    writer.writerows(csv_rows)
print(f"\n✅已导出全部case明细到文件: {out_csv}")

print("\n==== 汇总统计结果 ====")
print(f"全部case累计幻觉条目数 hallucination_count = {total_hallucination}")
print(f"全部case累计不可验证条目数 unverifiable_count = {total_unverifiable}")
if valid_case_rate > 0:
    avg_case_rate = sum_case_hallu_rate / valid_case_rate
    print(f"有效case数量（含有hallucination_rate字段） = {valid_case_rate}")
    print(f"【单case幻觉率算术平均】Avg hallucination_rate = {avg_case_rate:.4f}")

print("\n指标解释：")
print("- 累计幻觉条目：所有case检测出的幻觉claim总数量")
print("- Avg hallucination_rate：每个case内部幻觉率，全部有效case取平均，论文评估常用指标")