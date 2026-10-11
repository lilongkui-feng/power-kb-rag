# -*- coding: utf-8 -*-
"""拒答阈值扫描：基于重排 Top-1 分（hits[0].rerank_score）。
库内 = eval_set_50 的 50 道库内题；库外 = eval_set_50 的 R01–R05 + eval_ood.jsonl（N01–N25）。
输出 output/threshold_scan.md、output/threshold_curve.png；--run 指定读取哪个运行的 per_item（库内/R 题），--ood-run 读取库外集运行（看 LLM 自身拒答）"""
import glob, json, sys
import numpy as np
def per(name):
    d = sorted(glob.glob(f"output/eval_runs/{name}_2*"))[-1]
    return d, [json.loads(l) for l in open(d + "/per_item.jsonl", encoding="utf-8")]
run = sys.argv[1] if len(sys.argv) > 1 else "sf_v3_p2_k5"
ood_run = sys.argv[2] if len(sys.argv) > 2 else None
_, P = per(run)
inkb = [(r["id"], r["top1_rerank"]) for r in P if r["category"] != "拒答"]
ood = [(r["id"], r["top1_rerank"], "R") for r in P if r["category"] == "拒答"]
O = {}
if ood_run:
    _, Q = per(ood_run); keep = {json.loads(l)["id"] for l in open("eval_ood.jsonl", encoding="utf-8")}; O = {r["id"]: r for r in Q if r["id"] in keep}
kind = {json.loads(l)["id"]: json.loads(l)["kind"] for l in open("eval_ood.jsonl", encoding="utf-8")}
ood += [(r["id"], r["top1_rerank"], kind[r["id"]]) for r in (O.values() if O else [json.loads(l) for l in open("eval_ood.jsonl")])]
ths = [round(x, 2) for x in np.arange(0.05, 0.91, 0.05)]
rows = []
for t in ths:
    fr = sum(s < t for _, s in inkb) / len(inkb)
    orr = sum(s < t for _, s, _ in ood) / len(ood)
    near = [s for _, s, k in ood if k == "near"]; far = [s for _, s, k in ood if k != "near"]
    rows.append((t, fr, orr, sum(s < t for s in near) / max(1, len(near)), sum(s < t for s in far) / max(1, len(far))))
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans"]
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].hist([s for _, s in inkb], bins=20, range=(0, 1), alpha=.6, label="in-KB")
ax[0].hist([s for _, s, k in ood if k == "near"], bins=20, range=(0, 1), alpha=.6, label="OOD near")
ax[0].hist([s for _, s, k in ood if k != "near"], bins=20, range=(0, 1), alpha=.6, label="OOD far+R")
ax[0].set_xlabel("rerank top-1 score"); ax[0].legend(); ax[0].set_title("score distribution")
ax[1].plot(ths, [r[1] for r in rows], "o-", label="in-KB false refusal")
ax[1].plot(ths, [r[2] for r in rows], "s-", label="OOD refusal (all)")
ax[1].plot(ths, [r[3] for r in rows], "^--", label="OOD near"); ax[1].plot(ths, [r[4] for r in rows], "v--", label="OOD far")
ax[1].set_xlabel("threshold"); ax[1].legend(); ax[1].set_title("threshold sweep"); ax[1].grid(alpha=.3)
plt.tight_layout(); plt.savefig("output/threshold_curve.png", dpi=110)
pc = lambda x: f"{100*x:.0f}%"
L = ["# 拒答阈值扫描（重排 Top-1 分）", "", f"库内 {len(inkb)} 题（来自 {run}），库外 {len(ood)} 题（R01–R05 + N01–N25；near={sum(k=='near' for *_, k in ood)}，far/R={sum(k!='near' for *_, k in ood)}）", "",
     "![曲线](threshold_curve.png)", "", "| 阈值 | 库内误拒 | 库外拒答(全部) | 边界题 near | 完全库外 far+R |", "|---|---|---|---|---|"]
L += [f"| {t} | {pc(a)} | {pc(b)} | {pc(c)} | {pc(d)} |" for t, a, b, c, d in rows]
L += ["", "库内 Top-1 分最低的 5 题：" + "，".join(f"{i}={s:.3f}" for i, s in sorted(inkb, key=lambda x: x[1])[:5]),
      "", "库外题 Top-1 分：" + "，".join(f"{i}({k})={s:.3f}" for i, s, k in sorted(ood, key=lambda x: x[1]))]
if O:
    llm = {i: O[i].get("auto") == "正确" for i in O}
    L += ["", "## 库外集（N01–N25）：LLM 自身拒答 vs 阈值拒答", ""]
    for t in (None,) + tuple(ths):
        if t not in (None, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            continue
        tr = [i for i, r in O.items() if t is not None and r["top1_rerank"] < t]
        both = sum(1 for i in O if llm[i] or i in tr)
        L.append(f"- 阈值 {t if t is not None else '关闭'}：阈值拒掉 {len(tr)}/{len(O)}，LLM 自己拒答 {sum(llm.values())}/{len(O)}，合计正确拒答 {both}/{len(O)}")
    L += ["", "LLM 没拒答的库外题：" + "；".join(f"{i}：{O[i]['answer'][:60]}" for i in O if not llm[i])]
open("output/threshold_scan.md", "w", encoding="utf-8").write("\n".join(L) + "\n"); print("\n".join(L[5:22]))
