# -*- coding: utf-8 -*-
"""表格结构化：文字型 PDF 用 PyMuPDF page.find_tables()，扫描页用 PP-StructureV3 输出的 HTML。
统一表示 Table = {table_id, source, page_start, page_end, caption, number, header_rows, header, rows, n_rows, n_cols, engine, bbox}
  header_rows: 原始多行表头（合并单元格已展开填充）；header: 每列合成的列名（多行表头用 "/" 连接）
  rows: 表体（合并单元格：纵向合并向下填充、横向合并向右填充）
提供：Markdown 渲染、行级自然语言描述、跨页续表合并。"""
from __future__ import annotations
import html as _html, re
from html.parser import HTMLParser

CAPTION_RE = re.compile(r"^\s*(续?\s*表\s*[A-Z]?\.?\s*\d+(?:[.\-]\d+)*|Table\s+[A-Z]?\.?\d+(?:[.\-]\d+)*)\s*(.*)$", re.I)
CONT_RE = re.compile(r"^\s*(续\s*表|\(?continued\)?|表\s*[A-Z]?\d+(?:\.\d+)*\s*[（(]续[)）])", re.I)
NUMERIC_RE = re.compile(r"^[\s\d.,%~～≤≥<>±×xX/+\-—–μ()（）]*$")

def clean_cell(x) -> str:
    if x is None:
        return None
    x = re.sub(r"\s*\n\s*", " ", str(x))
    x = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", x)   # 单元格内中文折行产生的空格
    return re.sub(r"\s+", " ", x).strip()

