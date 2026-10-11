# Chroma vs Milvus（heading_v2，3543 块，bge-m3 1024 维，余弦）

迁移：`python migrate_chroma_to_milvus.py --methods heading_v2 --drop`，复用 Chroma 中已存向量，不重新 embedding。
Milvus Lite 用时 2.9 s；Milvus Standalone（docker，v2.5.10）用时 2.3 s。两边条数一致（3543），来源分布一致；
抽样 20 个向量，两边 Top-5 重合率：Lite 0.967，Standalone 0.983（两个都是 HNSW 近似检索，近似并列的邻居顺序会有差别）。

## 检索指标：eval_set_v3 全集，--retrieval-only（heading_v2 + hybrid α=0.5 + bge-reranker-v2-m3 Top-20 β=0.8）

| 后端 | 题数 | chunk Hit@1 | Hit@3 | Hit@5 | MRR | 文档 Hit@1 | 文档 MRR |
|---|---|---|---|---|---|---|---|
| Chroma 1.5.9（`vs_chroma_20261011-174851`） | 139 | 83.5% | 95.0% | 97.1% | 0.893 | 98.6% | 0.992 |
| Milvus Lite 3.2.1 / pymilvus 3.0.2（`vs_milvus_20261011-175528`） | 139 | 83.5% | 95.0% | 97.1% | 0.893 | 98.6% | 0.992 |

逐题对比（144 题，含 5 道拒答题）：chunk 命中名次和文档命中名次 **144/144 完全相同**；只有 1 道题的 Top-1 重排分有微小差别（候选池里有一个近似并列的块不同）。
说明：重排分走了缓存（`--rerank-cache`），所以两次运行的重排耗时不能当延迟数据用，延迟见下面的基准测试。

## 延迟与内存（`deploy/vs_bench.py`：50 个查询向量，Top-50 稠密检索，CPU，单进程）

| 后端 | 打开集合 | Top-50 p50 / p95 | 带过滤 Top-50（source $in）p50 / p95 | 内存增量（RSS） | 磁盘 |
|---|---|---|---|---|---|
| Chroma（PersistentClient） | 0.57 s | 4.5 / 5.6 ms | 7.1 / 8.1 ms | ≈ 190 MB | 274 MB（chroma_db 含 v1/v2 等全部集合） |
| Milvus Lite（本地 .db） | 0.44 s | 9.3 / 10.0 ms | 4.9 / 9.2 ms | ≈ 470 MB | 30 MB（只有 heading_v2 一个集合） |

完整检索链路里，一阶段（bge-m3 编码 + 向量 + BM25 + 融合）每题均值：Chroma 0.27 s，Milvus 0.20 s（p50 都约 0.08–0.09 s）；
重排 2.5–2.7 s/题，占检索耗时的 90% 以上。**在这个规模下，选哪个向量库对端到端延迟几乎没有影响。**
Milvus Standalone（docker）：/search 能正常工作；当时宿主机 CPU 很忙（多个容器同时运行），没有做严格的延迟基准。

## 结论
- 3.5k 块的规模下两者检索结果等价，默认继续用 **Chroma**：零运维、嵌入式，内存更小。
- 下面这些情况再切换 **Milvus**：块数到百万级、需要多副本/水平扩展、多个服务共享同一个向量库、需要标量索引加速过滤或混合检索。
  切换只要设置 `VECTOR_STORE=milvus`（以及 `MILVUS_URI`），再跑一次迁移脚本，代码不用改。
