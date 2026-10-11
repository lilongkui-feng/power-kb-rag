#!/bin/sh
# shellcheck disable=SC2086  # $F 有意不加引号（为空或含两个 -f 参数）
# 一键部署：sh deploy/up.sh            → docker compose up -d --build（Chroma）
#          sh deploy/up.sh milvus     → 加 Milvus Standalone，并让 api 使用它（首次自动从 Chroma 迁移向量）
#          sh deploy/up.sh down       → 停止
#          sh deploy/up.sh --hostnet [milvus|down]  → 宿主机网络模式（bridge 网络不可用的环境）
set -e
cd "$(dirname "$0")/.."
F=""
if [ "$1" = "--hostnet" ]; then F="-f docker-compose.yml -f docker-compose.hostnet.yml"; shift; fi   # bridge 网络不可用时
MURI=http://milvus:19530; [ -n "$F" ] && MURI=http://127.0.0.1:19530
[ -f .env ] || { cp .env.example .env; echo "已从 .env.example 生成 .env（按需填写 key）"; }
mkdir -p "${KB_DATA_DIR:-./data}" "${POWER_DOCS_DIR:-./power_docs}"
case "${1:-up}" in
  milvus) VECTOR_STORE=milvus MILVUS_URI=$MURI docker compose $F --profile milvus up -d --build ;;
  down)   docker compose $F --profile milvus down ;;
  *)      docker compose $F up -d --build ;;
esac
docker compose $F ps
echo "API: http://localhost:${KB_API_PORT:-8000}/docs   Web: http://localhost:${KB_WEB_PORT:-8501}   （首次启动要加载/下载模型，api 健康后 web 才启动）"
