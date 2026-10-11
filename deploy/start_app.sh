#!/bin/sh
cd /workspace/power_kb
export HF_HOME=/workspace/hf_cache
pgrep -f "streamlit run app.py" >/dev/null || nohup setsid .venv/bin/streamlit run app.py --server.port 8501 --server.headless true --server.address 0.0.0.0 --browser.gatherUsageStats false >> /workspace/streamlit.log 2>&1 &
