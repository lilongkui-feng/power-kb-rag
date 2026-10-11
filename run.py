# -*- coding: utf-8 -*-
"""Day3 流水线：选文档 -> (PDF->DOCX 测试) -> 解析 -> 三种切分 -> 统计 -> 对比样例
用法：python run.py [--docs-root /workspace/power_docs] [--skip-docx-convert]
"""
from __future__ import annotations
import argparse, json, os, re, statistics, time, difflib
from parse import parse_document, pdf_to_docx, detect_heading, TOC_RE
from chunk import chunk_fixed, chunk_heading, chunk_recursive

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

# (相对路径, 类别, 语言, 最大页数)  —— 西门子 2040 页手册只取前 150 页
SELECTED = [
    ("standards_DL/DL_T_664-2025_带电设备红外诊断应用规范.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_587-2025_继电保护和安全自动装置运行管理规程.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_2544-2022_继电保护装置状态检修导则.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_595-2025_六氟化硫电气设备气体监督导则.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_618-2022_GIS现场交接试验规程.pdf", "标准", "zh", None),
    ("standards_DL/DL_T_2890-2025_高压交流断路器机械特性现场试验导则.pdf", "标准", "zh", None),
    ("grid_company/南方电网_设备运行质量评价规则_变电在线监测装置部分_2025.pdf", "电网企业文件", "zh", None),
    ("manuals/Pinggao_平高/平高_ZF12B-126_GIS_安装使用说明书.pdf", "厂商手册", "zh", None),
    ("manuals/Schneider/施耐德_RM6_SeT_安装使用说明书_中文.pdf", "厂商手册", "zh", None),
    ("manuals/Chint_正泰/正泰_NM1系列塑料外壳式断路器说明书_2025-12.pdf", "厂商手册", "zh", None),
    ("manuals/ABB/ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf", "厂商手册", "en", None),
    ("manuals/ABB/ABB_SafeRing-SafePlus_12-24kV_RMU_IOM_1YVA000024_RevF.pdf", "厂商手册", "en", None),
    ("manuals/Schneider/Schneider_SM6-24_Operating_Maintenance_S1B7039801.pdf", "厂商手册", "en", None),
    ("manuals/Schneider/Schneider_GalaxyVS_UPS_Operation_990-5910G.pdf", "厂商手册", "en", None),
    ("manuals/Siemens/SIPROTEC5_7SJ82-85_V8.60_Manual.pdf", "厂商手册", "en", 150),
]
# PDF -> DOCX（pdf2docx），用于测试 docx 解析路径
DOCX_TESTS = [
    ("standards_DL/DL_T_595-2025_六氟化硫电气设备气体监督导则.pdf", "DL_T_595-2025_六氟化硫电气设备气体监督导则.docx", 0, None, "标准", "zh"),
    ("grid_company/南方电网_设备运行质量评价规则_变电在线监测装置部分_2025.pdf", "南方电网_设备运行质量评价规则_变电在线监测装置部分_2025.docx", 0, None, "电网企业文件", "zh"),
    ("manuals/ABB/ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf", "ABB_VD4_36-40.5kV_p1-12.docx", 0, 12, "厂商手册", "en"),
]

def length_stats(chunks):
    if not chunks:
        return {"chunks": 0}
    L = [c["char_len"] for c in chunks]
    return {"chunks": len(L), "avg_len": round(sum(L) / len(L), 1), "median_len": statistics.median(L),
            "max_len": max(L), "min_len": min(L), "lt_100": sum(1 for x in L if x < 100)}

SENT_END_RE = re.compile(r"[。！？；;.!?:：)）】\]]\s*$")

def quality_stats(chunks):
    """边界质量：块是否在句末结束；一个块里混入了几个不同编号条款"""
    if not chunks:
        return {}
    mid = sum(1 for c in chunks if not SENT_END_RE.search(c["text"]))
    mixed = 0
    for c in chunks:
        nums = set()
        for ln in c["text"].split("\n"):
            h = detect_heading(ln)
            if h and h["kind"].startswith("numbered"):
                nums.add(h["number"])
        if len(nums) >= 2:
            mixed += 1
    return {"end_mid_sentence_pct": round(100 * mid / len(chunks), 1),
            "multi_clause_chunks_pct": round(100 * mixed / len(chunks), 1)}

