# -*- coding: utf-8 -*-
"""OCR 质量抽查：对照人工转录（看页面图像逐字录入）的片段计算字符错误率 CER，并汇总置信度。
用法：python ocr_eval.py [--engine rapid|paddle] [--no-cache]   -> output/ocr_eval.md / output/ocr_eval_paddle.md + .json
      python ocr_eval.py --compare   -> output/ocr_compare.md（读取两引擎的 json）"""
import argparse, difflib, json, os, re, resource, statistics, time, unicodedata
import pymupdf
from ocr import ocr_page

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = "/workspace/power_docs/manuals/Chint_正泰/正泰_NM1系列塑料外壳式断路器说明书_2025-12.pdf"

# 人工转录的对照文本（只取少量片段用于评估）
GROUND_TRUTH = {
    3: """1 使用信息
a）产品正常使用环境温度-5℃～+40℃；
注：如在-35℃～+70℃范围内使用，请与制造厂协商使用
b）大气的相对湿度在周围最高温度+40℃时不超过50%，最湿月平均最低温度不超过+25℃，且该月平均最大相对湿度不超过90%，并考虑因温度变化发生在产品表面的凝露；
c）海拔超过2000m时，请与制造厂协商使用；
d）产品反时限特性及温度补偿曲线和海拔降容及修正系数表详见产品样本；
e）污染等级：3级；
f）主电路安装类别：Ⅲ；
g）安装条件：不能安装在有显著摇动和冲击振动、特别潮湿、易燃易爆、含有能腐蚀金属和破坏绝缘的气体及外部磁场大于地磁场5倍的地方，否则断路器不能正常工作；
h）安装方式：垂直安装、水平安装
i）外壳防护等级：IP30(接线端子除外)
j）额定绝缘电压Ui:800V(NM1-63H为500V)；
k）断路器不能频繁操作，否则会缩短断路器使用寿命。
l）短路脱扣器单极动作电流整定值：见下表。""",
    17: """6 维护
1）维护检查必须由专业资质人员负责操作。
2）如需加装内、外附件，须按所订型号通过本公司提供，以保证质量；如用户自行选购或改装，产生的使用风险，本公司不能负责。
3）维护操作之前必须切断上级电源，并确保断路器进线端不带电。断路器维护在正常操作条件下每年一次，在非正常条件下每半年一次，维护内容如下：""",
}
# 表格抽查：续表1（第 6 页）数值单元格，人工转录
TABLE_TRUTH = {
    6: """L1 232 235 254 255 367 362 362
L2 121 117 136 136 145 144 144
W 78 76 90 90 105 105 --
W1 25 25 30 30 35 35 35
W2 103 103 120 120 140 140 --
W3 -- -- 65 -- -- 75 75
A 25 25 30 30 35 35 --
B 117 117 130.5 130.5 126 126 126
Φd 4.2 4.5 4.5 4.5×6 4.2 5 5""",
}

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("|", "")
    return re.sub(r"\s", "", s)

def cer(ref: str, hyp: str) -> tuple[float, list]:
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    edits, diffs = 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            edits += max(i2 - i1, j2 - j1)
            diffs.append((op, ref[i1:i2], hyp[j1:j2]))
    return edits / max(1, len(ref)), diffs

ENGINE_DESC = {"rapid": "RapidOCR（PP-OCRv4 检测+方向分类+识别，ONNXRuntime CPU）",
               "paddle": "PaddleOCR 3.x PP-StructureV3（PP-OCRv5_server 检测/识别 + PP-DocLayout 版面 + SLANeXt/SLANet_plus 表格结构，Paddle CPU）"}

