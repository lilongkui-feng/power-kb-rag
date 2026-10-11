# -*- coding: utf-8 -*-
"""重排评测：dense / hybrid(weighted α=0.5) / dense+rerank / hybrid+rerank，Top-N 扫描 10/20/30，β 混合，bge-reranker-base 参考。
44 题（main32 + keyword12）× heading/fixed/recursive。相关性判定同 eval_retrieval.relevant。
输出 output/rerank_results.md / rerank_results.json / rerank_examples.md
用法：python eval_rerank.py [--methods heading,fixed,recursive] [--no-base]
"""
from __future__ import annotations
import argparse, json, os, time
import bm25_index, rerank as rr
from embed_index import get_model
from eval_retrieval import relevant
from retrieve import retrieve, fuse, format_hits

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
V2, BASE = "BAAI/bge-reranker-v2-m3", "BAAI/bge-reranker-base"
FOCUS = ["q06", "q19", "q25", "q26", "q27", "q32", "q03", "q21", "q31"]

def load(p):
    return [json.loads(l) for l in open(os.path.join(HERE, p), encoding="utf-8") if l.strip()]

def metrics(ranks):
    n = len(ranks)
    d = {f"Hit@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 5, 10)}
    d["MRR@10"] = round(sum(1 / r for r in ranks if r and r <= 10) / n, 3)
    return d

def first_rel(hits, q):
    return next((h["rank"] for h in hits if relevant(h, q)), None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="heading,fixed,recursive")
    ap.add_argument("--no-base", action="store_true")
    a = ap.parse_args()
    methods = [m.strip() for m in a.methods.split(",")]
    sets = {"main32": load("eval_questions.jsonl"), "keyword12": load("eval_questions_keyword.jsonl")}
    allq = sets["main32"] + sets["keyword12"]; sets["all44"] = allq
    qv = dict(zip([q["id"] for q in allq], get_model().encode([q["query"] for q in allq], normalize_embeddings=True, batch_size=16)))
    # ---- 一阶段候选 ----
    stage1 = {}
    for m in methods:
        for q in allq:
            dense50 = retrieve(q["query"], 50, m, query_vec=qv[q["id"]])
            bm50 = bm25_index.search(q["query"], m, 50)
            stage1[(m, "dense", q["id"])] = fuse({"dense": dense50}, 30, mode="dense")
            stage1[(m, "hybrid", q["id"])] = fuse({"dense": dense50, "bm25": bm50}, 30, "hybrid", "weighted", alpha=0.5)
    # ---- 延迟：无缓存实测（heading，前 8 题，hybrid 候选）----
    lat = {}
    models = [V2] + ([] if a.no_base else [BASE])
    for name in models:
        rr.get_reranker(name)
        for n in (10, 20, 30):
            ts = []
            for q in allq[:8]:
                t = time.time(); rr.rerank(q["query"], stage1[("heading", "hybrid", q["id"])], n, name, use_cache=False); ts.append(time.time() - t)
            lat[f"{name.split('/')[-1]}@{n}"] = round(sum(ts) / len(ts), 2)
            print("latency", name, n, lat[f"{name.split('/')[-1]}@{n}"], flush=True)
    # ---- 重排（缓存，全部候选）----
    t0 = time.time(); done = 0
    for (m, s, qid), hits in stage1.items():
        q = next(x for x in allq if x["id"] == qid)
        for name in models:
            if name == BASE and m != "heading":
                continue
            rr.score_pairs(q["query"], [rr.passage(h) for h in hits[:30]], name)
        done += 1
        if done % 20 == 0:
            rr.save_cache(V2); rr.save_cache(BASE)
            print(f"reranked {done}/{len(stage1)} {time.time() - t0:.0f}s", flush=True)
    rr.save_cache(V2); rr.save_cache(BASE)
    # ---- 配置 ----
    configs = [("dense", "dense", None, None, 1.0), ("hybrid", "hybrid", None, None, 1.0)]
    for n in (10, 20, 30):
        configs += [(f"dense+rr@{n}", "dense", V2, n, 1.0), (f"hybrid+rr@{n}", "hybrid", V2, n, 1.0)]
    configs += [(f"hybrid+rr@20 β{b}", "hybrid", V2, 20, b) for b in (0.8, 0.7, 0.5)]
    if not a.no_base:
        configs += [("hybrid+base@20", "hybrid", BASE, 20, 1.0)]
    ranks, res, recall = {}, {}, {}
    for m in methods:
        for cname, s1, name, n, beta in configs:
            if name == BASE and m != "heading":
                continue
            for q in allq:
                c = stage1[(m, s1, q["id"])]
                hits = c[:10] if not name else rr.rerank(q["query"], c, n, name, beta, k=10)
                ranks[(m, cname, q["id"])] = first_rel(hits, q)
            for sn, qs in sets.items():
                res.setdefault(sn, {}).setdefault(m, {})[cname] = metrics([ranks[(m, cname, q["id"])] for q in qs])
        for s1 in ("dense", "hybrid"):
            for n in (10, 20, 30):
                recall[f"{m}|{s1}@{n}"] = round(sum(1 for q in allq if first_rel(stage1[(m, s1, q["id"])][:n], q)) / len(allq), 3)
    json.dump({"latency_secs_per_query": lat, "candidate_recall": recall, "metrics": res,
               "ranks": {f"{a_}|{b}|{c}": r for (a_, b, c), r in ranks.items()}},
              open(os.path.join(OUT, "rerank_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# 重排评测（bge-reranker-v2-m3，CPU fp32，max_length=512）", "",
         "一阶段：dense = bge-m3/Chroma；hybrid = dense+BM25 加权融合 α=0.5（各取 Top-50）。rr@N = 对一阶段 Top-N 重排；β<1 = β·重排分 + (1-β)·一阶段归一化分。", "",
         "## 每问重排耗时（秒，无缓存实测，heading 前 8 题平均，不含模型加载）", "", "| 配置 | 秒/问 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in lat.items()]
    L += ["", "## 候选集召回率（44 题中，相关块出现在一阶段 Top-N 内的比例 = 重排可达上限）", "", "| 集合 | dense@10 | dense@20 | dense@30 | hybrid@10 | hybrid@20 | hybrid@30 |", "|---|---|---|---|---|---|---|"]
    for m in methods:
        L.append(f"| {m} | " + " | ".join(str(recall[f"{m}|{s}@{n}"]) for s in ("dense", "hybrid") for n in (10, 20, 30)) + " |")
    for sn in sets:
        L += ["", f"## {sn}", "", "| 集合 | 配置 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 |", "|---|---|---|---|---|---|---|"]
        for m in methods:
            for cname, r in res[sn][m].items():
                L.append(f"| {m} | {cname} | {r['Hit@1']} | {r['Hit@3']} | {r['Hit@5']} | {r['Hit@10']} | {r['MRR@10']} |")
    cols = ["dense", "hybrid", "dense+rr@20", "hybrid+rr@20", "hybrid+rr@20 β0.7"]
    L += ["", "## 逐题名次（heading；- = 前 10 未命中；⚑ = 重点关注题）", "", "| 题 | 问题 | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for q in allq:
        L.append(f"| {q['id']}{' ⚑' if q['id'] in FOCUS else ''} | {q['query'][:30]} | " + " | ".join(str(ranks[('heading', c, q['id'])] or '-') for c in cols) + " |")
    L += ["", "## 相对 hybrid 的变化（heading，hybrid+rr@20）", ""]
    for m in methods:
        ch = [(q["id"], ranks[(m, "hybrid", q["id"])], ranks[(m, "hybrid+rr@20", q["id"])]) for q in allq]
        L.append(f"- {m}：改善 {[x for x in ch if (x[2] or 99) < (x[1] or 99)]}；退步 {[x for x in ch if (x[2] or 99) > (x[1] or 99)]}")
    open(os.path.join(OUT, "rerank_results.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    E = ["# 重排前后对比示例（heading，hybrid α=0.5 → bge-reranker-v2-m3 重排 Top-20，展示 Top-3）", ""]
    for qid in ["q06", "q25", "q32", "k09"]:
        q = next(x for x in allq if x["id"] == qid)
        c = stage1[("heading", "hybrid", qid)]
        E += [f"## {qid}：{q['query']}", f"标注：{q['source']} / {q['section']}；hybrid 名次 {ranks[('heading','hybrid',qid)] or '>10'} → 重排后 {ranks[('heading','hybrid+rr@20',qid)] or '>10'}", "",
              "重排前：", "```text", format_hits(c[:3], 150), "```", "重排后：", "```text", format_hits(rr.rerank(q["query"], c, 20, V2, k=3), 150), "```", ""]
    open(os.path.join(OUT, "rerank_examples.md"), "w", encoding="utf-8").write("\n".join(E))
    print("\n".join(L))

if __name__ == "__main__":
    main()
