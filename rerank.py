# -*- coding: utf-8 -*-
"""Cross-encoder 重排：BAAI/bge-reranker-v2-m3（默认）/ BAAI/bge-reranker-base（参考）

rerank(query, hits, top_n=None, model=..., beta=1.0)
- hits: hybrid_retrieve / retrieve 的结果（已按一阶段名次排序），只对前 top_n 条重排（重排找不回候选集外的结果）
- 输入对 = (query, "【来源｜章节路径】\\n正文")，与向量/BM25 建库文本一致；max_length=512，fp32，CPU，batch=8
- rerank_score = sigmoid(logit) ∈ (0,1)；beta<1 时 final = beta*rerank_score + (1-beta)*一阶段分数(候选内 min-max 归一化)
- 每条补充 stage1_rank / stage1_score / rerank_score / rank（新名次）
- 分数缓存 emb_cache/rerank_<model>.json（键 = sha1(model, query, 文本)），评测扫描时不重复计算
"""
from __future__ import annotations
import hashlib, json, math, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "emb_cache")
DEFAULT_MODEL = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
MAX_LEN = 512
_models, _caches = {}, {}

def get_reranker(name: str = DEFAULT_MODEL):
    if name not in _models:
        from sentence_transformers import CrossEncoder
        import torch
        dev = os.environ.get("BGE_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        _models[name] = CrossEncoder(name, max_length=MAX_LEN, device=dev)   # fp32
    return _models[name]

def _cache(name):
    if name not in _caches:
        p = os.path.join(CACHE_DIR, "rerank_" + name.replace("/", "__") + ".json")
        _caches[name] = (p, json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {})
        if _caches[name][1].get("__v") != 2:
            _caches[name] = (p, {"__v": 2})   # 旧版缓存（双重 sigmoid）作废
    return _caches[name]

def save_cache(name: str = DEFAULT_MODEL):
    if name in _caches:
        p, d = _caches[name]
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump(d, open(p, "w", encoding="utf-8"))

def passage(hit: dict) -> str:
    m = hit.get("metadata", {})
    hp = m.get("heading_path") or hit.get("heading_path") or ""
    src = m.get("source") or hit.get("source", "")
    return f"【{src}" + (f"｜{hp}" if hp else "") + f"】\n{hit['text']}"

def _identity():
    import torch
    return torch.nn.Identity()   # 注意：activation_fn=None 会用模型默认 Sigmoid，这里显式取 logit 再自行 sigmoid

def score_pairs(query: str, texts: list[str], name: str = DEFAULT_MODEL, batch_size: int = 8, use_cache=True) -> list[float]:
    """返回 sigmoid 后的相关性分数"""
    _, cache = _cache(name)
    keys = [hashlib.sha1(f"{name}\x00{query}\x00{t}".encode()).hexdigest() for t in texts]
    todo = [i for i, k in enumerate(keys) if not use_cache or k not in cache]
    if todo:
        logits = get_reranker(name).predict([(query, texts[i]) for i in todo], batch_size=batch_size,
                                            show_progress_bar=False, activation_fn=_identity(), convert_to_numpy=True)   # 取原始 logit
        for i, lg in zip(todo, logits):
            cache[keys[i]] = 1.0 / (1.0 + math.exp(-float(lg)))
    return [cache[k] for k in keys]

def rerank(query: str, hits: list[dict], top_n: int | None = None, name: str = DEFAULT_MODEL,
           beta: float = 1.0, k: int | None = None, use_cache: bool = True) -> list[dict]:
    cand = [dict(h) for h in (hits[:top_n] if top_n else hits)]
    if not cand:
        return []
    t = time.time()
    rs = score_pairs(query, [passage(h) for h in cand], name, use_cache=use_cache)
    s1 = [h["score"] for h in cand]
    lo, hi = min(s1), max(s1)
    for h, r in zip(cand, rs):
        h["stage1_rank"], h["stage1_score"], h["rerank_score"] = h["rank"], h["score"], round(r, 5)
        n1 = (h["score"] - lo) / (hi - lo) if hi > lo else 1.0
        h["score"] = round(beta * r + (1 - beta) * n1, 5)
    cand.sort(key=lambda h: (-h["score"], h["stage1_rank"]))
    for i, h in enumerate(cand):
        h["rank"] = i + 1
    if cand:
        cand[0]["_rerank_secs"] = round(time.time() - t, 3)
    return cand[:k] if k else cand
