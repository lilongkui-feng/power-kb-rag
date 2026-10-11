#!/bin/sh
# 切分单因素扫描：每组 build -> embed -> bm25 -> retrieval-only；完成一组写一行进度
cd /workspace/power_kb
for cfg in "800 50" "400 50" "1200 50" "800 0" "800 150"; do
  set -- $cfg; n="v2s$1o$2"; [ "$n" = "v2s800o50" ] && n=heading_v2
  if grep -q "DONE $n" output/tuning_progress.md; then continue; fi
  { [ "$n" = heading_v2 ] || .venv/bin/python build_v2.py --max-size $1 --overlap $2 --name $n; } &&
  .venv/bin/python embed_index.py --methods $n &&
  .venv/bin/python bm25_index.py --methods $n &&
  .venv/bin/python evaluate.py --retrieval-only --collection $n --tag retr_$n &&
  echo "- [$(date +%H:%M)] DONE $n（切分 max=$1 overlap=$2，retrieval-only 完成，见 baseline_scores.md retr_$n）" >> output/tuning_progress.md
done
