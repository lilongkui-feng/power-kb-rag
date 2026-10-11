#!/bin/sh
# 硅基流动三轮全量生成（串行，每轮 4 并发）；key 只从环境变量读取
cd /workspace/power_kb
P=output/tuning_progress.md
run() { tag=$1; shift
  .venv/bin/python evaluate.py --tag $tag --collection heading_v2 --provider siliconflow --workers 4 "$@" > logs_$tag.log 2>&1 \
    && echo "- [$(date +%H:%M)] DONE $tag（$*）" >> $P || echo "- [$(date +%H:%M)] FAIL $tag，见 logs_$tag.log" >> $P; }
run sf_v3_p1_k5 --prompt p1
run sf_q72_p1_k5 --prompt p1 --model Qwen/Qwen2.5-72B-Instruct
run sf_v3_p2_k5 --prompt p2
