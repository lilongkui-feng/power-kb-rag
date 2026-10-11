# -*- coding: utf-8 -*-
"""校验 eval_set_v3.jsonl：
1) 字段齐全；id 唯一；类别/难度合法；key_points 非空；core 为合法下标且非空
2) evidence（及综合题的 evidence_2）是对应 chunk 的原文子串（去空白和表格分隔符 | 后比较）；chunk 可以来自 heading（v1）或 heading_v2
3) 规模：库内 120–150；三类各占 25%–40%；英文 15%–25%；每份文档 ≥3 题
退出码 0 = 全部通过"""
import collections, json, re, sys
sq = lambda s: re.sub(r"[\s|]+", "", s or "")
REQ = ["id", "category", "difficulty", "lang", "question", "reference_answer", "key_points", "source", "section", "page", "evidence", "chunk_id"]
chunks = {}
for f in ("output/chunks_heading.jsonl", "uploads/chunks_uploaded.jsonl", "output/chunks_heading_v2.jsonl", "uploads/chunks_uploaded_v2.jsonl"):
    for l in open(f, encoding="utf-8"):
        c = json.loads(l); chunks.setdefault(c["chunk_id"], []).append(c)   # docx/pdf 同名文档的 chunk_id 可能相同，按 source 匹配
rows = [json.loads(l) for l in open(sys.argv[1] if len(sys.argv) > 1 else "eval_set_v3.jsonl", encoding="utf-8")]
errs = []
ids = collections.Counter(r["id"] for r in rows)
errs += [f"id 重复 {i}" for i, n in ids.items() if n > 1]
for r in rows:
    if r["category"] == "拒答":
        continue
    errs += [f"{r['id']} 缺字段 {k}" for k in REQ if not r.get(k)]
    if r["category"] not in ("查参数", "故障排查", "操作步骤"): errs.append(f"{r['id']} 类别非法")
    if r["difficulty"] not in ("易", "中", "难"): errs.append(f"{r['id']} 难度非法")
    if not r.get("core") or any(not (0 <= i < len(r["key_points"])) for i in r["core"]): errs.append(f"{r['id']} core 非法")
    for ek, ck in (("evidence", "chunk_id"), ("evidence_2", "chunk_id_2")):
        if ek not in r:
            continue
        src = r.get("source_2" if ck == "chunk_id_2" else "source")
        c = next((x for x in chunks.get(r[ck], []) if x["source"] == src), None)
        if not c: errs.append(f"{r['id']} {ck} 不存在"); continue
        if sq(r[ek]) not in sq(c["text"]): errs.append(f"{r['id']} {ek} 不在 {r[ck]}")
        if len(sq(r[ek])) < 10: errs.append(f"{r['id']} {ek} 过短")
ink = [r for r in rows if r["category"] != "拒答"]
n = len(ink); cat = collections.Counter(r["category"] for r in ink); en = sum(r["lang"] == "en" for r in ink) / n
if not 120 <= n <= 150: errs.append(f"库内题数 {n} 不在 120–150")
errs += [f"类别 {c} 占比 {v/n:.0%} 不在 25%–40%" for c, v in cat.items() if not .25 <= v / n <= .40]
if not .15 <= en <= .25: errs.append(f"英文占比 {en:.0%}")
src = collections.Counter(r["source"] for r in ink)
errs += [f"文档 {s} 只有 {v} 题" for s, v in src.items() if v < 3]
print(f"库内 {n}｜{dict(cat)}｜英文 {en:.0%}｜综合题 {sum(bool(r.get('multi')) for r in ink)}｜文档 {len(src)} 份｜拒答 {len(rows) - n}")
print("错误：" + ("无" if not errs else "\n  " + "\n  ".join(errs)))
sys.exit(1 if errs else 0)
