# -*- coding: utf-8 -*-
"""用当前默认检索（heading + hybrid α=0.5 + bge-reranker-v2-m3 重排 Top-20，β=0.8）对 eval_set_50 跑检索指标（不调用 LLM）
命中判定（块级）：返回块 chunk_id ∈ 题目 all_chunk_ids，或 同一 source 且块文本（去空白）包含 evidence；
另给文档级命中（source 相同）。输出 output/eval50_retrieval.md 与 output/eval50_retrieval.json"""
import json, os, re, time, collections
os.environ.setdefault("HF_HOME", "/workspace/hf_cache")
from retrieve import search
import rerank as rr
HERE = os.path.dirname(os.path.abspath(__file__))
sq = lambda s: re.sub(r"\s+", "", s)
K = 10

def rank_of(r, hits, doc_level=False):
    ev = sq(r["evidence"])
    for i, h in enumerate(hits, 1):
        if h["source"] != r["source"]:
            continue
        if doc_level or h["chunk_id"] in r.get("all_chunk_ids", []) or ev in sq(h["text"]):
            return i
    return None

def metrics(ranks):
    n = len(ranks) or 1
    return {"n": len(ranks), "hit1": sum(1 for x in ranks if x and x <= 1) / n, "hit3": sum(1 for x in ranks if x and x <= 3) / n,
            "hit5": sum(1 for x in ranks if x and x <= 5) / n, "mrr": sum(1 / x for x in ranks if x) / n}

def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "eval_set_50.jsonl"), encoding="utf-8")]
    search("预热", k=3)                                           # 预热模型
    res, t0 = [], time.time()
    for r in rows:
        t = time.time()
        hits = search(r["question"], k=K)
        el = time.time() - t
        if r["category"] == "拒答":
            res.append({"id": r["id"], "category": r["category"], "top1": hits[0]["source"] if hits else "", "top1_rerank": hits[0].get("rerank_score") if hits else None, "secs": round(el, 2)})
            continue
        res.append({"id": r["id"], "category": r["category"], "lang": r["lang"], "rank": rank_of(r, hits), "doc_rank": rank_of(r, hits, True),
                    "top1": f"{hits[0]['source']}｜{hits[0]['heading_path']}", "top1_rerank": hits[0].get("rerank_score"), "secs": round(el, 2)})
    rr.save_cache()
    main_rows = [x for x in res if x["category"] != "拒答"]
    groups = collections.OrderedDict([("全部 50", main_rows)] + [(c, [x for x in main_rows if x["category"] == c]) for c in ("查参数", "故障排查", "操作步骤")]
                                     + [("中文", [x for x in main_rows if x["lang"] == "zh"]), ("英文", [x for x in main_rows if x["lang"] == "en"])])
    L = ["# eval_set_50 检索评测（默认：heading + hybrid α=0.5 + bge-reranker-v2-m3 Top-20，β=0.8）", "",
         f"运行时间 {time.strftime('%Y-%m-%d %H:%M')}（北京时间），共 {len(res)} 问，总耗时 {time.time() - t0:.0f}s，未调用 LLM。", "",
         "块级命中 = 返回块为标注块（或同文档且包含 evidence 原文）；文档级命中 = 返回块来自标注文档。MRR 取 Top-10。", "",
         "| 分组 | 题数 | 块 Hit@1 | 块 Hit@3 | 块 Hit@5 | 块 MRR | 文档 Hit@1 | 文档 Hit@5 |", "|---|---|---|---|---|---|---|---|"]
    summary = {}
    for g, xs in groups.items():
        m, d = metrics([x["rank"] for x in xs]), metrics([x["doc_rank"] for x in xs])
        summary[g] = {"chunk": m, "doc": d}
        L.append(f"| {g} | {m['n']} | {m['hit1']:.2f} | {m['hit3']:.2f} | {m['hit5']:.2f} | {m['mrr']:.3f} | {d['hit1']:.2f} | {d['hit5']:.2f} |")
    L += ["", "## 未进 Top-1 的题", "", "| id | 类别 | 块名次 | 文档名次 | Top-1 结果 |", "|---|---|---|---|---|"]
    for x in main_rows:
        if x["rank"] != 1:
            L.append(f"| {x['id']} | {x['category']} | {x['rank'] or '>10'} | {x['doc_rank'] or '>10'} | {x['top1']} |")
    L += ["", "## 库外拒答题（检索层面无法判断，仅列 Top-1 及重排分供设阈值参考）", "", "| id | Top-1 文档 | 重排分 |", "|---|---|---|"]
    for x in res:
        if x["category"] == "拒答":
            L.append(f"| {x['id']} | {x['top1']} | {x['top1_rerank']} |")
    ans = [x["top1_rerank"] for x in main_rows if x["rank"] == 1 and x["top1_rerank"] is not None]
    if ans:
        L += ["", f"对照：库内题 Top-1 命中时重排分最小 {min(ans):.3f}、中位数 {sorted(ans)[len(ans)//2]:.3f}。"]
    L += ["", f"平均每问检索+重排耗时 {sum(x['secs'] for x in res) / len(res):.2f}s（重排分走缓存时偏快）。"]
    open(os.path.join(HERE, "output", "eval50_retrieval.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"summary": summary, "per_question": res}, open(os.path.join(HERE, "output", "eval50_retrieval.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n".join(L))

if __name__ == "__main__":
    main()
