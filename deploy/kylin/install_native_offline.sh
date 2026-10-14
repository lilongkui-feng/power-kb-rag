#!/usr/bin/env bash
# 路线 B：不装 Docker，便携 Python 3.11 + 离线 wheel 直接运行 PowerKB（api + web 两个 systemd 服务）
# 在资料包目录（dist/）执行：sudo bash install_native_offline.sh [选项]
#   --prefix DIR        安装目录（默认 /opt/powerkb）
#   --kb-data DIR       kb_data 分卷目录（默认 ./kb_data）
#   --user NAME         运行用户（默认 powerkb，不存在则创建）
#   --api-port N / --web-port N   默认 8000 / 8501
#   --api-host H        API 监听地址（默认 127.0.0.1：只给本机 web 用；需外部直连 API 时用 0.0.0.0）
#   --no-firewall  --no-start
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=/opt/powerkb; KBD="$HERE/kb_data"; RUSER=powerkb; API_PORT=8000; WEB_PORT=8501; API_HOST=127.0.0.1; FW=1; START=1
while [ $# -gt 0 ]; do case "$1" in
  --prefix) PREFIX=$2; shift;; --kb-data) KBD=$2; shift;; --user) RUSER=$2; shift;;
  --api-port) API_PORT=$2; shift;; --web-port) WEB_PORT=$2; shift;; --api-host) API_HOST=$2; shift;;
  --no-firewall) FW=0;; --no-start) START=0;; -h|--help) sed -n 2,10p "$0"; exit 0;; *) echo "未知参数 $1"; exit 2;; esac; shift; done
