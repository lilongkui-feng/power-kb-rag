# -*- coding: utf-8 -*-
"""汇总各版本分数 -> output/version_scores.md / .xlsx（读取 output/eval_runs/<run>/summary.json）
VERSIONS 中列出参与对比的运行（目录名前缀，取最新一次），可加注释与是否推荐。"""
import glob, json, os
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "output")
# (版本名, run 前缀, 切分说明, overlap, prompt, 备注)
VERSIONS = [
    ("baseline v1", "baseline_2026", "heading v1（表格按文字流）max800", 50, "p0", "Day 11 基线"),
    ("v2（修复前）", "v2_full_gen", "heading_v2 表格父子块 max800", 50, "p0", "表格未人工核对修复"),
    ("v2 修复", "gen_v2fix_p0_k5", "heading_v2（核对修复后）max800", 50, "p0", ""),
]
EXTRA = os.path.join(OUT, "version_extra.json")      # 调参产生的其它版本，由主流程追加
if os.path.exists(EXTRA):
    VERSIONS += [tuple(x) for x in json.load(open(EXTRA, encoding="utf-8"))]
RECOMMEND = os.environ.get("RECOMMEND", "")

def latest(prefix):
    ds = sorted(d for d in glob.glob(os.path.join(OUT, "eval_runs", prefix + "*")) if os.path.exists(os.path.join(d, "summary.json")))
    return ds[-1] if ds else None

rows = []
for name, pre, chunk, ov, pr, note in VERSIONS:
    d = latest(pre)
    if not d:
        continue
    s = json.load(open(os.path.join(d, "summary.json"), encoding="utf-8"))
    g = s["groups"]["全部"]; gen = g.get("gen") or {}; c = s["config"]
    t = s.get("timing") or {}
    rows.append({"版本": name + (" ★推荐" if name == RECOMMEND else ""), "切分": chunk, "重叠": ov, "Prompt": c.get("prompt", pr), "top_k": c["top_k"],
                 "块Hit@1": g["chunk"]["hit@1"], "块Hit@5": g["chunk"]["hit@5"], "块MRR": g["chunk"]["mrr"],
                 "正确": gen.get("correct"), "部分": gen.get("partial"), "错误": gen.get("wrong"), "得分": gen.get("score"),
                 "引用命中标注块": gen.get("cite_chunk"), "库外拒答": (s.get("ood_refusal") or {}).get("rate") if isinstance(s.get("ood_refusal"), dict) else s.get("ood_refusal"),
                 "误拒": gen.get("false_refusal"), "秒/题": t.get("total") or t.get("retrieval"), "备注": note, "目录": os.path.relpath(d, HERE)})
pct = lambda v: "-" if v is None else (f"{100 * v:.0f}%" if isinstance(v, float) and v <= 1 else str(v))
cols = list(rows[0].keys()) if rows else []
L = ["# 各版本分数汇总", "", "评测集 eval_set_50（库内 50 + 库外 5），自动评分规则 v2；检索固定 hybrid(α=0.5)+bge-reranker Top-20 β0.8；LLM qwen2.5:3b-instruct（本地）。", "",
     "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
for r in rows:
    L.append("| " + " | ".join(pct(r[k]) if k in ("块Hit@1", "块Hit@5", "正确", "部分", "错误", "引用命中标注块", "库外拒答", "误拒") else str(r[k] if r[k] is not None else "-") for k in cols) + " |")
L += ["", "**显著性局限**：库内仅 50 题，1 题 = 2 个百分点；得分差 <0.05、正确率差 <8 个百分点基本在噪声内（小模型生成本身有随机性，同配置重跑也会波动 1–3 题）。",
      "检索/切分的结论只对这 50 题和 19 份文档成立；推荐配置以“不劣于基线 + 表格题明显变好 + 人工抽查确认”为准，而不是只看最高分。"]
open(os.path.join(OUT, "version_scores.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = "versions"; ws.append(cols)
for r in rows:
    ws.append([r[k] for k in cols])
wb.save(os.path.join(OUT, "version_scores.xlsx"))
print("\n".join(L))
