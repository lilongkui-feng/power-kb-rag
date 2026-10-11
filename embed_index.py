# -*- coding: utf-8 -*-
"""bge-m3 dense 向量 -> Chroma 持久化（chroma_db/）

用法：
  python embed_index.py                       # 增量构建 heading/fixed/recursive 三个集合
  python embed_index.py --methods heading     # 只建 heading
  python embed_index.py --rebuild             # 删除集合后全部重建
环境变量：HF_HOME（模型缓存目录），HF_ENDPOINT=https://hf-mirror.com（国内镜像，可选），BGE_DEVICE=cpu|cuda

设计：
- 向量化文本使用切块的 embed_text（"【来源｜章节路径】\\n正文"），让向量带上文档/章节上下文；Chroma 中 documents 存原文 text。
- normalize_embeddings=True + 集合 hnsw:space=cosine，返回距离 d，相似度 = 1 - d。
- 增量：以 chunk_id 为主键，metadata 存 text_hash；只对新增/内容变化的块计算向量，删除 jsonl 中已不存在的块。
- 向量缓存 emb_cache/<model>.npz：按 embed_text 的 sha1 缓存，重建集合或切换集合时无需重复计算。
"""
from __future__ import annotations
import argparse, hashlib, json, os, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
DB_DIR = os.path.join(HERE, "chroma_db")
CACHE_DIR = os.path.join(HERE, "emb_cache")
MODEL_NAME = os.environ.get("BGE_MODEL", "BAAI/bge-m3")
MAX_SEQ = 1024          # 最长块 800 字 + 前缀，中文约 1 字≈0.7–1 token，1024 足够不截断
from vector_store import COLLECTION, get_store, forget as _forget_store   # 向量库抽象层（VECTOR_STORE=chroma|milvus）

_model = None
def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        dev = os.environ.get("BGE_DEVICE")
        if not dev:
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        _model = SentenceTransformer(MODEL_NAME, device=dev)
        _model.max_seq_length = MAX_SEQ
    return _model

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

class EmbCache:
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.path = os.path.join(CACHE_DIR, MODEL_NAME.replace("/", "__") + ".npz")
        self.data: dict[str, np.ndarray] = {}
        if os.path.exists(self.path):
            z = np.load(self.path)
            self.data = dict(zip(z["keys"].tolist(), z["vecs"]))
    def save(self):
        if self.data:
            keys = np.array(list(self.data.keys()))
            np.savez(self.path, keys=keys, vecs=np.stack([self.data[k] for k in keys]).astype(np.float32))

