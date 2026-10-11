# -*- coding: utf-8 -*-
"""用 DeepSeek-V3（硅基流动）从 heading_v2 切块起草新评测题（之后人工审阅 + validate_eval_set_v3.py 校验）。
文档均衡：每份文档按配额抽块；英文手册出英文题；类别轮换；约 1/8 为多条款综合题（同文档两个不同章节的块）。
evidence 必须逐字摘自原块，脚本自动校验（去空白后为子串），不通过的重试一次后丢弃。输出 evalset/drafts_v3.jsonl"""
import json, os, random, re, sys
from concurrent.futures import ThreadPoolExecutor
import rag
SEED = int(os.environ.get("SEED", "20261011")); random.seed(SEED)
sq = lambda s: re.sub(r"[\s|]+", "", s or "")
EN_DOCS = ("ABB_", "SIPROTEC", "Schneider_")
SKIP = re.compile(r"前置内容|封面|目录|前言|范围|规范性引用|术语和定义|术语|Contents|Foreword|Legal|Copyright|Safety (?:instructions|information)$|附录.*资料性|参考文献")
chunks = []
for f in ("output/chunks_heading_v2.jsonl", "uploads/chunks_uploaded_v2.jsonl"):
    chunks += [json.loads(l) for l in open(f, encoding="utf-8")]
old = [json.loads(l) for l in open("eval_set_50.jsonl", encoding="utf-8")]
old_ev = {sq(o["evidence"])[:30] for o in old if o.get("evidence")}
by_src = {}
for c in chunks:
    if c.get("chunk_type") == "table_row" or SKIP.search(c.get("heading_path") or ""):
        continue
    if not (250 <= len(c["text"]) <= 1800) or any(e and e in sq(c["text"]) for e in old_ev):
        continue
    by_src.setdefault(c["source"], []).append(c)
QUOTA = int(sys.argv[1]) if len(sys.argv) > 1 else 5
CATS = ["查参数", "故障排查", "操作步骤"]
GEN_CATS = os.environ.get("GEN_CATS", "查参数,故障排查,操作步骤").split(",")
EN_QUOTA = int(os.environ.get("EN_QUOTA", "0")) or None
OUT = os.environ.get("OUT", "evalset/drafts_v3.jsonl")
USED = {json.loads(l)["chunk_id"] for f in os.environ.get("EXCLUDE", "").split(",") if f for l in open(f, encoding="utf-8")}
jobs, k = [], 0
for src, cs in sorted(by_src.items()):
    random.shuffle(cs)
    en = src.startswith(EN_DOCS)
    cs = [c for c in cs if c["chunk_id"] not in USED]
    q = (EN_QUOTA or QUOTA) if en else QUOTA
    for j in range(min(q, len(cs))):
        multi = ((j == q - 1) and len(cs) > q + 2 and (k % 2 == 0)) or (os.environ.get("FORCE_MULTI") == "1" and k % 2 == 0 and len(cs) > q + 2)
        pair = [cs[j]] + ([next(c for c in cs[q:] if c["heading_path"] != cs[j]["heading_path"])] if multi else [])
        jobs.append({"chunks": pair, "cat": GEN_CATS[k % len(GEN_CATS)], "lang": "en" if en else "zh", "multi": multi}); k += 1
SYS = """你是电力设备运维评测集的出题人。根据给定的原文片段出 1 道考题，要求：
1. 只用片段中的信息，答案能完全从片段得到；不要问页码、章节号、文件名这类元信息；问题要像现场运维人员会问的。
2. 题型尽量为指定类别（查参数=具体数值/限值/周期；故障排查=现象→原因/判断/处理；操作步骤=按顺序的操作或试验方法）。片段实在不适合时可改为其它类别，并在 category 中如实填写。
3. reference_answer：完整、准确，只含原文信息；操作步骤按顺序编号。
4. key_points：拆成若干要点。core=回答必须包含的核心要点（数值+单位+条件、关键步骤、关键结论），minor=次要补充（注释、例外、附带说明）。core 2–5 条，minor 0–3 条。
5. evidence：从片段中**逐字复制**一段 20–120 字的连续原文（不得改写、不得增删标点），它应是答案最关键的依据。多片段题给 evidence 和 evidence_2（分别来自片段1和片段2）。
6. 题目语言：lang=en 时问题、答案、要点用英文；lang=zh 用中文。
7. difficulty：易/中/难（多片段综合题为“难”）。
只输出 JSON：{"category":..,"difficulty":..,"question":..,"reference_answer":..,"key_points_core":[..],"key_points_minor":[..],"evidence":..,"evidence_2":..或null}"""
cfg = rag.llm_config("siliconflow")
def one(job, tries=2):
    cs = job["chunks"]
    user = f"类别：{job['cat']}；lang={job['lang']}；{'多片段综合题：问题必须同时用到片段1和片段2的信息' if job['multi'] else '单片段题'}\n\n" + \
           "\n\n".join(f"【片段{i+1}｜{c['source']}｜{c['heading_path']}】\n{c['text']}" for i, c in enumerate(cs))
    for _ in range(tries):
        try:
            text, info = rag.call_llm([{"role": "system", "content": SYS}, {"role": "user", "content": user}], cfg, max_tokens=900, temperature=0.3)
            d = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        except Exception:
            continue
        ok = sq(d.get("evidence")) and sq(d["evidence"]) in sq(cs[0]["text"])
        if job["multi"]:
            ok = ok and sq(d.get("evidence_2")) and sq(d["evidence_2"]) in sq(cs[1]["text"])
        if ok and d.get("key_points_core") and d.get("category") in CATS:
            c0 = cs[0]
            d.update(lang=job["lang"], source=c0["source"], section=c0["heading_path"], page=str(c0["page_start"]), chunk_id=c0["chunk_id"],
                     multi=job["multi"], usage=info.get("usage"))
            if job["multi"]:
                d.update(source_2=cs[1]["source"], section_2=cs[1]["heading_path"], page_2=str(cs[1]["page_start"]), chunk_id_2=cs[1]["chunk_id"])
            return d
    return None
with ThreadPoolExecutor(4) as ex:
    res = list(ex.map(one, jobs))
good = [r for r in res if r]
with open(OUT, "w", encoding="utf-8") as f:
    for r in good:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
u = [r["usage"] or {} for r in good]
print(f"jobs={len(jobs)} ok={len(good)} prompt_tokens={sum(x.get('prompt_tokens',0) for x in u)} completion_tokens={sum(x.get('completion_tokens',0) for x in u)}")
