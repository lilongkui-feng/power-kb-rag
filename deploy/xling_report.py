# 第 1/2 项检索对比 → output/xling_retrieval.md
import json, glob, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = lambda tag: sorted(glob.glob(os.path.join(HERE, f"output/eval_runs/{tag}_2026*")))
def load(tag):
    p = R(tag)
    if not p: return None
    return {r["id"]: r for r in map(json.loads, open(os.path.join(p[-1], "per_item.jsonl"), encoding="utf-8"))}, json.load(open(os.path.join(p[-1], "summary.json")))
def m(rows, ids, key="chunk_rank"):
    rs = [rows[i].get(key) for i in ids if i in rows]
    n = len(rs); f = lambda k: sum(1 for x in rs if x and x <= k) / n
    return f"{f(1):.1%} | {f(5):.1%} | {sum(1 / x for x in rs if x) / n:.3f}"
L = ["# 跨语言检索 / Contextual 前缀 / 多查询：retrieval-only 对比", ""]
xs = {t: load(t) for t in ("xl_none", "xl_dict", "xl_llm", "xl_auto", "xl_auto_llm", "xl_ctx", "xl_v3llm", "xl_v3mismatch", "xl_v3cap")}
items = [json.loads(l) for l in open(os.path.join(HERE, "eval_xling.jsonl"), encoding="utf-8")]
groups = [("全部 36", [d["id"] for d in items]), ("中文问英文档 26", [d["id"] for d in items if d["lang"] == "zh"]),
          ("英文问中文档 10", [d["id"] for d in items if d["lang"] == "en"])]
base = load("v3set_sf_v3_p2")
L += ["## 1. 跨语言评测集 eval_xling.jsonl（36 题：24 道英文原题人工译成中文 + F39/F40 + 10 道中文原题译成英文；gold 同原题）", "",
      "chunk 级 Hit@1 | Hit@5 | MRR；“原语言”= 同一批题用原始语言提问（v3 新基线检索结果），是跨语言的上界参考。", "",
      "| 配置 | " + " | ".join(g for g, _ in groups) + " |", "|---|" + "---|" * len(groups)]
if base:
    orig = {d["id"]: base[0].get(d["id"][:-1]) for d in items}
    orig = {k: v for k, v in orig.items() if v}
    L.append("| 原语言提问（参考上界） | " + " | ".join(m(orig, ids) for _, ids in groups) + " |")
for t, name in (("xl_none", "跨语言提问·无改写"), ("xl_dict", "+ 词典翻译 (xlang=dict)"), ("xl_llm", "+ 本地 3B 翻译 (xlang=llm)"), ("xl_auto", "+ 门控词典 (xlang=auto, 权重0.7)"), ("xl_auto_llm", "+ 门控 3B (xlang=auto_llm)"), ("xl_ctx", "Contextual 前缀集合 (无改写)"), ("xl_v3llm", "+ 云端 V3 翻译 (xlang=llm)"), ("xl_v3mismatch", "+ V3 翻译·语言不一致门控 (mismatch)"), ("xl_v3cap", "+ V3 翻译·译句候选≤30% (cap)")):
    if xs[t]:
        L.append(f"| {name} | " + " | ".join(m(xs[t][0], ids) for _, ids in groups) + " |")
L.append("")
v3 = {t: load(t) for t in ("v3set_sf_v3_p2", "v3_xl_dict", "v3_xl_auto", "v3_ctx", "v3_mq_rule", "v3_ctx_xl_dict", "v3_xl_v3llm", "v3_xl_v3mismatch", "v3_xl_v3cap")}
items3 = [json.loads(l) for l in open(os.path.join(HERE, "eval_set_v3.jsonl"), encoding="utf-8")]
inkb = [d for d in items3 if d["category"] != "拒答"]
g3 = [("全部 139", [d["id"] for d in inkb]), ("中文 113", [d["id"] for d in inkb if d["lang"] == "zh"]), ("英文 26", [d["id"] for d in inkb if d["lang"] == "en"]),
      ("查参数", [d["id"] for d in inkb if d["category"] == "查参数"]), ("故障排查", [d["id"] for d in inkb if d["category"] == "故障排查"]),
      ("操作步骤", [d["id"] for d in inkb if d["category"] == "操作步骤"]), ("综合(多条款)", [d["id"] for d in inkb if d.get("multi") or d.get("type") == "综合"])]
g3 = [g for g in g3 if g[1]]
L += ["## 2. eval_set_v3（139 道库内题）：中文题是否退步", "", "chunk 级 Hit@1 | Hit@5 | MRR", "",
      "| 配置 | " + " | ".join(g for g, _ in g3) + " |", "|---|" + "---|" * len(g3)]
for t, name in (("v3set_sf_v3_p2", "基线 heading_v2 hybrid+rerank"), ("v3_xl_dict", "+ 跨语言 xlang=dict"), ("v3_xl_auto", "+ 跨语言 xlang=auto（门控）"), ("v3_ctx", "Contextual 前缀集合 heading_v2_ctx"),
                ("v3_mq_rule", "+ 多查询 multiq=rule"), ("v3_xl_v3llm", "+ V3 翻译 xlang=llm"), ("v3_xl_v3mismatch", "+ V3 翻译 mismatch 门控"), ("v3_xl_v3cap", "+ V3 翻译 cap 30%"), ("v3_ctx_xl_dict", "ctx 集合 + xlang=dict")):
    if v3[t]:
        L.append(f"| {name} | " + " | ".join(m(v3[t][0], ids) for _, ids in g3) + " |")
L.append("")
if v3["v3set_sf_v3_p2"]:
    b = v3["v3set_sf_v3_p2"][0]
    for t in ("v3_xl_dict", "v3_xl_auto", "v3_ctx", "v3_mq_rule", "v3_ctx_xl_dict", "v3_xl_v3llm", "v3_xl_v3mismatch", "v3_xl_v3cap"):
        if not v3[t]: continue
        x = v3[t][0]; up = []; dn = []
        for d in inkb:
            i = d["id"]; r0 = b[i].get("chunk_rank") or 99; r1 = x[i].get("chunk_rank") or 99
            if r1 < r0: up.append(f"{i}({r0 if r0 < 99 else '-'}→{r1 if r1 < 99 else '-'})")
            if r1 > r0: dn.append(f"{i}({r0 if r0 < 99 else '-'}→{r1 if r1 < 99 else '-'})")
        L += [f"- **{t}** 变好 {len(up)}：{'、'.join(up[:20])}", f"  变差 {len(dn)}：{'、'.join(dn[:20])}"]
open(os.path.join(HERE, "output", "xling_retrieval.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
