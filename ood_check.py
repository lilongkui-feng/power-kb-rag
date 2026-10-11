# 生成 eval_ood.jsonl（库外/边界题）并打印检索 Top-3 供人工确认库中确实没有答案
import json, sys
from evalset.ood_items import OOD
from retrieve import search
rows = []
for i, kind, q in OOD:
    hs = search(q, k=3, collection="heading_v2", rerank=True)
    rows.append({"id": i, "category": "拒答", "kind": kind, "lang": "en" if q.isascii() else "zh", "question": q,
                 "reference_answer": "根据现有资料无法回答该问题。", "key_points": [], "top1_rerank": hs[0].get("rerank_score") if hs else None})
    print(f"\n### {i} [{kind}] {q}  top1={rows[-1]['top1_rerank']}")
    for h in hs:
        print(f"  - {h.get('rerank_score'):.3f} {h['source'][:28]}｜{h.get('heading_path','')[-30:]}｜{h['text'][:160].replace(chr(10),' ')}")
with open("eval_ood.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
