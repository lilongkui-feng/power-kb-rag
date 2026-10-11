#!/bin/sh
# chroma vs milvus：eval_set_v3 全集 retrieval-only（重排分走缓存，指标可比；延迟另见 deploy/vs_bench.py）
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md
echo "- [$(date +%H:%M)] vs_compare 开始：chroma" >> $P
VECTOR_STORE=chroma .venv/bin/python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --retrieval-only --rerank-cache --tag vs_chroma
echo "- [$(date +%H:%M)] chroma 完成，开始 milvus(Lite)" >> $P
VECTOR_STORE=milvus .venv/bin/python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --retrieval-only --rerank-cache --tag vs_milvus
echo "- [$(date +%H:%M)] vs_compare 完成" >> $P
