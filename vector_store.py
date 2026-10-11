# -*- coding: utf-8 -*-
"""向量库抽象层：VectorStore 接口 + ChromaStore（默认）+ MilvusStore（Milvus Lite 本地文件 / Milvus Standalone）。

环境变量：
  VECTOR_STORE   chroma（默认）| milvus
  CHROMA_DIR     Chroma 持久化目录，默认 <项目>/chroma_db
  MILVUS_URI     Milvus Lite 文件路径（默认 <项目>/milvus_db/power_kb.db）或 Standalone 地址 http://host:19530
  MILVUS_TOKEN   Standalone 开启鉴权时 "user:password"（可选）
  MILVUS_INDEX   HNSW（默认）| FLAT | AUTOINDEX；Milvus Lite 不支持 HNSW 时自动退回 FLAT（打印提示）

过滤条件统一用 Chroma 风格 where：{"source": "x"}、{"source": {"$in": [...]}}、{"page_start": {"$gte": 3}}、
{"$and": [...]}、{"$or": [...]}；MilvusStore 用 where_to_expr() 转成 Milvus 布尔表达式。
query() 返回的 score 一律是余弦相似度（越大越相似）。
"""
from __future__ import annotations
import json, os, threading
from collections import Counter
from typing import Iterable

HERE = os.path.dirname(os.path.abspath(__file__))
DIM = 1024                                                     # bge-m3
COLLECTION = {"heading": "power_heading", "fixed": "power_fixed", "recursive": "power_recursive", "heading_v2": "power_heading_v2"}

def collection_name(method_or_name: str) -> str:
    return COLLECTION.get(method_or_name) or (method_or_name if method_or_name.startswith("power_") else f"power_{method_or_name}")

def norm_where(where: dict | None):
    """{"a": 1, "b": 2} → {"$and": [{"a": 1}, {"b": 2}]}（Chroma 要求多条件显式 $and）"""
    if not where:
        return None
    if len(where) > 1 and not any(k.startswith("$") for k in where):
        return {"$and": [{k: v} for k, v in where.items()]}
    return where

class VectorStore:
    """所有实现共用的接口。ids/documents/metadatas 与 Chroma 语义一致；metadata 值只允许 str/int/float/bool。"""
    backend = "abstract"
    def __init__(self, name: str):
        self.name = name
    def upsert(self, ids: list[str], embeddings, documents: list[str], metadatas: list[dict]) -> None: raise NotImplementedError
    def delete(self, ids: list[str] | None = None, where: dict | None = None) -> None: raise NotImplementedError
    def query(self, vector, k: int = 5, where: dict | None = None) -> list[dict]:
        """→ [{"id", "document", "metadata", "score"(余弦相似度)}]，按 score 降序"""
        raise NotImplementedError
    def get(self, ids: list[str]) -> list[dict]:
        """→ [{"id", "document", "metadata"}]（不存在的 id 忽略）"""
        raise NotImplementedError
    def count(self) -> int: raise NotImplementedError
    def all_metadata(self) -> dict[str, dict]:
        """id → metadata（增量建库比对 text_hash 用）"""
        raise NotImplementedError
    def list_sources(self) -> Counter:
        return Counter(m.get("source", "") for m in self.all_metadata().values())
    def drop(self) -> None: raise NotImplementedError
    def all_vectors(self, batch: int = 1000) -> Iterable[tuple[list[str], list, list[str], list[dict]]]:
        """分批导出 (ids, embeddings, documents, metadatas)，迁移用"""
        raise NotImplementedError

# ---------------- Chroma ----------------
_chroma_client = None
_lock = threading.Lock()

def chroma_client():
    global _chroma_client
    with _lock:
        if _chroma_client is None:
            import chromadb
            from chromadb.config import Settings
            _chroma_client = chromadb.PersistentClient(path=os.environ.get("CHROMA_DIR", os.path.join(HERE, "chroma_db")),
                                                       settings=Settings(anonymized_telemetry=False))
        return _chroma_client

