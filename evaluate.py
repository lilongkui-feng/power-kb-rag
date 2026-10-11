# -*- coding: utf-8 -*-
"""统一评测入口：检索命中率 + 回答准确率 + 引用 + 拒答 + 耗时

用法：
  python evaluate.py --tag baseline                       # 默认：heading+hybrid(α=0.5)+rerank@20 β=0.8，top_k=5，本地 qwen2.5:3b，全量 55 题
  python evaluate.py --retrieval-only --tag ret_dense --mode dense --no-rerank
  python evaluate.py --limit 5 --tag smoke
  python evaluate.py --refuse-below 0.3 --tag thr03       # 重排分阈值拒答（Top-1 重排分 < 阈值时不调 LLM，直接拒答）
  python evaluate.py --rescore output/eval_runs/<run>     # 不重跑生成，按当前规则/人工标注重算并重写报告
  python evaluate.py --judge local                        # 打开 LLM-as-judge（默认关；3B 本地模型不可靠）
缓存：output/eval_cache/gen_<配置哈希>.jsonl，按 题目id+问题 存检索结果与生成结果；中断后重跑同配置即续跑。
人工标注：output/manual_labels.jsonl（{"id","human":"正确|部分|错误","note"}），存在时报告自动/人工一致率。
"""
from __future__ import annotations
import argparse, glob, collections, hashlib, json, os, re, sys, time, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", "/workspace/hf_cache")
OUT = os.path.join(HERE, "output")
CACHE = os.path.join(OUT, "eval_cache")
RUNS = os.path.join(OUT, "eval_runs")
LABELS = os.path.join(OUT, "manual_labels.jsonl")
BASELINE = os.path.join(OUT, "baseline_scores.md")
CATS = ["查参数", "故障排查", "操作步骤"]

# ---------------- 文本归一化与自动评分 ----------------
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().replace("µ", "μ")
    s = s.replace("～", "~").replace("—", "-").replace("–", "-").replace("·", "")
    s = re.sub(r"(?<=\d)\s*(?:至|到|-)\s*(?=\d)", "~", s)                    # 30%-50% / 30%至50% -> 30%~50%
    return re.sub(r"\s+", "", s)

NUM_RE = re.compile(r"(?<![a-z\d.])\d+(?:\.\d+)?")                            # 前面紧跟字母的不算（so2、t1、k10、i10、gvsopt001）
RULES_VERSION = int(os.environ.get("EVAL_RULES", "2"))   # 2=要点等权；3=core/minor 加权（--rules 3）
CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# 同义词归一（规则 v2，人工抽查后加入）：左侧各词统一替换为右侧
SYNONYMS = {"过滤器": "滤网", "空气滤网": "滤网", "重启": "重置", "复位": "重置", "金属夹": "卡扣", "熔丝": "熔断器", "维护保养": "保养",
            "服务": "保养", "维修": "修理", "电池": "蓄电池", "蓄蓄电池": "蓄电池", "warning": "警告", "警报": "告警", "alarm": "告警",
            "不能": "不可", "无法": "不可", "过电压": "过压", "欠电压": "欠压", "直流接地": "接地"}

def canon(s: str) -> str:
    s = norm(s)
    for a, b in SYNONYMS.items():
        s = s.replace(a, b)
    return s

def nums(s: str) -> set[float]:
    t = unicodedata.normalize("NFKC", s or "").lower()
    t = re.sub(r"[一两二三四五六七八九十](?=\s*(?:年|次|个月|月|天|周|小时|分钟|只|个))", lambda m: f" {CN_NUM[m.group(0)]}", t)   # 每五年 -> 每 5年
    t = re.sub(r"(?<=\d)\s*(?:至|到|-)\s*(?=\d)", "~", t)
    return {float(x) for x in NUM_RE.findall(t)}                              # 不先去空格，避免 "than 50%" 变成 than50

STOP = set("的 了 和 与 及 或 等 应 宜 为 时 后 前 中 对 在 是 按 由 可 并 将 其 该 各 以 至 进行 要求 检查 情况 使用 采用 进行 规定 不 有 无 一次 每 个 次 a the of to and or for in on with by be is are at as".split())

def keywords(s: str) -> list[str]:
    import jieba, logging
    jieba.setLogLevel(logging.WARNING)
    t = NUM_RE.sub(" ", norm(s))
    t = re.sub(r"(%|μl/l|kv|ka|mpa|kpa|pa|mm/s|m/s|mω|kω|hz|°c|℃|min|mm|n\.m|nm|ms|v|a|h|s|k)(?![a-z])", " ", t)
    out = []
    for seg in re.findall(r"[a-z][a-z0-9]+|[\u4e00-\u9fff]+", t):
        if seg[0].isascii():
            if len(seg) >= 3 and seg not in STOP:
                out.append(seg)
        else:
            for w in jieba.cut(seg):
                if len(w) >= 2 and w not in STOP:
                    out.append(w)
                elif len(w) == 1 and w not in STOP and len(seg) == 1:
                    out.append(w)
    return list(dict.fromkeys(out))

