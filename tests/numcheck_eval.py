# 数值校验回归评测：tests/numcheck_cases.jsonl（只含回答句子 + 引用块引用）→ 从本地 chunks 文件取原文 → 比较 v1/v2 的误报率/漏报率
import json, os, re, sys, glob
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
CASES = os.path.join(HERE, "tests", "numcheck_cases.jsonl")
FILES = {"heading": ["output/chunks_heading.jsonl", "uploads/chunks_uploaded.jsonl"],
         "heading_v2": ["output/chunks_heading_v2.jsonl", "uploads/chunks_uploaded_v2.jsonl"]}

def load_chunks():
    idx = {}
    for coll, fs in FILES.items():
        for f in fs:
            p = os.path.join(HERE, f)
            if os.path.exists(p):
                for l in open(p, encoding="utf-8"):
                    c = json.loads(l); idx[(coll, c["source"], c["chunk_id"])] = c["text"]
    return idx

def _num(s):
    m = re.match(r"\d+(?:\.\d+)?", s); return float(m.group(0)) if m else None

def flagged(warns, flag):
    v = _num(flag)
    return any(_num(re.match(r"“(.+?)”", w).group(1)) == v for w in warns if re.match(r"“(.+?)”", w))

def evaluate():
    import rag, numcheck
    idx = load_chunks()
    rows, skipped = [], 0
    for c in map(json.loads, open(CASES, encoding="utf-8")):
        texts = [idx.get((c["collection"], h["source"], h["chunk_id"])) for h in c["hits"]]
        if any(t is None for t in texts):
            skipped += 1; continue
        hits = [{"text": t} for t in texts]
        old = flagged(rag.support_check_v1(c["sentence"], hits), c["old_flag"])
        if c["kind"] == "历史告警" and not old:          # 切块已重建、原文变化，旧版都复现不了 → 跳过
            skipped += 1; continue
        new = flagged(numcheck.check(c["sentence"], hits), c["old_flag"])
        rows.append(dict(c, old=old, new=new))
    def rate(rs, key, want):
        return (sum(r[key] == want for r in rs), len(rs))
    fp = [r for r in rows if r["label"] == "误报"]; tp = [r for r in rows if r["label"] == "真"]
    res = {"n": len(rows), "skipped": skipped,
           "fp_old": rate(fp, "old", True), "fp_new": rate(fp, "new", True),          # 误报率 = 被告警的“误报”用例比例
           "miss_old": rate(tp, "old", False), "miss_new": rate(tp, "new", False),    # 漏报率 = 未告警的“真”用例比例
           "miss_hist_new": rate([r for r in tp if r["kind"] == "历史告警"], "new", False),
           "miss_syn_old": rate([r for r in tp if r["kind"] == "合成篡改"], "old", False),
           "miss_syn_new": rate([r for r in tp if r["kind"] == "合成篡改"], "new", False)}
    return res, rows