class ChromaStore(VectorStore):
    backend = "chroma"
    def __init__(self, name: str, create: bool = True, meta: dict | None = None):
        super().__init__(name)
        c = chroma_client()
        self.col = c.get_or_create_collection(name, metadata={"hnsw:space": "cosine", **(meta or {})}) if create else c.get_collection(name)
    def upsert(self, ids, embeddings, documents, metadatas):
        emb = embeddings.tolist() if hasattr(embeddings, "tolist") else [list(map(float, v)) for v in embeddings]
        for s in range(0, len(ids), 500):
            self.col.upsert(ids=ids[s:s + 500], embeddings=emb[s:s + 500], documents=documents[s:s + 500], metadatas=metadatas[s:s + 500])
    def delete(self, ids=None, where=None):
        if ids:
            self.col.delete(ids=list(ids))
        elif where:
            self.col.delete(where=norm_where(where))
    def query(self, vector, k=5, where=None):
        r = self.col.query(query_embeddings=[list(map(float, vector))], n_results=k, where=norm_where(where),
                           include=["documents", "metadatas", "distances"])
        return [{"id": i, "document": d, "metadata": m, "score": 1.0 - float(dist)}
                for i, d, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0])]
    def get(self, ids):
        r = self.col.get(ids=list(ids), include=["documents", "metadatas"])
        return [{"id": i, "document": d, "metadata": m} for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])]
    def count(self):
        return self.col.count()
    def all_metadata(self):
        out = {}
        for off in range(0, self.count(), 5000):
            g = self.col.get(include=["metadatas"], limit=5000, offset=off)
            out.update(zip(g["ids"], g["metadatas"]))
        return out
    def drop(self):
        chroma_client().delete_collection(self.name)
    def all_vectors(self, batch=1000):
        for off in range(0, self.count(), batch):
            g = self.col.get(include=["embeddings", "documents", "metadatas"], limit=batch, offset=off)
            yield g["ids"], g["embeddings"], g["documents"], g["metadatas"]

# ---------------- Milvus ----------------
def _lit(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)

