#!/bin/sh
# 用法：deploy/gen_run.sh <tag> <evaluate 参数...>；等切分扫描结束后串行跑，完成后写进度；已 DONE 的跳过
cd /workspace/power_kb
tag=$1; shift
grep -q "DONE $tag" output/tuning_progress.md && exit 0
while pgrep -f tune_chunks.sh >/dev/null || pgrep -f "evaluate.py --collection" >/dev/null; do sleep 30; done
.venv/bin/python evaluate.py --tag $tag "$@" && echo "- [$(date +%H:%M)] DONE $tag（$*）" >> output/tuning_progress.md
