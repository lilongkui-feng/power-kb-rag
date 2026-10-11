# -*- coding: utf-8 -*-
"""检索后上下文扩展（父子块）。
expand="none"     ：原样
expand="neighbor" ：命中块 + 同文档前后相邻正文块
expand="parent"   ：命中块所在条款（同一 heading_path 的连续正文块）整体返回；超过 max_chars 时以命中块为中心向两侧扩到上限
表格块（table / table_row）已在 retrieve.search 中展开为整表，这里不动。
同一父块只保留排名最高的那条（后面的命中合并进去，ctx_hits 记录被合并的 chunk_id），总上下文受 total_chars 约束（超出后其余命中保持原文）。"""
import json, os, re
from functools import lru_cache
HERE = os.path.dirname(os.path.abspath(__file__))

@lru_cache(maxsize=8)
def _index(method: str, sig: float):
    files = [os.path.join(HERE, "output", f"chunks_{method}.jsonl"), os.path.join(HERE, "uploads", f"chunks_uploaded_{method}.jsonl")]
    files[1] = _upload_file(method)
    by_src, pos = {}, {}
    for f in files:
        if not os.path.exists(f):
            continue
        for l in open(f, encoding="utf-8"):
            c = json.loads(l)
            if c.get("chunk_type") in ("table", "table_row"):
                continue
            by_src.setdefault(c["source"], []).append(c)
    for src, cs in by_src.items():
        cs.sort(key=lambda c: c["chunk_id"])
        for i, c in enumerate(cs):
            pos[c["chunk_id"]] = (src, i)
    return by_src, pos

def _upload_file(method):
    name = {"heading": "chunks_uploaded.jsonl", "heading_v2": "chunks_uploaded_v2.jsonl"}.get(method, f"chunks_uploaded_{method}.jsonl")
    return os.path.join(HERE, "uploads", name)

def _sig(method):
    fs = [os.path.join(HERE, "output", f"chunks_{method}.jsonl"), _upload_file(method)]
    return sum(os.path.getmtime(f) for f in fs if os.path.exists(f))

def _join(texts):
    out = texts[0]
    for t in texts[1:]:                       # 去掉切分重叠：前块结尾 == 后块开头
        k = next((k for k in range(min(200, len(t), len(out)), 9, -1) if out.endswith(t[:k])), 0)
        out += ("" if k else "\n") + t[k:]
    return out

def _span(cs, i, lo, hi, max_chars):
    """在 [lo, hi] 内以 i 为中心扩展，直到长度上限"""
    a = b = i; n = len(cs[i]["text"])
    while True:
        grown = False
        for j in (b + 1, a - 1):
            if lo <= j <= hi and (j == b + 1 or j == a - 1) and n + len(cs[j]["text"]) <= max_chars:
                n += len(cs[j]["text"]); a, b = min(a, j), max(b, j); grown = True
        if not grown:
            return a, b

def _group(cs, i, ok):
    lo = hi = i
    while lo > 0 and ok(cs[lo - 1].get("heading_path") or ""):
        lo -= 1
    while hi < len(cs) - 1 and ok(cs[hi + 1].get("heading_path") or ""):
        hi += 1
    return lo, hi

def expand_hits(hits, method="heading_v2", mode="parent", max_chars=2000, total_chars=8000):
    if mode in (None, "none") or not hits:
        return hits
    by_src, pos = _index(method, _sig(method))
    out, covered, used = [], {}, 0
    for h in hits:
        m = h.get("metadata") or {}
        if m.get("chunk_type") in ("table", "table_row") or h["chunk_id"] not in pos:
            out.append(h); used += len(h["text"]); continue
        src, i = pos[h["chunk_id"]]; cs = by_src[src]
        if (src, i) in covered:                 # 已被前面更高名次的父块覆盖 → 合并
            covered[(src, i)].setdefault("ctx_hits", []).append(h["chunk_id"]); continue
        if mode == "neighbor":
            a, b = _span(cs, i, max(0, i - 1), min(len(cs) - 1, i + 1), max_chars)
        else:
            hp = cs[i].get("heading_path") or ""
            lo, hi = _group(cs, i, lambda p: p == hp)
            if lo == hi and " > " in hp:            # 本条款只有一块 → 上升一级，取父条款下的连续块
                pre = hp.rsplit(" > ", 1)[0]
                lo, hi = _group(cs, i, lambda p: p == pre or p.startswith(pre + " > "))
            a, b = _span(cs, i, lo, hi, max_chars)
        if used + sum(len(cs[j]["text"]) for j in range(a, b + 1)) > total_chars:
            a = b = i                           # 总预算用完：保持原块
        h = dict(h)
        if b > a:
            h.update(text=_join([cs[j]["text"] for j in range(a, b + 1)]), expanded_ctx=mode,
                     ctx_ids=[cs[j]["chunk_id"] for j in range(a, b + 1)])
            h["metadata"] = dict(m, page_start=min(cs[j]["page_start"] for j in range(a, b + 1)),
                                 page_end=max(cs[j].get("page_end") or cs[j]["page_start"] for j in range(a, b + 1)))
        for j in range(a, b + 1):
            covered[(src, j)] = h
        used += len(h["text"]); out.append(h)
    for r, h in enumerate(out, 1):
        h["rank"] = r
    return out
