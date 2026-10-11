#!/bin/bash
# 第 1 项：跨语言检索 retrieval-only 批跑（串行）
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md
E=".venv/bin/python evaluate.py --collection heading_v2 --retrieval-only --rerank-cache"
log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
log "第1项 跨语言：开始 xling 36 题 none/dict/llm + v3 全集 dict"
$E --input eval_xling.jsonl --tag xl_none   > logs_xl.log 2>&1 && log "DONE xl_none"
$E --input eval_xling.jsonl --tag xl_dict --xlang dict >> logs_xl.log 2>&1 && log "DONE xl_dict"
$E --input eval_xling.jsonl --tag xl_llm --xlang llm  >> logs_xl.log 2>&1 && log "DONE xl_llm"
$E --input eval_set_v3.jsonl --tag v3_xl_dict --xlang dict >> logs_xl.log 2>&1 && log "DONE v3_xl_dict"
log "第1项批跑结束"