def _table_rows_paddle(res):
    """PP-StructureV3 表格 HTML -> 文本行（单元格用 | 分隔），供逐格对照"""
    from tables import html_to_grid
    out = []
    for t in res.get("tables", []):
        grid, _ = html_to_grid(t["html"])
        out += [" | ".join(r) for r in grid]
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="rapid", choices=["rapid", "paddle"])
    ap.add_argument("--no-cache", action="store_true", help="不用 OCR 缓存（测耗时）")
    ap.add_argument("--compare", action="store_true")
    a = args = ap.parse_args()
    if a.compare:
        return compare()
    d = pymupdf.open(PDF)
    L = [f"# NM1 OCR 质量评估（{a.engine}）", "", f"引擎：{ENGINE_DESC[a.engine]}，渲染 200 DPI。", ""]
    t0 = time.time(); per_page = {}
    res = {}
    for p in range(1, d.page_count + 1):
        t = time.time(); res[p] = ocr_page(d[p - 1], use_cache=not a.no_cache, engine=a.engine); per_page[p] = time.time() - t
    total_secs = time.time() - t0
    worker_mb = None
    if args.engine == "paddle":
        from ocr import PaddleClient
        worker_mb = max((r.get("worker_maxrss_mb") or 0) for r in res.values())
        load = PaddleClient._inst.info.get("load_secs") if PaddleClient._inst else None
    else:
        load = None
    main_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    L += ["## 每页置信度", "", "| 页 | 文本框 | 平均置信度(按字数加权) | <0.8 的框 | 版面行数 |", "|---|---|---|---|---|"]
    for p, r in res.items():
        L.append(f"| {p} | {r['n_boxes']} | {r['avg_conf']} | {r['low_conf_boxes']} | {len(r['rows'])} |")
    allc = [b["conf"] for r in res.values() for b in r["boxes"]]
    L += ["", f"全部 {len(allc)} 个文本框：平均置信度 {statistics.mean(allc):.4f}，中位数 {statistics.median(allc):.4f}，"
          f"<0.8 的框 {sum(c < 0.8 for c in allc)} 个（{100 * sum(c < 0.8 for c in allc) / len(allc):.1f}%），多为图中的尺寸标注/端子图形。", ""]
    L += ["## 与人工转录对照（字符错误率 CER，去空白与表格分隔符、NFKC 归一）", ""]
    for p, gt in GROUND_TRUTH.items():
        hyp_all = "\n".join(r["text"] for r in res[p]["rows"]) + "\n" + "\n".join(_table_rows_paddle(res[p]))
        ref, hyp = norm(gt), norm(hyp_all)
        # 在整页 OCR 结果中找与参考片段最匹配的区间
        sm = difflib.SequenceMatcher(None, hyp, ref, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size]
        start = max(0, blocks[0].a - 2) if blocks else 0
        end = min(len(hyp), (blocks[-1].a + blocks[-1].size) if blocks else len(hyp))
        c, diffs = cer(ref, hyp[start:end])
        L += [f"### 第 {p} 页：参考 {len(ref)} 字，CER = {100 * c:.2f}%", ""]
        for op, a, b in diffs[:12]:
            L.append(f"- {op}: 原文「{a}」→ 识别「{b}」")
        L.append("")
    cer_res = {}
    for p, gt in GROUND_TRUTH.items():
        hyp_all = "\n".join(r["text"] for r in res[p]["rows"]) + "\n" + "\n".join(_table_rows_paddle(res[p]))
        ref, hyp = norm(gt), norm(hyp_all)
        sm = difflib.SequenceMatcher(None, hyp, ref, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size]
        start = max(0, blocks[0].a - 2) if blocks else 0
        end = min(len(hyp), (blocks[-1].a + blocks[-1].size) if blocks else len(hyp))
        cer_res[p] = (len(ref), cer(ref, hyp[start:end])[0])
    table_res = {}
    L += ["## 表格抽查（数值单元格逐格对照）", ""]
    for p, gt in TABLE_TRUTH.items():
        rows = _table_rows_paddle(res[p]) or [r["text"] for r in res[p]["rows"]]
        ok = tot = 0
        detail = []
        for line in gt.splitlines():
            label, *cells = line.split()
            # 找以该行标签开头（允许前面有合并单元格的分组名）的 OCR 行
            cand = [r for r in rows if re.search(r"(^|\| )" + re.escape(label) + r" \|", r)] or \
                   [r for r in rows if label in r]
            got = [c.strip() for c in cand[0].split("|")] if cand else []
            got = got[got.index(label) + 1:] if label in got else [c for c in got if re.fullmatch(r"[\d.×\-]+", c)]
            for i, c in enumerate(cells):
                tot += 1
                if i < len(got) and got[i] == c:
                    ok += 1
            detail.append(f"| {label} | {' '.join(cells)} | {' '.join(got) if got else '（未找到）'} |")
        table_res[p] = (ok, tot)
        L += [f"第 {p} 页：{ok}/{tot} 个单元格位置与数值完全正确（{100 * ok / tot:.1f}%）", "",
              "| 行 | 原表 | OCR |", "|---|---|---|"] + detail + [""]
    allc = [b["conf"] for r in res.values() for b in r["boxes"]]
    summ = {"engine": args.engine, "pages": d.page_count, "total_secs": round(total_secs, 1), "secs_per_page": round(total_secs / d.page_count, 2),
            "cached": not args.no_cache, "model_load_secs": load, "main_maxrss_mb": main_mb, "worker_maxrss_mb": worker_mb,
            "boxes": len(allc), "mean_conf": round(statistics.mean(allc), 4), "low_conf_ratio": round(sum(c < 0.8 for c in allc) / len(allc), 4),
            "cer": {str(p): {"ref_chars": n, "cer": round(c, 4)} for p, (n, c) in cer_res.items()},
            "cer_overall": round(sum(n * c for n, c in cer_res.values()) / sum(n for n, _ in cer_res.values()), 4),
            "table_cells": {str(p): {"ok": ok, "total": tot} for p, (ok, tot) in table_res.items()},
            "tables_detected": sum(len(r.get("tables", [])) for r in res.values())}
    L += ["## 汇总", "", "```json", json.dumps(summ, ensure_ascii=False, indent=1), "```"]
    suffix = "" if args.engine == "rapid" else "_" + args.engine
    json.dump(summ, open(os.path.join(HERE, "output", f"ocr_eval{suffix}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = os.path.join(HERE, "output", f"ocr_eval{suffix}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(open(out, encoding="utf-8").read())

def compare():
    R = {e: json.load(open(os.path.join(HERE, "output", f"ocr_eval{'' if e == 'rapid' else '_' + e}.json"), encoding="utf-8")) for e in ("rapid", "paddle")}
    row = lambda name, f: f"| {name} | {f(R['rapid'])} | {f(R['paddle'])} |"
    L = ["# NM1 扫描件 OCR：RapidOCR vs PaddleOCR(PP-StructureV3)", "", "同一 PDF（20 页，文字转曲），200 DPI 渲染，CPU 8 核；人工抄录对照见 ocr_eval.py。", "",
         "| 指标 | RapidOCR | PaddleOCR PP-StructureV3 |", "|---|---|---|",
         row("正文 CER（第 3+17 页，加权）", lambda r: f"{100 * r['cer_overall']:.2f}%"),
         *[row(f"　第 {p} 页 CER（{R['rapid']['cer'][p]['ref_chars']} 字）", lambda r, p=p: f"{100 * r['cer'][p]['cer']:.2f}%") for p in R["rapid"]["cer"]],
         *[row(f"第 {p} 页尺寸表单元格准确率", lambda r, p=p: f"{r['table_cells'][p]['ok']}/{r['table_cells'][p]['total']}") for p in R["rapid"]["table_cells"]],
         row("识别出的结构化表格数", lambda r: r["tables_detected"]),
         row("文本框数 / 平均置信度", lambda r: f"{r['boxes']} / {r['mean_conf']}"),
         row("置信度<0.8 的框占比", lambda r: f"{100 * r['low_conf_ratio']:.1f}%"),
         row("总耗时（20 页，无缓存；Paddle 含子进程启动+模型加载）", lambda r: f"{r['total_secs']} s（{r['secs_per_page']} s/页）"),
         row("模型加载", lambda r: f"{r['model_load_secs']} s" if r["model_load_secs"] else "≈1 s"),
         row("峰值内存（RSS）", lambda r: f"主进程 {r['main_maxrss_mb']} MB" + (f" + 子进程 {r['worker_maxrss_mb']} MB" if r["worker_maxrss_mb"] else "")),
         ]
    open(os.path.join(HERE, "output", "ocr_compare.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
