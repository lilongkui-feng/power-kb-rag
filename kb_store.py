# -*- coding: utf-8 -*-
"""知识库增量管理（供 app.py 使用，也可命令行调用）
- ingest(path)：parse（含自动 OCR）→ heading 切分 → 写入 uploads/chunks_uploaded.jsonl → bge-m3 向量 upsert 到 Chroma power_heading → 重建 BM25(heading)
- 去重：文件 sha256 已登记 → 跳过；与基础库同名文件 → 跳过（避免重复）
- delete(source)：只允许删除上传的文档（Chroma 按 source 删除 + 移出 jsonl + 重建 BM25）
- list_docs()：基础库 + 上传文档及块数
用法：python kb_store.py add a.pdf b.docx | python kb_store.py del <文件名> | python kb_store.py ls
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, sys, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
UP_DIR = os.path.join(HERE, "uploads")
FILES = os.path.join(UP_DIR, "files")
REG = os.path.join(UP_DIR, "registry.json")
# 网页上传默认走 v2 管线（表格结构化 + 表格父子块 + PaddleOCR），写入 power_heading_v2；KB_METHOD=heading 可退回旧管线
from config import settings as _cfg
from kblog import get_logger
log = get_logger("powerkb.kb_store")
METHOD = _cfg().kb_method
CHUNK_FILES = {"heading": os.path.join(UP_DIR, "chunks_uploaded.jsonl"), "heading_v2": os.path.join(UP_DIR, "chunks_uploaded_v2.jsonl")}
CHUNKS = CHUNK_FILES[METHOD]

def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def _reg() -> dict:
    return json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else {}

def _save_reg(r):
    os.makedirs(UP_DIR, exist_ok=True)
    json.dump(r, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def _base_sources() -> Counter:
    p = os.path.join(HERE, "output", f"chunks_{METHOD}.jsonl")
    return Counter(json.loads(l)["source"] for l in open(p, encoding="utf-8") if '"docx"' not in l)

def _uploaded_chunks(path: str = CHUNKS) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []

def _write_chunks(cs, path: str = CHUNKS):
    os.makedirs(UP_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in cs:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

def list_docs() -> list[dict]:
    base = _base_sources()
    out = [{"source": s, "chunks": n, "origin": "基础库", "deletable": False} for s, n in sorted(base.items())]
    for h, r in _reg().items():
        out.append({"source": r["source"], "chunks": r["chunks"], "origin": "上传", "deletable": True,
                    "pages": r.get("pages"), "ocr_pages": r.get("ocr_pages"), "sha256": h[:12], "added": r.get("added")})
    return out

def _lang(text: str) -> str:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return "zh" if cjk > 0.1 * max(1, len(text)) else "en"

def _reindex_bm25(method: str = METHOD):
    import bm25_index
    bm25_index.build(method)
    bm25_index.invalidate(method)

def chunk_uploaded(path: str, h: str, max_size: int = 800, overlap: int = 50) -> tuple[list[dict], dict, object]:
    """解析 + 切分一个上传文件（METHOD 决定管线），chunk_id 加 up_<sha8> 前缀"""
    from parse import parse_document
    from chunk import chunk_heading, chunk_heading_v2
    if METHOD == "heading_v2":
        doc = parse_document(path, ocr="auto", tables=True)
        chunks, info = chunk_heading_v2(doc, max_size=max_size, min_size=120, overlap=overlap)
    else:
        doc = parse_document(path, ocr="auto")
        chunks, info = chunk_heading(doc, max_size=800, min_size=120, overlap=50)
    sample = " ".join(c["text"] for c in chunks[:20])
    ren = {}
    for c in chunks:
        new = f"up_{h[:8]}#{METHOD}#{c['chunk_id'].rsplit('#', 1)[-1]}"
        ren[c["chunk_id"]] = new; c["chunk_id"] = new
        c["category"], c["lang"] = "上传", _lang(sample)
    for c in chunks:
        if c.get("parent_id"):
            c["parent_id"] = ren.get(c["parent_id"], c["parent_id"])
    return chunks, info, doc

def ingest(path: str, name: str | None = None, progress=None) -> dict:
    """progress(frac, msg) 回调用于界面进度条"""
    prog = progress or (lambda f, m: log.info("[%.0f%%] %s", f * 100, m))
    name = name or os.path.basename(path)
    t0 = time.time()
    h = sha256(path)
    reg = _reg()
    if h in reg:
        return {"status": "duplicate", "source": reg[h]["source"], "msg": f"内容与已上传的《{reg[h]['source']}》相同（sha256 {h[:12]}），已跳过"}
    if name in _base_sources() or any(r["source"] == name for r in reg.values()):
        return {"status": "duplicate", "source": name, "msg": f"库中已有同名文档《{name}》，已跳过（如需替换请先删除或改名）"}
    os.makedirs(FILES, exist_ok=True)
    dst = os.path.join(FILES, name)
    if os.path.abspath(path) != os.path.abspath(dst):
        shutil.copyfile(path, dst)
    prog(0.05, "解析文档（扫描页自动 OCR，可能较慢）…")
    try:
        chunks, info, doc = chunk_uploaded(dst, h, _cfg().chunk_max_size, _cfg().chunk_overlap)
    except Exception as e:                    # 加密 / 损坏 / 非 PDF：清理副本，交给上层标记任务 failed，不影响服务
        log.warning("parse failed source=%s err=%s", name, type(e).__name__)
        if os.path.exists(dst):
            os.remove(dst)
        from errors import DocumentParseError
        raise DocumentParseError(f"《{name}》解析失败（{type(e).__name__}）：文件可能已加密、损坏或不是有效的 PDF/DOCX") from None
    try:
        from ocr import PaddleClient
        PaddleClient.close()                 # 释放 PP-StructureV3 子进程（峰值 ~4.5 GB）
    except Exception:
        pass
    ocr_pages = len(getattr(doc, "ocr_pages", None) or [])
    prog(0.45, f"解析完成：{len(doc.pages)} 页，OCR {ocr_pages} 页，表格 {len(doc.tables)} 张；切分为 {len(chunks)} 块")
    if not chunks:
        os.remove(dst)
        return {"status": "empty", "source": name, "msg": "未提取到文本（可能是加密或纯图片且 OCR 失败）"}
    prog(0.55, f"切分为 {len(chunks)} 块，bge-m3 向量化…")
    from embed_index import EmbCache, embed_texts, embed_input, _meta
    from vector_store import get_store
    cache = EmbCache()
    vecs = embed_texts([embed_input(c) for c in chunks], cache)
    get_store(METHOD, create=True).upsert([c["chunk_id"] for c in chunks], vecs, [c["text"] for c in chunks], [_meta(c) for c in chunks])
    _write_chunks(_uploaded_chunks() + chunks)
    prog(0.9, "写入 Chroma 完成，重建 BM25 索引…")
    _reindex_bm25()
    pages = len(doc.pages)
    reg[h] = {"source": name, "chunks": len(chunks), "pages": pages, "ocr_pages": ocr_pages, "file": dst,
              "added": time.strftime("%Y-%m-%d %H:%M"), "heading_mode": info.get("mode"),
              "tables": len(doc.tables), "method": METHOD}
    _save_reg(reg)
    secs = round(time.time() - t0, 1)
    prog(1.0, f"完成：{len(chunks)} 块，用时 {secs}s")
    return {"status": "ok", "source": name, "chunks": len(chunks), "pages": pages, "ocr_pages": ocr_pages,
            "secs": secs, "heading_mode": info.get("mode"), "msg": f"入库 {len(chunks)} 块（{pages} 页，OCR {ocr_pages} 页），{secs}s"}

def delete(source: str) -> dict:
    reg = _reg()
    hs = [h for h, r in reg.items() if r["source"] == source]
    if not hs:
        return {"status": "not_found", "msg": f"《{source}》不是上传的文档（基础库文档不可在此删除）"}
    from vector_store import get_store
    for m, path in CHUNK_FILES.items():                 # 新旧两个集合里都删掉
        if os.path.exists(path):
            get_store(m, create=True).delete(where={"source": source})
            _write_chunks([c for c in _uploaded_chunks(path) if c["source"] != source], path)
            if m != METHOD:
                _reindex_bm25(m)
    for h in hs:
        f = reg[h].get("file")
        if f and os.path.exists(f):
            os.remove(f)
        reg.pop(h)
    _save_reg(reg)
    _reindex_bm25()
    return {"status": "ok", "msg": f"已删除《{source}》"}

if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["ls"]
    if cmd == "add":
        for p in args:
            print(ingest(p)["msg"])
    elif cmd == "del":
        for s in args:
            print(delete(s)["msg"])
    else:
        for d in list_docs():
            print(f"{d['origin']}\t{d['chunks']}\t{d['source']}")
