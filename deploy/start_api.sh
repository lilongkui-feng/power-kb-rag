#!/bin/sh
# 后台启动 API（uvicorn）；host/port 取自配置（环境变量 > .env > config.yaml > 默认 127.0.0.1:8000）；日志 logs/powerkb.log + /workspace/api.log
cd /workspace/power_kb || exit 1
export HF_HOME="${HF_HOME:-/workspace/hf_cache}"
.venv/bin/python config.py >/dev/null || { echo "配置校验失败，见上方错误"; exit 2; }
HOST=$(.venv/bin/python config.py get kb_api_host); PORT=$(.venv/bin/python config.py get kb_api_port)
pgrep -f "uvicorn api:app" >/dev/null || nohup setsid .venv/bin/uvicorn api:app --host "$HOST" --port "$PORT" >> /workspace/api.log 2>&1 &
