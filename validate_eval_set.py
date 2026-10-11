# -*- coding: utf-8 -*-
"""校验 eval_set_50.jsonl
1) 字段齐全且非空（拒答题 source/section/page/evidence 允许为空）
2) id 唯一；category 合法；difficulty ∈ 易/中/难；key_points 为非空列表
3) evidence 是该 source 某个 chunk 的原文子串（去除全部空白后比较），且 chunk_id 指向的块确实包含它
4) 类别数量：查参数 18±2、故障排查 16±2、操作步骤 16±2，合计 50；拒答 4–5；英文题 ≥6
5) 文档覆盖：每份已入库 PDF 至少 1 题（列出未覆盖的）
退出码 0 = 全部通过"""
import collections, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REQ = ["id", "category", "difficulty", "lang", "question", "reference_answer", "key_points", "source", "section", "page", "evidence", "chunk_id"]
sq = lambda s: re.sub(r"\s+", "", s)

def main(path=os.path.join(HERE, "eval_set_50.jsonl")):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    chunks = {}
    for f in ["output/chunks_heading.jsonl", "uploads/chunks_uploaded.jsonl"]:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            for l in open(p, encoding="utf-8"):
                c = json.loads(l)
                if c["file_type"] == "pdf":
                    chunks[c["chunk_id"]] = c
    errs, warn = [], []
    ids = collections.Counter(r.get("id") for r in rows)
    errs += [f"id 重复：{i}" for i, n in ids.items() if n > 1]
    for r in rows:
        rid, refuse = r.get("id"), r.get("category") == "拒答"
        for k in REQ:
            if k not in r:
                errs.append(f"{rid}: 缺字段 {k}")
            elif not refuse and (r[k] in (None, "", [])):
                errs.append(f"{rid}: 字段 {k} 为空")
        if r.get("category") not in ("查参数", "故障排查", "操作步骤", "拒答"):
            errs.append(f"{rid}: category 非法 {r.get('category')}")
        if r.get("difficulty") not in ("易", "中", "难"):
            errs.append(f"{rid}: difficulty 非法")
        if not isinstance(r.get("key_points"), list) or not r["key_points"]:
            errs.append(f"{rid}: key_points 应为非空列表")
        if refuse:
            continue
        ev = sq(r.get("evidence", ""))
        c = chunks.get(r.get("chunk_id"))
        if not c:
            errs.append(f"{rid}: chunk_id 不存在 {r.get('chunk_id')}")
        elif ev not in sq(c["text"]):
            errs.append(f"{rid}: evidence 不在 chunk {r['chunk_id']} 中")
        elif c["source"] != r["source"]:
            errs.append(f"{rid}: chunk 来源与 source 不一致")
        if len(ev) < 10:
            warn.append(f"{rid}: evidence 偏短（{len(ev)} 字）")
    cats = collections.Counter(r["category"] for r in rows)
    main_n = sum(cats[c] for c in ("查参数", "故障排查", "操作步骤"))
    for c, (lo, hi) in {"查参数": (16, 20), "故障排查": (14, 18), "操作步骤": (14, 18), "拒答": (4, 5)}.items():
        if not lo <= cats[c] <= hi:
            errs.append(f"类别 {c} 数量 {cats[c]} 不在 [{lo},{hi}]")
    if main_n != 50:
        errs.append(f"非拒答题数 {main_n} ≠ 50")
    en = sum(r["lang"] == "en" for r in rows if r["category"] != "拒答")
    if en < 6:
        errs.append(f"英文题仅 {en} 道（要求约 8）")
    srcs = {c["source"] for c in chunks.values()}
    covered = collections.Counter(r["source"] for r in rows if r["source"])
    miss = sorted(srcs - set(covered))
    if miss:
        warn.append("未覆盖文档：" + "、".join(miss))
    print(f"题目 {len(rows)}：" + "，".join(f"{k} {v}" for k, v in cats.items()) + f"；英文题 {en}；覆盖文档 {len(covered)}/{len(srcs)}")
    print("各文档题数：" + "；".join(f"{s[:22]} {n}" for s, n in covered.most_common()))
    for w in warn:
        print("WARN", w)
    for e in errs:
        print("ERROR", e)
    print("校验通过" if not errs else f"校验失败：{len(errs)} 处")
    return 0 if not errs else 1

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
