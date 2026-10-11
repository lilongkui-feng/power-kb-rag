# -*- coding: utf-8 -*-
"""检索：retrieve()（纯向量）与 hybrid_retrieve()（向量 + BM25 融合，CLI 默认 hybrid-加权融合 alpha=0.5）

用法：
  python retrieve.py "相对温差法怎么计算" -k 5                       # 默认 hybrid + 加权融合(alpha=0.5)
  python retrieve.py "GIS 回路电阻 300A" --mode bm25
  python retrieve.py "REF615" --mode hybrid --fusion rrf --rrf-k 60
  python retrieve.py "SF6气体分解物多久检测一次"            # 默认：heading + hybrid(α=0.5) + bge-reranker-v2-m3 重排 Top-20，β=0.8
  python retrieve.py "SF6气体分解物多久检测一次" --no-rerank
  python retrieve.py "How to close VD4" -c fixed --source ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf
  python retrieve.py "蓄电池核对性放电周期" --where '{"category": "标准"}' --json
filters 为 Chroma where 语法：{"source": "..."}、{"category": {"$in": ["标准", "厂商手册"]}}、
{"$and": [{"lang": "zh"}, {"page_start": {"$gte": 10}}]} 等；也接受简写 dict（多个键自动 $and）。
"""
from __future__ import annotations
import argparse, json, os, sys
from embed_index import COLLECTION, get_client, get_model

_cols = {}
def _collection(name: str):
    cname = COLLECTION.get(name) or (name if name.startswith("power_") else f"power_{name}")
    if cname not in _cols:
        _cols[cname] = get_client().get_collection(cname)
    return _cols[cname]

def _norm_filters(filters: dict | None):
    if not filters:
        return None
    if len(filters) > 1 and not any(k.startswith("$") for k in filters):
        return {"$and": [{k: v} for k, v in filters.items()]}
    return filters

def encode_query(query: str):
    return get_model().encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]

def retrieve(query: str, k: int = 5, collection: str = "heading", filters: dict | None = None,
             query_vec=None) -> list[dict]:
    """返回 [{rank, score, chunk_id, source, heading_path, page_start, page_end, text, metadata}]，score = 余弦相似度"""
    col = _collection(collection)
    qv = encode_query(query) if query_vec is None else query_vec
    res = col.query(query_embeddings=[list(map(float, qv))], n_results=k, where=_norm_filters(filters),
                    include=["documents", "metadatas", "distances"])
    out = []
    for i, (doc, meta, dist) in enumerate(zip(res["documents"][0], res["metadatas"][0], res["distances"][0])):
        out.append({"rank": i + 1, "score": round(1.0 - float(dist), 4), "chunk_id": meta["chunk_id"],
                    "source": meta["source"], "heading_path": meta.get("heading_path", ""),
                    "page_start": meta.get("page_start"), "page_end": meta.get("page_end"),
                    "text": doc, "metadata": meta})
    return out

def hybrid_retrieve(query: str, k: int = 5, collection: str = "heading", filters: dict | None = None,
                    mode: str = "hybrid", fusion: str = "weighted", rrf_k: int = 60, alpha: float = 0.5,
                    top_n: int = 50, query_vec=None, bm25_weight=1.0) -> list[dict]:
    """混合检索。
    mode: dense（只用向量）| bm25（只用关键词）| hybrid（两路各取 top_n 后融合）
    fusion: rrf -> score = Σ 1/(rrf_k + rank)；weighted -> 各路分数在本路 top_n 内 min-max 归一化，
            score = alpha*dense + (1-alpha)*bm25（缺席记 0）。alpha 只对 weighted 生效。
    默认值（weighted, alpha=0.5, top_n=50）来自 44 题评测，见 README 7.x；
    bm25_weight: RRF 中 BM25 一路的权重（dense 恒为 1），默认 1.0。"auto" = 查询含型号/条款号/数值单位等精确词时取 1.0，
            否则取 0.5（自然语言问句以语义为主）；也可传数值。
    返回每条含 rank/score（融合分）以及 dense_rank/dense_score/bm25_rank/bm25_score 便于调试。
    collection 取 heading/fixed/recursive（BM25 索引按同名方法查找）。"""
    import bm25_index
    method = next((m for m, c in COLLECTION.items() if collection in (m, c)), collection)
    where = _norm_filters(filters)
    lists = {}
    if mode in ("dense", "hybrid"):
        lists["dense"] = retrieve(query, top_n if mode == "hybrid" else k, method, filters, query_vec=query_vec)
    if mode in ("bm25", "hybrid"):
        lists["bm25"] = bm25_index.search(query, method, top_n if mode == "hybrid" else k, where)
    if mode not in ("dense", "bm25", "hybrid"):
        raise ValueError(mode)
    wb = bm25_index.auto_bm25_weight(query) if bm25_weight == "auto" else float(bm25_weight)
    return fuse(lists, k, mode, fusion, rrf_k, alpha, w_bm25=wb)

