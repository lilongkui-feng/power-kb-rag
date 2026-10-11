#!/bin/bash
# 第 3 项：reflect / p3 本地 3B 子集验证（22 题；复用 v3set_sf_v3_p2 的检索结果；不调云端）
cd /workspace/power_kb; export HF_HOME=/workspace/hf_cache
P=output/tuning_progress.md; log(){ echo "- [$(date +%H:%M)] $*" >> $P; }
while pgrep -f deploy/ctx_run.sh >/dev/null || pgrep -f deploy/xl_run.sh >/dev/null; do sleep 20; done
IDS=P05,P13,P15,O03,P19,P36,P37,P38,F26,F28,F32,F34,F40,O06,O13,O17,O29,O40,P35,F21,F22,O31
E=".venv/bin/python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --provider local --rules 3 --ids $IDS --hits-from v3set_sf_v3_p2_2026"
log "第3项：本地 3B 子集 22 题 p1 / p3 / p3+reflect"
$E --prompt p1 --tag rf3b_p1 > logs_reflect.log 2>&1 && log "DONE rf3b_p1"
$E --prompt p3 --tag rf3b_p3 >> logs_reflect.log 2>&1 && log "DONE rf3b_p3"
$E --prompt p3 --reflect --tag rf3b_p3_reflect >> logs_reflect.log 2>&1 && log "DONE rf3b_p3_reflect"
log "第3项批跑结束"