def embed_texts(texts: list[str], cache: EmbCache | None = None, batch_size: int = 16, log_every: int = 160) -> np.ndarray:
    keys = [sha1(MODEL_NAME + "\x00" + t) for t in texts]
    todo = [i for i, k in enumerate(keys) if not cache or k not in cache.data]
    if todo:
        m = get_model()
        order = sorted(todo, key=lambda i: len(texts[i]))          # 按长度排序，减少 padding
        t0 = time.time()
        for s in range(0, len(order), batch_size * 10):
            part = order[s:s + batch_size * 10]
            vecs = m.encode([texts[i] for i in part], batch_size=batch_size, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False)
            for i, v in zip(part, vecs):
                if cache is not None:
                    cache.data[keys[i]] = v.astype(np.float32)
                else:
                    texts[i] = v                                   # 无缓存时临时存放
            done = min(s + len(part), len(order))
            if done % log_every < len(part) or done == len(order):
                el = time.time() - t0
                print(f"    embedded {done}/{len(order)}  {el:.0f}s  ({el / done:.2f}s/块)", flush=True)
            if cache is not None and (s // (batch_size * 10)) % 5 == 4:
                cache.save()                                       # 定期落盘，中断后可续跑
        if cache is not None:
            cache.save()
    return np.stack([cache.data[k] if cache else texts[i] for i, k in enumerate(keys)])

def _meta(c: dict) -> dict:
    """Chroma 元数据只能是 str/int/float/bool"""
    return {"chunk_id": c["chunk_id"], "source": c["source"], "file_type": c["file_type"], "method": c["method"],
            "heading_path": c.get("heading_path") or "", "title": c.get("title") or "",
            "page_start": int(c.get("page_start") or 0), "page_end": int(c.get("page_end") or 0),
            "category": c.get("category", ""), "lang": c.get("lang", ""), "char_len": int(c["char_len"]),
            "part": c.get("part", ""), "merged_sections": " ; ".join(c.get("merged_sections", [])),
            "text_hash": sha1(c.get("embed_text") or c["text"]),
            **({"chunk_type": c["chunk_type"], "table_id": c.get("table_id") or "", "parent_id": c.get("parent_id") or ""}
               if c.get("chunk_type") else {})}

def embed_input(c: dict) -> str:
    if c.get("embed_text"):
        return c["embed_text"]
    hp = c.get("heading_path") or ""
    return f"【{c['source']}" + (f"｜{hp}" if hp else "") + f"】\n{c['text']}"     # fixed/recursive 也加来源前缀，保证可比

def get_client():
    """兼容旧脚本：直接拿 Chroma 客户端（新代码请用 vector_store.get_store）"""
    from vector_store import chroma_client
    return chroma_client()

UPLOAD_CHUNKS = os.path.join(HERE, "uploads", "chunks_uploaded.jsonl")
UPLOAD_CHUNKS_BY_METHOD = {"heading": UPLOAD_CHUNKS, "heading_v2": os.path.join(HERE, "uploads", "chunks_uploaded_v2.jsonl")}

def load_chunks(method: str, include_docx: bool = False) -> list[dict]:
    """建库用的切块：output/chunks_<method>.jsonl（docx 测试件默认排除）+ heading 方法额外包含网页上传的文档切块"""
    path = os.path.join(OUT, f"chunks_{method}.jsonl")
    chunks = [json.loads(l) for l in open(path, encoding="utf-8")]
    if not include_docx:
        chunks = [c for c in chunks if c["file_type"] != "docx" or c.get("category") == "上传"]
    up = UPLOAD_CHUNKS_BY_METHOD.get(method, os.path.join(HERE, "uploads", f"chunks_uploaded_{method}.jsonl"))
    if up and os.path.exists(up):
        chunks += [json.loads(l) for l in open(up, encoding="utf-8") if l.strip()]
    return chunks

def build(method: str, rebuild: bool = False, cache: EmbCache | None = None, include_docx: bool = False) -> dict:
    chunks = load_chunks(method, include_docx)
    name = COLLECTION.get(method, f"power_{method}")       # 调参变体：power_<method>
    if rebuild:
        try:
            get_store(method, create=True).drop()
        except Exception:
            pass
        _forget_store(method)
    col = get_store(method, create=True, meta={"model": MODEL_NAME, "method": method})
    existing = {i: m.get("text_hash") for i, m in col.all_metadata().items()}
    want = {c["chunk_id"]: c for c in chunks}
    stale = [i for i in existing if i not in want]
    todo = [c for c in chunks if existing.get(c["chunk_id"]) != _meta(c)["text_hash"]]
    if stale:
        col.delete(ids=stale)
    t0 = time.time()
    print(f"[{name}] 共 {len(chunks)} 块：已有 {len(existing)}，需写入 {len(todo)}，删除 {len(stale)}", flush=True)
    if todo:
        vecs = embed_texts([embed_input(c) for c in todo], cache)
        col.upsert([c["chunk_id"] for c in todo], vecs, [c["text"] for c in todo], [_meta(c) for c in todo])
    info = {"collection": name, "backend": col.backend, "chunks": len(chunks), "written": len(todo), "deleted": len(stale),
            "count": col.count(), "secs": round(time.time() - t0, 1)}
    print(f"[{name}] 完成：{info}", flush=True)
    return info

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="heading,fixed,recursive")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--include-docx", action="store_true", help="同时入库 docx 测试件的切块（默认不入，避免与 PDF 重复）")
    a = ap.parse_args()
    cache = EmbCache()
    t = time.time()
    infos = [build(m.strip(), a.rebuild, cache, a.include_docx) for m in a.methods.split(",") if m.strip()]
    os.makedirs(OUT, exist_ok=True)
    json.dump({"model": MODEL_NAME, "max_seq_length": MAX_SEQ, "collections": infos, "total_secs": round(time.time() - t, 1)},
              open(os.path.join(OUT, "index_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"总耗时 {time.time() - t:.0f}s")