def search(query: str, k: int = 5, collection: str = "heading", filters: dict | None = None,
           mode: str = "hybrid", rerank: bool = True, rerank_top_n: int = 20, rerank_model: str | None = None,
           rerank_beta: float = 0.8, query_vec=None, rerank_use_cache: bool = True, expand_parent: bool = True,
           xlang: str = "none", multiq: str = "none", **kw) -> list[dict]:
    """统一入口：一阶段（dense/bm25/hybrid）取候选 -> 可选 cross-encoder 重排 -> （v2 集合）表格父子块展开。
    rerank=True 时先取 max(k, rerank_top_n) 个候选，对前 rerank_top_n 重排后返回前 k；
    每条含 stage1_rank/stage1_score（重排前）与 rerank_score/rank/score（重排后）。
    expand_parent：命中 chunk_type=table_row（行级描述）时把 text 换成父块（整表/行组 Markdown，含表头），
    matched_row 保留命中的行描述；同一父块只保留排名最高的一次，空位由后续候选补齐。"""
    n1 = max(k, rerank_top_n) if rerank else k
    n_out = k
    if expand_parent:
        n1 = max(n1, 3 * k) if not rerank else n1
        n_out = n1                                    # 先多取，去重后再截断到 k
    if (xlang and xlang != "none") or (multiq and multiq != "none"):   # 跨语言/多查询：多路召回 → RRF 合并 → 下面用原问题统一重排
        import qx
        hits = qx.stage1(query, n1, collection, filters, xlang=xlang, multiq=multiq, mode=mode, **kw)
    else:
        hits = hybrid_retrieve(query, n1, collection, filters, mode=mode, query_vec=query_vec, **kw)
    if rerank:
        import rerank as rr
        hits = rr.rerank(query, hits, rerank_top_n, rerank_model or rr.DEFAULT_MODEL, rerank_beta, n_out, use_cache=rerank_use_cache)
    if not expand_parent or not any((h.get("metadata") or {}).get("chunk_type") for h in hits):
        return hits[:k]
    return expand_parents(hits, collection, k)

def expand_parents(hits: list[dict], collection: str, k: int) -> list[dict]:
    need = {h["metadata"]["parent_id"] for h in hits if h["metadata"].get("chunk_type") == "table_row" and h["metadata"].get("parent_id")}
    parents = {}
    if need:
        r = _collection(collection).get(ids=list(need), include=["documents", "metadatas"])
        parents = {i: (d, m) for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])}
    out, seen = [], set()
    rr_secs = hits[0].get("_rerank_secs") if hits else None
    for h in hits:
        m = h["metadata"]
        key = m.get("parent_id") or h["chunk_id"]
        if key in seen:
            continue
        seen.add(key)
        if m.get("chunk_type") == "table_row" and key in parents:
            pd, pm = parents[key]
            h = dict(h, text=pd, matched_row=h["text"], matched_chunk_id=h["chunk_id"], chunk_id=key,
                     metadata=dict(pm, matched_row_chunk=h["chunk_id"]), expanded=True)
        out.append(h)
        if len(out) >= k:
            break
    for i, h in enumerate(out):
        h["rank"] = i + 1
        h.pop("_rerank_secs", None)
    if out and rr_secs is not None:
        out[0]["_rerank_secs"] = rr_secs
    return out

