#!/bin/sh
# 没有原件时：把宿主机已建好的索引拷进 compose 的数据目录（默认 ./data），容器启动即可用（拷出的切块含原文，勿公开分发）
set -e
cd "$(dirname "$0")/.."
D=${KB_DATA_DIR:-./data}
mkdir -p "$D/output/eval_runs" "$D/uploads"
cp -r chroma_db bm25_index emb_cache "$D/" 2>/dev/null || true
if [ -d milvus_db ]; then cp -r milvus_db "$D/"; fi
cp output/chunks_heading_v2.jsonl output/chunks_heading.jsonl "$D/output/" 2>/dev/null || true
cp uploads/registry.json uploads/chunks_uploaded*.jsonl "$D/uploads/" 2>/dev/null || true
# 容器内是 uid 1000（app）：数据目录须归它所有，否则评测写 output/eval_runs、上传等会报权限错误
if [ "$(id -u)" = 0 ]; then chown -R 1000:1000 "$D"; else echo "如以 root 运行 docker，请执行：sudo chown -R 1000:1000 $D"; fi
du -sh "$D"
