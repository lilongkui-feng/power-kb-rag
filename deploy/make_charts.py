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
# 图 1：output/rerank_results.md all44 + hybrid_results.md all44
R = [("定长切分\n纯向量", 0.658, 0.500), ("章节切分\n纯向量", 0.807, 0.727), ("+BM25 混合\nα=0.5", 0.850, 0.750), ("+bge-reranker\nTop20 β0.8", 0.911, 0.841)]
fig, ax = plt.subplots(figsize=(8, 4.2))
x = range(len(R))
ax.bar([i - .2 for i in x], [r[1] for r in R], .4, label="MRR@10", color="#4C72B0")
ax.bar([i + .2 for i in x], [r[2] for r in R], .4, label="Hit@1", color="#DD8452")
for i, r in enumerate(R):
    ax.text(i - .2, r[1] + .01, f"{r[1]:.3f}", ha="center", fontsize=9); ax.text(i + .2, r[2] + .01, f"{r[2]:.0%}", ha="center", fontsize=9)
ax.set_xticks(list(x)); ax.set_xticklabels([r[0] for r in R]); ax.set_ylim(0, 1.05)
ax.set_title("检索效果演进（44 题评测集，块级命中）"); ax.legend(loc="upper left"); ax.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.savefig("docs/images/retrieval_evolution.png", dpi=130); plt.close()
# 图 2：output/version_scores.md（eval_set_50 自动规则 v2；最后一项 eval_set_v3 规则 v3）
G = [("基线\n3B·p0", .50, .68), ("表格父子块\n3B·p0", .56, .70), ("Prompt p1\n3B", .56, .70), ("DeepSeek-V3\np1", .78, .89),
     ("Qwen2.5-72B\np1", .80, .90), ("DeepSeek-V3\np2", .86, .93), ("新评测集139题\nV3·p2", .85, .91)]
fig, ax = plt.subplots(figsize=(9.5, 4.4))
x = range(len(G)); col = ["#8C8C8C"] * 3 + ["#55A868"] * 3 + ["#C44E52"]
ax.bar(x, [g[1] for g in G], .55, color=col, label="正确率")
ax.plot(x, [g[2] for g in G], "o-", color="#4C72B0", label="综合得分")
for i, g in enumerate(G):
    ax.text(i, g[1] + .015, f"{g[1]:.0%}", ha="center", fontsize=9); ax.text(i, g[2] + .03, f"{g[2]:.2f}", ha="center", fontsize=8, color="#4C72B0")
ax.axvline(5.5, ls="--", color="gray", lw=.8); ax.text(5.45, 1.0, "← 评测集 50 题 | 139 题 →", fontsize=8, color="gray", ha="center")
ax.set_xticks(list(x)); ax.set_xticklabels([g[0] for g in G], fontsize=8.5); ax.set_ylim(0, 1.08)
ax.set_title("回答正确率演进（灰=本地 qwen2.5:3b，绿=云端，红=新评测集）"); ax.legend(loc="upper left"); ax.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.savefig("docs/images/answer_evolution.png", dpi=130); plt.close(); print("ok", plt.rcParams["font.sans-serif"][0])
