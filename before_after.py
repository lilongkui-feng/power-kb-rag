# -*- coding: utf-8 -*-
"""表格切分前后对照：DL/T 1359 表3。输出 output/table_before_after.md + output/table_before_after_page.png"""
import json, os, glob, pymupdf
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "output")
Q = "断路器灭弧气室 SO2、H2S 检测值多大时需要跟踪？对应的复测要求和诊断结论是什么？"   # 评测集 F04
pdf = glob.glob("/workspace/power_docs/**/DL_T_1359-2025*.pdf", recursive=True)[0]
d = pymupdf.open(pdf); p = d[4]
p.get_pixmap(dpi=130, clip=pymupdf.Rect(0, 360, p.rect.width, 610)).save(os.path.join(OUT, "table_before_after_page.png"))
v1 = [json.loads(l) for l in open(os.path.join(OUT, "chunks_heading.jsonl"), encoding="utf-8")]
v2 = [json.loads(l) for l in open(os.path.join(OUT, "chunks_heading_v2.jsonl"), encoding="utf-8")]
old = next(c for c in v1 if c["source"].startswith("DL_T_1359") and "表3" in c["text"] and "跟踪" in c["text"])
par = next(c for c in v2 if c.get("chunk_type") == "table" and c["source"].startswith("DL_T_1359") and c["table_caption"].startswith("表3"))
rows = [c for c in v2 if c.get("parent_id") == par["chunk_id"] and c["chunk_type"] == "table_row"]
L = ["# 表格切分前后对照：DL/T 1359-2025 表3 SO2 和 H2S 的注意值", "", "![PDF 第 5 页](table_before_after_page.png)", "",
     f"## v1 旧切块（{old['chunk_id']}，章节切分，表格按文字流抽取）", "", "```text", old["text"], "```", "",
     "问题：表头、行、列被打散成单列文字；“断路器灭弧气室>20”跨行粘连，SO2/H2S 数值失去列归属。", "",
     f"## v2 表格父块（{par['chunk_id']}，chunk_type=table）", "", par["text"], "",
     f"## v2 行级块（chunk_type=table_row，parent_id={par['chunk_id'].split('#')[-1]}）", ""]
L += [f"- `{c['chunk_id'].split('#')[-1]}` {c['text']}" for c in rows]
from retrieve import search
import rag
for name, col in (("v1 heading", "heading"), ("v2 heading_v2", "heading_v2")):
    hits = search(Q, k=5, collection=col)
    L += ["", f"## 同一问题检索：{name}", "", f"问题：{Q}", "", "| # | 类型 | 文件 | 章节 | 文本开头 |", "|---|---|---|---|---|"]
    for h in hits:
        t = h["metadata"].get("chunk_type", "text") + ("→父表" if h.get("expanded") else "")
        L.append(f"| {h['rank']} | {t} | {h['source'][:22]} | {h['heading_path'][:24]} | {h['text'][:60].replace(chr(10), ' ').replace('|', '/')} |")
    r = rag.answer(Q, k=5, hits=hits)
    L += ["", f"**回答（qwen2.5:3b，Prompt p0）**：", "", "> " + r["answer"].replace("\n", "\n> "), "",
          "引用：" + "；".join(f"[{s['id']}] {s['source'][:20]} {s['section']} p{s['pages']}" for s in r["sources"])]
open(os.path.join(OUT, "table_before_after.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("ok")
