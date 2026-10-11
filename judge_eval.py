# -*- coding: utf-8 -*-
"""用 DeepSeek-V3（硅基流动）做 LLM 评委：
1) 对 manual_labels.jsonl 已有人工标注的题（标注在哪次运行上就评哪次的回答）打分，算评委与人工一致率，并和自动规则 v2 对比；
2) 对指定运行（3B p1、V3 p1）全量打分，与自动规则对比。结果写 output/judge_eval.md / .json。不改原运行目录。"""
import glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor
import evaluate as E
OUT = "output"
items = {json.loads(l)["id"]: json.loads(l) for l in open("eval_set_50.jsonl", encoding="utf-8")}
def run_dir(name):
    return sorted(glob.glob(f"{OUT}/eval_runs/{name}*"))[-1]
def per_item(d):
    return {r["id"]: r for r in map(json.loads, open(os.path.join(d, "per_item.jsonl"), encoding="utf-8"))}
def judge(args):
    it, ans = args
    return E.llm_judge(it, {"answer": ans}, "siliconflow")["verdict"]
res = {}
# 1) 人工标注一致率
labs = [json.loads(l) for l in open(f"{OUT}/manual_labels.jsonl", encoding="utf-8")]
jobs = []
for lb in labs:
    p = per_item(run_dir(lb["labeled_on"]))[lb["id"]]
    jobs.append((lb, p))
with ThreadPoolExecutor(4) as ex:
    vs = list(ex.map(judge, [(items[lb["id"]], p["answer"]) for lb, p in jobs]))
rows = [{"id": lb["id"], "human": lb["human"], "auto": p["auto"], "judge": v, "set": lb.get("set")} for (lb, p), v in zip(jobs, vs)]
n = len(rows)
res["calib"] = {"n": n, "judge_agree": sum(r["judge"] == r["human"] for r in rows) / n, "auto_agree": sum(r["auto"] == r["human"] for r in rows) / n, "rows": rows}
# 2) 全量评委 vs 自动
for name in sys.argv[1:]:
    pi = per_item(run_dir(name))
    ids = [i for i in pi if not i.startswith("R")]
    with ThreadPoolExecutor(4) as ex:
        vs = list(ex.map(judge, [(items[i], pi[i]["answer"]) for i in ids]))
    cnt = lambda key, lab: sum(1 for x in key if x == lab) / len(ids)
    au = [pi[i]["auto"] for i in ids]
    res[name] = {"judge": {k: cnt(vs, k) for k in ("正确", "部分", "错误")}, "auto": {k: cnt(au, k) for k in ("正确", "部分", "错误")},
                 "agree_auto": sum(a == b for a, b in zip(vs, au)) / len(ids), "rows": dict(zip(ids, vs))}
json.dump(res, open(f"{OUT}/judge_eval.json", "w"), ensure_ascii=False, indent=1)
pc = lambda x: f"{100 * x:.0f}%"
L = ["# LLM 评委（DeepSeek-V3 @硅基流动）评估", "", f"## 1. 与人工标注一致率（{n} 题，3B 基线回答）", "",
     f"- LLM 评委 vs 人工：**{pc(res['calib']['judge_agree'])}**；自动规则 v2 vs 人工：**{pc(res['calib']['auto_agree'])}**", "",
     "| id | 人工 | 自动 v2 | 评委 |", "|---|---|---|---|"] + [f"| {r['id']} | {r['human']} | {r['auto']} | {r['judge']} |" for r in rows]
L += ["", "## 2. 全量 50 题：评委 vs 自动规则", "", "| 运行 | 评委 正确/部分/错误 | 自动 正确/部分/错误 | 评委与自动一致率 |", "|---|---|---|---|"]
for name in sys.argv[1:]:
    r = res[name]; f = lambda d: " / ".join(pc(d[k]) for k in ("正确", "部分", "错误"))
    L.append(f"| {name} | {f(r['judge'])} | {f(r['auto'])} | {pc(r['agree_auto'])} |")
open(f"{OUT}/judge_eval.md", "w", encoding="utf-8").write("\n".join(L) + "\n"); print("\n".join(L[:6]))
