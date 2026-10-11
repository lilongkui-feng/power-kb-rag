# -*- coding: utf-8 -*-
"""扫描页 / 文字转曲页 OCR：PyMuPDF 渲染 -> 识别引擎 -> 按版面排序成行。
引擎（--ocr-engine / 环境变量 OCR_ENGINE）：
  paddle（默认，若 /workspace/paddle_env 可用）：PP-StructureV3 = PP-OCRv5_server 识别 + 版面分析 + 表格结构识别(SLANeXt/SLANet_plus)，
          表格输出 HTML；以常驻子进程（paddle/paddle_worker.py，独立 Python 3.11 环境）方式调用
  rapid：RapidOCR(PP-OCRv4 ONNX)，只有文字，表格靠行重组（" | " 分隔）

用法：
  python ocr.py <file.pdf> [--pages 1-5] [--dpi 200] [--searchable out.pdf] [--show]

对外接口：
  ocr_page(page, dpi=200) -> {"rows": [{y0,y1,x0,x1,text,cells,conf}], "boxes": [...], "avg_conf", "n_boxes", "secs"}
  ocr_rows_as_blocks(res) -> [(y0, y1, [text])]   # 与 parse._pdf_blocks 同格式（PDF 坐标，pt）
  make_searchable_pdf(src, dst, results)         # 叠加不可见文字层，生成可搜索 PDF
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, statistics, time
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".ocr_cache")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
MIN_SCORE = 0.6           # 低于此置信度的文本框丢弃（多为图形线条误识别）

from config import settings as _cfg
PADDLE_PY = _cfg().paddle_py
PADDLE_WORKER = os.path.join(HERE, "paddle", "paddle_worker.py")

def default_engine() -> str:
    e = _cfg().ocr_engine
    if e:
        return e
    return "paddle" if os.path.exists(PADDLE_PY) else "rapid"

class PaddleClient:
    """常驻 paddle 子进程（首次调用时启动，模型只加载一次，约 20 s / 峰值内存约 3 GB）"""
    _inst = None
    def __init__(self):
        import subprocess
        self.p = subprocess.Popen([PADDLE_PY, PADDLE_WORKER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(os.path.join(HERE, ".paddle_worker.log"), "a"), text=True, bufsize=1)
        self.info = json.loads(self.p.stdout.readline())
        if not self.info.get("ready"):
            raise RuntimeError(f"paddle worker 启动失败：{self.info}")
    @classmethod
    def get(cls):
        if cls._inst is None or cls._inst.p.poll() is not None:
            cls._inst = PaddleClient()
        return cls._inst
    def run(self, image: str, mode: str = "structure") -> dict:
        self.p.stdin.write(json.dumps({"image": image, "mode": mode}) + "\n"); self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        if "error" in r:
            raise RuntimeError(r["error"])
        return r
    @classmethod
    def close(cls):
        if cls._inst and cls._inst.p.poll() is None:
            cls._inst.p.stdin.close(); cls._inst.p.wait(timeout=30)
        cls._inst = None

_engine = None
def get_engine():
    global _engine
    if _engine is None:
        import logging
        from rapidocr import RapidOCR
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        _engine = RapidOCR(params={"Global.log_level": "error"}) if _accepts_params() else RapidOCR()
    return _engine

def _accepts_params() -> bool:
    try:
        from rapidocr import RapidOCR
        RapidOCR(params={"Global.log_level": "error"})
        return True
    except Exception:
        return False

def _cache_key(page: pymupdf.Page, dpi: int, engine: str = "rapid") -> str:
    h = hashlib.md5()
    h.update((page.parent.name or "").encode()); h.update(f"{page.number}:{dpi}".encode())
    if engine != "rapid":
        h.update(engine.encode())                      # rapid 保持旧键，旧缓存可用
    try:
        h.update(page.read_contents()[:200000])
    except Exception:
        pass
    return h.hexdigest()

def ocr_page(page: pymupdf.Page, dpi: int = 200, use_cache: bool = True, engine: str | None = None) -> dict:
    engine = engine or default_engine()
    key = _cache_key(page, dpi, engine)
    cpath = os.path.join(CACHE_DIR, key + ".json")
    if use_cache and os.path.exists(cpath):
        res = json.load(open(cpath, encoding="utf-8"))
        res["rows"] = _rows(_text_boxes(res), _vertical_lines(page))   # 缓存只存原始框，行重组每次重新计算
        return res
    t0 = time.time()
    if engine == "paddle":
        res = _ocr_page_paddle(page, dpi)
    else:
        res = _ocr_page_rapid(page, dpi)
    res["secs"] = round(time.time() - t0, 2)
    kept = [b for b in res["boxes"] if b["conf"] >= MIN_SCORE and b["text"]]
    n = sum(len(b["text"]) for b in kept)
    res["avg_conf"] = round(sum(b["conf"] * len(b["text"]) for b in kept) / n, 4) if n else 0.0
    res["low_conf_boxes"] = sum(1 for b in res["boxes"] if b["conf"] < 0.8)
    res["n_boxes"] = len(res["boxes"])
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump(res, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    res["rows"] = _rows(_text_boxes(res), _vertical_lines(page))
    return res

def _text_boxes(res: dict) -> list[dict]:
    """参与正文行重组的文字框：去掉落在已识别表格区域内的框（表格单独结构化输出，避免正文重复）"""
    tabs = [t["bbox"] for t in res.get("tables", [])]
    if not tabs:
        return res["boxes"]
    def inside(b):
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        return any(t[0] - 2 <= cx <= t[2] + 2 and t[1] - 2 <= cy <= t[3] + 2 for t in tabs)
    return [b for b in res["boxes"] if not inside(b)]

def _ocr_page_paddle(page: pymupdf.Page, dpi: int) -> dict:
    import tempfile
    s = 72.0 / dpi
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        page.get_pixmap(dpi=dpi).save(f.name)
        r = PaddleClient.get().run(f.name, "structure")
    os.unlink(f.name)
    boxes = []
    for b in r["boxes"]:
        xs, ys = [p[0] for p in b["poly"]], [p[1] for p in b["poly"]]
        boxes.append({"x0": min(xs) * s, "y0": min(ys) * s, "x1": max(xs) * s, "y1": max(ys) * s, "text": b["text"].strip(), "conf": b["conf"]})
    sc = lambda bb: [bb[0] * s, bb[1] * s, bb[2] * s, bb[3] * s]
    layout = [{"label": b["label"], "bbox": sc(b["bbox"]), "content": b["content"]} for b in r["layout"]]
    tables = [{"bbox": sc(t["bbox"]), "html": t["html"]} for t in r["tables"]]
    for t in tables:                                   # 表题：表格上方最近的标题/文本块（版面标签 table_title / header / text）
        above = [b for b in layout if b["label"] in ("table_title", "header", "text", "paragraph_title", "figure_title")
                 and b["bbox"][3] <= t["bbox"][1] + 5 and t["bbox"][1] - b["bbox"][3] < 60]
        t["caption"] = max(above, key=lambda b: b["bbox"][3])["content"].strip() if above else ""
    return {"page": page.number + 1, "dpi": dpi, "engine": "paddle", "boxes": boxes, "layout": layout, "tables": tables,
            "worker_maxrss_mb": r.get("maxrss_mb")}

def _ocr_page_rapid(page: pymupdf.Page, dpi: int) -> dict:
    pix = page.get_pixmap(dpi=dpi)
    import numpy as np
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    img = img[:, :, ::-1].copy()                       # RGB -> BGR（OpenCV 约定）
    r = get_engine()(img)
    s = 72.0 / dpi                                     # 像素 -> PDF 坐标(pt)
    boxes = []
    if r.boxes is not None:
        for b, t, sc in zip(r.boxes, r.txts, r.scores):
            xs, ys = [p[0] for p in b], [p[1] for p in b]
            boxes.append({"x0": float(min(xs)) * s, "y0": float(min(ys)) * s, "x1": float(max(xs)) * s, "y1": float(max(ys)) * s,
                          "text": t.strip(), "conf": float(sc)})
    return {"page": page.number + 1, "dpi": dpi, "engine": "rapid", "boxes": boxes}

def _vertical_lines(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """矢量页面中的长竖线（栏分隔线候选）：[(x, y0, y1)]；纯图片扫描页返回空"""
    out = []
    try:
        for dr in page.get_drawings():
            for it in dr["items"]:
                if it[0] == "l" and abs(it[1].x - it[2].x) < 1.0 and abs(it[1].y - it[2].y) > 40:
                    out.append((it[1].x, min(it[1].y, it[2].y), max(it[1].y, it[2].y)))
                elif it[0] == "re" and it[1].width < 2 and it[1].height > 40:
                    out.append((it[1].x0, it[1].y0, it[1].y1))
    except Exception:
        pass
    return out

def _is_vertical(b) -> bool:
    w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
    return len(b["text"]) >= 2 and h > 2.5 * w

def _group_rows(bs: list[dict]) -> list[list[dict]]:
    """文本框聚成行：纵向中心落在当前行高度范围内即同一行"""
    bs = sorted(bs, key=lambda b: ((b["y0"] + b["y1"]) / 2, b["x0"]))
    rows: list[list[dict]] = []
    for b in bs:
        cy, h = (b["y0"] + b["y1"]) / 2, b["y1"] - b["y0"]
        if rows:
            r = rows[-1]
            ry0, ry1 = min(x["y0"] for x in r), max(x["y1"] for x in r)
            if abs(cy - (ry0 + ry1) / 2) <= 0.5 * min(h, ry1 - ry0):
                r.append(b); continue
        rows.append([b])
    return rows

def _gaps(intervals, min_gap):
    """区间并集之间的空隙 [(start, end)]，按宽度降序"""
    iv = sorted(intervals)
    out, end = [], iv[0][1]
    for a, b in iv[1:]:
        if a - end >= min_gap:
            out.append((end, a))
        end = max(end, b)
    return sorted(out, key=lambda g: g[0] - g[1])

def _xycut(bs: list[dict], depth: int = 0, seps: list | None = None) -> list[list[dict]]:
    """简化版递归 XY-cut，恢复多栏/侧栏版面的阅读顺序：
    1) 竖向切：存在贯穿整个区域的竖缝(≥1 字高)，且左右两侧各 ≥3 行、行基线大多不对齐（区别于表格的列）-> 先左后右；
    2) 横向切：在最大的横向空白(≥1 字高)处上下切开；
    3) 否则按行聚合。"""
    if len(bs) <= 2 or depth > 12:
        return _group_rows(bs)
    h = statistics.median(b["y1"] - b["y0"] for b in bs)
    for g0, g1 in _gaps([(b["x0"], b["x1"]) for b in bs], 1.0 * h):
        L = [b for b in bs if b["x1"] <= g0 + 0.1]
        R = [b for b in bs if b["x0"] >= g1 - 0.1]
        rl, rr = _group_rows(L), _group_rows(R)
        if len(rl) >= 3 and len(rr) >= 3:
            cl = [sum((x["y0"] + x["y1"]) / 2 for x in r) / len(r) for r in rl]
            aligned = sum(1 for r in rr if any(abs(sum((x["y0"] + x["y1"]) / 2 for x in r) / len(r) - c) < 0.4 * h for c in cl))
            ys0, ys1 = min(b["y0"] for b in bs), max(b["y1"] for b in bs)
            # 侧栏：竖缝里有一条贯穿区域大部分高度的竖线，且右侧多为单框中文文字行（不是表格的数值列）
            sep = any(g0 - 2 <= x <= g1 + 2 and min(y1, ys1) - max(y0, ys0) >= 0.7 * (ys1 - ys0)
                      for x, y0, y1 in (seps or []))
            prose = sum(1 for r in rr if len(r) == 1 and CJK_RE.search(r[0]["text"])) >= 0.7 * len(rr)
            if aligned < 0.5 * len(rr) or (sep and prose):
                return _xycut(L, depth + 1, seps) + _xycut(R, depth + 1, seps)
    gy = _gaps([(b["y0"], b["y1"]) for b in bs], 1.0 * h)
    if gy:
        cut = (gy[0][0] + gy[0][1]) / 2
        return _xycut([b for b in bs if b["y1"] <= cut], depth + 1, seps) + _xycut([b for b in bs if b["y1"] > cut], depth + 1, seps)
    return _group_rows(bs)

def _rows(boxes: list[dict], seps: list | None = None) -> list[dict]:
    """文本框 -> 按阅读顺序排列的行。行内 ≥3 个相距较远的框视为表格行，用 ' | ' 连接单元格。
    过滤：低置信度框、竖排文字（多为图中标注）、只含短编号/字母的图注行（如 'W1 W1'、'H2'）。"""
    bs = [b for b in boxes if b["conf"] >= MIN_SCORE and b["text"] and not _is_vertical(b)]
    if not bs:
        return []
    rows = _xycut(bs, 0, seps)
    out = []
    for r in rows:
        r.sort(key=lambda b: b["x0"])
        h = statistics.median(b["y1"] - b["y0"] for b in r)
        cells = [r[0]["text"]]
        for p, b in zip(r, r[1:]):
            gap = b["x0"] - p["x1"]
            if gap < 0.6 * h and len(r) < 3:          # 同一行被拆开的文字（如 '1' + '使用信息'）
                cells[-1] += ("" if CJK_RE.match(b["text"][:1]) and CJK_RE.search(cells[-1][-1:]) else " ") + b["text"]
            else:
                cells.append(b["text"])
        joined = "".join(cells)
        # 图中标注：多数单元格是 'W1'、'H'、'A1'、'7' 这类 ≤2 字母+≤1 数字的短标签
        lab = sum(1 for c in cells if re.fullmatch(r"[A-Za-zΦφ]{1,2}\d?|[A-Z]\d?\(max\)", c.replace(" ", "")))
        if lab >= 0.6 * len(cells) and len(cells) >= 2:
            continue
        nz = re.sub(r"\s", "", joined)
        if len(nz) >= 4 and max(nz.count(ch) for ch in set(nz)) >= 0.5 * len(nz) and not re.fullmatch(r"[-\d.|]+", nz):
            continue                                   # '电由由 由由由油' 之类图形误识别
        if len(cells) <= 3 and not CJK_RE.search(joined) and len(re.sub(r"\W", "", joined)) <= 4 * len(cells) \
                and all(len(c) <= 6 for c in cells):
            continue                                   # 图中尺寸标注 / 编号
        text = " | ".join(cells) if len(cells) >= 3 else " ".join(cells)
        out.append({"y0": min(b["y0"] for b in r), "y1": max(b["y1"] for b in r),
                    "x0": r[0]["x0"], "x1": max(b["x1"] for b in r), "text": text,
                    "cells": len(cells), "conf": round(min(b["conf"] for b in r), 4)})
    # 大字号章标题 '2检查 测试' -> '2 检查 测试'（编号与标题之间补空格，便于标题识别）
    if out:
        mh = statistics.median(r["y1"] - r["y0"] for r in out)
        for r in out:
            if r["y1"] - r["y0"] >= 1.3 * mh:
                r["big"] = round((r["y1"] - r["y0"]) / mh, 2)
                t = r["text"]
                parts = t.split(" | ")
                if 2 <= len(parts) <= 3 and len(t) <= 24 and all(re.fullmatch(r"[\d\u4e00-\u9fff]+", p) for p in parts):
                    t = parts[0] + " " + "、".join(parts[1:])          # '4 | 安装 | 接线' -> '4 安装、接线'
                # 章编号常印在色块里（反白），OCR 易把数字认成形近字母/圈码：仅在大字号行首且紧跟中文时纠正
                t = re.sub(r"^[①-⑨]", lambda m: str(ord(m.group(0)) - 0x245F), t)
                t = re.sub(r"^[BSOlIZ](?=[\u4e00-\u9fff])", lambda m: {"B": "3", "S": "5", "O": "0", "l": "1", "I": "1", "Z": "2"}[m.group(0)], t)
                r["text"] = re.sub(r"^(\d{1,2})(?=[\u4e00-\u9fff])", r"\1 ", t)
    # 列表序号纠错：'k）…' 之后的 '1）' 实为字母 'l）'（OCR 常把 l 识别为 1）
    for a, b in zip(out, out[1:]):
        if re.match(r"k[）)]", a["text"]) and re.match(r"1[）)]", b["text"]):
            b["text"] = "l" + b["text"][1:]
    return out

def ocr_rows_as_blocks(res: dict) -> list[tuple[float, float, list[str]]]:
    return [(r["y0"], r["y1"], [r["text"]]) for r in res["rows"]]

def make_searchable_pdf(src: str, dst: str, results: dict[int, dict]):
    """在原页面上叠加不可见文字（render_mode=3），可被选择/搜索/复制。"""
    d = pymupdf.open(src)
    for pno, res in results.items():
        page = d[pno - 1]
        for b in res["boxes"]:
            if b["conf"] < MIN_SCORE or not b["text"]:
                continue
            w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
            if w <= 0 or h <= 0:
                continue
            size = h * 0.85
            tl = pymupdf.get_text_length(b["text"], fontname="china-s", fontsize=size)
            if tl > w and tl > 0:
                size *= w / tl
            page.insert_text((b["x0"], b["y1"] - h * 0.18), b["text"], fontname="china-s",
                             fontsize=max(size, 1), render_mode=3)
    d.save(dst, garbage=3, deflate=True)

def _parse_range(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(1, n + 1))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return [p for p in out if 1 <= p <= n]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--pages", default=None, help="如 1-5,8")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--searchable", default=None, help="输出可搜索 PDF 路径")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--ocr-engine", choices=["paddle", "rapid"], default=None, help="默认 paddle（可用时），否则 rapid")
    a = ap.parse_args()
    d = pymupdf.open(a.file)
    results = {}
    for p in _parse_range(a.pages, d.page_count):
        res = ocr_page(d[p - 1], a.dpi, engine=a.ocr_engine)
        results[p] = res
        print(f"page {p}: boxes={res['n_boxes']} rows={len(res['rows'])} avg_conf={res['avg_conf']} "
              f"low_conf={res['low_conf_boxes']} {res['secs']}s")
        if a.show:
            print("\n".join(r["text"] for r in res["rows"]))
            for t in res.get("tables", []):
                print(f"[表格] {t.get('caption')}\n{t['html'][:2000]}")
    if a.searchable:
        make_searchable_pdf(a.file, a.searchable, results)
        print("searchable PDF ->", a.searchable)
