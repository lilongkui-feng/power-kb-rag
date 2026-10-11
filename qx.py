# -*- coding: utf-8 -*-
"""查询扩展：跨语言改写（xlang）+ 多查询（multiq），多路召回 → RRF 合并去重 → 用【原问题】统一重排。

xlang:  none | dict（术语词典 dict/term_zh_en.tsv 替换）| llm（本地 ollama 3B 翻译，结果缓存；失败回退 dict）
multiq: none | rule（规则拆子问题 + 按意图补“步骤/限值/周期/注意事项”子查询）| llm（本地 3B 生成 2–3 个子查询，缓存）
各开关独立；retrieve.search(..., xlang=, multiq=) 调用这里的 stage1()。只用本地能力，不调云端 API。
"""
from __future__ import annotations
import json, os, re, hashlib, unicodedata, threading

HERE = os.path.dirname(os.path.abspath(__file__))
DICT = os.path.join(HERE, "dict", "term_zh_en.tsv")
CACHE = os.path.join(HERE, "emb_cache", "qx_llm.json")
_lock = threading.Lock()
CJK = re.compile(r"[\u4e00-\u9fff]")

def detect_lang(q: str) -> str:
    """中文字符占可见字符 ≥15% 判为 zh（中英混写的问句按中文处理）"""
    vis = [c for c in q if not c.isspace()]
    return "zh" if vis and sum(bool(CJK.match(c)) for c in vis) / len(vis) >= 0.15 else "en"

_d = None
def _dict():
    global _d
    if _d is None:
        z2e, e2z = {}, {}
        for line in open(DICT, encoding="utf-8"):
            if not line.strip() or line.startswith("#") or "\t" not in line:
                continue
            zh, en = line.rstrip("\n").split("\t", 1)
            alts = [x.strip().lower() for x in en.split("|") if x.strip()]
            z2e[zh] = alts
            for a in alts:
                e2z.setdefault(a, zh)
        _d = (z2e, e2z, sorted(z2e, key=len, reverse=True), sorted(e2z, key=len, reverse=True))
    return _d

KEEP = re.compile(r"[A-Za-z][A-Za-z0-9/\-.]*\d[A-Za-z0-9/\-.]*|\d+(?:\.\d+)?\s*(?:kV|V|A|kA|mA|MPa|kPa|%|℃|°C|μL/L|ppm|Hz|mm|ms|s|min|h)?|[A-Z]{2,}[A-Za-z0-9]*")

def zh2en(q: str, alts: int = 2) -> str:
    """最长匹配替换中文术语，输出英文关键词串（保留型号/数值/英文缩写）；未覆盖的中文丢弃"""
    z2e, _, zks, _ = _dict()
    s = unicodedata.normalize("NFKC", q)
    out, i = [], 0
    keep = [m.group(0) for m in KEEP.finditer(s)]
    while i < len(s):
        for k in zks:
            if s.startswith(k, i):
                out.extend(z2e[k][:alts]); i += len(k); break
        else:
            i += 1
    words = list(dict.fromkeys(keep + out))
    return " ".join(words)

