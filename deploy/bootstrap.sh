#!/usr/bin/env bash
# PowerKB 一键部署（干净的 Ubuntu 22.04 / 24.04）：装 Docker → 拉代码 → 生成 .env → 启动。幂等，可重复运行。
#
#   curl -fsSL https://raw.githubusercontent.com/lilongkui-feng/power-kb-rag/main/deploy/bootstrap.sh -o bootstrap.sh
#   sudo bash bootstrap.sh                       # 默认：国内镜像装 Docker、Chroma、bridge 网络
#
# 可选环境变量（写在命令前，如 sudo CN_MIRROR=0 START=0 bash bootstrap.sh）：
#   REPO_URL     代码仓库，默认 https://github.com/lilongkui-feng/power-kb-rag.git
#   BRANCH       默认 main
#   APP_DIR      安装目录，默认 /opt/power-kb-rag
#   CN_MIRROR    1（默认）= 用阿里云镜像装 Docker，并在 .env 里写 HF_ENDPOINT=https://hf-mirror.com；0 = 官方源
#   DOCKER_REGISTRY_MIRROR  Docker Hub 加速地址（如你在阿里云控制台“容器镜像服务→镜像加速器”拿到的专属地址）；不填不配置
#   PROFILE      chroma（默认）| milvus
#   HOSTNET      1 = 宿主机网络模式（bridge 网络不通时用），默认 0
#   START        1（默认）= 最后执行 docker compose up；0 = 只准备环境
#   SKIP_DOCKER  1 = 跳过 Docker 安装和启动（只做代码/.env/目录，测试用）
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/lilongkui-feng/power-kb-rag.git}
BRANCH=${BRANCH:-main}
APP_DIR=${APP_DIR:-/opt/power-kb-rag}
CN_MIRROR=${CN_MIRROR:-1}
DOCKER_REGISTRY_MIRROR=${DOCKER_REGISTRY_MIRROR:-}
PROFILE=${PROFILE:-chroma}
HOSTNET=${HOSTNET:-0}
START=${START:-1}
SKIP_DOCKER=${SKIP_DOCKER:-0}

log()  { printf '\033[1;32m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap] 注意：\033[0m%s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap] 失败：\033[0m%s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 或 sudo 运行：sudo bash $0"
case "$PROFILE" in chroma|milvus) ;; *) die "PROFILE 只能是 chroma 或 milvus" ;; esac

# ---------- 0. 系统检查 ----------
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || warn "本脚本只在 Ubuntu 22.04/24.04 上验证过，当前是 ${PRETTY_NAME:-未知系统}"
fi
cores=$(nproc 2>/dev/null || echo 0)
mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
log "CPU ${cores} 核，内存 ${mem_gb} GB"
[ "$cores" -ge 8 ] || warn "建议至少 8 核（重排在 CPU 上较慢，核数少时单次问答会明显变慢）"
[ "$mem_gb" -ge 15 ] || warn "建议至少 16 GB 内存（实测 API 空闲约 1.6 GB、问答时重排有峰值，ollama 3B 约 2.4 GB，首次建索引更高；不足时可能被 OOM 杀掉）"

# ---------- 1. 基础工具 ----------
need=()
for c in git curl; do command -v "$c" >/dev/null 2>&1 || need+=("$c"); done
if [ "${#need[@]}" -gt 0 ]; then
  log "安装 ${need[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq "${need[@]}" ca-certificates >/dev/null
fi

# ---------- 2. Docker ----------
if [ "$SKIP_DOCKER" != "1" ]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker 已安装：$(docker --version)；$(docker compose version)"
  else
    log "安装 Docker（官方 get.docker.com 脚本$( [ "$CN_MIRROR" = 1 ] && echo '，阿里云镜像源')）"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    if [ "$CN_MIRROR" = "1" ]; then sh /tmp/get-docker.sh --mirror Aliyun; else sh /tmp/get-docker.sh; fi
    systemctl enable --now docker
  fi
  if [ -n "$DOCKER_REGISTRY_MIRROR" ]; then
    f=/etc/docker/daemon.json
    if [ -f "$f" ] && grep -q "$DOCKER_REGISTRY_MIRROR" "$f"; then
      log "镜像加速已配置：$DOCKER_REGISTRY_MIRROR"
    elif [ -f "$f" ] && [ -s "$f" ]; then
      warn "$f 已存在且内容非空，未自动修改；请手动把 \"registry-mirrors\": [\"$DOCKER_REGISTRY_MIRROR\"] 合并进去后 systemctl restart docker"
    else
      mkdir -p /etc/docker
      printf '{\n  "registry-mirrors": ["%s"]\n}\n' "$DOCKER_REGISTRY_MIRROR" > "$f"
      systemctl restart docker
      log "已写入 $f 并重启 Docker"
    fi
  fi
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && ! id -nG "$SUDO_USER" | grep -qw docker; then
    usermod -aG docker "$SUDO_USER"
    log "已把 $SUDO_USER 加入 docker 组（重新登录 SSH 后可不加 sudo 使用 docker）"
  fi
