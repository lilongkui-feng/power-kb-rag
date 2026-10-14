#!/usr/bin/env bash
# 受限网络（download.docker.com / Docker Hub 不通，清华镜像通）的麒麟 V10 / CentOS 8 系：从清华 docker-ce 仓库装 Docker
# 麒麟实测：docker-ce 26.1.3 + compose 2.27.0（x86_64，centos/8 仓库的 el8 包）
# 用法：sudo bash install_docker_tuna_rpm.sh [--download-only DIR] [--from DIR]
#   --download-only DIR  只把 rpm 下载到 DIR（可在联网机执行后拷到隔离区）
#   --from DIR           用 DIR 里已下载的 rpm 安装（离线）
# 说明：麒麟自带源的 docker-engine 18.09 太旧；依赖报错（container-selinux 等）时用 rpm --nodeps 强装（SELinux 关闭时无影响；
#       Enforcing 时请先从麒麟源装 container-selinux）。旧版 docker 19.03 会被 rpm -U 一并升级。
set -euo pipefail
MIRROR=${DOCKER_RPM_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/centos/8}
ARCH=$(uname -m)
PKGS=${DOCKER_RPMS:-"containerd.io-1.6.32-3.1.el8 docker-ce-cli-26.1.3-1.el8 docker-ce-26.1.3-1.el8 docker-ce-rootless-extras-26.1.3-1.el8 docker-buildx-plugin-0.14.0-1.el8 docker-compose-plugin-2.27.0-1.el8"}
DL=""; FROM=""
while [ $# -gt 0 ]; do case "$1" in --download-only) DL=$2; shift;; --from) FROM=$2; shift;; -h|--help) sed -n 2,9p "$0"; exit 0;; *) echo "未知参数 $1"; exit 2;; esac; shift; done
log(){ printf '\033[1;32m[docker-rpm]\033[0m %s\n' "$*"; }
D=${DL:-${FROM:-/tmp/docker_rpms}}; mkdir -p "$D"
if [ -z "$FROM" ]; then
  for p in $PKGS; do
    f="$p.$ARCH.rpm"; [ -s "$D/$f" ] && { log "已有 $f"; continue; }
    log "下载 $f"; curl -fL --retry 5 -C - -o "$D/$f" "$MIRROR/$ARCH/stable/Packages/$f"
  done
fi
[ -n "$DL" ] && { log "已下载到 $D"; exit 0; }
[ "$(id -u)" = 0 ] || { echo "请用 root 运行"; exit 1; }
systemctl stop docker docker.socket 2>/dev/null || true
log "rpm -Uvh（先尝试正常安装，依赖报错再 --nodeps）"
rpm -Uvh --replacepkgs "$D"/*.rpm || rpm -Uvh --replacepkgs --nodeps "$D"/*.rpm
systemctl daemon-reload; systemctl enable --now docker
docker version --format 'Docker {{.Server.Version}}'; docker compose version
log "下一步：/etc/docker/daemon.json 配 registry-mirrors（见 docs/DEPLOY_KYLIN.md），然后 systemctl restart docker"
