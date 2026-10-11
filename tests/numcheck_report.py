# 生成 output/numcheck_eval.md：回归集误报/漏报 + 在 v3 新基线全部回答上的告警量对比
import json, os, sys, glob, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from tests.numcheck_eval import evaluate
import rag, numcheck
r, rows = evaluate()
pc = lambda t: f"{t[0]}/{t[1]} = {t[0] / max(1, t[1]):.1%}"
run = sorted(glob.glob(os.path.join(HERE, "output/eval_runs/v3set_sf_v3_p2_2026*")))[-1]
w1 = w2 = a1 = a2 = n = 0
for rec in map(json.loads, open(os.path.join(run, "records.jsonl"), encoding="utf-8")):
    g = rec.get("gen")
    if not g or g.get("refused"):
        continue
    hits = rec["hits"][:5]; n += 1
    x1 = rag.support_check_v1(g["answer"], hits); x2 = numcheck.check(g["answer"], hits)
    w1 += len(x1); w2 += len(x2); a1 += bool(x1); a2 += bool(x2)
L = ["# 数值引用校验 v1 → v2 对比", "",
     "回归集 `tests/numcheck_cases.jsonl`：从历史运行（不含 expand 运行）收集旧版 support_check 的全部告警，逐条人工标注“真告警/误报”，"
     "再对“本有出处”的数值做篡改生成合成用例测漏报。用例只存回答句子与引用块 (source, chunk_id)，测试时从本地 chunks 取原文（不入库）。", "",
     f"有效用例 {r['n']}（跳过 {r['skipped']}：切块已重建、原文对不上）", "",
     "| 指标 | v1（字符串包含） | v2（numcheck.py） |", "|---|---|---|",
     f"| 误报率（人工判为误报的告警中仍告警） | {pc(r['fp_old'])} | {pc(r['fp_new'])} |",
     f"| 漏报率（全部“真”用例） | {pc(r['miss_old'])} | {pc(r['miss_new'])} |",
     f"| 　其中历史真告警 | 0（定义上全部告警） | {pc(r['miss_hist_new'])} |",
     f"| 　其中合成篡改 | {pc(r['miss_syn_old'])} | {pc(r['miss_syn_new'])} |",
     f"| v3 新基线 {n} 条回答的告警条数 | {w1} | {w2} |",
     f"| 有告警的回答占比 | {a1}/{n} = {a1 / n:.0%} | {a2}/{n} = {a2 / n:.0%} |", "",
     "## v2 仍误报", ""]
L += [f"- {x['case']}「{x['old_flag']}」{x['sentence'][:70]}…（{x['why']}）" for x in rows if x["label"] == "误报" and x["new"]]
L += ["", "## v2 漏报", ""]
L += [f"- {x['case']}「{x['old_flag']}」{x['sentence'][:70]}…（{x['why']}）" for x in rows if x["label"] == "真" and not x["new"]]
L += ["", "漏报主因：v2 允许“表头/整段声明单位 + 裸数值”匹配（解决 ≤ 300、单位:V 表格这类误报的代价），篡改后的值若恰好以裸数值出现在同一块的别处就会放过。",
      "", "## 误报类型（v1 的 120 条误报）", ""]
c = collections.Counter(x["why"] for x in rows if x["label"] == "误报")
L += [f"- {k}：{v}" for k, v in c.most_common()]
open(os.path.join(HERE, "output", "numcheck_eval.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L[:16]))