def kp_score(kp: str, ans_n: str, ans_nums: set[float]) -> dict:
    kp = re.sub(r"[（(][A-Za-z][A-Za-z\s]*[)）]", "", kp)                     # 中文要点里的英文括注不参与关键词匹配
    ns, kws = nums(kp), [canon(w) for w in keywords(kp)]
    hit_n = [x for x in ns if any(abs(x - y) < 1e-9 for y in ans_nums)]
    num_ratio = len(hit_n) / len(ns) if ns else 1.0
    kw_hit = [w for w in kws if w in ans_n]
    kw_ratio = len(kw_hit) / len(kws) if kws else 1.0
    need = 0.34 if ns else 0.5                                                # 有数值：数值全对 + 关键词≥1/3；纯文字：关键词≥1/2
    if num_ratio == 1.0 and kw_ratio >= need:
        credit = 1.0
    elif num_ratio >= 0.5 and kw_ratio >= need:                               # v2：多数值要点答对一半以上给半分
        credit = 0.5
    else:
        credit = 0.0
    return {"kp": kp, "covered": credit == 1.0, "credit": credit, "nums": sorted(ns), "num_ok": num_ratio == 1.0,
            "kw": kws, "kw_hit": kw_hit, "kw_ratio": round(kw_ratio, 2)}

REFUSE_RE = re.compile(r"无法回答|资料不足|未(提及|涉及|包含|找到)|没有(相关|提及|涉及)")

def auto_judge(item: dict, gen: dict, th_ok=0.75, th_part=0.4) -> dict:
    refused = bool(gen.get("refused"))
    if item["category"] == "拒答":
        return {"coverage": None, "verdict": "正确" if refused else "错误", "kps": []}
    ans = re.sub(r"\[\d+(?:[,，、]\s*\d+)*\]", "", gen.get("answer", ""))
    an, anum = canon(ans), nums(ans)
    zh, en = item.get("key_points_zh"), item["key_points"]
    res = []
    for i, k in enumerate(zh or en):                                          # 英文题：中文要点与英文要点各算一次取高（回答可能中英混杂）
        r = kp_score(k, an, anum)
        if zh and i < len(en):
            r2 = kp_score(en[i], an, anum)
            r = r2 if r2["credit"] > r["credit"] else r
        res.append(r)
    cov = sum(r["credit"] for r in res) / len(res)
    core = item.get("core")                                                   # v3：core 为 key_points 下标；minor 缺失不降级
    if RULES_VERSION >= 3 and core:
        ci = [i for i in core if i < len(res)]
        mi = [i for i in range(len(res)) if i not in ci]
        cc = sum(res[i]["credit"] for i in ci) / len(ci)
        mc = sum(res[i]["credit"] for i in mi) / len(mi) if mi else cc
        cov = 0.8 * cc + 0.2 * mc
        v = "正确" if cc >= th_ok else "部分" if cov >= th_part else "错误"
        for i in ci:
            res[i]["core"] = True
    else:
        v = "正确" if cov >= th_ok else "部分" if cov >= th_part else "错误"
    note = ""
    if refused:                                                               # 库内题拒答：无实质内容记错误；先答后拒（自相矛盾）最多给“部分”
        v, note = ("部分", "答后又拒") if cov >= th_part else ("错误", "误拒")
    return {"coverage": round(cov, 3), "verdict": v, "kps": res, "note": note}

# ---------------- 评测拆分：Context Recall / 忠实度 / 归因（规则版，不调 LLM） ----------------
class _Ctx:
    """上下文的预处理（数值量、单位、中文规范化文本、英文词集合），供要点/句子跨语言匹配"""
    def __init__(self, ctx: str):
        import numcheck
        self.q = numcheck.quantities(ctx); self.d = {x.dim for x in self.q if x.dim} | numcheck.unit_mentions(ctx); self.e = numcheck.explicit_units(ctx)
        self.cn = canon(ctx); self.low = unicodedata.normalize("NFKC", ctx).lower()
        self.words = {_stem(w) for w in re.findall(r"[a-z][a-z0-9\-]+", self.low)}

def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w

def _terms(text: str):
    """要点/句子的检索词：英文按词（≥3 字母、去停用词、词干化），中文按 jieba 关键词（canon 归一）"""
    low = unicodedata.normalize("NFKC", text).lower()
    en = [_stem(w) for w in re.findall(r"[a-z][a-z\-]{2,}", low) if w not in STOP]
    zh = [canon(w) for w in keywords(re.sub(r"[a-z]+", " ", low))]
    return list(dict.fromkeys(en)), list(dict.fromkeys(zh))

def _zh_hit(w: str, c: "_Ctx") -> bool:
    if w in c.cn:
        return True
    import qx
    z2e = qx._dict()[0]
    return any(t in c.low for t in z2e.get(w, []))                          # 中文词 → 词典英文译名（跨语言上下文）

def text_supported(text: str, c: "_Ctx", need: float = 0.5) -> bool:
    import numcheck
    qs = [x for x in numcheck.quantities(text) if not numcheck._skip(x)]
    if not all(numcheck.supported(x, c.q, c.d, c.e) for x in qs):
        return False
    en, zh = _terms(text)
    hits = sum(w in c.words for w in en) + sum(_zh_hit(w, c) for w in zh)
    n = len(en) + len(zh)
    return hits / n >= need if n else bool(qs)

