# -*- coding: utf-8 -*-
"""检索评测：eval_questions.jsonl -> Hit@1/3/5、MRR@10（三个集合对比）
相关性判定（与切分方式无关）：返回块的 source 与标注一致，且块文本包含该题任一 anchor（标注的目标条款中的特征原文，去空白比较）。
另给出宽松指标 SrcHit@k：只要求 source 一致。
用法：python eval_retrieval.py [--methods heading,fixed,recursive] [--k 10]
输出：output/eval_results.json、output/eval_results.md、output/retrieval_examples.md
"""
from __future__ import annotations
import argparse, json, os, re, time
from embed_index import get_model
from retrieve import retrieve, format_hits

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
n = lambda s: re.sub(r"\s", "", s)

def relevant(hit, q) -> bool:
    return hit["source"] == q["source"] and any(n(a) in n(hit["text"]) for a in q["anchors"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="heading,fixed,recursive")
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(os.path.join(HERE, "eval_questions.jsonl"), encoding="utf-8") if l.strip()]
    m = get_model()
    t = time.time()
    qvecs = m.encode([q["query"] for q in qs], normalize_embeddings=True, convert_to_numpy=True, batch_size=16)
    enc_secs = time.time() - t
    results, per_q = {}, {q["id"]: {"query": q["query"], "lang": q["lang"], "gold": f"{q['source']} / {q['section']}"} for q in qs}
    lat = {}
    for meth in [x.strip() for x in a.methods.split(",") if x.strip()]:
        ranks, src_ranks = [], []
        t = time.time()
        for q, v in zip(qs, qvecs):
            hits = retrieve(q["query"], a.k, meth, query_vec=v)
            r = next((h["rank"] for h in hits if relevant(h, q)), None)
            sr = next((h["rank"] for h in hits if h["source"] == q["source"]), None)
            ranks.append(r); src_ranks.append(sr)
            per_q[q["id"]][meth] = {"rank": r, "src_rank": sr,
                                    "top3": [f"{h['score']:.3f} {h['source'][:40]} | {h['heading_path'][:50]} | p{h['page_start']}" for h in hits[:3]]}
        lat[meth] = round((time.time() - t) / len(qs) * 1000, 1)
        def agg(rs, sub=None):
            idx = [i for i, q in enumerate(qs) if sub is None or q["lang"] == sub]
            rr = [rs[i] for i in idx]
            return {f"Hit@{k}": round(sum(1 for r in rr if r and r <= k) / len(rr), 3) for k in (1, 3, 5, 10)} | \
                   {"MRR@10": round(sum(1 / r for r in rr if r) / len(rr), 3), "n": len(rr)}
        results[meth] = {"all": agg(ranks), "zh": agg(ranks, "zh"), "en": agg(ranks, "en"),
                         "SrcHit@1": round(sum(1 for r in src_ranks if r == 1) / len(qs), 3),
                         "SrcHit@5": round(sum(1 for r in src_ranks if r and r <= 5) / len(qs), 3),
                         "query_latency_ms(chroma)": lat[meth]}
    json.dump({"n_questions": len(qs), "query_encode_secs_total": round(enc_secs, 2), "metrics": results, "per_question": per_q},
              open(os.path.join(OUT, "eval_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meths = list(results)
    L = ["# 检索评测结果（bge-m3 dense + Chroma cosine）", "",
         f"评测集：{len(qs)} 题（中文 {sum(q['lang'] == 'zh' for q in qs)}，英文 {sum(q['lang'] == 'en' for q in qs)}；含 2 道跨语言题）。"
         "相关 = 同一文件且块内含标注条款的特征原文（anchor）。", "",
         "| 集合 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | 中文 Hit@5 | 英文 Hit@5 | 文件级 Hit@1 | 文件级 Hit@5 | 单次查询(ms) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for mth in meths:
        r = results[mth]; al = r["all"]
        L.append(f"| {mth} | {al['Hit@1']} | {al['Hit@3']} | {al['Hit@5']} | {al['Hit@10']} | {al['MRR@10']} | "
                 f"{r['zh']['Hit@5']} | {r['en']['Hit@5']} | {r['SrcHit@1']} | {r['SrcHit@5']} | {r['query_latency_ms(chroma)']} |")
    L += ["", "## 每题首个相关结果的排名（- 表示前 10 未命中）", "", "| 题 | 问题 | " + " | ".join(meths) + " |", "|---|---|" + "---|" * len(meths)]
    for qid, d in per_q.items():
        L.append(f"| {qid} | {d['query'][:40]} | " + " | ".join(str(d[mt]['rank'] or '-') for mt in meths) + " |")
    L += ["", "## heading 集合未进前 1 的题（Top-3 明细）", ""]
    for qid, d in per_q.items():
        if "heading" in d and (d["heading"]["rank"] or 99) > 1:
            L += [f"**{qid}** {d['query']}  （标注：{d['gold']}；heading 排名 {d['heading']['rank'] or '>10'}）", ""]
            L += [f"- {x}" for x in d["heading"]["top3"]] + [""]
    open(os.path.join(OUT, "eval_results.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    # 检索示例
    ex_ids = ["q01", "q07", "q23", "q25", "q31"]
    E = ["# 检索示例（heading 集合，Top-3）", ""]
    for q, v in zip(qs, qvecs):
        if q["id"] in ex_ids:
            hits = retrieve(q["query"], 3, "heading", query_vec=v)
            E += [f"## {q['id']}：{q['query']}", f"标注：{q['source']} / {q['section']}", "", "```text", format_hits(hits, 220), "```", ""]
    open(os.path.join(OUT, "retrieval_examples.md"), "w", encoding="utf-8").write("\n".join(E))
    print("\n".join(L[:4 + len(meths) + 2]))

if __name__ == "__main__":
    main()
