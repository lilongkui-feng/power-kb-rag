#!/usr/bin/env bash
# 在【联网、与目标服务器同架构】的 Linux 机器上运行，生成麒麟 V10 离线资料包 dist/
# 用法：bash prepare_on_online_machine.sh [选项]
#   --src DIR          power_kb 代码目录（默认：本脚本在仓库 deploy/kylin/ 下时取仓库根；否则当前目录是 power_kb 时取当前目录；再否则 ./power_kb）
#   --out DIR          输出目录（默认 ./dist）
#   --arch ARCH        目标架构 x86_64|aarch64（默认本机 uname -m）
#   --mode M           docker | native | both（默认 both）
#   --hf-cache DIR     已下载 bge-m3 / bge-reranker-v2-m3 的 HF 缓存（含 hub/，默认 ~/.cache/huggingface）
#   --reuse-image      不重新构建，直接 docker save 本机已有 powerkb:latest（必须与目标同架构）
#   --kb-data DIR      kb_data.tar.gz 分卷 + SHA256SUMS 所在目录（可选，一并拷入 dist/kb_data/）
#   --docker-source S  static（默认，download.docker.com 静态包）| tuna（清华 docker-ce el8 rpm，download.docker.com 不通时）
#   --docker-version V（默认 29.9.0）  --compose-version V（默认 v5.6.0）  --python-tag T（默认 3.11.17+20261009）
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -f "$HERE/../../requirements-docker.txt" ]; then SRC=$(cd "$HERE/../.." && pwd)
elif [ -f "$PWD/requirements-docker.txt" ]; then SRC=$PWD
else SRC=$PWD/power_kb; fi
DSRC=static; OUT=$PWD/dist; ARCH=$(uname -m); MODE=both; HFC=${HF_HOME:-$HOME/.cache/huggingface}
REUSE=0; KBD=""; DOCKER_VER=29.9.0; COMPOSE_VER=v5.6.0; PY_TAG=3.11.17+20261009; TORCH_VER=2.14.1
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC=$2; shift;; --out) OUT=$2; shift;; --arch) ARCH=$2; shift;; --mode) MODE=$2; shift;;
  --hf-cache) HFC=$2; shift;; --reuse-image) REUSE=1;; --kb-data) KBD=$2; shift;;
  --docker-source) DSRC=$2; shift;; --docker-version) DOCKER_VER=$2; shift;; --compose-version) COMPOSE_VER=$2; shift;; --python-tag) PY_TAG=$2; shift;;
  -h|--help) sed -n 2,14p "$0"; exit 0;; *) echo "未知参数 $1"; exit 2;; esac; shift; done
log(){ printf '\033[1;32m[prepare]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[prepare] 错误：\033[0m%s\n' "$*" >&2; exit 1; }
case "$ARCH" in x86_64|amd64) ARCH=x86_64; PLAT=linux/amd64;; aarch64|arm64) ARCH=aarch64; PLAT=linux/arm64;; *) die "不支持的架构 $ARCH";; esac
[ -f "$SRC/requirements-docker.txt" ] || die "$SRC 不是 power_kb 目录（缺 requirements-docker.txt），用 --src 指定代码目录"
SRC=$(cd "$SRC" && pwd); log "代码目录：$SRC"
mkdir -p "$OUT"; cd "$OUT"; OUT=$PWD
dl(){ [ -s "$2" ] && { log "已存在 $2，跳过下载"; return; }; curl -fL --retry 3 -o "$2.tmp" "$1" && mv "$2.tmp" "$2"; }

# ---- 1. 代码（排除日志、索引、虚拟环境等大目录）----
log "打包代码 → code/power_kb.tar.gz"
mkdir -p code
tar -C "$(dirname "$SRC")" -czf code/power_kb.tar.gz \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='*.log' --exclude='.env' \
  --exclude="$(basename "$SRC")/chroma_db" --exclude="$(basename "$SRC")/milvus_db" --exclude="$(basename "$SRC")/bm25_index" \
  --exclude="$(basename "$SRC")/emb_cache" --exclude="$(basename "$SRC")/data" --exclude="$(basename "$SRC")/uploads" \
  --exclude="$(basename "$SRC")/paddle" --exclude="$(basename "$SRC")/logs" "$(basename "$SRC")"

# ---- 2. HF 模型缓存 ----
[ -d "$HFC/hub/models--BAAI--bge-m3" ] && [ -d "$HFC/hub/models--BAAI--bge-reranker-v2-m3" ] || die "$HFC/hub 下缺少 bge-m3 / bge-reranker-v2-m3。hf 不通时：python3 $HERE/modelscope_to_hf_cache.py --cache $HFC（魔搭直连，标准库，支持续传）；否则在联网机执行：HF_HOME=$HFC python -c \"from sentence_transformers import SentenceTransformer,CrossEncoder;SentenceTransformer('BAAI/bge-m3');CrossEncoder('BAAI/bge-reranker-v2-m3')\""
mkdir -p models
[ -s models/hf_models.tar ] || { log "打包模型 → models/hf_models.tar（约 6.4 GB）"; tar -C "$HFC" -cf models/hf_models.tar hub/models--BAAI--bge-m3 hub/models--BAAI--bge-reranker-v2-m3; }

