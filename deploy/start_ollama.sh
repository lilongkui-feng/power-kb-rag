#!/bin/sh
# 本地 LLM 服务（OpenAI 兼容接口 http://127.0.0.1:11434/v1）
export OLLAMA_MODELS=/workspace/ollama_models OLLAMA_HOST=127.0.0.1:11434 OLLAMA_KEEP_ALIVE=30m OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1
pgrep -f "ollama serve" >/dev/null || nohup setsid ollama serve >> /workspace/ollama.log 2>&1 &
