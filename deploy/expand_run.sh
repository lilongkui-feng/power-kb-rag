#!/bin/sh
cd /workspace/power_kb; P=output/tuning_progress.md
for ex in parent neighbor; do
  .venv/bin/python evaluate.py --tag sf_v3_p2_ex_$ex --collection heading_v2 --provider siliconflow --prompt p2 --expand $ex --workers 4 --hits-from sf_v3_p2_k5 > logs_sf_v3_p2_ex_$ex.log 2>&1 \
   && echo "- [$(date +%H:%M)] DONE sf_v3_p2_ex_$ex" >> $P || echo "- [$(date +%H:%M)] FAIL sf_v3_p2_ex_$ex" >> $P
done
