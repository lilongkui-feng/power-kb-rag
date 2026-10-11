#!/bin/bash
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache QX_LLM_PROVIDER=siliconflow
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
while pgrep -f deploy/cloud_xl.sh >/dev/null; do sleep 20; done
for m in mismatch cap; do
  .venv/bin/python evaluate.py --retrieval-only --rerank-cache --collection heading_v2 --input eval_xling.jsonl --xlang $m --tag xl_v3$m >> logs_cxl2.log 2>&1 && log "DONE xl_v3$m"
done
