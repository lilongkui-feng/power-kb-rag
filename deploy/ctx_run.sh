#!/bin/bash
# 第 2 项：Contextual 前缀集合 + 多查询 retrieval-only（等第 1 项批跑结束后串行）
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
while pgrep -f deploy/xl_run.sh >/dev/null; do sleep 20; done
E=".venv/bin/python evaluate.py --retrieval-only --rerank-cache"
log "第2项：建 heading_v2_ctx 向量+BM25"
.venv/bin/python embed_index.py --methods heading_v2_ctx > logs_ctx.log 2>&1 && .venv/bin/python bm25_index.py --methods heading_v2_ctx >> logs_ctx.log 2>&1 && log "DONE 建索引 heading_v2_ctx"
$E --input eval_set_v3.jsonl --collection heading_v2_ctx --tag v3_ctx >> logs_ctx.log 2>&1 && log "DONE v3_ctx"
$E --input eval_set_v3.jsonl --collection heading_v2 --multiq rule --tag v3_mq_rule >> logs_ctx.log 2>&1 && log "DONE v3_mq_rule"
$E --input eval_xling.jsonl --collection heading_v2_ctx --tag xl_ctx >> logs_ctx.log 2>&1 && log "DONE xl_ctx"
log "第2项批跑结束"
