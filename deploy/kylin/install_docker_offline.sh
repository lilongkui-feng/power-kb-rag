#!/usr/bin/env bash
# 路线 A：麒麟 V10 离线安装 Docker（静态二进制）+ compose 插件 + 导入 powerkb 镜像 + 部署启动
# 在资料包目录（dist/）执行：sudo bash install_docker_offline.sh [选项]
#   --prefix DIR        安装目录（默认 /opt/powerkb）
#   --kb-data DIR       kb_data 分卷目录（默认 ./kb_data）
#   --api-port N / --web-port N   默认 8000 / 8501
#   --hostnet           容器 bridge 网络异常时改用宿主机网络
#   --skip-docker       已装好 Docker ≥ 20.10 且 compose ≥ 2.24 时跳过 Docker 安装
#   --no-firewall       不修改 firewalld      --no-start  只安装不启动
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=/opt/powerkb; KBD="$HERE/kb_data"; API_PORT=8000; WEB_PORT=8501; HOSTNET=0; SKIPD=0; FW=1; START=1
while [ $# -gt 0 ]; do case "$1" in
  --prefix) PREFIX=$2; shift;; --kb-data) KBD=$2; shift;; --api-port) API_PORT=$2; shift;; --web-port) WEB_PORT=$2; shift;;
  --hostnet) HOSTNET=1;; --skip-docker) SKIPD=1;; --no-firewall) FW=0;; --no-start) START=0;;
  -h|--help) sed -n 2,10p "$0"; exit 0;; *) echo "未知参数 $1"; exit 2;; esac; shift; done
