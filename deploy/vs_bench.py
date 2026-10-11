# 向量库延迟 / 内存基准：同一批 50 个查询向量，测 Top-50 dense 检索延迟（含/不含过滤）与进程 RSS 增量
# 用法：VECTOR_STORE=chroma|milvus python deploy/vs_bench.py
import json, os, resource, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
def _rss(pid):
    try:
        return int(open(f"/proc/{pid}/statm").read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except OSError:
        return 0.0
def _children(pid):
    out = []
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            for c in open(f"/proc/{pid}/task/{t}/children").read().split():
                out += [int(c)] + _children(int(c))
        except OSError:
            pass
    return out
def rss():  # MB：本进程 + 子进程（Milvus Lite 的 milvus 服务是子进程）
    return _rss(os.getpid()) + sum(_rss(c) for c in _children(os.getpid()))
b = os.environ.get("VECTOR_STORE", "chroma")
r0 = rss(); t = time.time()
import vector_store as vs
s = vs.get_store("heading_v2"); n = s.count(); open_secs = time.time() - t
ids, emb = [], []
for i, e, _, _ in s.all_vectors(1000):
    ids += i; emb += list(e)
rng = np.random.default_rng(0); Q = np.asarray([emb[i] for i in rng.choice(len(emb), 50, replace=False)], dtype=np.float32)
Q = Q + rng.normal(scale=0.02, size=Q.shape).astype(np.float32); Q /= np.linalg.norm(Q, axis=1, keepdims=True)
r1 = rss()
out = {"backend": b, "count": n, "open_secs": round(open_secs, 2), "rss_after_open_mb": round(r1 - r0, 1)}
for name, where in (("top50", None), ("top50_filter", {"source": {"$in": ["DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf"]}})):
    s.query(Q[0], 50, where)                                  # 预热
    lat = []
    for q in Q:
        t = time.perf_counter(); s.query(q, 50, where); lat.append((time.perf_counter() - t) * 1000)
    out[name] = {"p50_ms": round(float(np.percentile(lat, 50)), 2), "p95_ms": round(float(np.percentile(lat, 95)), 2), "mean_ms": round(float(np.mean(lat)), 2)}
out["rss_total_mb_after_queries"] = round(rss() - r0, 1)
out["children"] = len(_children(os.getpid()))
print(json.dumps(out, ensure_ascii=False))