def context_recall(item, ctx: str) -> float | None:
    """core 要点（无 core 时用全部要点）在送入 LLM 的上下文中的覆盖率（数值 numcheck 归一化 + 关键词≥50%，中英要点任一满足即算）"""
    if item["category"] == "拒答" or not item.get("key_points"):
        return None
    c = _Ctx(ctx)
    zh, en = item.get("key_points_zh"), item["key_points"]
    idx = item.get("core") or list(range(len(zh or en)))
    cr = []
    for i in idx:
        cands = [k for k in ((zh[i] if zh and i < len(zh) else None), (en[i] if i < len(en) else None)) if k]
        cr.append(1.0 if any(text_supported(k, c) for k in cands) else 0.0)
    return round(sum(cr) / len(cr), 3) if cr else None

def faithfulness(answer: str, ctx: str) -> float | None:
    """回答中有实质内容的句子，其数值和关键词（≥50%，中文词可经术语词典对上英文上下文）都能在上下文中找到的比例"""
    ans = re.sub(r"\[\d+(?:[,，、]\s*\d+)*\]", "", answer or "")
    sents = [x for x in re.split(r"[。；;\n]|(?<=[a-z])\.\s", ans) if len(x.strip()) >= 6 and not REFUSE_RE.search(x) and not x.strip().startswith("总结")]
    if not sents:
        return None
    c = _Ctx(ctx)
    return round(sum(text_supported(x, c) for x in sents) / len(sents), 3)

def attribution(verdict, cr, refused=False) -> str:
    if verdict == "正确":
        return "正确"
    if cr is None:
        return "-"
    return "检索失败" if cr < 0.75 else "生成漏写"

_TBL = {}
def evidence_in_table(item) -> bool:
    """标注证据是否只出现在 heading_v2 的表格块中（表格题/文本题分桶用）"""
    if not _TBL:
        for f in (os.path.join(OUT, "chunks_heading_v2.jsonl"), os.path.join(HERE, "uploads", "chunks_uploaded_v2.jsonl")):
            if os.path.exists(f):
                for c in map(json.loads, open(f, encoding="utf-8")):
                    _TBL.setdefault(c["source"], []).append((c.get("chunk_type", "text"), sq(c["text"])))
    ev = sq(item.get("evidence", ""))
    types = {t for t, tx in _TBL.get(item.get("source"), []) if ev and ev in tx}
    return bool(types) and types <= {"table", "table_row"}

# ---------------- LLM-as-judge（默认关闭） ----------------
JUDGE_PROMPT = """你是严格的评卷人。根据【标准答案】和【评分要点】判断【待评回答】：
- 正确：覆盖全部关键要点且无错误数值/结论；部分：覆盖部分要点且无严重错误；错误：关键数值/结论错误、答非所问或无实质内容。
只输出 JSON：{"verdict": "正确|部分|错误", "reason": "不超过30字"}"""

def llm_judge(item, gen, provider):
    import rag
    cfg = rag.llm_config(provider)
    user = f"【问题】{item['question']}\n【标准答案】{item['reference_answer']}\n【评分要点】{'；'.join(item['key_points'])}\n【待评回答】{gen.get('answer','')}"
    text, _ = rag.call_llm([{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}], cfg, max_tokens=120, temperature=0.0)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        d = {}
    return {"verdict": d.get("verdict") if d.get("verdict") in ("正确", "部分", "错误") else None, "raw": text[:200]}

# 证据位于表格中的题（v2 管线下证据只出现在 table/table_row 块中）
TABLE_IDS = ["P04", "P06", "P11", "P14", "F03", "F04", "F10", "F14", "O09"]

# ---------------- 检索 ----------------
sq = lambda s: re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", s or ""))   # 去空白与表格分隔符 |，NFKC 统一全/半角

def gold_match(item, hit, doc_level=False):
    """块级命中：chunk_id 在标注列表中，或证据原文（归一化后）是命中文本的子串。
    v2 集合的表格块是 Markdown，单元格之间有 | ，归一化时去掉；行级命中已在 search() 中展开为父表。"""
    if hit["source"] != item["source"]:
        return False
    return doc_level or hit["chunk_id"] in item.get("all_chunk_ids", []) or sq(item["evidence"]) in sq(hit["text"])

def rank_of(item, hits, doc_level=False):
    return next((i for i, h in enumerate(hits, 1) if gold_match(item, h, doc_level)), None)

def slim_hit(h):
    m = h.get("metadata", {})
    return {"rank": h["rank"], "chunk_id": h["chunk_id"], "source": h["source"], "heading_path": h.get("heading_path", ""),
            "page_start": h.get("page_start"), "page_end": h.get("page_end"), "score": h.get("score"),
            "rerank_score": h.get("rerank_score"), "text": h["text"], "metadata": m}

# ---------------- 主流程 ----------------
def kb_sig(collection: str) -> str:
    """切块文件指纹：同名集合重切后生成缓存自动失效（否则会复用旧检索结果下的回答）"""
    method = collection.replace("power_", "")
    h = hashlib.sha1()
    for p in (os.path.join(HERE, "output", f"chunks_{method}.jsonl"),):
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()[:10]

