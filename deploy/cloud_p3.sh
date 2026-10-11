#!/bin/bash
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
E=".venv/bin/python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --provider siliconflow --rules 3 --workers 4 --hits-from v3set_sf_v3_p2_2026"
log "云端验证①：V3 + p3 全集（检索复用 v3set_sf_v3_p2）"
$E --prompt p3 --tag v3set_sf_v3_p3 > logs_cp3.log 2>&1 && log "DONE v3set_sf_v3_p3"
$E --prompt p3 --reflect --tag v3set_sf_v3_p3_reflect >> logs_cp3.log 2>&1 && log "DONE v3set_sf_v3_p3_reflect"
