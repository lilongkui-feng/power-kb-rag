# -*- coding: utf-8 -*-
"""v2 管线：parse(tables=True, OCR 引擎默认 PaddleOCR/PP-StructureV3) -> chunk_heading_v2（正文 + 表格父子块）
输出：output/chunks_heading_v2.jsonl（基础库 18 份 PDF）、uploads/chunks_uploaded_v2.jsonl（网页上传过的文档按 v2 重切）、
      output/tables_v2.json（全部结构化表格）、output/tables_stats.md（按文档统计）
之后：python embed_index.py --methods heading_v2 && python bm25_index.py --methods heading_v2（向量缓存命中的正文块不重算）
用法：python build_v2.py [--ocr-engine paddle|rapid] [--only 关键字]"""
from __future__ import annotations
import argparse, json, os, statistics, time
from run import SELECTED
from parse import parse_document
from chunk import chunk_heading_v2

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-root", default="/workspace/power_docs")
    ap.add_argument("--ocr-engine", default=None, choices=["paddle", "rapid"])
    ap.add_argument("--only", default=None)
    ap.add_argument("--max-size", type=int, default=800)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--name", default="heading_v2", help="输出方法名：output/chunks_<name>.jsonl、uploads/chunks_uploaded_<name>.jsonl（heading_v2 用 chunks_uploaded_v2.jsonl）")
    a = ap.parse_args()
    if a.ocr_engine:
        os.environ["OCR_ENGINE"] = a.ocr_engine
    import kb_store
    rows, all_tables, chunks_out = [], [], []
    jobs = [(os.path.join(a.docs_root, p), cat, lang, mp, None) for p, cat, lang, mp in SELECTED]
    jobs += [(r["file"], "上传", None, None, h) for h, r in kb_store._reg().items() if os.path.exists(r["file"])]
    up_chunks = []
    for path, cat, lang, mp, h in jobs:
        if a.only and a.only not in path:
            continue
        t0 = time.time()
        if h:                                            # 上传文档：与网页入库同一函数（chunk_id 前缀 up_<sha8>）
            os.environ["KB_METHOD"] = "heading_v2"
            cs, info, doc = kb_store.chunk_uploaded(path, h, max_size=a.max_size, overlap=a.overlap)
            up_chunks += cs
        else:
            doc = parse_document(path, max_pages=mp, ocr="auto", tables=True)
            cs, info = chunk_heading_v2(doc, max_size=a.max_size, min_size=120, overlap=a.overlap)
            for c in cs:
                c["category"], c["lang"] = cat, lang
            chunks_out += cs
        for t in doc.tables:
            t2 = dict(t); t2["section"] = next((c["heading_path"] for c in cs if c.get("table_id") == t["table_id"]), "")
            all_tables.append(t2)
        n_text = sum(c["chunk_type"] == "text" for c in cs)
        rows.append({"source": doc.source, "pages": len(doc.pages), "ocr_pages": len(doc.ocr_pages),
                     "ocr_engine": ",".join(sorted({o.get("engine", "") for o in doc.ocr_pages})) or "-",
                     "tables": len(doc.tables), "tables_captioned": sum(1 for t in doc.tables if t["caption"]),
                     "tables_cross_page": sum(1 for t in doc.tables if t["page_end"] != t["page_start"]),
                     "text_chunks": n_text, "table_chunks": info["table_chunks"], "row_chunks": info["table_row_chunks"],
                     "secs": round(time.time() - t0, 1)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    from ocr import PaddleClient
    PaddleClient.close()
    if a.only:
        return
    with open(os.path.join(OUT, f"chunks_{a.name}.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks_out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(HERE, "uploads", "chunks_uploaded_v2.jsonl" if a.name == "heading_v2" else f"chunks_uploaded_{a.name}.jsonl"), "w", encoding="utf-8") as f:
        for c in up_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    if a.name != "heading_v2":
        print(f"[{a.name}] 写出 {len(chunks_out)} + {len(up_chunks)} 块"); return
    json.dump(all_tables, open(os.path.join(OUT, "tables_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# v2 管线表格抽取统计", "", f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}（北京时间）；文字页 PyMuPDF find_tables，OCR 页 PP-StructureV3 表格识别。", "",
         "| 文档 | 页 | OCR页(引擎) | 表格 | 有表题 | 跨页合并 | 正文块 | 表格块 | 行级块 | 用时s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['source']} | {r['pages']} | {r['ocr_pages']}({r['ocr_engine']}) | {r['tables']} | {r['tables_captioned']} | {r['tables_cross_page']} | "
                 f"{r['text_chunks']} | {r['table_chunks']} | {r['row_chunks']} | {r['secs']} |")
    tot = lambda k: sum(r[k] for r in rows)
    L.append(f"| **合计** | {tot('pages')} | {tot('ocr_pages')} | {tot('tables')} | {tot('tables_captioned')} | {tot('tables_cross_page')} | "
             f"{tot('text_chunks')} | {tot('table_chunks')} | {tot('row_chunks')} | {round(tot('secs'), 1)} |")
    sizes = [t["n_rows"] for t in all_tables]
    if sizes:
        L += ["", f"表格行数：中位数 {statistics.median(sizes)}，最大 {max(sizes)}；列数中位数 {statistics.median(t['n_cols'] for t in all_tables)}。"]
    open(os.path.join(OUT, "tables_stats.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