# ---- 3. Docker 路线 ----
if [ "$MODE" != native ]; then
  mkdir -p docker images
  log "下载 Docker 静态包 $DOCKER_VER ($ARCH) 与 compose 插件 $COMPOSE_VER"
  if [ "$DSRC" = tuna ]; then
    log "从清华镜像下载 docker-ce rpm（el8）→ docker/rpms/"
    bash "$HERE/install_docker_tuna_rpm.sh" --download-only "$OUT/docker/rpms"
  else
    dl "https://download.docker.com/linux/static/stable/$ARCH/docker-$DOCKER_VER.tgz" "docker/docker-$DOCKER_VER.tgz"
    dl "https://github.com/docker/compose/releases/download/$COMPOSE_VER/docker-compose-linux-$ARCH" "docker/docker-compose-linux-$ARCH"
  fi
  command -v docker >/dev/null || die "本机没有 docker，无法导出镜像（或用 --mode native）"
  if [ "$REUSE" = 1 ]; then
    IA=$(docker image inspect -f '{{.Architecture}}' powerkb:latest) || die "本机没有 powerkb:latest"
    [ "$IA" = "${PLAT#linux/}" ] || die "已有 powerkb:latest 架构为 $IA，与目标 ${PLAT#linux/} 不符，去掉 --reuse-image 重新构建"
  else
    log "构建 powerkb:latest（$PLAT）"
    if [ "$PLAT" = "linux/$(docker version -f '{{.Server.Arch}}')" ]; then
      docker build -t powerkb:latest "$SRC"
    else
      log "跨架构构建（需 qemu-user-static / binfmt，速度慢）：docker run --privileged --rm tonistiigi/binfmt --install all"
      docker buildx build --platform "$PLAT" -t powerkb:latest --load "$SRC"
    fi
  fi
  log "docker save → images/powerkb_image.tar.gz"
  docker save powerkb:latest | gzip > images/powerkb_image.tar.gz
  cp "$SRC/docker-compose.yml" "$SRC/docker-compose.hostnet.yml" "$SRC/.env.example" code/
  [ -f "$HERE/docker-compose.offline.yml" ] && cp "$HERE/docker-compose.offline.yml" code/
fi

# ---- 4. 原生路线：便携 Python + wheel ----
if [ "$MODE" != docker ]; then
  mkdir -p python wheels
  PYF="cpython-$PY_TAG-$ARCH-unknown-linux-gnu-install_only.tar.gz"
  log "下载便携 Python $PYF"
  dl "https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG#*+}/${PYF//+/%2B}" "python/$PYF"
  # 用本机 python3 创建临时 venv 来跑 pip download（--platform 方式与本机 Python 版本无关）
  python3 -m venv "$OUT/.pipenv" && "$OUT/.pipenv/bin/pip" -q install -U pip wheel
  PIP="$OUT/.pipenv/bin/pip"
  grep -v '^jieba' "$SRC/requirements-docker.txt" > wheels/requirements-native.txt
  echo "torch==$TORCH_VER" >> wheels/requirements-native.txt
  log "pip download 目标 cp311 / manylinux（glibc ≤ 2.28）$ARCH wheel …"
  "$PIP" download -r wheels/requirements-native.txt pip setuptools wheel -d wheels \
    --platform manylinux2014_$ARCH --platform manylinux_2_17_$ARCH --platform manylinux_2_24_$ARCH \
    --platform manylinux_2_27_$ARCH --platform manylinux_2_28_$ARCH \
    --python-version 311 --implementation cp --only-binary=:all: \
    --extra-index-url https://download.pytorch.org/whl/cpu
  # jieba 只有源码包（纯 Python），在这里构建成 py3-none-any wheel
  log "构建 jieba==0.42.1 wheel（PyPI 只有 sdist）"
  "$PIP" wheel --no-deps jieba==0.42.1 -w wheels
  echo "jieba==0.42.1" >> wheels/requirements-native.txt
  rm -rf "$OUT/.pipenv"
fi

# ---- 5. 知识库数据、安装脚本 ----
if [ -n "$KBD" ]; then mkdir -p kb_data; cp "$KBD"/kb_data.tar.gz.p[0-9][0-9] "$KBD"/SHA256SUMS kb_data/; fi
for f in install_docker_offline.sh install_docker_tuna_rpm.sh install_native_offline.sh powerkb.service modelscope_to_hf_cache.py KYLIN_OFFLINE_DEPLOY.md; do
  [ -f "$HERE/$f" ] && cp "$HERE/$f" "$OUT/"; done
echo "$ARCH" > ARCH
log "生成 SHA256SUMS"
find . -type f ! -name SHA256SUMS ! -path './kb_data/*' ! -name '*.tmp' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
du -sh "$OUT"/*; log "完成：把 $OUT 整个目录拷到目标服务器，先执行 sha256sum -c SHA256SUMS"
