# -*- coding: utf-8 -*-
"""合并 eval_set_50（补 core 标注）+ V3 起草并人工审阅后的新题 → eval_set_v3.jsonl（库内 133 + 拒答 5）。
审阅结论（删除/改类别/改要点）记录在 REVIEW 中，可复现。"""
import json, collections, re
old = [json.loads(l) for l in open("eval_set_50.jsonl", encoding="utf-8")]
core_old = json.load(open("evalset/core_old.json", encoding="utf-8"))
A = [json.loads(l) for l in open("evalset/drafts_v3.jsonl", encoding="utf-8")]
B = [json.loads(l) for l in open("evalset/drafts_v3b.jsonl", encoding="utf-8")]
C = [json.loads(l) for l in open("evalset/drafts_v3c.jsonl", encoding="utf-8")]
REVIEW = {  # 键：a<序号>/b<序号>；值：drop 或修改
    **{f"a{i:02d}": "drop" for i in (6, 8, 12, 15, 18, 20, 28, 29, 30, 32, 47, 52, 59, 69, 71)},
    **{f"b{i:02d}": "drop" for i in (4, 19, 26, 28)},
    **{f"c{i:02d}": "drop" for i in (13, 14, 16, 17, 18, 19)},
    # 类别均衡：删掉较琐碎的查参数题（继电器型号、报送月份、NM1 尺寸、紧固件清单、PT 频率、与 a58 重复的 EI 分值、事件条数、多类别取最低值）
    "a01": "drop", "a27": "drop", "a68": "drop", "a64": "drop", "b25": "drop", "b22": "drop", "a51": "drop", "a43": "drop",
    "a60": {"category": "查参数"}, "b06": {"category": "查参数"}, "b08": {"category": "操作步骤"}, "b12": {"category": "操作步骤"},
    "b18": {"category": "操作步骤"}, "b20": {"category": "操作步骤"},
    "a31": {"key_points_core": ["灭弧气室湿度限值≤150μL/L（20℃，101.3 kPa）", "180μL/L 超出限值，不符合要求"]},
}
out = []
for o in old:
    o = dict(o)
    if o["category"] != "拒答":
        o["core"] = core_old[o["id"]]
    o["origin"] = "eval_set_50"
    out.append(o)
nxt = {"查参数": 19, "故障排查": 17, "操作步骤": 17}
pre = {"查参数": "P", "故障排查": "F", "操作步骤": "O"}
for tag, D in (("a", A), ("b", B), ("c", C)):
    for i, d in enumerate(D):
        r = REVIEW.get(f"{tag}{i:02d}")
        if r == "drop":
            continue
        d = dict(d, **(r or {}))
        strip = lambda ks: [re.sub(r"[（(]\s*(?:片段|表)[^）)]*[）)]", "", k).strip() for k in ks]   # 去掉要点里的“（片段1…）”类出处括注
        core, minor = strip(d["key_points_core"]), strip(d.get("key_points_minor") or [])
        c = d["category"]; rid = f"{pre[c]}{nxt[c]:02d}"; nxt[c] += 1
        item = {"id": rid, "category": c, "difficulty": d.get("difficulty") if d.get("difficulty") in ("易", "中", "难") else "中",
                "lang": d["lang"], "device": "", "question": d["question"], "reference_answer": d["reference_answer"],
                "key_points": core + minor, "core": list(range(len(core))), "source": d["source"], "section": d["section"],
                "page": d["page"], "evidence": d["evidence"], "chunk_id": d["chunk_id"], "multi": bool(d.get("multi")),
                "origin": f"v3_draft_{tag}{i:02d}（DeepSeek-V3 起草，人工审阅）"}
        if d.get("multi"):
            item.update(evidence_2=d["evidence_2"], source_2=d["source_2"], section_2=d["section_2"], page_2=d["page_2"], chunk_id_2=d["chunk_id_2"])
        out.append(item)
KZ = json.load(open("evalset/kp_zh.json", encoding="utf-8")) if __import__("os").path.exists("evalset/kp_zh.json") else {}   # add_kp_zh.py 生成的英文题中文要点
for r in out:
    if r["id"] in KZ and "key_points_zh" not in r:
        r["key_points_zh"] = KZ[r["id"]]
out.sort(key=lambda r: ("PFOR".index(r["id"][0]), r["id"]))
with open("eval_set_v3.jsonl", "w", encoding="utf-8") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
ink = [r for r in out if r["category"] != "拒答"]
print("库内", len(ink), collections.Counter(r["category"] for r in ink), "英文", sum(r["lang"] == "en" for r in ink), "综合题", sum(r.get("multi", False) for r in ink))
print(collections.Counter(r["source"][:24] for r in ink).most_common())
