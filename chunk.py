# -*- coding: utf-8 -*-
"""三种切分方式：
  a) fixed     固定长度（按字符，默认 500，重叠 50）
  b) heading   按章节标题切分（编号标题识别 + 层级路径；过长二次切分、过短合并）
  c) recursive 递归切分（段落 -> 换行 -> 句号 -> 分号/逗号 -> 字符）
所有块的元数据：source, chunk_id, method, heading_path, title, page_start, page_end, char_len
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from parse import ParsedDoc, detect_heading, TOC_RE

# ---------------- 公共：把文档展平成“行 + 页码” ----------------
@dataclass
class Line:
    text: str
    page: int
    idx_in_page: int = 0     # 该行在页内的序号（非空行），用于判断“页首重新编号”

def doc_lines(doc: ParsedDoc) -> list[Line]:
    out = []
    for p in doc.pages:
        if p["scanned"] and not p.get("ocr"):
            continue
        k = 0
        for ln in p["text"].split("\n"):
            out.append(Line(ln, p["page"], k))
            if ln.strip():
                k += 1
    return out

def _flatten(doc: ParsedDoc):
    """返回 (full_text, offsets) ；offsets[i] = (起始字符位置, 页码)"""
    parts, offsets, pos = [], [], 0
    for p in doc.pages:
        if (p["scanned"] and not p.get("ocr")) or not p["text"]:
            continue
        offsets.append((pos, p["page"]))
        parts.append(p["text"])
        pos += len(p["text"]) + 1
    return "\n".join(parts), offsets

def _page_at(offsets, pos):
    pg = offsets[0][1] if offsets else None
    for start, page in offsets:
        if start <= pos:
            pg = page
        else:
            break
    return pg

def _clen(s: str) -> int:
    return len(re.sub(r"\s", "", s))

# ---------------- a) 固定长度 ----------------
def chunk_fixed(doc: ParsedDoc, size: int = 500, overlap: int = 50) -> list[dict]:
    """按字符滑窗。中文 1 字=1 字符，英文同样按字符计（500 字符≈80-100 英文词）。"""
    text, offsets = _flatten(doc)
    chunks, start, i = [], 0, 0
    step = size - overlap
    while start < len(text):
        end = min(len(text), start + size)
        piece = text[start:end].strip()
        if piece:
            chunks.append(_mk(doc, "fixed", i, piece, _page_at(offsets, start), _page_at(offsets, end - 1)))
            i += 1
        if end >= len(text):
            break
        start += step
    return chunks

# ---------------- c) 递归切分 ----------------
SEPS = ["\n\n", "\n", "。", "；", ". ", "; ", "，", ", ", ""]

def _split_recursive(text: str, size: int, seps=SEPS) -> list[str]:
    if len(text) <= size:
        return [text]
    sep = next((s for s in seps if s and s in text), "")
    if sep == "":
        return [text[i:i + size] for i in range(0, len(text), size)]
    rest = seps[seps.index(sep) + 1:]
    pieces = [p + sep if k < len(text.split(sep)) - 1 else p for k, p in enumerate(text.split(sep))]
    out, cur = [], ""
    for p in pieces:
        if len(p) > size:
            if cur:
                out.append(cur); cur = ""
            out.extend(_split_recursive(p, size, rest))
        elif len(cur) + len(p) <= size:
            cur += p
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out

def recursive_split_text(text: str, size: int = 500, overlap: int = 50, cap: int | None = None) -> list[str]:
    """cap：碎片合并后的长度上限（默认 1.2×size）"""
    cap = cap or int(1.2 * size)
    raw = [p for p in _split_recursive(text, size) if p.strip()]
    # 合并碎片：< 20% size 的小块并入相邻块（合并后不超过 1.2×size），避免只含标题行的孤块
    parts: list[str] = []
    for p in raw:
        if parts and (len(p.strip()) < 0.2 * size or len(parts[-1].strip()) < 0.2 * size) \
                and len(parts[-1]) + len(p) <= cap:
            parts[-1] += p
        else:
            parts.append(p)
    if overlap <= 0 or len(parts) < 2:
        return [p.strip() for p in parts]
    res = [parts[0].strip()]
    for prev, p in zip(parts, parts[1:]):
        tail = prev[-overlap:]
        # 尽量从句子边界开始重叠
        m = re.search(r"[。；.;!?！？]\s*", tail)
        if m and m.end() < len(tail):
            tail = tail[m.end():]
        elif re.search(r"[A-Za-z]\S*\s", tail):          # 英文：至少从词边界开始，避免半个单词
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
        res.append((tail + p).strip())
    return res

def chunk_recursive(doc: ParsedDoc, size: int = 500, overlap: int = 50) -> list[dict]:
    text, offsets = _flatten(doc)
    chunks, cursor = [], 0
    for i, piece in enumerate(recursive_split_text(text, size, overlap)):
        probe = piece[min(len(piece) - 1, overlap):][:30] or piece[:30]
        pos = text.find(probe, max(0, cursor - size))
        pos = cursor if pos < 0 else pos
        cursor = pos
        chunks.append(_mk(doc, "recursive", i, piece, _page_at(offsets, pos), _page_at(offsets, pos + len(piece))))
    return chunks

# ---------------- b) 按章节标题 ----------------
def _num_tuple(num: str):
    return tuple(int(x) if x.isdigit() else x for x in num.replace("附录", "").split("."))

class HeadingTracker:
    """维护标题栈；对候选标题做“编号连续性”校验，过滤表格行、正文中的数字开头行。"""
    def __init__(self):
        self.stack: list[dict] = []    # [{number, title, level}]
        self.accepted = 0
        self.rejected = 0
        self.mode = ""
        self.seen_top = set()
        self.toc_lines_dropped = 0

    def accept(self, h: dict, big_font: bool = False, page_top: bool = False) -> bool:
        kind, num, lvl = h["kind"], h["number"], h["level"]
        if kind in ("cn_chapter", "appendix"):
            ok = True
        elif kind == "appendix_clause":
            ok = any(x["number"] == f"附录{num[0]}" or x["number"].startswith(num[0] + ".") for x in self.stack)
        else:
            parts = num.split(".")
            top = next((x for x in self.stack if x["level"] == 1 and x["number"].isdigit()), None)
            if lvl == 1:
                n = int(parts[0])
                # 一级编号：首次出现或递增(<=+3) 或重新从 1 开始（手册常由多份子说明书拼成）
                short = len(h["title"].split()) <= 6 if h["kind"] == "numbered_en" else len(h["title"]) <= 15
                seen = h["title"] in self.seen_top
                restart = n == 1 and short and (big_font or page_top or seen) and (top is None or int(top["number"]) >= 2)
                # 文档中第一个一级编号标题须从 0/1/2 起（防止前言里的“10 xxx”列表项被当作第 10 章）
                first_ok = n <= 2 or big_font
                ok = (first_ok if top is None else 0 < n - int(top["number"]) <= 2) or restart
                if self.stack and self.stack[0]["kind"] == "appendix":
                    ok = big_font      # 附录内的 '1 xxx' 多为表格/记录模板条目
            else:
                parent = ".".join(parts[:-1])
                # 父编号必须在栈中（允许跳级：父的前缀在栈中）
                ok = any(x["number"] == parent for x in self.stack) or \
                     (top is not None and top["number"] == parts[0] and int(parts[-1]) <= 30)
        if ok:
            if lvl == 1:
                self.seen_top.add(h["title"])
            self.stack = [x for x in self.stack if x["level"] < lvl]
            if kind.startswith("numbered") and lvl > 1:
                # 跳号时去掉不是本编号前缀的同级旧节点，保证路径正确（如 7.1 后直接出现 7.2.2）
                self.stack = [x for x in self.stack if not re.fullmatch(r"[\d.]+", x["number"] or "x")
                              or num.startswith(x["number"] + ".")]
            self.stack.append(h)
            self.accepted += 1
        else:
            self.rejected += 1
        return ok

    def path(self) -> str:
        return " > ".join(f'{x["number"]} {x["title"]}'.strip() for x in self.stack)

def split_sections(doc: ParsedDoc, mode: str = "auto") -> tuple[list[dict], HeadingTracker]:
    """把文档切成章节：[{heading_path, title, number, level, text, page_start, page_end}]
    mode: numbered（只用编号标题） / font（PDF 字号标题 + docx Heading 样式） / auto（编号标题太少时退回 font）"""
    if mode == "auto":
        _, tr0 = _split(doc, "numbered")
        n_pages = max(1, len([p for p in doc.pages if p["text"]]))
        _, tr1 = _split(doc, "font")
        # 编号标题足够多（≥0.4/页）用编号；否则取识别标题更多的方式
        # OCR 页的“字号”来自文本框高度，图中标注/大号数字会混入，可靠性低：OCR 为主的文档只要有 ≥5 个编号标题就用编号模式
        ocr_doc = sum(1 for p in doc.pages if p.get("ocr")) >= 0.5 * len(doc.pages)
        mode = "numbered" if tr0.accepted >= max(5, 0.4 * n_pages) or tr0.accepted >= tr1.accepted \
            or (ocr_doc and tr0.accepted >= 5) else "font"
    secs, tr = _split(doc, mode)
    tr.mode = mode
    return secs, tr

def _legend_lines(lines: list[Line]) -> set[int]:
    """图注/零件清单/参数表：同一页内连续 ≥3 个“一级编号短行”，彼此之间最多隔 1 行 -> 不作为标题"""
    cand = []
    for i, ln in enumerate(lines):
        h = detect_heading(ln.text.strip()) if ln.text.strip() else None
        if h and h["level"] == 1 and h["kind"].startswith("numbered"):
            cand.append(i)
    out, run = set(), []
    def flush():
        if len(run) >= 3:
            out.update(run)
    for i in cand:
        if run and lines[i].page == lines[run[-1]].page and \
                sum(1 for k in range(run[-1] + 1, i) if lines[k].text.strip()) <= 1 and \
                all(len(lines[k].text.strip()) <= 30 for k in range(run[-1] + 1, i)):   # 中间夹正文长段落 -> 是真标题
            run.append(i)
        else:
            flush(); run = [i]
    flush()
    return out

TOC_LINE_RE = re.compile(r"(\.{6,}|…{3,}|·{5,})\s*[\dIVX]+\s*$")   # 目录行：点引导线 + 页码

FRONT = ("前言", "引言", "Foreword", "Introduction")

def _split(doc: ParsedDoc, mode: str):
    tr = HeadingTracker()
    font_idx = {}
    for c in (doc.font_headings or []):
        font_idx[(c["page"], c["text"])] = c["level"]
    for c in (doc.docx_headings or []):
        m = re.search(r"(\d)", c.get("style", ""))
        font_idx[(c["page"], c["text"])] = int(m.group(1)) if m else 1
    toc = set(doc.toc_pages or [])
    lines = doc_lines(doc)
    legend = _legend_lines(lines) if mode == "numbered" else set()
    tr.legend_skipped = len(legend)
    sections = []
    cur = {"heading_path": "（前置内容/封面/目录）", "title": "", "number": "", "level": 0,
           "lines": [], "page_start": None, "page_end": None}
    fstack: list[tuple[int, str]] = []
    seen_front = set()
    for li, ln in enumerate(lines):
        t = ln.text.strip()
        h = None
        if t and ln.page not in toc and not TOC_RE.search(t) and li not in legend and " | " not in t:
            if t.replace(" ", "") in FRONT and t.replace(" ", "") not in seen_front:
                seen_front.add(t.replace(" ", ""))
                h = {"number": "", "title": t.replace(" ", ""), "level": 1, "kind": "front"}
            elif mode == "numbered":
                h = detect_heading(t)
                if h and not tr.accept(h, big_font=(ln.page, t) in font_idx, page_top=ln.idx_in_page <= 2):
                    h = None
            else:  # font
                lvl = font_idx.get((ln.page, t))
                if lvl:
                    h = {"number": "", "title": t, "level": lvl, "kind": "font"}
                    tr.accepted += 1
        if h:
            if cur["lines"] and any(x.strip() for x in cur["lines"]):
                sections.append(cur)
            if h["kind"] == "front":
                tr.stack, fstack = [], []
                path = h["title"]
            elif h["kind"] == "font":
                fstack = [x for x in fstack if x[0] < h["level"]] + [(h["level"], h["title"])]
                path = " > ".join(x[1] for x in fstack)
            else:
                path = tr.path()
            cur = {"heading_path": path, "title": h["title"], "number": h["number"], "level": h["level"],
                   "lines": [t], "page_start": ln.page, "page_end": ln.page}
            continue
        if ln.page in toc or (t and TOC_LINE_RE.search(t)):
            tr.toc_lines_dropped += 1      # 目录页/目录行：检索价值低且与正文标题重复 -> 不进入 heading 块
            continue
        cur["lines"].append(ln.text)
        if t:
            cur["page_start"] = cur["page_start"] or ln.page
            cur["page_end"] = ln.page
    if cur["lines"] and any(x.strip() for x in cur["lines"]):
        sections.append(cur)
    for s in sections:
        s["text"] = re.sub(r"\n{3,}", "\n\n", "\n".join(s.pop("lines"))).strip()
    return sections, tr

def chunk_heading(doc: ParsedDoc, max_size: int = 800, min_size: int = 120, overlap: int = 50, method: str = "heading") -> tuple[list[dict], dict]:
    sections, tr = split_sections(doc)
    # 1) 小节合并：同一一级章内，连续的小节合并，直到 >= min_size（且不超过 max_size）
    merged = []
    for s in sections:
        if merged:
            last = merged[-1]
            # 过短的节（如只有标题的父节、只有一行的列表项）并入下一节，合并后不超过 max_size
            if _clen(last["text"]) < min_size and _clen(last["text"]) + _clen(s["text"]) <= max_size:
                last["text"] += "\n" + s["text"]
                last["merged_titles"] = last.get("merged_titles", [last["heading_path"]]) + [s["heading_path"]]
                last["page_end"] = s["page_end"] or last["page_end"]
                continue
        merged.append(dict(s))
    # 2) 过长章节二次切分（递归切分，块首加章节路径作上下文）
    chunks, i = [], 0
    for s in merged:
        body = s["text"]
        pieces = [body] if len(body) <= max_size else recursive_split_text(body, max_size - 50, overlap, cap=max_size - overlap)
        for k, piece in enumerate(pieces):
            c = _mk(doc, method, i, piece, s["page_start"], s["page_end"])
            c["heading_path"] = s["heading_path"]
            c["title"] = s["title"]
            c["section_number"] = s["number"]
            c["part"] = f"{k + 1}/{len(pieces)}"
            if s.get("merged_titles"):
                c["merged_sections"] = s["merged_titles"]
            # 用于向量化的文本：章节路径 + 正文（二次切分后的后续块也能知道自己属于哪一节）
            c["embed_text"] = f"【{doc.source}｜{s['heading_path']}】\n{piece}"
            chunks.append(c); i += 1
    info = {"mode": getattr(tr, "mode", ""), "sections": len(sections), "headings_accepted": tr.accepted,
            "headings_rejected": tr.rejected, "legend_lines_skipped": getattr(tr, "legend_skipped", 0),
            "toc_lines_dropped": tr.toc_lines_dropped}
    return chunks, info

# ---------------- d) 章节切分 v2：正文 + 表格父子块 ----------------
TABLE_WHOLE_MAX = 1200      # 整表 Markdown 不超过此长度 -> 一块；否则按行组切
TABLE_GROUP_MAX = 800       # 行组块目标长度（含重复的表头/表题/章节）

def _strip_ph(t: str) -> str:
    """二次切分可能把占位符切成两半（块边界/重叠区）：清掉残片"""
    t = re.sub(r"⟦TABLE:[^⟧\n]*", "", t)
    return re.sub(r"\S*#p\d+t\d+⟧", "", t)

def chunk_heading_v2(doc: ParsedDoc, max_size: int = 800, min_size: int = 120, overlap: int = 50) -> tuple[list[dict], dict]:
    """parse(tables=True) 的结果：正文按章节切（表格区域已移出正文流，只留占位符），表格单独成块：
    chunk_type=text      正文块（占位符替换为『[表N 表题]』引用）
    chunk_type=table     整表（小表）或行组块（大表，每块重复 表题+章节+表头），parent_id 指向自己
    chunk_type=table_row 行级自然语言描述，parent_id = 所属 table 块（检索命中后返回父块给 LLM）"""
    from parse import TABLE_PH_RE
    from tables import to_markdown, title_line, row_description
    method = "heading_v2"
    chunks, info = chunk_heading(doc, max_size, min_size, overlap, method=method)
    tmap = {t["table_id"]: t for t in doc.tables}
    tsec = {}
    out = []
    for c in chunks:
        for m in TABLE_PH_RE.finditer(c["text"]):
            hp, title = c["heading_path"], c["title"]
            best = -1
            for path in c.get("merged_sections") or []:          # 合并块：取占位符之前最后出现的那个小节标题
                last = path.split(" > ")[-1]
                pos = c["text"].rfind(last, 0, m.start())
                if pos > best:
                    best, hp, title = pos, path, last
            tsec.setdefault(m.group(1), (hp, title, c.get("section_number")))
        def ref(m, text=c["text"]):
            t = tmap.get(m.group(1))
            return f"[{t['caption']}]" if t and t["caption"] and t["caption"] not in text else ""
        c["text"] = re.sub(r"\n{3,}", "\n\n", _strip_ph(TABLE_PH_RE.sub(ref, c["text"]))).strip()
        if c.get("embed_text"):
            c["embed_text"] = _strip_ph(TABLE_PH_RE.sub(ref, c["embed_text"]))
        if _clen(c["text"]) < 8:
            continue
        c["char_len"] = len(c["text"]); c["chunk_type"] = "text"
        out.append(c)
    tchunks = []
    for t in doc.tables:
        hp, title, num = tsec.get(t["table_id"], ("", "", ""))
        head = f"【表格】{title_line(t)}" + (f"\n章节：{hp}" if hp else "")
        whole = head + "\n" + to_markdown(t)
        if len(whole) <= TABLE_WHOLE_MAX or len(t["rows"]) <= 1:
            groups = [(0, len(t["rows"]))]
        else:
            groups, a, cur = [], 0, len(head) + len(to_markdown(t, []))
            for j, r in enumerate(t["rows"]):
                rl = len(to_markdown(t, [r]).split("\n", 2)[-1]) + 1
                if j > a and cur + rl > TABLE_GROUP_MAX:
                    groups.append((a, j)); a, cur = j, len(head) + len(to_markdown(t, []))
                cur += rl
            groups.append((a, len(t["rows"])))
        base = dict(heading_path=hp, title=title, section_number=num, table_id=t["table_id"], table_caption=t["caption"],
                    table_number=t.get("number", ""), page_start=t["page_start"], page_end=t["page_end"])
        for g, (a, b) in enumerate(groups):
            txt = head + (f"\n（第 {a + 1}–{b} 行，共 {len(t['rows'])} 行）" if len(groups) > 1 else "") + "\n" + to_markdown(t, t["rows"][a:b])
            tc = _mk(doc, method, 0, txt, t["page_start"], t["page_end"]); tc.update(base)
            tc.update(chunk_type="table", part=f"{g + 1}/{len(groups)}", row_range=[a, b],
                      embed_text=f"【{doc.source}｜{hp}｜{t['caption']}】\n" + txt)
            tchunks.append(tc)
            gi = len(tchunks) - 1
            if len(t["rows"]) >= 2:
                for j in range(a, b):
                    d = row_description(t, t["rows"][j], hp)
                    rc = _mk(doc, method, 0, d, t["page_start"], t["page_end"]); rc.update(base)
                    rc.update(chunk_type="table_row", row_index=j, parent_index=gi,
                              embed_text=f"【{doc.source}｜{hp}】\n" + d)
                    tchunks.append(rc)
    allc = out + tchunks
    stem = re.sub(r"\.[^.]+$", "", doc.source)
    for i, c in enumerate(allc):
        c["chunk_id"] = f"{stem}#{method}#{i:04d}"
    for c in tchunks:
        if c["chunk_type"] == "table":
            c["parent_id"] = c["chunk_id"]
    for c in tchunks:
        if c["chunk_type"] == "table_row":
            c["parent_id"] = tchunks[c.pop("parent_index")]["chunk_id"]
    info.update(tables=len(doc.tables), table_chunks=sum(c["chunk_type"] == "table" for c in tchunks),
                table_row_chunks=sum(c["chunk_type"] == "table_row" for c in tchunks),
                tables_without_section=sum(1 for t in doc.tables if t["table_id"] not in tsec))
    return allc, info

# ---------------- 公共构造 ----------------
def _mk(doc, method, i, text, p0, p1):
    stem = re.sub(r"\.[^.]+$", "", doc.source)
    return {"chunk_id": f"{stem}#{method}#{i:04d}", "source": doc.source, "file_type": doc.file_type,
            "method": method, "heading_path": "", "title": "", "page_start": p0, "page_end": p1,
            "char_len": len(text), "text": text}

if __name__ == "__main__":
    import argparse, json
    from parse import parse_document
    ap = argparse.ArgumentParser(description="对单个文档做切分并打印前几块")
    ap.add_argument("file")
    ap.add_argument("--method", choices=["fixed", "heading", "recursive"], default="heading")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--show", type=int, default=5)
    a = ap.parse_args()
    d = parse_document(a.file, a.max_pages)
    if a.method == "fixed":
        cs, info = chunk_fixed(d), {}
    elif a.method == "recursive":
        cs, info = chunk_recursive(d), {}
    else:
        cs, info = chunk_heading(d)
    print(f"{d.source}: {len(cs)} chunks {info}")
    for c in cs[:a.show]:
        print(json.dumps({k: (v[:200] if isinstance(v, str) else v) for k, v in c.items() if k != "embed_text"}, ensure_ascii=False))