# ---------------- HTML -> 网格 ----------------
class _HP(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.cell = None
    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self.cell = {"text": "", "rs": int(a.get("rowspan", 1) or 1), "cs": int(a.get("colspan", 1) or 1)}
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(self.cell); self.cell = None
    def handle_data(self, d):
        if self.cell is not None:
            self.cell["text"] += d

def html_to_grid(h: str) -> tuple[list[list[str]], list[list[bool]]]:
    """展开 rowspan/colspan -> (grid, is_span)：被合并覆盖的格子填入原单元格文字，is_span 标 True"""
    p = _HP(); p.feed(h)
    grid, span = {}, {}
    for r, row in enumerate(p.rows):
        c = 0
        for cell in row:
            while (r, c) in grid:
                c += 1
            t = clean_cell(_html.unescape(cell["text"]))
            for dr in range(cell["rs"]):
                for dc in range(cell["cs"]):
                    grid[(r + dr, c + dc)] = t
                    span[(r + dr, c + dc)] = (dr, dc) != (0, 0)
            c += cell["cs"]
    if not grid:
        return [], []
    R = max(k[0] for k in grid) + 1; C = max(k[1] for k in grid) + 1
    return ([[grid.get((r, c), "") for c in range(C)] for r in range(R)],
            [[span.get((r, c), False) for c in range(C)] for r in range(R)])

# ---------------- PyMuPDF 表格 -> 网格 ----------------
def fill_merged(raw: list[list]) -> tuple[list[list[str]], list[list[bool]]]:
    """find_tables().extract() 中合并单元格被覆盖的位置为 None：首行/表头横向填充，其余优先纵向填充"""
    R = len(raw); C = max((len(r) for r in raw), default=0)
    g = [[clean_cell(r[c]) if c < len(r) else None for c in range(C)] for r in raw]
    span = [[v is None for v in row] for row in g]
    for r in range(R):
        if g[r][0] and all(v is None for v in g[r][1:]):      # 整行通栏（表注“注：…”/分组标题）
            g[r][1:] = [""] * (C - 1); span[r][1:] = [True] * (C - 1); continue
        headerish = r < 2 and sum(1 for x in g[r] if x and not NUMERIC_RE.match(x)) >= sum(1 for x in g[r] if x)
        for c in range(C):
            if g[r][c] is None:
                up = g[r - 1][c] if r > 0 else None
                left = g[r][c - 1] if c > 0 else None
                if headerish and r == 0 and left is not None:
                    g[r][c] = left                 # 表头跨列分组
                elif up is not None:
                    g[r][c] = up                   # 纵向合并（行标签/分组列）
                elif left is not None:
                    g[r][c] = left                 # 横向合并
                else:
                    g[r][c] = ""
    return g, span

def split_header(grid, span, max_header=4) -> int:
    """表头行数：第 1 行默认表头；若表头行存在横向合并（跨列分组），下一行也算表头（多行表头），最多 3 行"""
    if len(grid) < 2:
        return 0
    k = 1
    while k < min(max_header, len(grid) - 1):
        row_has_hspan = any(span[k - 1][c] and c > 0 and grid[k - 1][c] == grid[k - 1][c - 1] for c in range(len(grid[0])))
        nxt = grid[k]
        nxt_text = sum(1 for x in nxt if x and not NUMERIC_RE.match(x))
        nxt_vspan = any(span[k][c] and grid[k][c] == grid[k - 1][c] for c in range(len(nxt)))   # 与上一行纵向合并的格
        nxt_num = sum(1 for x in nxt if x and NUMERIC_RE.match(x))
        no_digit = not any(re.search(r"\d", x or "") for x in nxt)
        short = sum(len(x) for x in nxt if x) / max(1, sum(1 for x in nxt if x)) <= 8
        prev_holes = [c for c, x in enumerate(grid[k - 1]) if not x]
        is_val = lambda x: bool(re.fullmatch(r"[<>≤≥±~～＜]?\s*\d+(?:\.\d+)?\s*[a-zA-ZΩ%μ/()（）]*", x or ""))
        fills_holes = prev_holes and all(nxt[c] for c in prev_holes) and nxt_num == 0 and not any(is_val(x) for x in nxt)
        if ((row_has_hspan or nxt_vspan) and nxt_text >= max(1, len(nxt) // 2) and nxt_num == 0) \
                or (no_digit and short and any(nxt)) or fills_holes:
            k += 1
        else:
            break
    return k

def header_names(header_rows: list[list[str]]) -> list[str]:
    if not header_rows:
        return []
    C = len(header_rows[0]); out = []
    for c in range(C):
        parts = []
        for r in header_rows:
            v = r[c] if c < len(r) else ""
            if v and (not parts or parts[-1] != v):
                parts.append(v)
        out.append("/".join(parts) or f"列{c + 1}")
    return out

def make_table(grid, span, *, source, page, caption="", engine="pymupdf", bbox=None, idx=0) -> dict | None:
    grid = [r for r in grid if any(x for x in r)]
    # 通栏行（表注“a 参考注意值…”、分组标题）：所有列文字相同 -> 只保留在第 1 列
    grid = [([r[0]] + [""] * (len(r) - 1)) if len(r) > 1 and r[0] and len(set(r)) == 1 else r for r in grid]
    if len(grid) < 2 or len(grid[0]) < 2:
        return None
    # 去掉全空列
    keep = [c for c in range(len(grid[0])) if any(r[c] for r in grid)]
    grid = [[r[c] for c in keep] for r in grid]; span = [[s[c] for c in keep] for s in span[:len(grid)]] if span else [[False] * len(keep)] * len(grid)
    k = split_header(grid, span)
    # 假表过滤（人工核对发现）：封面/版式框/图中符号被识别成表——不同单元格文字 ≤3 种，或表体 ≤1 行且只有 2 列
    distinct = {x for r in grid for x in r if x}
    if len(distinct) <= 3 or (len(grid) - k <= 1 and len(grid[0]) <= 2):
        return None
    m = CAPTION_RE.match(caption or "")
    return {"table_id": f"{source}#p{page}t{idx}", "source": source, "page_start": page, "page_end": page,
            "caption": (caption or "").strip(), "number": re.sub(r"\s", "", m.group(1)) if m else "",
            "header_rows": grid[:k], "header": header_names(grid[:k]), "rows": grid[k:],
            "n_rows": len(grid) - k, "n_cols": len(grid[0]), "engine": engine, "bbox": list(bbox) if bbox else None}

def _join_rows(prev: list[list[str]], rows: list[list[str]]) -> list[list[str]]:
    """续表拼接：①续页第一行是上一行被分页截断的后半（首列为空或以括号开头）-> 逐格并入上一行；
    ②上一页末尾的纵向合并单元格（分组列）延续到续页 -> 续页开头该列为空的行向下填充"""
    rows = [list(r) for r in rows]
    if prev and rows and (not rows[0][0] or rows[0][0].startswith(("（", "("))) and any(rows[0][1:]):
        last = prev[-1]
        prev = prev[:-1] + [[(a + " " + b).strip() if b and b not in a else a for a, b in zip(last, rows[0])]]
        rows = rows[1:]
    if prev:
        last = prev[-1]
        for c, v in enumerate(last):
            if v and sum(1 for r in prev if r[c] == v) >= 2:      # 该列在上一页是合并单元格
                for r in rows:
                    if r[c]:
                        break
                    r[c] = v
    return prev + rows

def drop_template_rows(tables: list[dict], min_pages: int = 3) -> list[dict]:
    """页框/标题栏（如『河南平高电气股份有限公司｜安装使用说明书｜第3页｜共5页』）被并进表格：
    同一行文字（数字归一）出现在 ≥3 个不同页的表中 -> 视为版式行删除；删完不足 2 行的表丢弃"""
    from collections import defaultdict
    key = lambda r: re.sub(r"\d+", "#", "|".join(r))
    pages = defaultdict(set)
    for t in tables:
        for r in t["rows"]:
            pages[key(r)].add(t["page_start"])
    out = []
    for t in tables:
        t["rows"] = [r for r in t["rows"] if len(pages[key(r)]) < min_pages]
        t["n_rows"] = len(t["rows"])
        if t["n_rows"] >= 1:
            out.append(t)
    return out

def merge_continuations(tables: list[dict], page_heights: dict) -> list[dict]:
    """跨页续表：下一页顶部的表与上一页底部的表列数相同，且（无表题 / 表题为“续表” / 表号相同 / 表头相同）-> 合并"""
    out = []
    for t in tables:
        prev = out[-1] if out else None
        if prev and t["page_start"] == prev["page_end"] + 1 and t["n_cols"] == prev["n_cols"]:
            h = page_heights.get(t["page_start"], 842)
            top = (t["bbox"] or [0, 0])[1] < 0.3 * h
            same_head = t["header"] == prev["header"]
            cap = t["caption"]
            cont = (not cap) or CONT_RE.match(cap) or (t["number"] and t["number"].replace("续", "") == prev["number"].replace("续", ""))
            if top and (cont or same_head):
                rows = t["rows"] if same_head else (t["header_rows"] + t["rows"] if not t["header_rows"] or t["header"] != prev["header"] and not cap else t["rows"])
                if not same_head and cap and CONT_RE.match(cap):
                    rows = t["rows"]               # 续表重复了表头（可能略有差异）：丢弃其表头
                prev["rows"] = _join_rows(prev["rows"], rows); prev["n_rows"] = len(prev["rows"])
                prev["page_end"] = t["page_end"]
                prev.setdefault("merged_from", [prev["table_id"]]).append(t["table_id"])
                continue
        out.append(t)
    return out

# ---------------- 渲染 ----------------
def _md_cell(x: str) -> str:
    return (x or "").replace("|", "\\|").replace("\n", " ")

def to_markdown(t: dict, rows: list[list[str]] | None = None) -> str:
    hdr = t["header"] or [f"列{i + 1}" for i in range(t["n_cols"])]
    rows = t["rows"] if rows is None else rows
    L = ["| " + " | ".join(_md_cell(h) for h in hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        L.append("| " + " | ".join(_md_cell(x) for x in r) + " |")
    return "\n".join(L)

def title_line(t: dict) -> str:
    cap = t["caption"] or "（无表题）"
    pg = f"第{t['page_start']}页" + (f"–{t['page_end']}页" if t["page_end"] != t["page_start"] else "")
    return f"{cap}（{pg}）"

def row_description(t: dict, row: list[str], section: str = "") -> str:
    """行级自然语言描述，如『表3 运行中 SF6 气体质量标准：项目=湿度；有电弧分解物气室 ≤300 μL/L；…』"""
    cap = t["caption"] or "表格"
    groups = []                                        # 同名列（表头跨列）合并为一个字段
    for h, v in zip(t["header"], row):
        if groups and groups[-1][0] == h:
            if v and v not in groups[-1][1]:
                groups[-1][1].append(v)
        else:
            groups.append((h, [v] if v else []))
    pairs, last = [], None
    for h, vs in groups:
        v = " ".join(vs).rstrip("。；; ")
        if not v or v == last and not NUMERIC_RE.match(v):
            last = v; continue
        last = v
        pairs.append(f"{h}：{v}" if h and not h.startswith("列") else v)
    head = f"{cap}" + (f"（{section}）" if section else "")
    return f"{head}：" + "；".join(pairs) + "。"

# ---------------- 文字型 PDF：PyMuPDF find_tables ----------------
def _cell_text(words, rect) -> str:
    """单元格文字：按行聚类（上下标与基线重叠即同一行，避免 'SO\\n2'），行内按 x 排序，紧邻字符不加空格"""
    x0, y0, x1, y1 = rect
    ws = [w for w in words if x0 - 1 <= (w[0] + w[2]) / 2 <= x1 + 1 and y0 - 1 <= (w[1] + w[3]) / 2 <= y1 + 1]
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        h = w[3] - w[1]
        for ln in lines:
            ov = min(ln["y1"], w[3]) - max(ln["y0"], w[1])
            if ov >= 0.3 * min(h, ln["y1"] - ln["y0"]) and (w[3] - w[1]) < 1.5 * (ln["y1"] - ln["y0"]) + 1:
                ln["w"].append(w); ln["y0"] = min(ln["y0"], w[1]); ln["y1"] = max(ln["y1"], w[3]); break
        else:
            lines.append({"y0": w[1], "y1": w[3], "w": [w]})
    out = []
    for ln in sorted(lines, key=lambda l: l["y0"]):
        s, prev = "", None
        for w in sorted(ln["w"], key=lambda w: w[0]):
            if prev is not None:
                gap = w[0] - prev[2]
                cjk = re.search(r"[\u4e00-\u9fff]$", s) or re.match(r"[\u4e00-\u9fff]", w[4])
                s += "" if gap < 1.5 or cjk and gap < 6 else " "
            s += w[4]; prev = w
        out.append(s)
    return "\n".join(out)

SKIP_TITLES = {"前言", "目次", "目录", "引言"}

def _caption_near(blocks, bbox, page_h) -> str:
    """表题：表格上方 45pt 内最近的『表 N …』行（中文标准），或下方 30pt 内的『Table N』；续表亦识别"""
    best, bd = "", 1e9
    for b in blocks:
        if b[6] != 0:
            continue
        for ln in [x.strip() for x in b[4].split("\n") if x.strip()]:
            if not CAPTION_RE.match(ln) or len(ln) > 60:
                continue
            d = bbox[1] - b[3] if b[3] <= bbox[1] + 3 else (b[1] - bbox[3] + 15 if b[1] >= bbox[3] - 3 else 1e9)
            if -3 <= d < 45 and d < bd:
                best, bd = ln, d
    return re.sub(r"\s+", " ", best)

def _grid_from_rects(t, words):
    """按单元格矩形重建网格：被覆盖的位置判断来自左侧（跨列）还是上方（跨行），复制原单元格文字；
    再删掉从不作为单元格起点的列（PyMuPDF 因细碎线段切出的伪列）"""
    rows = [list(r.cells) for r in t.rows]
    R = len(rows); C = max(len(r) for r in rows)
    rows = [r + [None] * (C - len(r)) for r in rows]
    colx = [min((rows[r][c][0] for r in range(R) if rows[r][c]), default=None) for c in range(C)]
    rowy = [t.rows[r].bbox[1] for r in range(R)]
    txt = [[_cell_text(words, rows[r][c]) if rows[r][c] else None for c in range(C)] for r in range(R)]
    grid = [[""] * C for _ in range(R)]; span = [[False] * C for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if rows[r][c]:
                grid[r][c] = clean_cell(txt[r][c]) or ""; continue
            span[r][c] = True
            lc = next((j for j in range(c - 1, -1, -1) if rows[r][j]), None)
            if lc is not None and colx[c] is not None and rows[r][lc][2] > colx[c] + 1:
                grid[r][c] = grid[r][lc]; continue
            if lc is not None and colx[c] is None:
                grid[r][c] = grid[r][lc]; continue
            ur = next((i for i in range(r - 1, -1, -1) if rows[i][c]), None)
            if ur is not None and rows[ur][c][3] > rowy[r] + 1:
                grid[r][c] = grid[ur][c]
    keep = [c for c in range(C) if any(rows[r][c] and grid[r][c] for r in range(R))]
    grid = [[g[c] for c in keep] for g in grid]; span = [[sp[c] for c in keep] for sp in span]
    # 相邻两列“兼容”（每行要么相同要么一侧为空，且至少一行相同非空）-> 同一列被细碎线段切开，合并
    k = 1
    while grid and k < len(grid[0]):
        comp = all(g[k] == g[k - 1] or not g[k] or not g[k - 1] for g in grid)
        same = any(g[k] and g[k] == g[k - 1] for g in grid)
        if comp and same:
            for g, sp in zip(grid, span):
                g[k - 1] = g[k - 1] or g[k]; sp[k - 1] = sp[k - 1] and sp[k]
                del g[k]; del sp[k]
        else:
            k += 1
    return grid, span

def extract_pdf_tables(page, source: str, start_idx: int = 0) -> list[dict]:
    try:
        tf = page.find_tables()
    except Exception:
        return []
    words = page.get_text("words")
    blocks = page.get_text("blocks")
    out = []
    for t in tf.tables:
        if t.row_count < 2:
            continue
        grid, span = _grid_from_rects(t, words)
        if not grid or len(grid[0]) > 12 or len(grid[0]) < 2:
            continue                                   # 图形里的线框（接线图等）常被识别成几十列的“表”
        cells = [x for r in grid for x in r]
        filled = sum(1 for x in cells if x) / max(1, len(cells))
        if filled < 0.35 or sum(len(x) for x in cells if x) < 12:
            continue
        if re.sub(r"\s", "", grid[0][0] or "") in SKIP_TITLES:
            continue                                   # 前言/目次的外框
        cap = _caption_near(blocks, t.bbox, page.rect.height)
        tb = make_table(grid, span, source=source, page=page.number + 1, caption=cap, bbox=t.bbox, idx=start_idx + len(out))
        if tb:
            out.append(tb)
    return out

def _ocr_caption(layout: list[dict], bbox) -> str:
    """扫描页表题：表格上方 80pt 内、以『表N/续表N/Table N』开头的版面块；其次版面标签为 table_title 的块"""
    best, bd = "", 1e9
    for b in layout:
        txt = (b.get("content") or "").strip().split("\n")[0]
        d = bbox[1] - b["bbox"][3]
        if -5 <= d < 80 and (CAPTION_RE.match(txt) or b["label"] == "table_title") and d < bd and len(txt) <= 60:
            best, bd = txt, d
    return re.sub(r"\s+", " ", best)

def tables_from_ocr(res: dict, source: str, start_idx: int = 0) -> list[dict]:
    out = []
    for t in res.get("tables", []):
        grid, span = html_to_grid(t["html"])
        tb = make_table(grid, span, source=source, page=res["page"], caption=_ocr_caption(res.get("layout", []), t["bbox"]), engine="paddle",
                        bbox=t["bbox"], idx=start_idx + len(out))
        if tb:
            out.append(tb)
    return out
