#!/bin/sh
# 容器入口：把可写目录链接到 /data 卷；api 角色首次启动时若索引为空则自动建索引
#   1) /data/power_docs 里有 PDF/docx → build_v2.py + embed_index.py + bm25_index.py（首次约 10–30 分钟，含模型下载）
#   2) VECTOR_STORE=milvus 且 Milvus 集合为空、但有 Chroma 索引 → migrate_chroma_to_milvus.py（复用向量）
#   3) 都没有 → 照常启动，/health 报告 load_error；可把宿主机预建索引放进 /data（见 deploy/seed_data.sh）
set -e
# .env.example 复制来的空值（如 SILICONFLOW_MODEL=、OCR_ENGINE=）会盖掉代码默认值：空变量一律视为未设置
for v in $(env | sed -n "s/^\([A-Za-z_][A-Za-z0-9_]*\)=$/\1/p"); do unset "$v"; done
export HF_HOME="${HF_HOME:-/models/hf}"           # .env 里的空 HF_HOME= 会覆盖镜像 ENV，这里兜底
D=${KB_DATA:-/data}
mkdir -p "$D/output" "$D/chroma_db" "$D/bm25_index" "$D/emb_cache" "$D/uploads" "$D/milvus_db" "$D/power_docs" "$D/logs" 2>/dev/null || true
cp -rn /app/output.dist/. "$D/output/" 2>/dev/null || true          # 报告等小文件（不覆盖卷里已有的）
for x in output chroma_db bm25_index emb_cache uploads milvus_db logs; do
  [ -L "/app/$x" ] || { rm -rf "/app/$x"; ln -s "$D/$x" "/app/$x"; }
done
role=${1:-api}; shift 2>/dev/null || true
# 模型已在缓存卷里就离线加载（避免每次启动访问 huggingface.co；首次无缓存时联网下载）
if [ -z "${HF_HUB_OFFLINE:-}" ] && [ -d "${HF_HOME:-/models/hf}/hub/models--BAAI--bge-m3" ] && [ -d "${HF_HOME:-/models/hf}/hub/models--BAAI--bge-reranker-v2-m3" ]; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
fi

index_empty() {
  python - <<'PY'
import os, sys
try:
    from vector_store import get_store
    n = get_store("heading_v2").count()
except Exception as e:
    n = 0
ok = n > 0 and os.path.exists("output/chunks_heading_v2.jsonl") and os.path.exists("bm25_index/heading_v2.pkl")
sys.exit(0 if not ok else 1)
PY
}

if [ "$role" = "api" ] || [ "$role" = "build" ]; then
  if [ "$role" = "build" ] || index_empty; then
    VS=${VECTOR_STORE:-chroma}
    if [ "$VS" = "milvus" ] && [ -f "$D/chroma_db/chroma.sqlite3" ] && [ -f "$D/output/chunks_heading_v2.jsonl" ]; then
      echo "[entrypoint] Milvus 集合为空，从 Chroma 迁移（不重新 embedding）"
      python migrate_chroma_to_milvus.py --methods heading_v2 --drop
      [ -f "$D/bm25_index/heading_v2.pkl" ] || python bm25_index.py --methods heading_v2
    elif [ -n "$(find "$DOCS_ROOT" -maxdepth 4 \( -name '*.pdf' -o -name '*.docx' \) -print -quit 2>/dev/null)" ]; then
      echo "[entrypoint] 索引为空，用 $DOCS_ROOT 的原件建索引（首次较慢）"
      python build_v2.py --docs-root "$DOCS_ROOT" --ocr-engine rapid
      python embed_index.py --methods heading_v2
      python bm25_index.py --methods heading_v2
    else
      echo "[entrypoint] ⚠ 索引为空且 $DOCS_ROOT 无原件：API 照常启动但检索不可用。请挂载原件目录（POWER_DOCS_DIR）或预建索引（deploy/seed_data.sh）"
    fi
  fi
  [ "$role" = "build" ] && exit 0
  exec uvicorn api:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" "$@"
elif [ "$role" = "web" ]; then
  exec streamlit run app.py --server.port "${WEB_PORT:-8501}" --server.address "${WEB_HOST:-0.0.0.0}" --server.headless true --browser.gatherUsageStats false "$@"
else
  exec "$role" "$@"
fi
