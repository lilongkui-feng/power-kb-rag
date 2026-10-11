# eval_set_v3.jsonl → eval_set_v3.md / .xlsx（按类别分组，core 要点加★）
import json, collections
from openpyxl import Workbook
rows = [json.loads(l) for l in open("eval_set_v3.jsonl", encoding="utf-8")]
L = ["# 评测集 v3（库内 %d 题 + 拒答 %d 题）" % (sum(r["category"] != "拒答" for r in rows), sum(r["category"] == "拒答" for r in rows)), "",
     "来源：eval_set_50（旧 50 题，补了 core 标注）+ DeepSeek-V3 起草并人工审阅的新题（origin 字段注明）。★ = core 要点。库外/边界拒答题另见 eval_ood.jsonl。", ""]
wb = Workbook(); ws = wb.active; ws.title = "eval_set_v3"
ws.append(["id", "类别", "难度", "语言", "综合", "问题", "参考答案", "core 要点", "minor 要点", "来源", "章节", "页", "证据", "来源"])
for cat in ("查参数", "故障排查", "操作步骤", "拒答"):
    rs = [r for r in rows if r["category"] == cat]
    L += [f"## {cat}（{len(rs)}）", ""]
    for r in rs:
        core = set(r.get("core") or [])
        kp = "；".join(("★" if i in core else "") + k for i, k in enumerate(r["key_points"]))
        L.append(f"- **{r['id']}**（{r['difficulty']}，{r['lang']}{'，综合' if r.get('multi') else ''}）{r['question']}  \n  答：{r['reference_answer']}  \n  要点：{kp}  \n  出处：{r.get('source','')}｜{r.get('section','')}｜p{r.get('page','')}")
        ws.append([r["id"], cat, r["difficulty"], r["lang"], "是" if r.get("multi") else "", r["question"], r["reference_answer"],
                   "；".join(k for i, k in enumerate(r["key_points"]) if i in core), "；".join(k for i, k in enumerate(r["key_points"]) if i not in core),
                   r.get("source", ""), r.get("section", ""), r.get("page", ""), r.get("evidence", ""), r.get("origin", "")])
    L.append("")
open("eval_set_v3.md", "w", encoding="utf-8").write("\n".join(L)); wb.save("eval_set_v3.xlsx"); print("ok", len(rows))
