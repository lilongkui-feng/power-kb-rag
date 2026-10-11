# -*- coding: utf-8 -*-
"""混合检索评测：dense / bm25 / hybrid-RRF / hybrid-weighted（含 rrf_k、alpha 小范围扫描），三个集合 × 两个题集
相关性判定同 eval_retrieval.py（同 source + 含 anchor）。两路各取 top_n=50 一次，离线融合，结果可复现。
输出：output/hybrid_results.md / hybrid_results.json / hybrid_examples.md
"""
from __future__ import annotations
import json, os, time
import bm25_index
from embed_index import get_model
from eval_retrieval import relevant
from retrieve import retrieve, fuse, format_hits

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TOP_N = 50
METHODS = ["heading", "fixed", "recursive"]
CONFIGS = [("dense", {"mode": "dense"}), ("bm25", {"mode": "bm25"})] + \
          [(f"rrf_k{k}", {"mode": "hybrid", "fusion": "rrf", "rrf_k": k}) for k in (10, 30, 60, 100)] + \
          [(f"rrf_k60_wb{w}", {"mode": "hybrid", "fusion": "rrf", "rrf_k": 60, "w_bm25": w}) for w in (0.3, 0.5)] + \
          [("rrf_k60_auto", {"mode": "hybrid", "fusion": "rrf", "rrf_k": 60, "w_bm25": "auto"})] + \
          [(f"w_a{a}", {"mode": "hybrid", "fusion": "weighted", "alpha": a}) for a in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)]
DEFAULT = "w_a0.5"
OLD_FAIL = ["q06", "q19", "q25", "q26", "q27", "q32"]

def load(p):
    return [json.loads(l) for l in open(os.path.join(HERE, p), encoding="utf-8") if l.strip()]

def metrics(ranks):
    n = len(ranks)
    d = {f"Hit@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 5, 10)}
    d["MRR@10"] = round(sum(1 / r for r in ranks if r and r <= 10) / n, 3)
    return d

def main():
    sets = {"main32": load("eval_questions.jsonl"), "keyword12": load("eval_questions_keyword.jsonl")}
    allq = [q for qs in sets.values() for q in qs]
    sets["all44"] = allq
    m = get_model()
    qv = dict(zip([q["id"] for q in allq], m.encode([q["query"] for q in allq], normalize_embeddings=True, batch_size=16)))
    t0 = time.time()
    raw = {}            # (method, qid) -> lists
    for meth in METHODS:
        for q in allq:
            raw[(meth, q["id"])] = {"dense": retrieve(q["query"], TOP_N, meth, query_vec=qv[q["id"]]),
                                    "bm25": bm25_index.search(q["query"], meth, TOP_N)}
    retr_secs = time.time() - t0
    t1 = time.time(); [bm25_index.search(q["query"], "heading", TOP_N) for q in allq]
    bm25_ms = (time.time() - t1) / len(allq) * 1000
    ranks, res = {}, {}
    for meth in METHODS:
        for cname, cfg in CONFIGS:
            for q in allq:
                c = dict(cfg)
                if c.get("w_bm25") == "auto":
                    c["w_bm25"] = bm25_index.auto_bm25_weight(q["query"])
                hits = fuse(raw[(meth, q["id"])] if c["mode"] == "hybrid" else {c["mode"]: raw[(meth, q["id"])][c["mode"]]},
                            10, **c)
                ranks[(meth, cname, q["id"])] = next((h["rank"] for h in hits if relevant(h, q)), None)
            for sname, qs in sets.items():
                res.setdefault(sname, {}).setdefault(meth, {})[cname] = metrics([ranks[(meth, cname, q["id"])] for q in qs])
    json.dump({"top_n": TOP_N, "bm25_query_ms": round(bm25_ms, 1), "metrics": res,
               "ranks": {f"{a}|{b}|{c}": r for (a, b, c), r in ranks.items()}},
              open(os.path.join(OUT, "hybrid_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# 混合检索评测（dense=bge-m3/Chroma，bm25=jieba+rank_bm25，两路各取 Top-50 后融合）", "",
         f"BM25 单次查询 ≈ {bm25_ms:.1f} ms（heading，1578 块，纯 Python 全量打分）。", ""]
    for sname, qs in sets.items():
        L += [f"## 题集 {sname}（{len(qs)} 题）", "", "| 集合 | 配置 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 |", "|---|---|---|---|---|---|---|"]
        for meth in METHODS:
            for cname, _ in CONFIGS:
                r = res[sname][meth][cname]
                L.append(f"| {meth} | {cname} | {r['Hit@1']} | {r['Hit@3']} | {r['Hit@5']} | {r['Hit@10']} | {r['MRR@10']} |")
        L.append("")
    cols = ["dense", "bm25", "rrf_k10", "rrf_k60", "w_a0.5", "w_a0.7"]
    for sname, qs in list(sets.items())[:2]:
        L += [f"## 每题排名（heading 集合，{sname}；- 表示前 10 未命中）", "", "| 题 | 问题 | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
        for q in qs:
            mark = " ⚑旧失败题" if q["id"] in OLD_FAIL else ""
            L.append(f"| {q['id']}{mark} | {q['query'][:36]} | " + " | ".join(str(ranks[('heading', c, q['id'])] or '-') for c in cols) + " |")
        L.append("")
    # 退步/改善统计（heading，默认配置 vs dense）
    L += ["## heading：推荐默认 hybrid-weighted(alpha=0.5) 相对 dense 的逐题变化", ""]
    for sname, qs in list(sets.items())[:2]:
        imp = [(q["id"], ranks[('heading', 'dense', q['id'])], ranks[('heading', DEFAULT, q['id'])]) for q in qs]
        better = [x for x in imp if (x[2] or 99) < (x[1] or 99)]
        worse = [x for x in imp if (x[2] or 99) > (x[1] or 99)]
        L.append(f"- {sname}：改善 {len(better)} 题 {better}；退步 {len(worse)} 题 {worse}")
    L.append("")
    open(os.path.join(OUT, "hybrid_results.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    # 示例
    E = ["# 混合检索示例（heading，hybrid 加权融合 alpha=0.5，Top-3，括号内为两路各自名次/分数）", ""]
    for qid in ["q26", "q27", "k02", "k03", "k05"]:
        q = next(x for x in allq if x["id"] == qid)
        hits = fuse(raw[("heading", qid)], 3, "hybrid", "weighted", alpha=0.5)
        E += [f"## {qid}：{q['query']}", f"标注：{q['source']} / {q['section']}；dense 排名 {ranks[('heading','dense',qid)] or '>10'}，bm25 排名 {ranks[('heading','bm25',qid)] or '>10'}，hybrid 排名 {ranks[('heading',DEFAULT,qid)] or '>10'}", "", "```text", format_hits(hits, 200), "```", ""]
    open(os.path.join(OUT, "hybrid_examples.md"), "w", encoding="utf-8").write("\n".join(E))
    print("\n".join(L))
    print(f"retrieval {retr_secs:.1f}s")

if __name__ == "__main__":
    main()
