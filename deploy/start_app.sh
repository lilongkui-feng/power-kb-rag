#!/bin/sh
# 先起 API（若未运行），再起 Streamlit 前端（:8501，只调 API，不加载模型）
cd /workspace/power_kb || exit 1
sh deploy/start_api.sh
export KB_API_URL="${KB_API_URL:-http://127.0.0.1:8000}"
pgrep -f "streamlit run app.py" >/dev/null || nohup setsid .venv/bin/streamlit run app.py --server.port 8501 --server.headless true --server.address 0.0.0.0 --browser.gatherUsageStats false >> /workspace/streamlit.log 2>&1 &
