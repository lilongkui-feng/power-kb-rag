# -*- coding: utf-8 -*-
"""README 图表：数据全部取自 output/rerank_results.md（all44）、output/version_scores.md、output/baseline_scores.md
图 1 检索演进（44 题，heading 系列，块级 MRR@10 / Hit@1）；图 2 回答正确率演进（eval_set_50 / eval_set_v3）"""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
for f in ("Noto Sans CJK SC", "Noto Sans CJK JP", "WenQuanYi Micro Hei", "Source Han Sans SC"):
    if any(f in x.name for x in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [f]; break
plt.rcParams["axes.unicode_minus"] = False
# 图 1：左 = output/rerank_results.md、hybrid_results.md（44 题）；右 = version_scores.md / xling 报告（eval_set_v3 139 题、跨语言 36 题）
R = [("定长切分\n纯向量", 0.658, 0.500), ("章节切分\n纯向量", 0.807, 0.727), ("+BM25 混合\nα=0.5", 0.850, 0.750), ("+bge-reranker\nTop20 β0.8", 0.911, 0.841)]
R2 = [("139题\n默认", 0.893, 0.835), ("139题\n+xlang cap", 0.896, 0.84), ("跨语言36题\n默认", 0.657, None), ("跨语言36题\n+xlang cap", 0.745, None)]
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12, 4.3), gridspec_kw={"width_ratios": [4, 4]})
x = range(len(R))
ax.bar([i - .2 for i in x], [r[1] for r in R], .4, label="MRR@10", color="#4C72B0")
ax.bar([i + .2 for i in x], [r[2] for r in R], .4, label="Hit@1", color="#DD8452")
for i, r in enumerate(R):
    ax.text(i - .2, r[1] + .01, f"{r[1]:.3f}", ha="center", fontsize=9); ax.text(i + .2, r[2] + .01, f"{r[2]:.0%}", ha="center", fontsize=9)
ax.set_xticks(list(x)); ax.set_xticklabels([r[0] for r in R], fontsize=8.5); ax.set_ylim(0, 1.05)
ax.set_title("① 早期 44 题：切分 → 混合 → 重排"); ax.legend(loc="upper left"); ax.grid(axis="y", alpha=.3)
x2 = range(len(R2))
ax2.bar(list(x2), [r[1] for r in R2], .5, color=["#4C72B0", "#55A868", "#8C8C8C", "#55A868"])
for i, r in enumerate(R2):
    ax2.text(i, r[1] + .01, f"{r[1]:.3f}", ha="center", fontsize=9)
ax2.set_xticks(list(x2)); ax2.set_xticklabels([r[0] for r in R2], fontsize=8.5); ax2.set_ylim(0, 1.05)
ax2.set_title("② 新评测集：块级 MRR（heading_v2 + 混合 + 重排）"); ax2.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.savefig("docs/images/retrieval_evolution.png", dpi=130); plt.close()
# 图 2：output/version_scores.md（eval_set_50 自动规则 v2；最后一项 eval_set_v3 规则 v3）
G = [("基线\n3B·p0", .50, .68), ("表格父子块\n3B·p0", .56, .70), ("Prompt p1\n3B", .56, .70), ("DeepSeek-V3\np1", .78, .89),
     ("Qwen2.5-72B\np1", .80, .90), ("DeepSeek-V3\np2", .86, .93), ("新评测集139题\nV3·p2", .85, .91), ("139题\nV3·p3", .86, .906)]
fig, ax = plt.subplots(figsize=(10.5, 4.4))
x = range(len(G)); col = ["#8C8C8C"] * 3 + ["#55A868"] * 3 + ["#C44E52"] * 2
ax.bar(x, [g[1] for g in G], .55, color=col, label="正确率")
ax.plot(x, [g[2] for g in G], "o-", color="#4C72B0", label="综合得分")
for i, g in enumerate(G):
    ax.text(i, g[1] + .015, f"{g[1]:.0%}", ha="center", fontsize=9); ax.text(i, g[2] + .03, f"{g[2]:.2f}", ha="center", fontsize=8, color="#4C72B0")
ax.axvline(5.5, ls="--", color="gray", lw=.8); ax.text(5.45, 1.0, "← 评测集 50 题 | 139 题 →", fontsize=8, color="gray", ha="center")
ax.set_xticks(list(x)); ax.set_xticklabels([g[0] for g in G], fontsize=8.5); ax.set_ylim(0, 1.08)
ax.set_title("回答正确率演进（灰=本地 qwen2.5:3b，绿=云端，红=新评测集）"); ax.legend(loc="upper left"); ax.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.savefig("docs/images/answer_evolution.png", dpi=130); plt.close()
# 图 3：归因（output/eval_runs/v3set_sf_v3_p2_attr_20261011-120349/summary.json → attribution）
A = [("全部 139", .849, .05, .101), ("查参数 55", .873, .055, .073), ("故障排查 41", .805, .073, .122), ("操作步骤 43", .86, .023, .116),
     ("中文 113", .867, .044, .088), ("英文 26", .769, .077, .154), ("表格题 33", .848, .121, .03), ("文本题 106", .849, .028, .123)]
fig, ax = plt.subplots(figsize=(10.5, 4.2)); x = range(len(A))
b1 = [a[1] for a in A]; b2 = [a[2] for a in A]; b3 = [a[3] for a in A]
ax.bar(x, b1, .6, color="#55A868", label="正确"); ax.bar(x, b2, .6, bottom=b1, color="#C44E52", label="检索失败")
ax.bar(x, b3, .6, bottom=[i + j for i, j in zip(b1, b2)], color="#DD8452", label="生成漏写/部分")
for i, a in enumerate(A):
    ax.text(i, a[1] / 2, f"{a[1]:.0%}", ha="center", color="white", fontsize=9)
    ax.text(i, a[1] + a[2] + a[3] + .01, f"检{a[2]:.0%}·生{a[3]:.0%}", ha="center", fontsize=7.5)
ax.set_xticks(list(x)); ax.set_xticklabels([a[0] for a in A], fontsize=9); ax.set_ylim(0, 1.12)
ax.set_title("失败归因（eval_set_v3，DeepSeek-V3 + p2，规则 v3）"); ax.legend(loc="lower right", fontsize=8); ax.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.savefig("docs/images/attribution.png", dpi=130); plt.close(); print("ok", plt.rcParams["font.sans-serif"][0])
