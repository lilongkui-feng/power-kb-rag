# -*- coding: utf-8 -*-
"""端到端 RAG 测试：选 10 道评测题 + 2 道库外题，记录回答/引用/耗时 -> output/rag_raw.json（人工评判写在 rag_results.md）"""
import json, os, sys, time
from rag import answer, format_result

HERE = os.path.dirname(os.path.abspath(__file__))
PICK = ["q01", "q07", "q10", "q14", "q16", "q23", "q25", "q27", "k03", "k08"]
OOD = [{"id": "n01", "query": "变压器油中溶解气体乙炔含量的注意值是多少？", "source": "（库中无变压器油色谱标准）"},
       {"id": "n02", "query": "220kV 架空输电线路导线弧垂应如何计算？", "source": "（库中无线路设计规范）"}]

def main():
    qs = {}
    for f in ("eval_questions.jsonl", "eval_questions_keyword.jsonl"):
        for l in open(os.path.join(HERE, f), encoding="utf-8"):
            q = json.loads(l); qs[q["id"]] = q
    items = [qs[i] for i in PICK] + OOD
    from retrieve import search
    t = time.time(); search("预热", k=1); print(f"warm-up（加载 bge-m3 + reranker）{time.time() - t:.1f}s", flush=True)
    out = []
    for q in items:
        r = answer(q["query"])
        r["id"], r["gold"] = q["id"], f"{q['source']} / {q.get('section', '')}"
        out.append(r)
        print(f"=== {q['id']} {q['query']}\n{format_result(r)}\n", flush=True)
    json.dump(out, open(os.path.join(HERE, "output", "rag_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