_OPS = {"$eq": "==", "$ne": "!=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}

def where_to_expr(where: dict | None) -> str:
    """Chroma where → Milvus 表达式。字段名直接引用（source 是显式标量字段，其余在动态字段 $meta 中，Milvus 同样支持按名引用）"""
    where = norm_where(where)
    if not where:
        return ""
    parts = []
    for k, v in where.items():
        if k in ("$and", "$or"):
            subs = [f"({where_to_expr(x)})" for x in v if x]
            parts.append((" and " if k == "$and" else " or ").join(subs))
        elif isinstance(v, dict):
            for op, x in v.items():
                if op in _OPS:
                    parts.append(f"{k} {_OPS[op]} {_lit(x)}")
                elif op in ("$in", "$nin"):
                    parts.append(f"{k} {'not in' if op == '$nin' else 'in'} [{', '.join(_lit(i) for i in x)}]")
                else:
                    raise ValueError(f"不支持的过滤操作符 {op}")
        else:
            parts.append(f"{k} == {_lit(v)}")
    return " and ".join(parts)

_milvus_clients: dict[str, object] = {}

def milvus_client(uri: str | None = None):
    uri = uri or os.environ.get("MILVUS_URI") or os.path.join(HERE, "milvus_db", "power_kb.db")
    with _lock:
        if uri not in _milvus_clients:
            env = os.environ.pop("MILVUS_URI", None)          # pymilvus 导入时会读取 MILVUS_URI 且只接受 http 地址，Lite 文件路径会报错
            try:
                from pymilvus import MilvusClient
            finally:
                if env is not None:
                    os.environ["MILVUS_URI"] = env
            if not uri.startswith(("http://", "https://", "tcp://")):
                os.makedirs(os.path.dirname(os.path.abspath(uri)), exist_ok=True)       # Milvus Lite：本地文件
            _milvus_clients[uri] = MilvusClient(uri=uri, token=os.environ.get("MILVUS_TOKEN", ""))
        return _milvus_clients[uri]

class MilvusStore(VectorStore):
    backend = "milvus"
    OUT = ["document", "*"]                                   # 文本 + 全部动态字段（metadata）
    def __init__(self, name: str, create: bool = True, meta: dict | None = None, uri: str | None = None):
        super().__init__(name)
        self.c = milvus_client(uri)
        self.index_type = None
        if not self.c.has_collection(name):
            if not create:
                raise ValueError(f"Milvus 集合 {name} 不存在")
            self._create()
        self.c.load_collection(name)
    def _create(self):
        from pymilvus import DataType, MilvusClient
        sch = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        sch.add_field("id", DataType.VARCHAR, is_primary=True, max_length=512)
        sch.add_field("vector", DataType.FLOAT_VECTOR, dim=DIM)
        sch.add_field("document", DataType.VARCHAR, max_length=65535)
        sch.add_field("source", DataType.VARCHAR, max_length=1024)
        want = os.environ.get("MILVUS_INDEX", "HNSW").upper()
        for it in dict.fromkeys([want, "FLAT"]):
            ip = self.c.prepare_index_params()
            ip.add_index(field_name="vector", index_type=it, metric_type="COSINE",
                         params={"M": 16, "efConstruction": 200} if it == "HNSW" else {})
            try:
                self.c.create_collection(self.name, schema=sch, index_params=ip)
                self.index_type = it
                break
            except Exception as e:                            # Milvus Lite 只支持 FLAT/IVF_FLAT/AUTOINDEX 等
                if self.c.has_collection(self.name):
                    self.c.drop_collection(self.name)
                print(f"[milvus] 索引 {it} 不可用（{str(e)[:120]}），改用下一个", flush=True)
    def _rows(self, ids, embeddings, documents, metadatas):
        emb = embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings
        rows = []
        for i, v, d, m in zip(ids, emb, documents, metadatas):
            r = {k: x for k, x in (m or {}).items() if k not in ("id", "vector", "document")}
            r.update(id=i, vector=[float(x) for x in v], document=d or "", source=(m or {}).get("source", ""))
            rows.append(r)
        return rows
    def upsert(self, ids, embeddings, documents, metadatas):
        rows = self._rows(ids, embeddings, documents, metadatas)
        for s in range(0, len(rows), 500):
            self.c.upsert(self.name, rows[s:s + 500])
    def delete(self, ids=None, where=None):
        if ids:
            self.c.delete(self.name, ids=list(ids))
        elif where:
            self.c.delete(self.name, filter=where_to_expr(where))
    @staticmethod
    def _meta(e: dict) -> dict:
        return {k: v for k, v in e.items() if k not in ("id", "vector", "document", "distance", "$meta")}
    def query(self, vector, k=5, where=None):
        sp = {"metric_type": "COSINE", "params": {"ef": max(64, 2 * k)} if self.index_type in (None, "HNSW") else {}}
        r = self.c.search(self.name, data=[[float(x) for x in vector]], limit=k, filter=where_to_expr(where),
                          output_fields=self.OUT, search_params=sp)
        out = []
        for h in r[0]:
            e = h.get("entity", h)
            out.append({"id": h.get("id", e.get("id")), "document": e.get("document", ""), "metadata": self._meta(e), "score": float(h["distance"])})
        return out
    def get(self, ids):
        if not ids:
            return []
        return [{"id": e["id"], "document": e.get("document", ""), "metadata": self._meta(e)}
                for e in self.c.get(self.name, ids=list(ids), output_fields=self.OUT)]
    def count(self):
        # Standalone 默认 Bounded 一致性，刚写入后 count(*) 会偏小；计数用 Strong
        return int(self.c.query(self.name, filter="", output_fields=["count(*)"], consistency_level="Strong")[0]["count(*)"])
    def _iter(self, fields, batch=1000):
        it = self.c.query_iterator(self.name, batch_size=batch, filter="", output_fields=fields)
        try:
            while True:
                b = it.next()
                if not b:
                    break
                yield b
        finally:
            it.close()
    def all_metadata(self):
        return {e["id"]: self._meta(e) for b in self._iter(["*"]) for e in b}
    def list_sources(self):
        return Counter(e["source"] for b in self._iter(["source"]) for e in b)
    def drop(self):
        self.c.drop_collection(self.name)
    def all_vectors(self, batch=1000):
        for b in self._iter(["vector", "document", "*"], batch):
            yield [e["id"] for e in b], [e["vector"] for e in b], [e.get("document", "") for e in b], [self._meta(e) for e in b]

# ---------------- 工厂 ----------------
_stores: dict[tuple, VectorStore] = {}

def backend() -> str:
    b = (os.environ.get("VECTOR_STORE") or "chroma").lower()          # 空值视为默认
    if b not in ("chroma", "milvus"):
        raise ValueError(f"VECTOR_STORE 只能是 chroma 或 milvus，当前 {b}")
    return b

def get_store(method_or_name: str, create: bool = False, backend_name: str | None = None, meta: dict | None = None, **kw) -> VectorStore:
    """按 VECTOR_STORE（或显式 backend_name）返回集合句柄；进程内缓存同一集合的句柄"""
    b = backend_name or backend()
    name = collection_name(method_or_name)
    key = (b, name, kw.get("uri"))
    if key not in _stores:
        _stores[key] = (MilvusStore if b == "milvus" else ChromaStore)(name, create=create, meta=meta, **kw)
    return _stores[key]

def forget(method_or_name: str | None = None):
    """drop/重建后清掉缓存句柄"""
    for k in [k for k in _stores if method_or_name is None or k[1] == collection_name(method_or_name)]:
        _stores.pop(k)
