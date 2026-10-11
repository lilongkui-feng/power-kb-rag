#!/bin/bash
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache QX_LLM_PROVIDER=siliconflow
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
E=".venv/bin/python evaluate.py --retrieval-only --rerank-cache --collection heading_v2"
log "云端验证②：V3 翻译问句 xlang=llm / mismatch / cap"
for m in llm mismatch cap; do
  $E --input eval_xling.jsonl --xlang $m --tag xl_v3$m >> logs_cxl.log 2>&1 && log "DONE xl_v3$m"
done
for m in llm mismatch cap; do
  $E --input eval_set_v3.jsonl --xlang $m --tag v3_xl_v3$m >> logs_cxl.log 2>&1 && log "DONE v3_xl_v3$m"
done