log(){ printf '\033[1;32m[docker-install]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[docker-install] 注意：\033[0m%s\n' "$*"; }
die(){ printf '\033[1;31m[docker-install] 错误：\033[0m%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "请用 root 或 sudo 运行"
cd "$HERE"

# ---- 0. 环境检查 ----
ARCH=$(uname -m); [ -f ARCH ] && [ "$(cat ARCH)" != "$ARCH" ] && die "资料包架构 $(cat ARCH) 与本机 $ARCH 不符"
log "系统：$(. /etc/os-release; echo "$PRETTY_NAME") / 内核 $(uname -r) / $ARCH / glibc $(ldd --version | head -1 | awk '{print $NF}')"
mem=$(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo); [ "$mem" -lt 12 ] && warn "内存 ${mem} GB，建议 ≥ 16 GB"
mkdir -p "$PREFIX"; free_gb=$(df -P "$PREFIX" | awk 'NR==2{print int($4/1048576)}')
[ "$free_gb" -lt 25 ] && die "$PREFIX 所在分区可用 ${free_gb} GB，至少需要 25 GB"
log "校验资料包 sha256 …"
if [ -f SHA256SUMS ]; then grep -v -E '/(python|wheels)/' SHA256SUMS | sha256sum -c --quiet - || die "资料包校验失败，重新拷贝"; fi

# ---- 1. Docker 静态二进制 + systemd ----
if [ "$SKIPD" = 0 ]; then
  if command -v dockerd >/dev/null && [ "$(command -v dockerd)" != /usr/local/bin/dockerd ]; then
    warn "已存在 $(command -v dockerd)（可能是麒麟源里的 docker-engine 18.09）。将安装新版到 /usr/local/bin 并接管 docker.service"
    systemctl disable --now docker.service docker.socket 2>/dev/null || true
  fi
  if ls docker/rpms/*.rpm >/dev/null 2>&1; then           # prepare --docker-source tuna 打的 rpm 包
    bash "$HERE/install_docker_tuna_rpm.sh" --from "$HERE/docker/rpms"
    SKIPD=rpm
  fi
fi
if [ "$SKIPD" = 0 ]; then
  TGZ=$(ls docker/docker-*.tgz | head -1) || die "缺少 docker/docker-*.tgz"
  log "安装 $TGZ → /usr/local/bin"
  tar -xzf "$TGZ" -C /tmp && install -m 755 /tmp/docker/* /usr/local/bin/ && rm -rf /tmp/docker
  mkdir -p /usr/local/lib/docker/cli-plugins
  install -m 755 "docker/docker-compose-linux-$ARCH" /usr/local/lib/docker/cli-plugins/docker-compose
  getent group docker >/dev/null || groupadd docker
  cat > /etc/systemd/system/containerd.service <<'U'
[Unit]
Description=containerd (static)
After=network.target local-fs.target
[Service]
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/local/bin/containerd
Type=notify
Delegate=yes
KillMode=process
Restart=always
RestartSec=5
LimitNPROC=infinity
LimitCORE=infinity
LimitNOFILE=1048576
TasksMax=infinity
OOMScoreAdjust=-999
[Install]
WantedBy=multi-user.target
U
  cat > /etc/systemd/system/docker.socket <<'U'
[Unit]
Description=Docker Socket for the API
[Socket]
ListenStream=/run/docker.sock
SocketMode=0660
SocketUser=root
SocketGroup=docker
[Install]
WantedBy=sockets.target
U
  cat > /etc/systemd/system/docker.service <<'U'
[Unit]
Description=Docker Application Container Engine (static)
After=network-online.target firewalld.service containerd.service
Wants=network-online.target containerd.service
Requires=docker.socket
[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
ExecReload=/bin/kill -s HUP $MAINPID
TimeoutStartSec=0
RestartSec=2
Restart=always
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
Delegate=yes
KillMode=process
OOMScoreAdjust=-500
[Install]
WantedBy=multi-user.target
U
  mkdir -p /etc/docker
  if [ ! -f /etc/docker/daemon.json ]; then
    # 麒麟 V10 内核 4.19 支持 overlay2；cgroup v1 + cgroupfs/systemd 均可，这里与 systemd 保持一致
    cat > /etc/docker/daemon.json <<'J'
{
  "storage-driver": "overlay2",
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {"max-size": "50m", "max-file": "3"},
  "data-root": "/var/lib/docker"
}
J
  fi
  modprobe overlay 2>/dev/null || true; modprobe br_netfilter 2>/dev/null || true
  printf 'net.bridge.bridge-nf-call-iptables=1\nnet.ipv4.ip_forward=1\n' > /etc/sysctl.d/99-docker.conf; sysctl -q --system || true
  systemctl daemon-reload
  systemctl enable --now containerd.service docker.socket docker.service
fi
for _ in $(seq 1 20); do docker info >/dev/null 2>&1 && break; sleep 1; done
docker info >/dev/null 2>&1 || die "dockerd 未启动：journalctl -u docker -n 80"
log "Docker $(docker version -f '{{.Server.Version}}')，Compose $(docker compose version --short)"
docker info 2>/dev/null | grep -Ei 'storage driver|cgroup|security' | sed 's/^/    /'

# ---- 2. 导入镜像 ----
log "docker load powerkb 镜像 …"
gunzip -c images/powerkb_image.tar.gz | docker load
IA=$(docker image inspect -f '{{.Architecture}}' powerkb:latest); case "$ARCH:$IA" in x86_64:amd64|aarch64:arm64) ;; *) die "镜像架构 $IA 与本机 $ARCH 不符";; esac

# ---- 3. 代码 / 模型 / 数据 ----
APP="$PREFIX/app"; HF="$PREFIX/hf"; DATA="$PREFIX/data"; mkdir -p "$APP" "$HF" "$DATA" "$PREFIX/power_docs"
log "解压代码 → $APP"
tar -xzf code/power_kb.tar.gz -C "$APP" --strip-components=1
cp code/docker-compose.yml code/docker-compose.hostnet.yml code/.env.example "$APP/" 2>/dev/null || true
cp code/docker-compose.offline.yml "$APP/" 2>/dev/null || cp docker-compose.offline.yml "$APP/"
[ -d "$HF/hub/models--BAAI--bge-m3" ] || { log "解压模型 → $HF"; tar -xf models/hf_models.tar -C "$HF"; }
if [ ! -d "$DATA/chroma_db" ]; then
  [ -f "$KBD/SHA256SUMS" ] || die "找不到 $KBD/SHA256SUMS（kb_data 分卷目录用 --kb-data 指定）"
  log "校验并合并 kb_data 分卷 …"
  (cd "$KBD" && grep -E 'kb_data\.tar\.gz\.p[0-9][0-9]$' SHA256SUMS | sha256sum -c --quiet -)
  cat "$KBD"/kb_data.tar.gz.p[0-9][0-9] > /tmp/kb_data.tar.gz
  (cd /tmp && grep -E ' kb_data\.tar\.gz$' "$KBD/SHA256SUMS" | sha256sum -c --quiet -) || die "合并后 kb_data.tar.gz 校验失败"
  tar -xzf /tmp/kb_data.tar.gz -C "$DATA" && rm -f /tmp/kb_data.tar.gz
fi
mkdir -p "$DATA/logs"; chown -R 1000:1000 "$DATA" "$HF"     # 容器内 uid 1000

# ---- 4. SELinux：给绑定目录打容器标签（Enforcing 时必须）----
if command -v getenforce >/dev/null && [ "$(getenforce)" != Disabled ]; then
  log "SELinux=$(getenforce)，为 $DATA $HF $PREFIX/power_docs 设置 container_file_t 标签"
  if command -v semanage >/dev/null; then
    for d in "$DATA" "$HF" "$PREFIX/power_docs"; do semanage fcontext -a -t container_file_t "$d(/.*)?" 2>/dev/null || true; restorecon -R "$d"; done
  else
    chcon -R -t container_file_t "$DATA" "$HF" "$PREFIX/power_docs" 2>/dev/null || warn "chcon 失败（策略中无 container_file_t？），见手册排障"
  fi
fi

# ---- 5. .env ----
ENVF="$APP/.env"; [ -f "$ENVF" ] || cp "$APP/.env.example" "$ENVF"
setv(){ if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else echo "$1=$2" >> "$ENVF"; fi; }
CF="docker-compose.yml"; [ "$HOSTNET" = 1 ] && CF="$CF:docker-compose.hostnet.yml"; CF="$CF:docker-compose.offline.yml"
setv COMPOSE_PROJECT_NAME powerkb; setv COMPOSE_FILE "$CF"
grep -q "^COMPOSE_PROFILES=" "$ENVF" && sed -i "s|^COMPOSE_PROFILES=.*|COMPOSE_PROFILES=|" "$ENVF" || echo "COMPOSE_PROFILES=" >> "$ENVF"   # 离线默认不启用 ollama
setv KB_DATA_DIR "$DATA"; setv HF_CACHE_DIR "$HF"; setv POWER_DOCS_DIR "$PREFIX/power_docs"
setv KB_API_PORT "$API_PORT"; setv KB_WEB_PORT "$WEB_PORT"
setv HF_HUB_OFFLINE 1; setv TRANSFORMERS_OFFLINE 1; sed -i "/^HF_ENDPOINT=/d" "$ENVF"
grep -q '^LLM_FALLBACK=.\+' "$ENVF" || setv LLM_FALLBACK retrieval
chmod 600 "$ENVF"
[ -f "$HERE/powerkb.service" ] && sed -e "s|/opt/powerkb|$PREFIX|g" -e "s|/usr/local/bin/docker |$(command -v docker) |g" "$HERE/powerkb.service" > /etc/systemd/system/powerkb.service && systemctl daemon-reload && systemctl enable powerkb.service

# ---- 6. firewalld ----
if [ "$FW" = 1 ] && systemctl is-active -q firewalld; then
  log "firewalld 放行 $WEB_PORT/tcp（前端）与 $API_PORT/tcp（API）"
  firewall-cmd -q --permanent --add-port="$WEB_PORT/tcp"; firewall-cmd -q --permanent --add-port="$API_PORT/tcp"
  firewall-cmd -q --permanent --zone=trusted --add-interface=docker0 2>/dev/null || true
  firewall-cmd -q --reload
fi

# ---- 7. 启动与验证 ----
[ "$START" = 1 ] || { log "已安装未启动：systemctl start powerkb"; exit 0; }
cd "$APP"; docker compose up -d
log "等待模型加载（1–3 分钟）…"
ok=0; for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$API_PORT/health" 2>/dev/null | grep -q '"models_loaded":true' && { ok=1; break; }; sleep 5; done
[ "$ok" = 1 ] || { docker compose ps; docker compose logs --tail 60 api; die "API 未就绪，见手册排障"; }
curl -fsS "http://127.0.0.1:$API_PORT/health"; echo; docker compose ps
log "完成：http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
