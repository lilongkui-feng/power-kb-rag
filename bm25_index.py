# -*- coding: utf-8 -*-
"""BM25 关键词索引（与 Chroma 集合同步：同一份 chunks_*.jsonl、同一 chunk_id、同一元数据/过滤语法）

用法：
  python bm25_index.py                  # 构建/更新 heading,fixed,recursive -> bm25_index/<method>.pkl
  python bm25_index.py --methods heading --rebuild
  python bm25_index.py --tokenize "GIS 回路电阻测试电流不小于300A，见8.2条"   # 查看分词
分词：
- NFKC + 小写；先用正则"保护"整体 token：
  条款号 8.2 / 7.4.1.2 / A.2 / E.3；数值+单位 300a、0.5%、500μl/l、40.5kv、3i10；型号 rm6、vd4、nm1-250h、ref615、gvsopt014、dc200/100cs
  数值+单位同时额外输出纯数值（300），提高召回
- 其余中文用 jieba.cut_for_search（加载 dict/power_terms.txt 电力术语词典），英文按 [a-z]+ 切词
- 去停用词与标点；英文做极简复数归一（filters->filter）
增量：保存每块 text_hash 与分词器签名，jsonl/分词规则/词典均未变则跳过；变化则整体重建（BM25 的 idf 是全局统计，重建 ~2 s）。
"""
from __future__ import annotations
import argparse, os, pickle, re, time, unicodedata, json, logging
import jieba
from rank_bm25 import BM25Okapi

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
IDX_DIR = os.path.join(HERE, "bm25_index")
DICT = os.path.join(HERE, "dict", "power_terms.txt")
VERSION = 2
jieba.setLogLevel(logging.WARNING)
_jieba_ready = False

def _init_jieba():
    global _jieba_ready
    if not _jieba_ready:
        if os.path.exists(DICT):
            jieba.load_userdict(DICT)
        _jieba_ready = True

UNITS = r"(?:%|‰|μl/l|ul/l|ppm|mm|cm|km|m/s|m|kva|mva|kvar|kv|mv|v|ka|ma|a|kw|mw|w|mω|ω|hz|khz|ms|s|min|h|°c|℃|k|bar|mpa|kpa|pa|ah|kg|g|n·m|nm)"
PROTECT = re.compile(
    r"(?P<num>(?<![a-z\d.])\d+(?:\.\d+)?\s?" + UNITS + r"(?![a-z0-9]))"         # 300a 0.5% 500μl/l 1.5 m/s
    r"|(?P<model>(?<![a-z0-9])[a-z]{1,8}\d+[a-z0-9]*(?:[-/][a-z0-9]+)*(?![a-z0-9]))"  # rm6 vd4 ref615 nm1-250h dc200/100cs sf6
    r"|(?P<i10>(?<![a-z0-9])\d*i10(?![a-z0-9]))"
    r"|(?P<clause>(?<![\d.a-z])(?:[a-k]\.\d+(?:\.\d+)*|\d+(?:\.\d+){1,4})(?![\d.]*\d))"  # 8.2 7.4.1.2 a.2
)
STOP_ZH = set("第 条 见 章 节 的 了 和 与 及 或 等 在 是 为 对 以 应 宜 可 按 由 其 中 时 后 前 上 下 内 外 不 并 将 被 从 向 于 之 该 本 各 个 每 所 有 无 也 都 而 则 若 如 即 又 此 这 那 些 哪 哪些 什么 怎么 怎样 如何 多少 多久 几 吗 呢 吧 啊 要 需要 进行 应该 一 二 三 一个 什么样 是否 能 会 还 就 用 使用 及其 以及 规定 要求".split())
STOP_EN = set("a an the of to in on at for by with and or not is are was were be been being as from that this these those it its into than then there their which what how when where who whom why do does did can could should would may might must shall will i you we they he she our your if about per via also any all each such other".split())
PUNCT = re.compile(r"^[\W_]+$")

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return s.replace("µ", "μ")

