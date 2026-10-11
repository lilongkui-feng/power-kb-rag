#!/bin/sh
# 后台启动 API（uvicorn :8000）；日志 /workspace/api.log
cd /workspace/power_kb
export HF_HOME=/workspace/hf_cache
pgrep -f "uvicorn api:app" >/dev/null || nohup setsid .venv/bin/uvicorn api:app --host ${KB_API_HOST:-127.0.0.1} --port ${KB_API_PORT:-8000} >> /workspace/api.log 2>&1 &