def toc_recall(doc, heading_chunks):
    """标题识别率（以目录为参照）：目录中的编号/标题有多少被识别为章节标题"""
    toc_entries = []
    last_page = doc.pages[-1]["page"] if doc.pages else 0
    for p in doc.pages:
        if p["page"] in doc.toc_pages or any(TOC_RE.search(x) for x in p["text"].split("\n")):
            for ln in p["text"].split("\n"):
                if not TOC_RE.search(ln) and p["page"] not in doc.toc_pages:
                    continue
                m = re.search(r"(\d+)\s*$", ln)
                if m and TOC_RE.search(ln) and int(m.group(1)) > last_page:
                    continue      # 只取解析范围内的目录项（如西门子只解析前 150 页）
                s = TOC_RE.sub("", ln).strip()
                h = detect_heading(s)
                if h:
                    toc_entries.append(h["number"] or h["title"])
                elif s.replace(" ", "") in ("前言", "引言"):
                    toc_entries.append(s.replace(" ", ""))
    toc_entries = list(dict.fromkeys(toc_entries))
    if len(toc_entries) < 3:
        return None
    found = set()
    for c in heading_chunks:
        for seg in [c["heading_path"]] + c.get("merged_sections", []):
            for part in seg.split(" > "):
                found.add(part.split(" ")[0])
                found.add(part)
    hit = sum(1 for e in toc_entries if e in found)
    return {"toc_entries": len(toc_entries), "found": hit, "recall_pct": round(100 * hit / len(toc_entries), 1)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-root", default="/workspace/power_docs")
    ap.add_argument("--skip-docx-convert", action="store_true")
    ap.add_argument("--size", type=int, default=500)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--ocr", choices=["auto", "off", "force"], default="auto", help="无文本层页面是否 OCR（默认 auto）")
    ap.add_argument("--searchable-pdf", action="store_true", help="为 OCR 页 ≥50%% 的文档输出带文字层的可搜索 PDF 到 ocr_out/")
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "parsed"), exist_ok=True)
    docx_dir = os.path.join(HERE, "docx_test")
    os.makedirs(docx_dir, exist_ok=True)

    # 1) PDF -> DOCX
    if not a.skip_docx_convert:
        for src, dst, s, e, *_ in DOCX_TESTS:
            out = os.path.join(docx_dir, dst)
            if not os.path.exists(out):
                t = time.time(); pdf_to_docx(os.path.join(a.docs_root, src), out, s, e)
                print(f"[pdf2docx] {dst} {time.time() - t:.1f}s")

    jobs = [(os.path.join(a.docs_root, p), cat, lang, mp) for p, cat, lang, mp in SELECTED]
    jobs += [(os.path.join(docx_dir, d), cat, lang, None) for _, d, _, _, cat, lang in DOCX_TESTS]

    files = {m: open(os.path.join(OUT, f"chunks_{m}.jsonl"), "w", encoding="utf-8") for m in ("fixed", "heading", "recursive")}
    per_doc, all_chunks = [], {"fixed": [], "heading": [], "recursive": []}
    parsed = {}
    ocr_detail = []
    for path, cat, lang, mp in jobs:
        t0 = time.time()
        doc = parse_document(path, max_pages=mp, ocr=a.ocr)
        parsed[doc.source] = doc
        stem = os.path.splitext(doc.source)[0]
        json.dump({**{k: v for k, v in doc.to_dict().items()}, "category": cat, "lang": lang, "max_pages": mp},
                  open(os.path.join(OUT, "parsed", stem + f".{doc.file_type}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        row = {"source": doc.source, "file_type": doc.file_type, "category": cat, "lang": lang,
               "pages_total": doc.n_pages, "pages_parsed": len(doc.pages), "chars": sum(p["chars"] for p in doc.pages),
               "scanned_pages": len(doc.scanned_pages), "is_scanned": doc.is_scanned,
               "header_footer_templates": len(doc.removed_header_footer),
               "ocr_pages": len(doc.ocr_pages),
               "ocr_avg_conf": (lambda v: round(sum(v) / len(v), 4) if v else None)([o["avg_conf"] for o in doc.ocr_pages if o["boxes"]])}
        if doc.ocr_pages:
            ocr_detail.append({"source": doc.source, "pages": doc.ocr_pages})
            if a.searchable_pdf and len(doc.ocr_pages) >= 0.5 * len(doc.pages) and doc.file_type == "pdf":
                import pymupdf
                from ocr import ocr_page, make_searchable_pdf
                os.makedirs(os.path.join(HERE, "ocr_out"), exist_ok=True)
                src = pymupdf.open(path)
                res = {o["page"]: ocr_page(src[o["page"] - 1]) for o in doc.ocr_pages}
                dst = os.path.join(HERE, "ocr_out", stem + "_searchable.pdf")
                make_searchable_pdf(path, dst, res)
                print(f"[searchable] {dst}")
        if sum(p["chars"] for p in doc.pages) == 0:
            row.update({"note": "无文本层且未 OCR（--ocr off 或未安装 rapidocr），未切分"})
            per_doc.append(row); print(f"[SCANNED] {doc.source}"); continue
        fx = chunk_fixed(doc, a.size, a.overlap)
        hd, info = chunk_heading(doc, max_size=800, min_size=120, overlap=a.overlap)
        rc = chunk_recursive(doc, a.size, a.overlap)
        for c in fx + hd + rc:
            c["category"], c["lang"] = cat, lang
        for m, cs in (("fixed", fx), ("heading", hd), ("recursive", rc)):
            for c in cs:
                files[m].write(json.dumps(c, ensure_ascii=False) + "\n")
            all_chunks[m].extend(cs)
        with_head = sum(1 for c in hd if not c["heading_path"].startswith("（前置"))
        row.update({"fixed_chunks": len(fx), "heading_chunks": len(hd), "recursive_chunks": len(rc),
                    "heading_mode": info["mode"], "headings_detected": info["headings_accepted"],
                    "heading_candidates_rejected": info["headings_rejected"],
                    "legend_lines_skipped": info.get("legend_lines_skipped", 0),
                    "toc_lines_dropped": info.get("toc_lines_dropped", 0),
                    "heading_chunk_with_path_pct": round(100 * with_head / max(1, len(hd)), 1),
                    "toc_recall": toc_recall(doc, hd), "secs": round(time.time() - t0, 2)})
        per_doc.append(row)
        print(f"[OK] {doc.source}: fixed={len(fx)} heading={len(hd)} recursive={len(rc)} mode={info['mode']} "
              f"headings={info['headings_accepted']} toc={row['toc_recall']}")
    for f in files.values():
        f.close()

    # 2) 汇总统计
    summary = {}
    for m, cs in all_chunks.items():
        summary[m] = {**length_stats(cs), **quality_stats(cs)}
        for cat in ("标准", "厂商手册", "电网企业文件"):
            sub = [c for c in cs if c["category"] == cat]
            summary[m][f"by_category:{cat}"] = {**length_stats(sub), **quality_stats(sub)}
    hd = all_chunks["heading"]
    rec = [r["toc_recall"] for r in per_doc if r.get("toc_recall")]
    summary["heading_recognition"] = {
        "chunks_with_heading_path_pct": round(100 * sum(1 for c in hd if not c["heading_path"].startswith("（前置")) / max(1, len(hd)), 1),
        "toc_recall_docs": len(rec),
        "toc_recall_macro_avg_pct": round(sum(r["recall_pct"] for r in rec) / max(1, len(rec)), 1),
        "toc_recall_micro_pct": round(100 * sum(r["found"] for r in rec) / max(1, sum(r["toc_entries"] for r in rec)), 1),
    }
    # docx vs pdf 一致性
    dv = []
    for _, d, s, e, *_ in DOCX_TESTS:
        pdf_name = None
        for p, *_r in SELECTED:
            if os.path.basename(p).startswith(d.split("_p1-")[0].replace(".docx", "")):
                pdf_name = os.path.basename(p)
        dd = parsed.get(d); pd = parsed.get(pdf_name)
        if not dd or not pd:
            continue
        n = len(dd.pages)
        ptext = "".join(re.sub(r"\s", "", p["text"]) for p in pd.pages[:n])
        dtext = "".join(re.sub(r"\s", "", p["text"]) for p in dd.pages)
        sm = difflib.SequenceMatcher(None, ptext[:6000], dtext[:6000], autojunk=False)
        dhd = [c for c in hd if c["source"] == d]
        phd = [c for c in hd if c["source"] == pdf_name and (c["page_start"] or 0) <= n]
        dv.append({"docx": d, "pdf": pdf_name, "pages_compared": n, "pdf_chars": len(ptext), "docx_chars": len(dtext),
                   "text_similarity_first6000": round(sm.ratio(), 3),
                   "docx_heading_style_paragraphs": len(dd.docx_headings),
                   "pdf_heading_chunks(same pages)": len(phd), "docx_heading_chunks": len(dhd)})
    stats = {"params": {"fixed": {"size": a.size, "overlap": a.overlap}, "heading": {"max_size": 800, "min_size": 120},
                        "recursive": {"size": a.size, "overlap": a.overlap}},
             "summary": summary, "per_doc": per_doc, "docx_vs_pdf": dv, "ocr": ocr_detail}
    json.dump(stats, open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_stats_md(stats)
    write_examples(all_chunks)
    print("done ->", OUT)

def write_stats_md(st):
    L = ["# 切分统计", "", f"参数：{json.dumps(st['params'], ensure_ascii=False)}", "", "## 总体（含 OCR 文档；未 OCR 的无文本文档不计）", "",
         "| 方法 | 块数 | 平均长度 | 中位数 | 最大 | 最小 | <100字块 | 句中截断% | 混入多条款% |", "|---|---|---|---|---|---|---|---|---|"]
    for m in ("fixed", "heading", "recursive"):
        s = st["summary"][m]
        L.append(f"| {m} | {s['chunks']} | {s['avg_len']} | {s['median_len']} | {s['max_len']} | {s['min_len']} | {s['lt_100']} | {s['end_mid_sentence_pct']} | {s['multi_clause_chunks_pct']} |")
    L += ["", "## 按文档类别", "", "| 方法 | 类别 | 块数 | 平均 | 最大 | 句中截断% | 混入多条款% |", "|---|---|---|---|---|---|---|"]
    for m in ("fixed", "heading", "recursive"):
        for cat in ("标准", "厂商手册", "电网企业文件"):
            s = st["summary"][m][f"by_category:{cat}"]
            if s.get("chunks"):
                L.append(f"| {m} | {cat} | {s['chunks']} | {s['avg_len']} | {s['max_len']} | {s['end_mid_sentence_pct']} | {s['multi_clause_chunks_pct']} |")
    hr = st["summary"]["heading_recognition"]
    L += ["", "## 标题识别率", "",
          f"- 带章节路径的块占比（heading 法）：{hr['chunks_with_heading_path_pct']}%",
          f"- 以目录为参照的召回（{hr['toc_recall_docs']} 份有目录的文档）：宏平均 {hr['toc_recall_macro_avg_pct']}%，微平均 {hr['toc_recall_micro_pct']}%",
          "", "## 每份文档", "",
          "| 文档 | 类型 | 页(解析/总) | 字数 | 无文本层页 | OCR页(平均置信度) | fixed | heading | recursive | 标题模式 | 识别标题 | 带路径% | 目录召回 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in st["per_doc"]:
        tr = r.get("toc_recall")
        trs = f"{tr['found']}/{tr['toc_entries']} ({tr['recall_pct']}%)" if tr else "-"
        L.append(f"| {r['source']} | {r['file_type']} | {r['pages_parsed']}/{r['pages_total']} | {r['chars']} | {r['scanned_pages']} | "
                 f"{(str(r['ocr_pages']) + ' (' + str(r['ocr_avg_conf'] if r['ocr_avg_conf'] is not None else '无文字') + ')') if r.get('ocr_pages') else '-'} | "
                 f"{r.get('fixed_chunks', '-')} | {r.get('heading_chunks', '-')} | {r.get('recursive_chunks', '-')} | "
                 f"{r.get('heading_mode', r.get('note', '-'))} | {r.get('headings_detected', '-')} | {r.get('heading_chunk_with_path_pct', '-')} | {trs} |")
    if st["docx_vs_pdf"]:
        L += ["", "## DOCX 路径测试（pdf2docx 转换后再用 python-docx 解析）", "",
              "| docx | 对照 PDF | 比较页数 | PDF 字数 | DOCX 字数 | 文本相似度(前6000字) | docx Heading 样式段落 | heading 块(docx) |", "|---|---|---|---|---|---|---|---|"]
        for d in st["docx_vs_pdf"]:
            L.append(f"| {d['docx']} | {d['pdf']} | {d['pages_compared']} | {d['pdf_chars']} | {d['docx_chars']} | {d['text_similarity_first6000']} | {d['docx_heading_style_paragraphs']} | {d['docx_heading_chunks']} |")
    if st.get("ocr"):
        L += ["", "## OCR（RapidOCR / PP-OCR 模型，200 DPI）", "",
              "无文本层页面自动 OCR；置信度为按字符数加权的平均识别置信度，低置信框 = 置信度 < 0.8 的文本框数。", "",
              "| 文档 | OCR 页数 | 平均置信度 | 最低页置信度 | 低置信框/总框 |", "|---|---|---|---|---|"]
        for o in st["ocr"]:
            ps = [p for p in o["pages"] if p["boxes"]]
            if not ps:
                L.append(f"| {o['source']} | {len(o['pages'])} | - | - | 0/0（无文字的图片/空白页）|")
                continue
            L.append(f"| {o['source']} | {len(ps)} | {round(sum(p['avg_conf'] for p in ps) / len(ps), 4)} | "
                     f"{min(p['avg_conf'] for p in ps)} (p{min(ps, key=lambda p: p['avg_conf'])['page']}) | "
                     f"{sum(p['low_conf_boxes'] for p in ps)}/{sum(p['boxes'] for p in ps)} |")
    open(os.path.join(OUT, "stats.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

EXAMPLES = [
    ("DL_T_664-2025_带电设备红外诊断应用规范.pdf", "4.3 环境和设备要求", "环境和设备要求如下"),
    ("DL_T_664-2025_带电设备红外诊断应用规范.pdf", "8.2 相对温差法", "8.2 相对温差法"),
    ("ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf", "3.3.2 Closing procedure", "3.3.2 Closing procedure"),
]

def write_examples(all_chunks):
    L = ["# 切分方式对比样例", "", "同一条款在 fixed（500/50）、heading（章节）、recursive（递归）三种方法下的切分结果。", ""]
    for src, label, needle in EXAMPLES:
        L += [f"## {src} — {label}", ""]
        for m in ("heading", "fixed", "recursive"):
            hits = [c for c in all_chunks[m] if c["source"] == src and
                    ((m != "heading" and needle in c["text"]) or (m == "heading" and (label in c["heading_path"] or any(label in x for x in c.get("merged_sections", [])))))]
            L.append(f"### {m}：命中 {len(hits)} 个块")
            for c in hits[:3]:
                L += ["", f"- chunk_id `{c['chunk_id']}`，页 {c['page_start']}-{c['page_end']}，{c['char_len']} 字"
                      + (f"，章节路径：`{c['heading_path']}`" if c["heading_path"] else "")
                      + (f"，合并的小节：{c['merged_sections']}" if c.get("merged_sections") else ""), "", "```text", c["text"], "```", ""]
        L.append("")
    open(os.path.join(OUT, "comparisons.md"), "w", encoding="utf-8").write("\n".join(L))

if __name__ == "__main__":
    main()
