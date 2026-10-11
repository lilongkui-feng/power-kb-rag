# 从历史运行收集旧版 support_check 告警 → tests/numcheck_review.md（人工看）+ tests/numcheck_cases_raw.jsonl
# 用例只存回答句子与引用块的 (source, chunk_id)，不存资料原文；测试时从本地 chunks 文件加载
import json, glob, os, re, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
import rag
cases, seen = [], set()
for f in sorted(glob.glob(os.path.join(HERE, "output/eval_runs/*/records.jsonl"))):
    run = f.split("/")[-2]
    for r in map(json.loads, open(f, encoding="utf-8")):
        g = r.get("gen") or {}
        if not g.get("support_warnings"):
            continue
        hits = r["hits"][:5]
        ans = g["answer"]
        for sent in rag.SENT_RE.findall(ans):
            cites, _ = rag.parse_citations(sent, len(hits))
            if not cites:
                continue
            w = rag.support_check(sent, hits)
            for x in w:
                num = re.match(r"“(.+?)”", x).group(1)
                key = (sent.strip(), num)
                if key in seen:
                    continue
                seen.add(key)
                cited = [{"source": hits[i - 1]["source"], "chunk_id": hits[i - 1]["chunk_id"]} for i in cites]
                allh = [{"source": h["source"], "chunk_id": h["chunk_id"]} for h in hits]
                win = []
                digits = re.match(r"\d+(?:\.\d+)?", num).group(0)
                for i in cites:
                    t = re.sub(r"\s+", " ", hits[i - 1]["text"])
                    ms = [m.start() for m in re.finditer(rf"(?<![\d.]){re.escape(digits)}(?![\d])", t)][:3]
                    win.append(f"[{i}] " + (" ‖ ".join(t[max(0, p - 45):p + 45] for p in ms) if ms else "（数字未出现）"))
                cases.append({"case": f"H{len(cases) + 1:03d}", "run": run, "qid": r["id"], "sentence": sent.strip(), "old_flag": num,
                              "cites": cites, "cited": cited, "hits": allh, "_win": win})
with open(os.path.join(HERE, "tests/numcheck_cases_raw.jsonl"), "w", encoding="utf-8") as fo:
    for c in cases:
        fo.write(json.dumps(c, ensure_ascii=False) + "\n")
with open("/tmp/numcheck_review.md", "w", encoding="utf-8") as fo:
    for c in cases:
        fo.write(f"{c['case']} {c['qid']} 旧告警「{c['old_flag']}」 句：{c['sentence'][:160]}\n   " + "\n   ".join(c["_win"]) + "\n")
print(len(cases))