def config_from_args(a):
    import rag
    cfg = rag.llm_config(a.provider) if not a.retrieval_only else {"base_url": "-", "model": "-"}
    return {"collection": a.collection, "mode": a.mode, "fusion": a.fusion, "alpha": a.alpha, "rerank": a.rerank,
            "rerank_top_n": a.rerank_top_n, "rerank_beta": a.rerank_beta, "top_k": a.top_k, "retrieve_k": max(10, a.top_k),
            "provider": a.provider or "local", "model": a.model or cfg["model"], "base_url": cfg["base_url"],
            "max_tokens": a.max_tokens, "refuse_below": a.refuse_below, "prompt_sha": hashlib.sha1(rag.PROMPTS[a.prompt].encode()).hexdigest()[:8],
            **({"prompt": a.prompt} if a.prompt != "p0" else {}), **({"expand": a.expand} if a.expand != "none" else {}),
            **({"xlang": a.xlang} if a.xlang != "none" else {}), **({"multiq": a.multiq} if a.multiq != "none" else {}), **({"reflect": True} if a.reflect else {}), "kb_sig": kb_sig(a.collection)}

def cache_path(cfg):
    keys = {k: cfg[k] for k in sorted(cfg)}
    return os.path.join(CACHE, "gen_" + hashlib.sha1(json.dumps(keys, sort_keys=True).encode()).hexdigest()[:12] + ".jsonl")