def fuse(lists: dict, k: int, mode: str = "hybrid", fusion: str = "rrf", rrf_k: int = 60, alpha: float = 0.5,
         w_dense: float = 1.0, w_bm25: float = 1.0) -> list[dict]:
    """lists = {"dense": [...], "bm25": [...]}（各路按名次排好）。评测脚本复用它对缓存的两路结果做离线融合。"""
    pool = {}
    for name, hits in lists.items():
        if not hits:
            continue
        sc = [h["score"] for h in hits]
        lo, hi = min(sc), max(sc)
        for h in hits:
            e = pool.setdefault(h["chunk_id"], {"chunk_id": h["chunk_id"], "text": h["text"], "metadata": h["metadata"],
                                                "dense_rank": None, "dense_score": None, "bm25_rank": None, "bm25_score": None,
                                                "_norm": {}})
            e[f"{name}_rank"], e[f"{name}_score"] = h["rank"], h["score"]
            e["_norm"][name] = (h["score"] - lo) / (hi - lo) if hi > lo else 1.0
    for e in pool.values():
        if mode != "hybrid":
            e["score"] = e["dense_score"] if mode == "dense" else e["bm25_score"]
        elif fusion == "rrf":
            w = {"dense": w_dense, "bm25": w_bm25}
            e["score"] = sum(w[n] / (rrf_k + e[f"{n}_rank"]) for n in ("dense", "bm25") if e[f"{n}_rank"])
        elif fusion == "weighted":
            e["score"] = alpha * e["_norm"].get("dense", 0.0) + (1 - alpha) * e["_norm"].get("bm25", 0.0)
        else:
            raise ValueError(fusion)
    out = sorted(pool.values(), key=lambda e: (-e["score"], min(r for r in (e["dense_rank"], e["bm25_rank"]) if r)))[:k]
    for i, e in enumerate(out):
        m = e.pop("_norm") and e["metadata"]
        e.update(rank=i + 1, score=round(e["score"], 5), source=m["source"], heading_path=m.get("heading_path", ""),
                 page_start=m.get("page_start"), page_end=m.get("page_end"))
    return out

def format_hits(hits: list[dict], width: int = 160) -> str:
    lines = []
    for h in hits:
        loc = f"p{h['page_start']}" + (f"-{h['page_end']}" if h["page_end"] != h["page_start"] else "")
        dbg = ""
        if "bm25_rank" in h:
            dbg = f"  (dense#{h['dense_rank'] or '-'} {h['dense_score'] if h['dense_score'] is not None else '-'} | bm25#{h['bm25_rank'] or '-'} {h['bm25_score'] if h['bm25_score'] is not None else '-'})"
        if "rerank_score" in h:
            dbg = f"  (重排前#{h['stage1_rank']} {h['stage1_score']} → rerank {h['rerank_score']})" + dbg
        lines.append(f"[{h['rank']}] {h['score']:.4f}  {h['source']}  {loc}  {h['heading_path'] or '-'}{dbg}")
        lines.append("    " + h["text"].replace("\n", " ")[:width])
    return "\n".join(lines)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("-c", "--collection", default="heading_v2", help="heading_v2（推荐）/ heading / fixed / recursive 或集合全名")
    ap.add_argument("--source", default=None, help="只检索某个文件")
    ap.add_argument("--category", default=None, help="标准 / 厂商手册 / 电网企业文件")
    ap.add_argument("--where", default=None, help="Chroma where 条件（JSON）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "bm25"])
    ap.add_argument("--fusion", default="weighted", choices=["rrf", "weighted"])
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--alpha", type=float, default=0.5, help="weighted 融合中 dense 的权重")
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--rerank", dest="rerank", action="store_true", default=True, help="用 bge-reranker 重排一阶段 Top-N（默认开启）")
    ap.add_argument("--no-rerank", dest="rerank", action="store_false", help="关闭重排（只用一阶段结果，快 ~4 s/问）")
    ap.add_argument("--rerank-top-n", type=int, default=20)
    ap.add_argument("--no-expand", dest="expand_parent", action="store_false", default=True, help="不把表格行级命中展开为整表")
    ap.add_argument("--rerank-model", default=None, help="默认 BAAI/bge-reranker-v2-m3；可选 BAAI/bge-reranker-base")
    ap.add_argument("--rerank-beta", type=float, default=0.8, help="final=β·重排分+(1-β)·一阶段归一化分；1=只用重排分")
    ap.add_argument("--bm25-weight", default="1.0", help='RRF 中 BM25 权重，数值或 auto')
    a = ap.parse_args()
    f = json.loads(a.where) if a.where else {}
    if a.source:
        f["source"] = a.source
    if a.category:
        f["category"] = a.category
    import time as _t
    t0 = _t.time()
    hits = search(a.query, a.k, a.collection, f or None, mode=a.mode, rerank=a.rerank, rerank_top_n=a.rerank_top_n, expand_parent=a.expand_parent,
                  rerank_model=a.rerank_model, rerank_beta=a.rerank_beta, fusion=a.fusion, rrf_k=a.rrf_k,
                  alpha=a.alpha, top_n=a.top_n, bm25_weight=a.bm25_weight)
    if a.rerank:
        import rerank as _rr; _rr.save_cache(a.rerank_model or _rr.DEFAULT_MODEL)
    for h in hits:
        h.pop("_rerank_secs", None)
    if a.json:
        json.dump(hits, sys.stdout, ensure_ascii=False, indent=1)
    else:
        print(format_hits(hits))
        print(f"-- 用时 {_t.time() - t0:.2f}s（含模型加载）")