def _stem(w: str) -> str:
    for suf in ("ings", "ing", "ions", "ion", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w

def _stem_phrase(p: str) -> str:
    return " ".join(_stem(w) for w in re.split(r"[\s\-]+", p) if w)

_es = None
def en2zh(q: str) -> str:
    """英文短语（词干化后最长匹配，词边界）→ 中文术语；保留型号/数值"""
    global _es
    _, e2z, _, _ = _dict()
    if _es is None:
        m = {}
        for k, z in e2z.items():
            m.setdefault(_stem_phrase(k), z)
        _es = (m, sorted(m, key=lambda x: -len(x.split())))
    m, keys = _es
    s = " " + _stem_phrase(re.sub(r"[^\w/.%\-]+", " ", unicodedata.normalize("NFKC", q).lower())) + " "
    out = [x.group(0) for x in KEEP.finditer(q)]
    for k in keys:
        pat = f" {k} "
        while pat in s:
            out.append(m[k]); s = s.replace(pat, " | ", 1)
    return " ".join(dict.fromkeys(out))

# ---------- 本地 3B（可选，带缓存） ----------
def _cache():
    if not hasattr(_cache, "d"):
        _cache.d = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    return _cache.d

from config import settings as _cfg
QX_PROVIDER = _cfg().qx_llm_provider   # local=ollama 3B；siliconflow=云端 V3（key 只从环境变量读）

def _llm(kind: str, prompt: str, max_tokens: int = 120) -> str | None:
    prov = QX_PROVIDER
    key = hashlib.sha1((f"{kind}|{prompt}" if prov == "local" else f"{prov}|{kind}|{prompt}").encode()).hexdigest()
    c = _cache()
    if key in c:
        return c[key]
    import httpx
    if prov != "local":
        import rag
        try:
            txt, _ = rag.call_llm([{"role": "user", "content": prompt}], rag.llm_config(prov), max_tokens=max_tokens, temperature=0.0)
            txt = txt.strip()
        except Exception:
            return None
        with _lock:
            c[key] = txt
            json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        return txt
    try:
        r = httpx.post(_cfg().local_llm_url + "/chat/completions", timeout=120,
                       json={"model": _cfg().qx_llm_model, "temperature": 0, "max_tokens": max_tokens,
                             "messages": [{"role": "user", "content": prompt}]})
        txt = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
    with _lock:
        c[key] = txt
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return txt

def translate(q: str, mode: str = "dict") -> str:
    lang = detect_lang(q)
    if mode == "llm":
        z2e, _, zks, _ = _dict()
        if lang == "zh":
            hint = "；".join(f"{k}={z2e[k][0]}" for k in zks if k in q)[:300]
            p = f"把下面的电力设备运维问题翻译成英文，只输出译文。术语对照：{hint}\n问题：{q}"
        else:
            p = f"把下面的电力设备运维问题翻译成中文，只输出译文。\n问题：{q}"
        t = _llm("xlate", p)
        if t:
            return t.splitlines()[0].strip()
    return zh2en(q) if lang == "zh" else en2zh(q)

# ---------- 多查询 ----------
ASPECT = [(re.compile(r"步骤|如何|怎么|怎样|程序|流程|how (to|do|should|can)|steps|procedure"), ("操作步骤", "steps procedure")),
          (re.compile(r"多少|限值|要求|不小于|不大于|范围|数值|what is the rated|value|limit"), ("限值 要求", "limit value requirement")),
          (re.compile(r"多久|周期|频率|间隔|how often|interval"), ("周期", "interval")),
          (re.compile(r"注意|安全|禁止|warning|caution|safety"), ("注意事项", "safety precautions"))]

def rule_subqueries(q: str) -> list[str]:
    lang = detect_lang(q)
    parts = [p.strip(" ，,。") for p in re.split(r"[？?；;]|\(\d\)|（\d）|，(?=(?:并|同时|以及|此时|若|如果|应如何|如何|怎么|是否|有什么|多少))", q) if p and p.strip()]
    z2e, _, zks, _ = _dict()
    ents = [m.group(0) for m in KEEP.finditer(q)][:2]
    if lang == "zh":
        ents += [k for k in zks if len(k) >= 2 and k in q][:2]
    subj = " ".join(dict.fromkeys(ents)) or re.split(r"[，,？?]", q)[0][:16]
    subs = []
    if len(parts) > 1:
        for p in parts:
            if len(p) < 4:
                continue
            subs.append(p if any(e in p for e in ents[:1]) else f"{subj} {p}")
    for rx, (zh, en) in ASPECT:
        if rx.search(q.lower()):
            subs.append(f"{subj} {zh if lang == 'zh' else en}")
    return [s for s in dict.fromkeys(subs) if s != q][:4]

def llm_subqueries(q: str) -> list[str]:
    t = _llm("multiq", f"把下面的运维问题拆成 2-3 个便于检索的独立子查询（每行一个，不编号，不解释）：\n{q}", 150)
    if not t:
        return rule_subqueries(q)
    return [re.sub(r"^[\d.、\-\s*]+", "", x).strip() for x in t.splitlines() if len(x.strip()) >= 4][:3]

EN_DOC = re.compile(r"vd4|safe\s*ring|safe\s*plus|sm6|siprotec|digsi|galaxy|gvs|7sj|abb|schneider|siemens", re.I)   # 只有英文手册的设备/厂商
ZH_DOC = re.compile(r"zf12b|nm1|rm6|平高|正泰|施耐德|dl/?t|南方电网|csg", re.I)                                          # 只有中文资料的设备/标准

def need_xlang(q: str) -> bool:
    """auto 门控：中文问句点名英文手册设备才加英文改写；英文问句未点名英文手册设备（或点名中文资料）才加中文改写"""
    if detect_lang(q) == "zh":
        return bool(EN_DOC.search(q))
    return bool(ZH_DOC.search(q)) or not EN_DOC.search(q)

XLANG_W = 0.7

def variants(q: str, xlang: str = "none", multiq: str = "none") -> list[tuple[str, float]]:
    """返回 [(查询, RRF 权重)]，原问题权重 1.0；xlang: dict | llm | auto（门控+词典）| auto_llm（门控+3B）"""
    out = [(q, 1.0)]
    if xlang and xlang != "none" and (not xlang.startswith("auto") or need_xlang(q)):
        t = translate(q, "llm" if xlang.endswith("llm") else "dict")
        if t and t.strip() and t.strip() != q:
            out.append((t, XLANG_W))
    if multiq and multiq != "none":
        for s in (llm_subqueries(q) if multiq == "llm" else rule_subqueries(q)):
            out.append((s, 0.6))
    return out

def stage1(query: str, n: int, collection: str, filters=None, xlang="none", multiq="none", rrf_k: int = 60, per_n: int = 30, **kw) -> list[dict]:
    """每个改写各跑一次 hybrid_retrieve（dense+BM25 融合）取 per_n，按名次 RRF 合并去重，返回前 n；
    score = Σ w/(rrf_k+rank)，供后续重排的 β 混合使用；qx_variants 记录改写。"""
    from retrieve import hybrid_retrieve
    if xlang in ("mismatch", "cap"):          # 两个门控变体都用 LLM 翻译
        return _stage1_gated(query, n, collection, filters, gate=xlang, rrf_k=rrf_k, per_n=per_n, **kw)
    vs = variants(query, xlang, multiq)
    pool = {}
    for v, w in vs:
        for h in hybrid_retrieve(v, per_n, collection, filters, **kw):
            e = pool.setdefault(h["chunk_id"], dict(h, score=0.0, qx_from=[]))
            e["score"] += w / (rrf_k + h["rank"])
            e["qx_from"].append(v[:30])
    out = sorted(pool.values(), key=lambda e: -e["score"])[:n]
    for i, e in enumerate(out):
        e["rank"] = i + 1
        e["score"] = round(e["score"], 6)
    if out:
        out[0]["qx_variants"] = [v for v, _ in vs]
    return out

def _stage1_gated(query, n, collection, filters, gate, rrf_k=60, per_n=30, **kw):
    """mismatch：原句召回 Top-5 中与问句同语言的文档 <3 个时才加译句（语言不一致 → 跨语言）；
    cap：总是加译句，但译句独有的候选最多占重排池 30%，其余位置留给原句召回"""
    from retrieve import hybrid_retrieve
    orig = hybrid_retrieve(query, per_n, collection, filters, **kw)
    lang = detect_lang(query)
    if gate == "mismatch":
        same = sum((h.get("metadata", {}).get("lang") or "zh") == lang for h in orig[:5])
        if same >= 3:
            out = orig[:n]
            for i, h in enumerate(out):
                h["rank"] = i + 1
            return out
    t = translate(query, "llm")
    trans = hybrid_retrieve(t, per_n, collection, filters, **kw) if t and t.strip() != query else []
    if gate == "cap":
        ids = {h["chunk_id"] for h in orig}
        extra = [h for h in trans if h["chunk_id"] not in ids][: int(n * 0.3)]
        out = orig[: n - len(extra)] + extra
    else:
        pool = {}
        for lst in (orig, trans):
            for h in lst:
                e = pool.setdefault(h["chunk_id"], dict(h, score=0.0)); e["score"] += 1.0 / (rrf_k + h["rank"])
        out = sorted(pool.values(), key=lambda e: -e["score"])[:n]
    for i, h in enumerate(out):
        h["rank"] = i + 1
    if out:
        out[0]["qx_variants"] = [query, t]
    return out

if __name__ == "__main__":
    import sys
    for q in sys.argv[1:] or ["正常运行条件下，VD4真空断路器多久检查一次？", "How often should a VD4 vacuum circuit-breaker be inspected?",
                               "在SM6-24开关柜中，如果发现电缆连接处硅胶帽未正确展开，同时需要抽出断路器进行维护，应如何正确处理？"]:
        print(detect_lang(q), "|", q, "\n  dict:", translate(q), "\n  sub:", rule_subqueries(q))
