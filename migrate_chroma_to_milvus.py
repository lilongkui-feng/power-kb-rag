# -*- coding: utf-8 -*-
"""把 Chroma 集合迁移到 Milvus（复用已存的 bge-m3 向量，不重新 embedding）。
用法：
  python migrate_chroma_to_milvus.py --methods heading_v2                       # 目标 = MILVUS_URI（默认 Milvus Lite 文件 milvus_db/power_kb.db）
  python migrate_chroma_to_milvus.py --methods heading_v2 --uri http://localhost:19530 --drop   # Standalone，先删同名集合
迁移后校验：数量一致、来源分布一致、抽样 20 个向量在两边 Top-5 的重合度。
"""
from __future__ import annotations
import argparse, os, random, time
import numpy as np
from vector_store import ChromaStore, MilvusStore, collection_name

def migrate(method: str, uri: str | None, drop: bool, batch: int = 1000, check: int = 20) -> dict:
    name = collection_name(method)
    src = ChromaStore(name, create=False)
    if drop:
        try:
            MilvusStore(name, create=False, uri=uri).drop()
        except Exception:
            pass
    dst = MilvusStore(name, create=True, uri=uri)
    t0 = time.time(); n = 0; sample = []
    for ids, emb, docs, metas in src.all_vectors(batch):
        dst.upsert(list(ids), np.asarray(emb, dtype=np.float32), list(docs), list(metas))
        n += len(ids)
        sample += [(i, e) for i, e in zip(ids, emb)][:3]
        print(f"[{name}] 已迁移 {n}/{src.count()}", flush=True)
    secs = round(time.time() - t0, 1)
    ok_cnt = dst.count() == src.count()
    ok_src = dst.list_sources() == src.list_sources()
    random.seed(0); overlap = []
    for _, v in random.sample(sample, min(check, len(sample))):
        a = [h["id"] for h in src.query(v, 5)]; b = [h["id"] for h in dst.query(v, 5)]
        overlap.append(len(set(a) & set(b)) / 5)
    info = {"collection": name, "migrated": n, "chroma": src.count(), "milvus": dst.count(), "count_ok": ok_cnt, "sources_ok": ok_src,
            "top5_overlap": round(float(np.mean(overlap)), 3) if overlap else None, "index": dst.index_type, "secs": secs}
    print(info, flush=True)
    return info

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", nargs="+", default=["heading_v2"])
    ap.add_argument("--uri", default=None, help="默认读 MILVUS_URI；Lite 为本地 .db 文件路径")
    ap.add_argument("--drop", action="store_true", help="先删除 Milvus 中的同名集合")
    a = ap.parse_args()
    for m in a.methods:
        migrate(m, a.uri, a.drop)
