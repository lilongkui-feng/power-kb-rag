# 两次生成运行对比：总体 + 归因 + 逐题变化
import json, glob, os, sys
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def run(pre):
    d = sorted(x for x in glob.glob(os.path.join(H, "output/eval_runs", pre + "*")) if os.path.exists(x + "/summary.json"))[-1]
    return d, json.load(open(d + "/summary.json")), {r["id"]: r for r in map(json.loads, open(d + "/per_item.jsonl"))}
a, b = sys.argv[1], sys.argv[2]
for pre in (a, b):
    d, s, _ = run(pre); g = s["groups"]["全部"]["gen"]; at = s.get("attribution", {}).get("全部", {})
    print(pre, {k: g.get(k) for k in ("correct", "partial", "wrong", "score", "cite_chunk", "false_refusal")}, "OOD拒答", s.get("ood_refusal"),
          "归因", {k: at.get(k) for k in ("检索失败", "生成漏写", "ctx_recall", "faithfulness")}, "耗时", s["timing"].get("total"), s["timing"].get("generation"), os.path.basename(d))
_, _, A = run(a); _, _, B = run(b)
rank = {"正确": 2, "部分": 1, "错误": 0}
up = [i for i in A if i in B and A[i].get("auto") in rank and rank[B[i]["auto"]] > rank[A[i]["auto"]]]
dn = [i for i in A if i in B and A[i].get("auto") in rank and rank[B[i]["auto"]] < rank[A[i]["auto"]]]
print("变好", len(up), [f"{i}({A[i]['auto']}→{B[i]['auto']})" for i in up])
print("变差", len(dn), [f"{i}({A[i]['auto']}→{B[i]['auto']})" for i in dn])
