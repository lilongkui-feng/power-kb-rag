#!/bin/bash
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
while pgrep -f deploy/ctx_run.sh >/dev/null; do sleep 20; done
E=".venv/bin/python evaluate.py --retrieval-only --rerank-cache --collection heading_v2"
log "第1项追加：xlang=dict 让中文题退步（Hit@1 85.0%→76.1%），改为 auto 门控 + 改写权重 0.7"
$E --input eval_xling.jsonl --xlang auto --tag xl_auto > logs_xl2.log 2>&1 && log "DONE xl_auto"
$E --input eval_xling.jsonl --xlang auto_llm --tag xl_auto_llm >> logs_xl2.log 2>&1 && log "DONE xl_auto_llm"
$E --input eval_set_v3.jsonl --xlang auto --tag v3_xl_auto >> logs_xl2.log 2>&1 && log "DONE v3_xl_auto"
nohup deploy/reflect_run.sh >/dev/null 2>&1 &