log(){ printf '\033[1;32m[native-install]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[native-install] 注意：\033[0m%s\n' "$*"; }
die(){ printf '\033[1;31m[native-install] 错误：\033[0m%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "请用 root 或 sudo 运行"
cd "$HERE"

# ---- 0. 环境检查 ----
ARCH=$(uname -m); [ -f ARCH ] && [ "$(cat ARCH)" != "$ARCH" ] && die "资料包架构 $(cat ARCH) 与本机 $ARCH 不符"
GLIBC=$(ldd --version | head -1 | awk '{print $NF}')
log "系统：$(. /etc/os-release; echo "$PRETTY_NAME") / 内核 $(uname -r) / $ARCH / glibc $GLIBC"
[ "$(printf '%s\n2.28\n' "$GLIBC" | sort -V | head -1)" = 2.28 ] || die "glibc $GLIBC < 2.28：torch / onnxruntime / pymupdf wheel 需要 manylinux_2_28，请改用 Docker 路线"
mkdir -p "$PREFIX"; free_gb=$(df -P "$PREFIX" | awk 'NR==2{print int($4/1048576)}')
[ "$free_gb" -lt 15 ] && die "$PREFIX 所在分区可用 ${free_gb} GB，至少需要 15 GB"
if [ -f SHA256SUMS ]; then log "校验资料包 sha256 …"; grep -v -E '/(docker|images)/' SHA256SUMS | sha256sum -c --quiet - || die "资料包校验失败"; fi

# ---- 1. 便携 Python + venv + 离线安装 wheel ----
PYT=$(ls python/cpython-3.11*-"$ARCH"-unknown-linux-gnu-install_only.tar.gz | head -1) || die "缺少 python/cpython-3.11*.tar.gz"
if [ ! -x "$PREFIX/python/bin/python3.11" ]; then log "解压便携 Python → $PREFIX/python"; tar -xzf "$PYT" -C "$PREFIX"; fi
"$PREFIX/python/bin/python3.11" -V
[ -x "$PREFIX/venv/bin/python" ] || "$PREFIX/python/bin/python3.11" -m venv "$PREFIX/venv"
PIP="$PREFIX/venv/bin/pip"
log "pip --no-index 离线安装依赖（torch CPU 等，约 3–5 分钟）…"
"$PIP" install -q --no-index --find-links "$HERE/wheels" -U pip setuptools wheel
"$PIP" install --no-index --find-links "$HERE/wheels" -r "$HERE/wheels/requirements-native.txt"
"$PREFIX/venv/bin/python" -c "import torch, onnxruntime, fitz, chromadb, jieba, sentence_transformers, streamlit; print('依赖导入 OK，torch', torch.__version__)"

# ---- 2. 代码 / 模型 / 数据 ----
APP="$PREFIX/app"; HF="$PREFIX/hf"; DATA="$PREFIX/data"; mkdir -p "$APP" "$HF" "$DATA" "$PREFIX/power_docs"
log "解压代码 → $APP"; tar -xzf code/power_kb.tar.gz -C "$APP" --strip-components=1
[ -d "$HF/hub/models--BAAI--bge-m3" ] || { log "解压模型 → $HF"; tar -xf models/hf_models.tar -C "$HF"; }
if [ ! -d "$DATA/chroma_db" ]; then
  [ -f "$KBD/SHA256SUMS" ] || die "找不到 $KBD/SHA256SUMS（用 --kb-data 指定分卷目录）"
  log "校验并合并 kb_data 分卷 …"
  (cd "$KBD" && grep -E 'kb_data\.tar\.gz\.p[0-9][0-9]$' SHA256SUMS | sha256sum -c --quiet -)
  cat "$KBD"/kb_data.tar.gz.p[0-9][0-9] > /tmp/kb_data.tar.gz
  (cd /tmp && grep -E ' kb_data\.tar\.gz$' "$KBD/SHA256SUMS" | sha256sum -c --quiet -) || die "合并后 kb_data.tar.gz 校验失败"
  tar -xzf /tmp/kb_data.tar.gz -C "$DATA" && rm -f /tmp/kb_data.tar.gz
fi
# 与容器入口一致：代码目录下的可写目录全部链接到 data/
mkdir -p "$DATA"/{output,chroma_db,bm25_index,emb_cache,uploads,milvus_db,logs}
if [ -d "$APP/output" ] && [ ! -L "$APP/output" ]; then cp -rn "$APP/output/." "$DATA/output/" 2>/dev/null || true; fi
for x in output chroma_db bm25_index emb_cache uploads milvus_db logs; do
  [ -L "$APP/$x" ] || { rm -rf "${APP:?}/$x"; ln -s "$DATA/$x" "$APP/$x"; }; done

# ---- 3. 用户与权限 ----
id "$RUSER" >/dev/null 2>&1 || useradd -r -m -d "$PREFIX/home" -s /sbin/nologin "$RUSER"
chown -R "$RUSER": "$DATA" "$HF" "$PREFIX/power_docs"; chown -R root: "$APP" "$PREFIX/venv" "$PREFIX/python"

# ---- 4. .env ----
ENVF="$APP/.env"; [ -f "$ENVF" ] || cp "$APP/.env.example" "$ENVF"
setv(){ if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else echo "$1=$2" >> "$ENVF"; fi; }
setv HF_HOME "$HF"; setv HF_HUB_OFFLINE 1; setv TRANSFORMERS_OFFLINE 1; sed -i "/^HF_ENDPOINT=/d" "$ENVF"
setv OCR_ENGINE rapid; setv KB_API_HOST "$API_HOST"; setv KB_API_PORT "$API_PORT"; setv KB_API_URL "http://127.0.0.1:$API_PORT"
grep -q '^LLM_FALLBACK=.\+' "$ENVF" || setv LLM_FALLBACK retrieval
chown root:"$RUSER" "$ENVF"; chmod 640 "$ENVF"

# ---- 5. systemd ----
cat > /etc/systemd/system/powerkb-api.service <<U
[Unit]
Description=PowerKB API (uvicorn, native)
After=network-online.target
Wants=network-online.target
[Service]
User=$RUSER
WorkingDirectory=$APP
EnvironmentFile=$ENVF
Environment=PYTHONUNBUFFERED=1 OMP_NUM_THREADS=$(nproc)
ExecStart=$PREFIX/venv/bin/uvicorn api:app --host $API_HOST --port $API_PORT
Restart=on-failure
RestartSec=10
TimeoutStartSec=600
LimitNOFILE=65536
[Install]
WantedBy=multi-user.target
U
cat > /etc/systemd/system/powerkb-web.service <<U
[Unit]
Description=PowerKB Web (streamlit, native)
After=powerkb-api.service
Wants=powerkb-api.service
[Service]
User=$RUSER
WorkingDirectory=$APP
EnvironmentFile=$ENVF
Environment=HOME=$PREFIX/home
ExecStart=$PREFIX/venv/bin/streamlit run app.py --server.port $WEB_PORT --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload; systemctl enable powerkb-api.service powerkb-web.service

# ---- 6. SELinux / firewalld ----
if command -v getenforce >/dev/null && [ "$(getenforce)" = Enforcing ]; then
  warn "SELinux Enforcing：服务以 unconfined_service_t 运行，一般无需处理；若有拒绝见手册 §9（ausearch -m avc）"
  command -v semanage >/dev/null && semanage port -a -t http_port_t -p tcp "$WEB_PORT" 2>/dev/null || true
fi
if [ "$FW" = 1 ] && systemctl is-active -q firewalld; then
  log "firewalld 放行 $WEB_PORT/tcp"; firewall-cmd -q --permanent --add-port="$WEB_PORT/tcp"
  [ "$API_HOST" = 127.0.0.1 ] || firewall-cmd -q --permanent --add-port="$API_PORT/tcp"
  firewall-cmd -q --reload
fi

# ---- 7. 启动与验证 ----
[ "$START" = 1 ] || { log "已安装未启动：systemctl start powerkb-api powerkb-web"; exit 0; }
systemctl restart powerkb-api.service
log "等待模型加载（1–3 分钟）…"
ok=0; for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$API_PORT/health" 2>/dev/null | grep -q '"models_loaded":true' && { ok=1; break; }; sleep 5; done
[ "$ok" = 1 ] || { journalctl -u powerkb-api -n 60 --no-pager; die "API 未就绪"; }
systemctl restart powerkb-web.service
curl -fsS "http://127.0.0.1:$API_PORT/health"; echo
log "完成：http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