def run(a):
    from retrieve import search
    items = [json.loads(l) for l in open(a.input, encoding="utf-8") if l.strip()]
    if getattr(a, "ids", None):
        want = set(TABLE_IDS if a.ids == "table" else a.ids.split(","))
        items = [it for it in items if it["id"] in want]
    if a.limit:
        items = items[:a.limit]
    cfg = config_from_args(a)
    os.makedirs(CACHE, exist_ok=True)
    cp = cache_path(cfg)
    cache = {}
    if os.path.exists(cp) and not a.retrieval_only:
        for l in open(cp, encoding="utf-8"):
            r = json.loads(l); cache[r["key"]] = r
    print(f"配置：{json.dumps(cfg, ensure_ascii=False)}\n缓存：{cp}（已有 {len(cache)} 条）", flush=True)
    recs, t_all = [], time.time()
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()
    todo = []
    reuse = {}
    if getattr(a, "hits_from", None) and not a.retrieval_only:
        d = sorted(glob.glob(os.path.join(RUNS, a.hits_from + "*")))[-1]
        rc = json.load(open(os.path.join(d, "run_config.json"), encoding="utf-8"))["config"]
        same = all(rc.get(k) == cfg.get(k) for k in ("collection", "mode", "fusion", "alpha", "rerank", "rerank_top_n", "rerank_beta", "retrieve_k", "kb_sig", "xlang", "multiq"))
        if not same:
            raise SystemExit(f"--hits-from {d} 的检索配置与当前不一致")
        reuse = {r["id"]: r for r in map(json.loads, open(os.path.join(d, "records.jsonl"), encoding="utf-8"))}
        print(f"复用检索结果：{d}（{len(reuse)} 题）", flush=True)
    for n, it in enumerate(items, 1):           # 第 1 阶段：检索+重排（本地模型，串行）
        key = it["id"] + ":" + hashlib.sha1(it["question"].encode()).hexdigest()[:8]
        if key in cache:
            recs.append(cache[key]); continue
        t0 = time.time()
        if it["id"] in reuse:                     # --hits-from：复用同一检索配置的旧运行结果（只换 LLM/Prompt/expand 时省去重排）
            r0 = reuse[it["id"]]
            rec = {"key": key, "id": it["id"], "hits": r0["hits"], "t_retrieval": r0["t_retrieval"], "t_rerank": r0.get("t_rerank", 0.0)}
            recs.append(rec); todo.append((it, rec, [dict(h) for h in r0["hits"]])); continue
        hits = search(it["question"], k=cfg["retrieve_k"], collection=cfg["collection"], mode=cfg["mode"], fusion=cfg["fusion"],
                      alpha=cfg["alpha"], rerank=cfg["rerank"], rerank_top_n=cfg["rerank_top_n"], rerank_beta=cfg["rerank_beta"],
                      rerank_use_cache=a.rerank_cache, xlang=a.xlang, multiq=a.multiq)
        t_ret = time.time() - t0
        rr_secs = hits[0].pop("_rerank_secs", 0.0) if hits else 0.0
        rec = {"key": key, "id": it["id"], "hits": [slim_hit(h) for h in hits], "t_retrieval": round(t_ret, 2), "t_rerank": round(rr_secs, 2)}
        recs.append(rec)
        if a.retrieval_only:
            print(f"[{n}/{len(items)}] {it['id']} {rec['t_retrieval']}s  累计 {time.time() - t_all:.0f}s", flush=True)
        else:
            todo.append((it, rec, hits))

    def gen_one(job):                           # 第 2 阶段：生成（可并发，API 提供方用 --workers 4）
        it, rec, hits = job
        t0 = time.time()
        top_rr = hits[0].get("rerank_score") if hits else None
        if cfg["refuse_below"] is not None and top_rr is not None and top_rr < cfg["refuse_below"]:
            rec["gen"] = {"answer": "根据现有资料无法回答该问题。", "refused": True, "sources": [], "invalid_citations": [], "used": [],
                          "threshold_refused": True, "timing": {"generation_secs": 0.0, "first_token_secs": None}, "support_warnings": []}
        else:
            import rag
            g = rag.answer(it["question"], k=cfg["top_k"], provider=a.provider, hits=hits[:cfg["top_k"]],
                           max_tokens=cfg["max_tokens"], model=a.model, prompt=a.prompt,
                           expand=a.expand, refuse_below=None, search_kw={"collection": cfg["collection"]}, reflect_round=a.reflect)
            rec["gen"] = {k: g[k] for k in ("answer", "raw_answer", "refused", "retried", "sources", "invalid_citations", "support_warnings", "timing", "usage", "model", "reflect", "extra_hits")}
            rec["gen"]["used"] = [s["id"] for s in g["sources"]]
        rec["t_total"] = round(rec["t_retrieval"] + time.time() - t0, 2)
        with lock:
            with open(cp, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[gen] {it['id']} {rec['t_total']}s  累计 {time.time() - t_all:.0f}s", flush=True)
    if todo:
        with ThreadPoolExecutor(max(1, a.workers)) as ex:
            list(ex.map(gen_one, todo))
    if not a.retrieval_only:
        u = [((r.get("gen") or {}).get("usage") or {}) for r in recs]
        tok = {"prompt_tokens": sum(x.get("prompt_tokens", 0) for x in u), "completion_tokens": sum(x.get("completion_tokens", 0) for x in u)}
        print("token 用量：" + json.dumps(tok), flush=True)
    if not a.retrieval_only:
        import rerank as rr; rr.save_cache()
    run_dir = os.path.join(RUNS, f"{a.tag}_{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)
    json.dump({"config": cfg, "input": a.input, "retrieval_only": a.retrieval_only, "tag": a.tag, "judge": a.judge},
              open(os.path.join(run_dir, "run_config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    score_and_report(run_dir, items, recs, cfg, a)

def score_and_report(run_dir, items, recs, cfg, a, rescored=False):
    byid = {r["id"]: r for r in recs}
    labels = {}
    if os.path.exists(LABELS):
        labels = {d["id"]: d for d in map(json.loads, open(LABELS, encoding="utf-8")) if d.get("human")}
    per = []
    for it in items:
        r = byid[it["id"]]
        hits = r["hits"]
        row = {"id": it["id"], "category": it["category"], "lang": it["lang"], "question": it["question"],
               "t_retrieval": r["t_retrieval"], "t_rerank": r.get("t_rerank"), "top1": f"{hits[0]['source']}｜{hits[0]['heading_path']}" if hits else "",
               "top1_rerank": hits[0].get("rerank_score") if hits else None}
        if it["category"] != "拒答":
            row.update(chunk_rank=rank_of(it, hits), doc_rank=rank_of(it, hits, True))
        g = r.get("gen")
        if g:
            topk = hits[:cfg["top_k"]] + (g.get("extra_hits") or [])     # reflect 补检的资料也算上下文（引用编号顺延）
            j = auto_judge(it, g)
            cited = [topk[i - 1] for i in g.get("used", []) if 0 < i <= len(topk)]
            n_bad = len(g.get("invalid_citations", []))
            row.update(answer=g["answer"], refused=g["refused"], threshold_refused=g.get("threshold_refused", False),
                       auto=j["verdict"], coverage=j["coverage"], kp_detail=j["kps"], auto_note=j.get("note", ""), n_cited=len(cited), n_invalid=n_bad,
                       t_generation=g["timing"].get("generation_secs"), t_first_token=g["timing"].get("first_token_secs"), t_total=r.get("t_total"),
                       support_warnings=len(g.get("support_warnings", [])))
            ctx = "\n".join(h["text"] for h in topk)
            cr = context_recall(it, ctx)
            row.update(ctx_recall=cr, faithfulness=faithfulness(g["answer"], ctx) if not g["refused"] else None)
            if it["category"] != "拒答":
                row.update(attribution=attribution(j["verdict"], cr, g["refused"]), is_table=evidence_in_table(it))
            if it["category"] != "拒答":
                row.update(cite_doc=any(c["source"] == it["source"] for c in cited) if cited else False,
                           cite_chunk=any(gold_match(it, c) for c in cited) if cited else False,
                           gold_in_topk=any(gold_match(it, h) for h in topk))
            if a.judge and not (rescored and "judge" in r):
                r["judge"] = llm_judge(it, g, a.judge)
            if r.get("judge"):
                row["judge"] = r["judge"]["verdict"]
            if it["id"] in labels:
                row["human"] = labels[it["id"]]["human"]; row["human_note"] = labels[it["id"]].get("note", "")
                row["label_set"] = labels[it["id"]].get("set", "calib")
        per.append(row)
    with open(os.path.join(run_dir, "per_item.jsonl"), "w", encoding="utf-8") as f:
        for row in per:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(run_dir, "records.jsonl"), "w", encoding="utf-8") as f:          # 原始检索+生成，--rescore 用
        for it in items:
            f.write(json.dumps(byid[it["id"]], ensure_ascii=False) + "\n")
    summary = summarize(per, cfg)
    summary["run_dir"] = os.path.relpath(run_dir, HERE)
    json.dump(summary, open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = report(summary, per, cfg, a, rescored)
    open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8").write(rep)
    append_baseline(summary, cfg, a.tag + (" (rescore)" if rescored else ""), run_dir)
    print(rep)

def _ret(rows, key):
    rk = [r.get(key) for r in rows]
    n = len(rk) or 1
    return {f"hit@{k}": round(sum(1 for x in rk if x and x <= k) / n, 3) for k in (1, 3, 5)} | {"mrr": round(sum(1 / x for x in rk if x) / n, 3)}

def _gen(rows):
    rows = [r for r in rows if "auto" in r]
    if not rows:
        return {}
    n = len(rows)
    c = collections.Counter(r["auto"] for r in rows)
    cited_rows = [r for r in rows if r["n_cited"] + r["n_invalid"] > 0]
    out = {"n": n, "correct": round(c["正确"] / n, 3), "partial": round(c["部分"] / n, 3), "wrong": round(c["错误"] / n, 3),
           "score": round((c["正确"] + 0.5 * c["部分"]) / n, 3), "coverage": round(sum(r["coverage"] or 0 for r in rows) / n, 3),
           "false_refusal": round(sum(r["refused"] for r in rows) / n, 3),
           "cite_doc": round(sum(r.get("cite_doc", False) for r in rows) / n, 3), "cite_chunk": round(sum(r.get("cite_chunk", False) for r in rows) / n, 3),
           "no_citation": round(sum(1 for r in rows if r["n_cited"] == 0 and not r["refused"]) / n, 3),
           "cite_valid": round(sum(r["n_cited"] for r in cited_rows) / max(1, sum(r["n_cited"] + r["n_invalid"] for r in cited_rows)), 3),
           "gold_in_topk": round(sum(r.get("gold_in_topk", False) for r in rows) / n, 3)}
    return out

def summarize(per, cfg):
    inkb = [r for r in per if r["category"] != "拒答"]
    ood = [r for r in per if r["category"] == "拒答"]
    groups = [("全部", inkb)] + [(c, [r for r in inkb if r["category"] == c]) for c in CATS] + \
             [("中文", [r for r in inkb if r["lang"] == "zh"]), ("英文", [r for r in inkb if r["lang"] == "en"])]
    s = {"config": cfg, "rules_version": RULES_VERSION, "n_inkb": len(inkb), "n_ood": len(ood), "groups": {}}
    for g, rows in groups:
        if rows:
            s["groups"][g] = {"n": len(rows), "chunk": _ret(rows, "chunk_rank"), "doc": _ret(rows, "doc_rank"), "gen": _gen(rows)}
    gen_rows = [r for r in inkb if "attribution" in r]
    if gen_rows:
        def bucket(rows):
            c = collections.Counter(r["attribution"] for r in rows); n = len(rows)
            crs = [r["ctx_recall"] for r in rows if r.get("ctx_recall") is not None]
            fs = [r["faithfulness"] for r in rows if r.get("faithfulness") is not None]
            return {"n": n, "正确": round(c["正确"] / n, 3), "检索失败": round(c["检索失败"] / n, 3), "生成漏写": round(c["生成漏写"] / n, 3),
                    "ctx_recall": round(sum(crs) / len(crs), 3) if crs else None, "faithfulness": round(sum(fs) / len(fs), 3) if fs else None}
        bk = [("全部", gen_rows)] + [(c, [r for r in gen_rows if r["category"] == c]) for c in CATS] + \
             [("中文", [r for r in gen_rows if r["lang"] == "zh"]), ("英文", [r for r in gen_rows if r["lang"] == "en"]),
              ("表格题", [r for r in gen_rows if r.get("is_table")]), ("文本题", [r for r in gen_rows if not r.get("is_table")])]
        s["attribution"] = {g: bucket(rows) for g, rows in bk if rows}
    if ood and "refused" in ood[0]:
        s["ood_refusal"] = round(sum(r["refused"] for r in ood) / len(ood), 3)
    tim = [r for r in per if "t_total" in r]
    def avg(k, rows):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(v) / len(v), 2) if v else None
    s["timing"] = {"retrieval": avg("t_retrieval", per), "rerank": avg("t_rerank", per), "generation": avg("t_generation", tim),
                   "first_token": avg("t_first_token", tim), "total": avg("t_total", tim)}
    lab = [r for r in inkb + ood if r.get("human") and r.get("auto")]
    for setname in ("calib", "holdout"):
        sub = [r for r in lab if r.get("label_set", "calib") == setname]
        if sub:
            s.setdefault("calibration_sets", {})[setname] = {"n": len(sub), "agree": round(sum(r["human"] == r["auto"] for r in sub) / len(sub), 3),
                "agree_binary": round(sum((r["human"] == "正确") == (r["auto"] == "正确") for r in sub) / len(sub), 3),
                "confusion": dict(collections.Counter(f"{r['human']}→{r['auto']}" for r in sub))}
    if lab:
        s["calibration"] = {"n": len(lab), "agree": round(sum(r["human"] == r["auto"] for r in lab) / len(lab), 3),
                            "agree_binary": round(sum((r["human"] == "正确") == (r["auto"] == "正确") for r in lab) / len(lab), 3),
                            "confusion": dict(collections.Counter(f"{r['human']}→{r['auto']}" for r in lab))}
        jl = [r for r in lab if r.get("judge")]
        if jl:
            s["calibration"]["judge_agree"] = round(sum(r["human"] == r["judge"] for r in jl) / len(jl), 3)
    return s

def pct(x):
    return "-" if x is None else f"{x * 100:.0f}%"

def report(s, per, cfg, a, rescored):
    c = cfg
    L = [f"# 评测报告：{a.tag}{'（重算）' if rescored else ''}", "",
         f"时间 {time.strftime('%Y-%m-%d %H:%M')}（北京时间）｜配置：{c['collection']} + {c['mode']}({c['fusion']}, α={c['alpha']})"
         f"{' + rerank@' + str(c['rerank_top_n']) + ' β=' + str(c['rerank_beta']) if c['rerank'] else ''}｜top_k={c['top_k']}｜LLM {c['model']}"
         f"{'｜重排分阈值拒答 ' + str(c['refuse_below']) if c['refuse_below'] is not None else ''}", "",
         f"库内 {s['n_inkb']} 题 + 库外 {s['n_ood']} 题。自动评分规则 v{s.get('rules_version')}。", "", "## 检索（块级 / 文档级）", "",
         "| 分组 | 题数 | 块 Hit@1 | 块 Hit@3 | 块 Hit@5 | 块 MRR | 文档 Hit@1 | 文档 Hit@5 | 文档 MRR |", "|---|---|---|---|---|---|---|---|---|"]
    for g, v in s["groups"].items():
        ch, d = v["chunk"], v["doc"]
        L.append(f"| {g} | {v['n']} | {pct(ch['hit@1'])} | {pct(ch['hit@3'])} | {pct(ch['hit@5'])} | {ch['mrr']:.3f} | {pct(d['hit@1'])} | {pct(d['hit@5'])} | {d['mrr']:.3f} |")
    if s["groups"].get("全部", {}).get("gen"):
        L += ["", "## 回答（自动规则分）与引用", "",
              "| 分组 | 正确 | 部分 | 错误 | 得分¹ | 要点覆盖率 | 误拒率 | 引用含标注文档 | 引用含标注块 | 无引用 | 引用有效率 | 标注块在Top-k |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for g, v in s["groups"].items():
            q = v["gen"]
            L.append(f"| {g} | {pct(q['correct'])} | {pct(q['partial'])} | {pct(q['wrong'])} | {q['score']:.2f} | {pct(q['coverage'])} | {pct(q['false_refusal'])} | "
                     f"{pct(q['cite_doc'])} | {pct(q['cite_chunk'])} | {pct(q['no_citation'])} | {pct(q['cite_valid'])} | {pct(q['gold_in_topk'])} |")
        L += ["", "¹ 得分 = (正确 + 0.5×部分)/题数。自动规则：要点得分（全对 1、多数值答对过半 0.5）平均 ≥0.75 正确、≥0.4 部分，否则错误；库内题拒答记错误，先答后拒最多记部分。首 token 为 None 表示评测走非流式调用。", "",
              f"**拒答**：库外题正确拒答率 {pct(s.get('ood_refusal'))}；库内题误拒率 {pct(s['groups']['全部']['gen']['false_refusal'])}。", ""]
    if s.get("attribution"):
        L += ["## 评测拆分：Context Recall / 忠实度 / 归因（规则版）", "",
              "Context Recall = core 要点在送入 LLM 的 Top-k 上下文中的覆盖率；忠实度 = 回答实质句（数值+关键词）能在上下文中找到的比例；"
              "归因：答对=正确；未答对且 Context Recall<0.75=检索失败；未答对但上下文已含要点=生成漏写。", "",
              "| 分桶 | 题数 | 正确 | 检索失败 | 生成漏写 | Context Recall | 忠实度 |", "|---|---|---|---|---|---|---|"]
        for g, v in s["attribution"].items():
            L.append(f"| {g} | {v['n']} | {pct(v['正确'])} | {pct(v['检索失败'])} | {pct(v['生成漏写'])} | {pct(v['ctx_recall'])} | {pct(v['faithfulness'])} |")
        L.append("")
    t = s["timing"]
    L += ["## 耗时（秒/题，均值）", "", f"检索 {t['retrieval']}（其中重排 {t['rerank']}）｜生成 {t['generation']}（首 token {t['first_token']}）｜端到端 {t['total']}", ""]
    if s.get("calibration"):
        cb = s["calibration"]
        L += ["## 自动评分校准（人工抽查）", "", f"抽查 {cb['n']} 题：三档一致率 {pct(cb['agree'])}，“是否正确”二分类一致率 {pct(cb['agree_binary'])}"
              + (f"，LLM-judge 与人工一致率 {pct(cb['judge_agree'])}" if "judge_agree" in cb else "") + "。", "",
              "人工→自动：" + "，".join(f"{k} {v}" for k, v in sorted(cb["confusion"].items())), ""]
        for nm, lbl in (("calib", "调规则用的校准集"), ("holdout", "调规则后另抽的留出集")):
            c2 = s.get("calibration_sets", {}).get(nm)
            if c2:
                L.append(f"- {lbl}（{c2['n']} 题）：三档一致 {pct(c2['agree'])}，二分类一致 {pct(c2['agree_binary'])}；人工→自动 "
                         + "，".join(f"{k} {v}" for k, v in sorted(c2["confusion"].items())))
        L.append("")
    if any("auto" in r for r in per):
        L += ["## 逐题", "", "| id | 类别 | 块名次 | 自动 | 覆盖 | 人工 | 引用标注块 | 回答（截断） |", "|---|---|---|---|---|---|---|---|"]
        for r in per:
            ans = (r.get("answer") or "").replace("\n", " ").replace("|", "/")[:80]
            L.append(f"| {r['id']} | {r['category']} | {r.get('chunk_rank') or ('-' if r['category'] == '拒答' else '>10')} | {r.get('auto', '-')} | "
                     f"{'-' if r.get('coverage') is None else r['coverage']} | {r.get('human', '')} | {'✓' if r.get('cite_chunk') else ('-' if r['category'] == '拒答' else '✗')} | {ans} |")
    return "\n".join(L) + "\n"

def append_baseline(s, cfg, tag, run_dir):
    head = ("# 实验对比表（evaluate.py 自动追加）\n\n| 时间 | 实验 | 检索配置 | LLM | 块Hit@1 | 块Hit@5 | 块MRR | 文档Hit@1 | 正确 | 部分 | 得分 | 引用含标注块 | 库外拒答 | 误拒 | 秒/题 | 目录 |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    if not os.path.exists(BASELINE):
        open(BASELINE, "w", encoding="utf-8").write(head)
    g = s["groups"]["全部"]; q = g["gen"]
    ret = f"{cfg['collection']}+{cfg['mode']}" + (f"+rr@{cfg['rerank_top_n']}β{cfg['rerank_beta']}" if cfg["rerank"] else "") + f",k={cfg['top_k']}" + \
          (f",thr={cfg['refuse_below']}" if cfg["refuse_below"] is not None else "") + (f",{cfg['prompt']}" if cfg.get('prompt') else "")
    row = (f"| {time.strftime('%m-%d %H:%M')} | {tag} | {ret} | {cfg['model'] if q else '-'} | {pct(g['chunk']['hit@1'])} | {pct(g['chunk']['hit@5'])} | {g['chunk']['mrr']:.3f} | "
           f"{pct(g['doc']['hit@1'])} | {pct(q.get('correct'))} | {pct(q.get('partial'))} | {q.get('score', '-')} | {pct(q.get('cite_chunk'))} | "
           f"{pct(s.get('ood_refusal'))} | {pct(q.get('false_refusal'))} | {s['timing']['total'] or s['timing']['retrieval']} | {os.path.relpath(run_dir, HERE)} |\n")
    open(BASELINE, "a", encoding="utf-8").write(row)

def rescore(a):
    d = a.rescore
    rc = json.load(open(os.path.join(d, "run_config.json"), encoding="utf-8"))
    cfg = rc["config"]; a.tag = rc["tag"]
    items = [json.loads(l) for l in open(rc["input"] if os.path.isabs(rc["input"]) else os.path.join(HERE, rc["input"]), encoding="utf-8") if l.strip()]
    recs = [json.loads(l) for l in open(os.path.join(d, "records.jsonl"), encoding="utf-8")]
    ids = {r["id"] for r in recs}
    score_and_report(d, [it for it in items if it["id"] in ids], recs, cfg, a, rescored=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="eval_set_50.jsonl")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--collection", default="heading")
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "bm25"])
    ap.add_argument("--fusion", default="weighted", choices=["weighted", "rrf"])
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--rerank", dest="rerank", action="store_true", default=True)
    ap.add_argument("--no-rerank", dest="rerank", action="store_false")
    ap.add_argument("--rerank-top-n", type=int, default=20)
    ap.add_argument("--rerank-beta", type=float, default=0.8)
    ap.add_argument("--rerank-cache", action="store_true", help="重排分走缓存（快，但重排耗时失真）")
    ap.add_argument("--top-k", type=int, default=5, help="送入 LLM 的资料条数")
    ap.add_argument("--provider", default=None, help="local/deepseek/openai/xai；不填按环境变量/本地")
    ap.add_argument("--model", default=None)
    ap.add_argument("--rules", type=int, default=None, help="自动评分规则版本（2/3），默认取 EVAL_RULES 或 2")
    ap.add_argument("--hits-from", default=None, help="复用某次运行（目录名前缀）的检索结果")
    ap.add_argument("--expand", default="none", choices=["none", "neighbor", "parent"], help="检索后上下文扩展")
    ap.add_argument("--workers", type=int, default=1, help="生成并发数（API 提供方建议 4；本地 Ollama 用 1）")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--refuse-below", type=float, default=None, help="Top-1 重排分低于该值直接拒答（默认关）")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--xlang", default="none", choices=["none", "dict", "llm", "auto", "auto_llm"], help="跨语言改写：词典 / 本地 3B 翻译；auto=按问句点名的设备门控")
    ap.add_argument("--multiq", default="none", choices=["none", "rule", "llm"], help="多查询：规则拆分 / 本地 3B")
    ap.add_argument("--prompt", default="p0", choices=["p0", "p1", "p2", "p3"], help="rag.PROMPTS 版本")
    ap.add_argument("--reflect", action="store_true", help="生成前自检（LLM 判断资料是否足够）+ 缺失点补检 1 轮")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", default=None, help="只评这些题，逗号分隔；'table' = 证据在表格中的题（TABLE_IDS）")
    ap.add_argument("--judge", default=None, help="LLM-as-judge 的 provider（默认关闭）")
    ap.add_argument("--rescore", default=None, help="对已有运行目录按当前规则重算")
    a = ap.parse_args()
    if a.rules:
        globals()["RULES_VERSION"] = a.rules
    rescore(a) if a.rescore else run(a)