def _en_word(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w

def tokenize(text: str) -> list[str]:
    _init_jieba()
    s = _norm(text)
    toks, pos = [], 0
    def plain(seg: str):
        for part in re.findall(r"[a-z]+|[\u4e00-\u9fff]+|\d+", seg):
            if part[0].isascii() and part.isalpha():
                if part not in STOP_EN and len(part) > 1:
                    toks.append(_en_word(part))
            elif part.isdigit():
                toks.append(part)
            else:
                for w in jieba.cut_for_search(part):
                    if w and w not in STOP_ZH and not PUNCT.match(w):
                        toks.append(w)
    for m in PROTECT.finditer(s):
        plain(s[pos:m.start()])
        t = re.sub(r"\s", "", m.group(0))
        toks.append(t)
        if m.lastgroup == "num":                                   # 300a -> 另加 300
            toks.append(re.match(r"\d+(?:\.\d+)?", t).group(0))
        elif m.lastgroup == "model":                               # 型号也拆出字母前缀与整体之外的子部件
            for p in re.split(r"[-/]", t):
                if p != t and len(p) > 1:
                    toks.append(p)
        pos = m.end()
    plain(s[pos:])
    return toks

def exact_terms(query: str) -> list[str]:
    """查询中的"精确词"：型号/条款号/数值+单位/I10 类，以及纯 ASCII 缩写（NETD、GIS 不算，太常见）"""
    s = _norm(query)
    return [re.sub(r"\s", "", m.group(0)) for m in PROTECT.finditer(s) if m.lastgroup != "model" or not re.fullmatch(r"sf6", m.group(0))]

def auto_bm25_weight(query: str) -> float:
    return 1.0 if exact_terms(query) else 0.5

def _load_chunks(method: str, include_docx=False):
    from embed_index import _meta, embed_input, load_chunks
    return load_chunks(method, include_docx), _meta, embed_input

def _tok_sig() -> str:
    """分词器签名 = 本文件 + 词典内容的哈希；分词规则或词典一改就自动重建"""
    import hashlib
    h = hashlib.sha1(open(__file__, "rb").read())
    if os.path.exists(DICT):
        h.update(open(DICT, "rb").read())
    return h.hexdigest()

def index_path(method: str) -> str:
    return os.path.join(IDX_DIR, f"{method}.pkl")

def build(method: str, rebuild=False, include_docx=False) -> dict:
    cs, _meta, embed_input = _load_chunks(method, include_docx)
    metas = [_meta(c) for c in cs]
    sig = [m["text_hash"] for m in metas]
    p = index_path(method)
    if not rebuild and os.path.exists(p):
        old = pickle.load(open(p, "rb"))
        if old.get("version") == VERSION and old.get("sig") == sig and old.get("tok_sig") == _tok_sig():
            print(f"[bm25:{method}] 未变化，跳过（{len(cs)} 块）")
            return {"method": method, "chunks": len(cs), "rebuilt": False}
    t = time.time()
    # 与 dense 一致：索引文本 = 来源/章节前缀 + 正文（前缀让"RM6""8.2 相对温差法"等标题词也能命中）
    corpus = [tokenize(embed_input(c)) for c in cs]
    bm = BM25Okapi(corpus, k1=1.5, b=0.75)
    os.makedirs(IDX_DIR, exist_ok=True)
    pickle.dump({"version": VERSION, "method": method, "ids": [c["chunk_id"] for c in cs], "metas": metas,
                 "docs": [c["text"] for c in cs], "bm25": bm, "sig": sig, "tok_sig": _tok_sig()},
                open(p, "wb"), protocol=pickle.HIGHEST_PROTOCOL)
    secs = time.time() - t
    print(f"[bm25:{method}] 构建 {len(cs)} 块，平均 {sum(map(len, corpus)) / len(corpus):.0f} token/块，{secs:.1f}s -> {p}")
    return {"method": method, "chunks": len(cs), "rebuilt": True, "secs": round(secs, 1)}

# ---------- 查询 ----------
_cache = {}
def invalidate(method: str | None = None):
    """索引文件被重建后，丢弃进程内缓存"""
    if method:
        _cache.pop(method, None)
    else:
        _cache.clear()

def load(method: str) -> dict:
    p = index_path(method)
    if method in _cache and _cache[method].get("_mtime") != (os.path.getmtime(p) if os.path.exists(p) else None):
        _cache.pop(method)                                   # 其他进程/页面重建了索引：自动重新加载
    if method not in _cache:
        if not os.path.exists(p):
            raise FileNotFoundError(f"{p} 不存在，请先运行 python bm25_index.py --methods {method}")
        _cache[method] = pickle.load(open(p, "rb"))
        _cache[method]["_mtime"] = os.path.getmtime(p)
    return _cache[method]

def _cmp(v, cond) -> bool:
    if not isinstance(cond, dict):
        return v == cond
    for op, x in cond.items():
        ok = {"$eq": lambda: v == x, "$ne": lambda: v != x, "$in": lambda: v in x, "$nin": lambda: v not in x,
              "$gt": lambda: v > x, "$gte": lambda: v >= x, "$lt": lambda: v < x, "$lte": lambda: v <= x}[op]()
        if not ok:
            return False
    return True

def match_where(meta: dict, where: dict | None) -> bool:
    """Chroma where 语法子集：$and/$or + $eq/$ne/$in/$nin/$gt/$gte/$lt/$lte + 简写等值"""
    if not where:
        return True
    for k, v in where.items():
        if k == "$and":
            if not all(match_where(meta, w) for w in v): return False
        elif k == "$or":
            if not any(match_where(meta, w) for w in v): return False
        elif not _cmp(meta.get(k), v):
            return False
    return True

def search(query: str, method: str = "heading", n: int = 50, where: dict | None = None) -> list[dict]:
    idx = load(method)
    qt = tokenize(query)
    if not qt:
        return []
    scores = idx["bm25"].get_scores(qt)
    cand = [i for i in range(len(scores)) if scores[i] > 0 and match_where(idx["metas"][i], where)]
    cand.sort(key=lambda i: -scores[i])
    return [{"rank": r + 1, "score": round(float(scores[i]), 4), "chunk_id": idx["ids"][i], "text": idx["docs"][i],
             "metadata": idx["metas"][i]} for r, i in enumerate(cand[:n])]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="heading,fixed,recursive")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--include-docx", action="store_true")
    ap.add_argument("--tokenize", default=None)
    a = ap.parse_args()
    if a.tokenize:
        print(tokenize(a.tokenize))
    else:
        for m in a.methods.split(","):
            build(m.strip(), a.rebuild, a.include_docx)