fi

# ---------- 3. 代码 ----------
if [ -d "$APP_DIR/.git" ]; then
  log "代码已存在：$APP_DIR，尝试更新（git pull --ff-only）"
  if [ -n "$(git -C "$APP_DIR" status --porcelain --untracked-files=no)" ]; then
    warn "$APP_DIR 有本地修改，跳过 git pull（如需更新请先处理本地修改）"
  else
    if ! { git -C "$APP_DIR" fetch -q origin "$BRANCH" && git -C "$APP_DIR" checkout -q "$BRANCH" && git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"; }; then
      warn "git 更新失败（网络？），继续使用现有代码"
    fi
  fi
else
  log "克隆 $REPO_URL → $APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone -q --depth 1 -b "$BRANCH" "$REPO_URL" "$APP_DIR" || die "git clone 失败。国内访问 GitHub 不稳定时可重试，或 REPO_URL=<你的 Gitee 镜像> 再运行"
fi
cd "$APP_DIR"

# ---------- 4. .env（只在不存在时生成，绝不覆盖） ----------
if [ -f .env ]; then
  log ".env 已存在，保持不变"
else
  cp .env.example .env
  chmod 600 .env
  if [ "$CN_MIRROR" = "1" ]; then
    sed -i 's#^HF_ENDPOINT=$#HF_ENDPOINT=https://hf-mirror.com#' .env
  fi
  log "已生成 .env（权限 600）。如要用云端模型，编辑 .env 填 SILICONFLOW_API_KEY 等；对公网开放时务必填 KB_API_TOKEN"
fi
[ -f config.yaml ] || { cp config.example.yaml config.yaml; log "已生成 config.yaml（非敏感参数，可按需修改）"; }

# ---------- 5. 数据目录 ----------
mkdir -p data power_docs
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  chown -R "$SUDO_USER": "$APP_DIR"                 # 方便普通用户 scp 上传到 power_docs/、编辑 .env
fi
chown -R 1000:1000 data                             # 容器内以 uid 1000（app）运行，需要写 data/
n_docs=$(find power_docs -type f \( -iname '*.pdf' -o -iname '*.docx' \) 2>/dev/null | wc -l)
if [ "$n_docs" -eq 0 ] && [ ! -d data/chroma_db ]; then
  warn "power_docs/ 里还没有 PDF/DOCX（原件不在仓库里）。请用 scp 上传到 $APP_DIR/power_docs/，或按 docs/sources.md 下载；也可以先启动，之后在网页上传"
else
  log "power_docs/ 中有 ${n_docs} 个文档"
fi

# ---------- 6. 启动 ----------
if [ "$SKIP_DOCKER" = "1" ] || [ "$START" != "1" ]; then
  log "已准备好。启动：cd $APP_DIR && sh deploy/up.sh$( [ "$HOSTNET" = 1 ] && echo ' --hostnet')$( [ "$PROFILE" = milvus ] && echo ' milvus')"
  exit 0
fi
args=()
[ "$HOSTNET" = "1" ] && args+=(--hostnet)
[ "$PROFILE" = "milvus" ] && args+=(milvus)
log "启动：sh deploy/up.sh ${args[*]:-}（首次构建镜像 + 下载模型，约 10–30 分钟）"
sh deploy/up.sh "${args[@]}"
port=$(grep -E '^KB_API_PORT=[0-9]+' .env | cut -d= -f2 || true); port=${port:-8000}
wport=$(grep -E '^KB_WEB_PORT=[0-9]+' .env | cut -d= -f2 || true); wport=${wport:-8501}
log "等待 API 就绪（http://127.0.0.1:${port}/health，最多 40 分钟）…"
for _ in $(seq 240); do
  if curl -fsS "http://127.0.0.1:${port}/health" 2>/dev/null | grep -q '"models_loaded":true'; then
    log "API 就绪：$(curl -fsS "http://127.0.0.1:${port}/health")"
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    log "浏览器访问：http://${ip:-<服务器IP>}:${wport}   API 文档：http://${ip:-<服务器IP>}:${port}/docs"
    exit 0
  fi
  sleep 10
done
warn "40 分钟内 API 未就绪，请查看日志：docker compose logs --tail 100 api（常见原因见 docs/DEPLOY.md「常见故障排查」）"
exit 1
