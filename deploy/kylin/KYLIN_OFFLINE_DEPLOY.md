# PowerKB 银河麒麟 V10 离线部署指南（x86_64，无外网）

> 本目录即仓库内的麒麟部署包（`deploy/kylin/`）。一次真实的麒麟 V10 受限网络部署复盘与实测数据见 [docs/DEPLOY_KYLIN.md](../../docs/DEPLOY_KYLIN.md)。
> 在仓库里直接执行 `bash deploy/kylin/prepare_on_online_machine.sh` 时，`--src` 默认就是仓库根目录。

> 目标服务器：**Kylin Linux Advanced Server V10 (Halberd)**，x86_64，属于 V10 SP2 系列（glibc 2.28、内核 4.19），**不能访问互联网**。
> 鲲鹏 / 飞腾（aarch64）见 **附录 A**。
> 本文与脚本**没有在真实麒麟机器上跑过**。wheel 可用性已在联网机上用 `pip download --platform` 和便携 Python 3.11 安装测试过，见 §5.1。

## 0. 总览

| 路线 | 适合 | 目标机上要装 | 推荐度 |
|---|---|---|---|
| **A. Docker** | 首选。镜像自带 Debian 运行环境，**与麒麟的 glibc、Python 版本无关** | Docker 静态二进制 + compose 插件 | ★★★ |
| **B. 原生 Python** | 不允许装 Docker，或内核 / 安全策略不让容器运行 | 便携 Python 3.11 + 离线 wheel | ★★ |

整体流程：在**联网的 x86_64 Linux 机器**上运行 `prepare_on_online_machine.sh`，生成 `dist/`。用 U 盘或跳板机把它拷到麒麟服务器，校验 sha256 后运行 `install_docker_offline.sh` 或 `install_native_offline.sh`。

文件清单（本目录）：

| 文件 | 作用 |
|---|---|
| `prepare_on_online_machine.sh` | 联网机：打包代码、模型、镜像，下载 Docker 静态包、便携 Python 和 wheel，生成 SHA256SUMS |
| `install_docker_offline.sh` | 目标机，路线 A：安装 Docker（systemd）→ docker load → 解压 → 配置 SELinux 和 firewalld → compose up → 健康检查 |
| `install_native_offline.sh` | 目标机，路线 B：便携 Python + venv → pip 离线安装 → 解压 → systemd（api 和 web）→ 健康检查 |
| `powerkb.service` | 路线 A 开机自启单元（安装脚本会自动替换路径并 enable） |
| `docker-compose.offline.yml` | 沿用旧离线包的覆盖文件：不启动 ollama，本地或内网 LLM 地址可配置（需 compose ≥ 2.24） |

---

## 1. 目标机检查（先做，把结果记下来）

```bash
uname -m                                   # 应为 x86_64（aarch64 见附录 A）
cat /etc/os-release; cat /etc/kylin-release 2>/dev/null   # VERSION="V10 (Halberd)"；SP1=Tercel、SP2/SP3=Sword/Lance 等，以 kylin-release 为准
uname -r                                   # 4.19.90-xx.ky10.x86_64（SP2 典型）
ldd --version | head -1                    # glibc 2.28 —— 路线 B 的硬性下限
nproc; free -g                             # 建议 ≥ 8 核、≥ 16 GB 内存
df -h /opt /var/lib                        # /opt 需 ≥ 25 GB（A）或 ≥ 15 GB（B）；Docker 镜像落在 /var/lib/docker
getenforce; sestatus                       # SELinux：Enforcing / Permissive / Disabled
systemctl is-active firewalld; firewall-cmd --list-all
ss -lntp | grep -E ':(8000|8501)\b'        # 端口占用
rpm -q docker-engine podman 2>/dev/null    # 麒麟源可能自带旧版 docker-engine 18.09（太旧，compose v2 的 !override 等特性不可用）
grep -E 'overlay|cgroup' /proc/filesystems; stat -fc %T /sys/fs/cgroup   # 应有 overlay；cgroup 一般是 tmpfs（v1）
```

V10 SP2 的典型值：内核 4.19，cgroup v1，glibc 2.28，系统自带 Python 3.7（项目需要 ≥ 3.11，**不能用系统 Python**）。

## 2. 联网机准备资料包

要求：**x86_64** Linux（Ubuntu、CentOS、麒麟都可以），能访问 download.docker.com、github.com、pypi.org、download.pytorch.org，装有 Docker、python3 ≥ 3.8 和 curl。

### 2.1 获取代码、脚本和知识库数据

```bash
mkdir -p ~/powerkb_build && cd ~/powerkb_build

# ① 克隆代码（GitHub 访问慢可加代理：git -c http.proxy=http://127.0.0.1:7890 clone ...）
git clone https://github.com/lilongkui-feng/power-kb-rag.git power_kb
ls power_kb/requirements-docker.txt      # 能看到这个文件说明代码齐了

# ② 解压本部署包（power_kb_kylin.zip）
unzip power_kb_kylin.zip                 # 得到 ./power_kb_kylin/

# ③ 把知识库 13 个分卷（kb_data.tar.gz.p00…p12 + SHA256SUMS）放到 ./kbdata/
mkdir -p kbdata && cp /你存放分卷的位置/kb_data.tar.gz.p* /你存放分卷的位置/SHA256SUMS kbdata/
(cd kbdata && sha256sum -c SHA256SUMS)   # 13 行全部 OK
```

> 没有 git 也可以：在 GitHub 页面点 Code → Download ZIP，解压后把目录改名为 `power_kb`。

### 2.2 下载模型（联网机上没有模型缓存时）

```bash
cd ~/powerkb_build
python3 -m venv .dl && . .dl/bin/activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -U huggingface_hub
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 HF_HOME=$PWD/hf_cache
huggingface-cli download BAAI/bge-m3 --exclude "*.DS_Store" "imgs/*" "onnx/*"
huggingface-cli download BAAI/bge-reranker-v2-m3 --exclude "*.DS_Store"
deactivate
```

**hf-mirror 不通 / 系统只有 Python 3.7 时**（麒麟实测：`huggingface-cli download` 要 huggingface_hub ≥ 0.17，3.7 只能装到 0.16.4；新版 modelscope 要 Python ≥ 3.8）：

```bash
# 方案 1：老版 huggingface_hub（0.16.x）没有 download 子命令，用等效的 snapshot_download
HF_ENDPOINT=https://hf-mirror.com python3 -c "from huggingface_hub import snapshot_download as s; s('BAAI/bge-m3', cache_dir='/opt/hf_cache/hub', ignore_patterns=['onnx/*','imgs/*']); s('BAAI/bge-reranker-v2-m3', cache_dir='/opt/hf_cache/hub')"
# 方案 2：魔搭 ModelScope 直连（只用标准库，不装任何包；断点续传；直接写成 HF 缓存布局）
nohup python3 modelscope_to_hf_cache.py --cache /opt/hf_cache > /root/ms_dl.log 2>&1 &
tail -f /root/ms_dl.log
chmod -R a+rX /opt/hf_cache        # 容器内 uid 1000 要能读；不要把缓存放在 /root 下（/root 是 700）
```
动手前先逐个测连通性：`for u in https://hf-mirror.com https://www.modelscope.cn https://pypi.tuna.tsinghua.edu.cn https://download.docker.com https://registry-1.docker.io; do curl -sI -m 8 -o /dev/null -w "%{http_code} $u\n" $u; done`

### 2.3 打包

```bash
cd ~/powerkb_build
# 路线 A 需要镜像：联网机有 Docker 时脚本会用 power_kb/Dockerfile 现场构建 powerkb:latest
bash power_kb_kylin/prepare_on_online_machine.sh \
     --src $PWD/power_kb --out $PWD/dist \
     --hf-cache $PWD/hf_cache --kb-data $PWD/kbdata
#   --mode docker    只做路线 A（不下 Python 和 wheel）
#   --mode native    只做路线 B（联网机不需要 Docker）
#   --reuse-image    联网机上已有构建好的 powerkb:latest 时直接导出，不再构建
```

产物（约 10–12 GB）：

```text
dist/
├── ARCH                            x86_64
├── code/power_kb.tar.gz            代码（已排除索引、日志、.venv、.env）+ compose 文件 + .env.example
├── models/hf_models.tar            bge-m3 + bge-reranker-v2-m3（约 6.4 GB）
├── docker/docker-29.9.0.tgz        Docker 静态二进制（路线 A）
├── docker/docker-compose-linux-x86_64   compose 插件 v5.6.0
├── images/powerkb_image.tar.gz     docker save 的 powerkb:latest（约 1–2 GB 压缩后）
├── python/cpython-3.11.17+…-x86_64-unknown-linux-gnu-install_only.tar.gz   便携 Python（路线 B）
├── wheels/*.whl + requirements-native.txt   cp311 manylinux wheel（约 0.6 GB，含 torch CPU）
├── kb_data/kb_data.tar.gz.p00…p12 + SHA256SUMS   知识库（用户已有的 13 个分卷）
├── install_*.sh  powerkb.service  KYLIN_OFFLINE_DEPLOY.md
└── SHA256SUMS                      除 kb_data 外全部文件（kb_data 用自带的 SHA256SUMS）
```

说明：
- **镜像复用**：已有 `powerkb:latest` 是 linux/amd64，加 `--reuse-image` 时脚本会先确认镜像架构。镜像以 `python:3.12-slim`（Debian）为基础，容器内 glibc 与麒麟宿主机无关。也可以手动导出：`docker save powerkb:latest | gzip > images/powerkb_image.tar.gz`。
- 没有现成模型缓存时，先在联网机下载：`HF_HOME=/path/hf python -c "from sentence_transformers import SentenceTransformer,CrossEncoder;SentenceTransformer('BAAI/bge-m3');CrossEncoder('BAAI/bge-reranker-v2-m3')"`（国内可加 `HF_ENDPOINT=https://hf-mirror.com`）。
- 版本号可用 `--docker-version`、`--compose-version`、`--python-tag` 改，对应版本见 download.docker.com/linux/static/stable/x86_64/ 和 python-build-standalone 的 releases 页。

## 3. 传输与校验

**U 盘**：总量超过 4 GB，单个文件（hf_models.tar）也超过 4 GB，所以 **U 盘不能用 FAT32**。请用 exFAT 或 ext4。麒麟 V10 默认可能不带 exFAT 驱动，最稳妥的是 ext4 或 xfs。如果只能用 FAT32，先切分再合并：
```bash
split -b 3900M models/hf_models.tar models/hf_models.tar.part-   # 联网机
cat models/hf_models.tar.part-* > models/hf_models.tar           # 目标机，然后再 sha256sum -c
```
挂载：`sudo mount /dev/sdb1 /mnt/usb && rsync -a --info=progress2 /mnt/usb/dist/ /data/powerkb_dist/`。

**经跳板机**（办公网 → 跳板 → 隔离区服务器）：
```bash
# OpenSSH ≥ 7.3：直接用 ProxyJump，数据不落跳板机
rsync -avP -e "ssh -J user@jump" dist/ root@10.x.x.x:/data/powerkb_dist/
# 或 scp -J user@jump -r dist root@10.x.x.x:/data/powerkb_dist
# 跳板机不允许转发时：先 rsync 到跳板机，再从跳板机 rsync 到目标机（rsync -P 支持断点续传）
```

**校验（必须做）**：
```bash
cd /data/powerkb_dist
sha256sum -c SHA256SUMS                    # 全部 OK
(cd kb_data && grep -E 'p[0-9][0-9]$' SHA256SUMS | sha256sum -c -)   # 13 个分卷 OK
```
安装脚本会再校验一遍；kb_data 合并后还会按 SHA256SUMS 中 `kb_data.tar.gz` 那一行校验整包。

## 4. 路线 A：Docker（推荐）

```bash
cd /data/powerkb_dist
sudo bash install_docker_offline.sh            # 默认 /opt/powerkb，端口 8000/8501
#   --prefix /data/powerkb  --api-port 18000 --web-port 18501  --hostnet  --skip-docker  --no-firewall
```

脚本步骤：
1. **环境检查**：架构与资料包一致、内存、磁盘、sha256。
2. **安装 Docker 静态二进制**到 `/usr/local/bin`（dockerd、containerd、runc、docker-init 等），compose 插件放到 `/usr/local/lib/docker/cli-plugins/`。写入 `containerd.service`、`docker.socket`、`docker.service` 并 `enable --now`。如果系统已有麒麟源的旧 `docker-engine`，会先停掉，由新版接管（旧包不卸载）。
3. 写 `/etc/docker/daemon.json`（已有就不覆盖）：overlay2、`native.cgroupdriver=systemd`、日志轮转。加载 `overlay`、`br_netfilter`，开启 `ip_forward`。
4. `docker load` 镜像并核对架构。
5. 解压代码、模型、数据到 `/opt/powerkb/{app,hf,data}`；kb_data 先校验分卷，再合并、校验、解压。`chown 1000:1000`（容器内用户 uid 是 1000）。
6. **SELinux**：Enforcing 或 Permissive 时，给 data、hf、power_docs 打 `container_file_t` 标签（有 semanage 时持久化，否则用 chcon）。
7. 生成 `.env`：`COMPOSE_FILE=docker-compose.yml:docker-compose.offline.yml`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`LLM_FALLBACK=retrieval`、各目录路径。权限 600。
8. 安装 `powerkb.service` 并 enable，firewalld 放行 8501/8000，把 docker0 加入 trusted 区域。
9. `docker compose up -d`，等 `/health` 返回 `models_loaded:true`。

手动验证：
```bash
cd /opt/powerkb/app
docker compose ps                                        # api、web 都是 healthy
curl -s http://127.0.0.1:8000/health                     # models_loaded:true，vector_count 约 3500
curl -s -X POST http://127.0.0.1:8000/search -H 'Content-Type: application/json' \
     -d '{"query":"运行中SF6设备灭弧气室湿度限值","top_k":3}'
systemctl is-enabled docker powerkb; sudo reboot          # 重启后再查 docker compose ps
```
浏览器访问 `http://<服务器IP>:8501`，接口文档在 `:8000/docs`。

### 4.1 麒麟 V10 上 Docker 的注意点
- **内核 4.19 / cgroup v1**：Docker 29 仍支持 cgroup v1，但已标记弃用，`docker info` 会提示 warning，可以忽略。如果启动失败并提示 cgroup 相关错误，把 daemon.json 里的 `native.cgroupdriver` 改成 `cgroupfs` 后 `systemctl restart docker`。
- **overlay2**：需要 xfs 的 `ftype=1`（`xfs_info /var/lib | grep ftype`）。如果是 0，把 `data-root` 改到 ext4 分区或 ftype=1 的分区。
- **iptables**：麒麟 V10 使用 iptables-legacy（1.8.x nft 兼容层也能用）。dockerd 报 `iptables ... No chain/target` 时，执行 `modprobe ip_tables iptable_nat iptable_filter br_netfilter`，然后重启 docker。firewalld 重载后，Docker 的规则可能被清空，表现为容器端口不通，执行 `systemctl restart docker` 恢复。
- **SELinux**：静态包不带 container-selinux 策略。如果系统里没有 `container_file_t` 类型（`seinfo -t | grep container_file_t`），在 Enforcing 模式下挂载目录可能被拒。临时做法是 `setenforce 0` 验证，长期做法是装 container-selinux RPM（从麒麟 ISO 或内网源获取），或 `/etc/selinux/config` 改为 permissive（需安全负责人同意）。也可以给 daemon.json 加 `"selinux-enabled": false`（这是默认值），由宿主机标签控制。
- **bridge 网络不通**（web 连不上 api）：重装时加 `--hostnet`。
- **API 不需要对最终用户开放**：生产环境可以只放行 8501，或在 `.env` 设 `KB_BIND=127.0.0.1`，前面加 Nginx。注意 **Docker 发布的端口会绕过 firewalld 的 zone 规则**。

## 5. 路线 B：原生 Python（不装 Docker）

### 5.1 依赖与 wheel 可用性（已在联网机上实测）
- 麒麟自带 Python 3.7，太旧。本方案用 **python-build-standalone 便携 CPython 3.11.17**（`install_only` 包，解压即用，依赖 glibc ≥ 2.17）。备选：Miniconda 离线安装包（`Miniconda3-latest-Linux-x86_64.sh -b -p /opt/conda`，再 `conda create --offline`，比较麻烦），或者用源码编译 3.11（需要 gcc、openssl-devel、libffi-devel、zlib-devel、sqlite-devel 等 RPM 都能离线拿到，一般不推荐）。
- 依赖用 `requirements-docker.txt`（运行时精简版）+ `torch==2.14.1`（CPU 版）。2026-10-14 实测 `pip download --platform manylinux2014/2_17/2_24/2_27/2_28 --python-version 311 --only-binary=:all:` 的结果：

| 架构 | 结果 |
|---|---|
| x86_64 cp311 / cp312 | 除 **jieba** 外全部有 wheel，共 574 MB |
| aarch64 cp311 / cp312 | 除 **jieba** 外全部有 wheel，共 499 MB |

- **jieba 0.42.1 在 PyPI 上只有 sdist**。它是纯 Python 包，`prepare` 脚本会在联网机上用 `pip wheel` 构建成 `py3-none-any.whl`，目标机不需要编译。
- **以下 wheel 要求 glibc ≥ 2.28（manylinux_2_28）**：torch 2.14.1+cpu、onnxruntime 1.31.0、pymupdf 1.28.2、pyarrow（streamlit 依赖）、hf_xet（aarch64）。V10 的 glibc 正好是 2.28，**刚好满足**。如果某台机器的 glibc 更旧（`ldd --version` < 2.28），这些包无法安装，只能走路线 A。
- chromadb 1.5.9 是 abi3 manylinux2014 wheel（内含 Rust 编译的 hnswlib），faiss-cpu 1.15.1 是间接依赖，也都有 wheel。milvus-lite 和 pymilvus 只在 `VECTOR_STORE=milvus` 时使用，默认是 Chroma。
- 在联网机上用便携 Python 3.11 实测过：`pip install --no-index --find-links` 能装全，`import torch, onnxruntime, fitz, chromadb, jieba, sentence_transformers, streamlit, pymilvus, rapidocr` 都能导入（测试机是 Debian x86_64，glibc 更新，**不是**麒麟）。

### 5.2 安装
```bash
cd /data/powerkb_dist
sudo bash install_native_offline.sh            # 默认 /opt/powerkb，运行用户 powerkb，API 只监听 127.0.0.1:8000，web 0.0.0.0:8501
#   --api-host 0.0.0.0（需要对外提供 API 时）  --user xxx  --prefix …  --no-firewall
```
脚本步骤：检查 glibc ≥ 2.28 → 解压 Python 到 `/opt/powerkb/python` → 创建 venv `/opt/powerkb/venv` → `pip install --no-index --find-links wheels -r wheels/requirements-native.txt` → 导入自检 → 解压代码、模型、数据。和容器入口一样，把 `app/{output,chroma_db,bm25_index,emb_cache,uploads,milvus_db,logs}` 软链接到 `data/`。然后写 `.env`，内容包括 `HF_HOME=/opt/powerkb/hf`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`OCR_ENGINE=rapid`、`KB_API_HOST/PORT`、`KB_API_URL`、`LLM_FALLBACK=retrieval`，并删除空的 `HF_ENDPOINT=`。最后生成 **`powerkb-api.service`、`powerkb-web.service`** 并 enable，放行 firewalld 端口，启动并做健康检查。

验证：
```bash
systemctl status powerkb-api powerkb-web
journalctl -u powerkb-api -f                   # 首次加载模型 1–2 分钟
curl -s http://127.0.0.1:8000/health
```
说明：上传 PDF 入库时，原生模式使用 RapidOCR（onnxruntime）。PaddleOCR 没有打包。

## 6. 大模型（LLM）配置：完全内网

服务器访问不到 `api.siliconflow.cn`，默认的硅基流动 DeepSeek-V3 不能用。检索部分（向量 + BM25 + 重排）完全在本地运行，不受影响。生成回答有三种方案，都在 **`/opt/powerkb/app/.env`** 里配置：

| 方案 | 效果（同一 50 题评测集） | 说明 |
|---|---|---|
| ① 内网 OpenAI 兼容接口（单位自建的 DeepSeek、Qwen-72B、vLLM、One-API 网关等） | 取决于模型；72B 及以上预计接近云端 86% | **推荐**。需要接口地址、模型名，可能还需要 Key |
| ② 本机 Ollama 或 vLLM 跑 Qwen（只用 CPU） | qwen2.5:3b **56%**（云端 DeepSeek-V3 是 **86%**），约 19 s/题；7B 更慢（CPU 上可能 40–90 s/题） | 只适合演示或联调 |
| ③ 不接 LLM（仅检索） | 不生成答案，返回条款原文和出处 | 安装默认 `LLM_FALLBACK=retrieval` |

**① 内网接口**（provider 留空时走 `LLM_BASE_URL`，请求时 provider 为 `custom`）：
```ini
LLM_BASE_URL=http://<gateway-ip>:8001/v1     # 必须是 OpenAI 兼容的 /v1 根路径
LLM_MODEL=Qwen2.5-72B-Instruct              # 与服务端 /v1/models 返回的 id 一致
LLM_API_KEY=sk-xxx                          # 没有鉴权就留空
LLM_FALLBACK=retrieval                      # LLM 出错时退回仅检索
```
注意：
- 设了 `LLM_BASE_URL` 后，网页「LLM 提供方」下拉会出现 **「自定义网关（OpenAI 兼容）」** 并默认选中，下方显示网关地址；API 请求 `provider` 留空或填 `custom` 都走它。旧版需要用 override 把「本地」档改指网关，现在不需要了。
- 也可以把「本地」档指向别的地址：`.env` 设 `LOCAL_LLM_URL` / `LOCAL_LLM_MODEL`（compose 不再写死 ollama）。
- 不要写 `127.0.0.1`，bridge 网络下它指向容器自己。改用宿主机内网 IP，或用 `--hostnet` 安装。
- 先测试连通性：`curl -s $LLM_BASE_URL/models -H "Authorization: Bearer $LLM_API_KEY"`。

**② 本机 Ollama**：在联网机准备 Ollama Linux amd64 二进制包（github.com/ollama/ollama/releases 的 `ollama-linux-amd64.tgz`）或 `ollama/ollama` 镜像（`docker save`），再执行 `ollama pull qwen2.5:3b-instruct`，把 `~/.ollama/models` 打包拷过去。
- 原生运行：解压到 `/usr/local`，执行 `OLLAMA_MODELS=/opt/powerkb/ollama ollama serve`（建议写成 systemd 服务），然后设 `LOCAL_LLM_URL=http://127.0.0.1:11434/v1`、`LOCAL_LLM_MODEL=qwen2.5:3b-instruct`、`LLM_FALLBACK=local_then_retrieval`。
- Docker 运行：在 `.env` 设 `COMPOSE_PROFILES=ollama`、`OLLAMA_MODELS_DIR=/opt/powerkb/ollama`、`LOCAL_LLM_URL=http://ollama:11434/v1`。
- 项目会自动给本地模型使用 Prompt p1（3B 用 p2 时，库外拒答率会从 100% 降到 80%）。
- vLLM 的 CPU 后端需要自己构建，效果和速度都**没有验证**。有 GPU 机器时，按方案 ① 接入即可。

**修改后生效**：
- Docker：`cd /opt/powerkb/app && docker compose up -d`（会按新 .env 重建容器）
- 原生：`sudo systemctl restart powerkb-api powerkb-web`

验证：`curl -s http://127.0.0.1:8000/config` 查看各 provider 是否就绪。再提一个问题：
```bash
curl -s -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{"question":"运行中SF6设备灭弧气室的湿度限值是多少？"}'
```
返回的 `provider` 应为 custom（设了 LLM_BASE_URL）或 local；如果是 `llm_unavailable` 或仅检索结果，说明 LLM 没连上。换模型后建议用 `evaluate.py` 跑一遍评测集。

## 7. 日常运维
- 日志：`/opt/powerkb/data/logs/powerkb.log`；Docker 用 `docker compose logs -f api`；原生用 `journalctl -u powerkb-api`
- 备份：停掉 api 后执行 `tar czf backup.tgz -C /opt/powerkb data app/.env`（Docker 路线也可以用旧离线包的 backup.sh）
- 鉴权：多人使用时在 `.env` 设 `KB_API_TOKEN`（前后端共用）

## 8. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `sha256sum -c` FAILED | 拷贝损坏或 U 盘是 FAT32 被截断（文件超过 4 GB）。用 ext4 或 exFAT 重拷，或切分（§3） |
| `dockerd` 起不来：`failed to mount overlay` | `modprobe overlay`；xfs 的 ftype=0 时换 data-root（§4.1） |
| `iptables failed: ... No chain/target/match` | `modprobe ip_tables iptable_nat iptable_filter br_netfilter`，然后 `systemctl restart docker`；firewalld reload 后也要重启 docker |
| `cgroup` / `systemd cgroup driver` 报错 | daemon.json 改 `"native.cgroupdriver=cgroupfs"` |
| 已有 docker-engine 18.09 冲突 | 脚本会 disable 旧服务；`which -a docker` 确认用的是 `/usr/local/bin/docker`；也可以 `rpm -e docker-engine` |
| `docker compose` 报 `!override` / `!reset` 不支持 | compose 插件太旧（低于 2.24），用资料包里的 v5.6.0 |
| 容器 `Permission denied` 写 /data、/models | `chown -R 1000:1000 /opt/powerkb/{data,hf}`；SELinux：`ausearch -m avc -ts recent`，然后 `chcon -R -t container_file_t …`，或在 compose 卷后加 `:z` |
| SELinux 拒绝原生服务 | `ausearch -m avc -ts recent \| audit2why`；临时 `setenforce 0` 定位；`semanage fcontext` / `restorecon` 修正 /opt/powerkb 标签；必要时 `audit2allow -M powerkb && semodule -i powerkb.pp` |
| pip：`... is not a supported wheel on this platform` | 联网机下载时的 `--python-version` 或架构不对（必须是 cp311 + x86_64），或者 venv 用的不是 3.11 |
| pip：`No matching distribution`（离线） | wheels 目录缺包。在联网机把缺的包补进 `pip download` 再拷过来；只有 sdist 的纯 Python 包（如 jieba）用 `pip wheel --no-deps` 构建 |
| import 报 `GLIBC_2.28 not found` / `GLIBCXX_3.4.xx` | 系统库太旧，原生路线不可行，改用 Docker（路线 A） |
| onnxruntime / torch 报 `Illegal instruction` | CPU 太老、不支持 AVX（x86），或虚拟机没有透传 CPU 指令集。虚拟机 CPU 模式改为 host-passthrough |
| chromadb 报 sqlite 版本过低 | 便携 Python 自带新版 sqlite3，确认用的是 `/opt/powerkb/venv/bin/python`，不是系统 Python |
| api 卡在加载、日志访问 huggingface.co | 确认 `hf/hub/models--BAAI--bge-m3`、`models--BAAI--bge-reranker-v2-m3` 存在，`.env` 有 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，且**没有**空的 `HF_ENDPOINT=` |
| api `Killed` / OOM | `dmesg \| grep -i oom`；内存要 ≥ 16 GB，或加 swap；Docker 下调 `API_MEM_LIMIT` |
| `/health` 中 vector_count 为 0 | kb_data 没解压到 data/，或软链接、挂载路径不对：`ls -l /opt/powerkb/app/chroma_db`，`ls /opt/powerkb/data/chroma_db` |
| jieba 首次很慢 / 写缓存失败 | 词典缓存写在 /tmp；确认 /tmp 可写（运行用户有权限） |
| 浏览器打不开 8501 | `ss -lntp \| grep 8501`；`firewall-cmd --list-ports`；网络上的硬件防火墙；端口冲突时用 `--web-port` 重装 |
| 前端提示无法连接 API | 原生：`.env` 中的 `KB_API_URL` 与 API 端口一致；Docker：`docker compose exec web curl -s http://api:8000/health`，不通就用 `--hostnet` |

## 附录 A：aarch64（鲲鹏 920 / 飞腾 FT-2000+、S2500）
- 资料包必须在 **aarch64 联网机**上制作：`prepare_on_online_machine.sh --arch aarch64`。也可以在 x86 机器上交叉打包：wheel 用 `--platform manylinux…_aarch64` 下载，镜像用 `docker buildx build --platform linux/arm64 --load` 构建（需先 `docker run --privileged --rm tonistiigi/binfmt --install arm64`，QEMU 构建很慢，约 30–60 分钟）。**现有的 x86_64 powerkb:latest 不能复用。**
- Docker 静态包下载地址：`https://download.docker.com/linux/static/stable/aarch64/`；compose：`docker-compose-linux-aarch64`；Python：`cpython-3.11.17+20261009-aarch64-unknown-linux-gnu-install_only.tar.gz`。
- wheel 实测：除 jieba（需要构建，纯 Python）外，cp311 和 cp312 都有 aarch64 wheel。torch 用 `download.pytorch.org/whl/cpu` 上的 `torch-2.14.1+cpu-cp311-…manylinux_2_28_aarch64`，同样要求 glibc ≥ 2.28。
- 部分麒麟 aarch64 内核的页大小是 64K。Docker 镜像本身没有问题，但个别 wheel（如 jemalloc 相关）可能报错。目前依赖中没有发现，但**没有实测**。
- 飞腾 CPU 的推理速度明显慢于 x86，重排耗时可能达到数倍，建议调小 `RERANK_TOP_N`。

## 附录 B：未验证事项
- 所有脚本只通过了 `bash -n` 和 shellcheck（warning 级）检查，**没有在麒麟 V10 上实际运行**。
- 没有验证 Docker 29 + 麒麟 4.19 内核 + cgroup v1 的组合，也没有验证 container-selinux 的可用性。
- 原生路线只在 Debian x86_64 上用便携 Python 3.11 完成了离线安装和导入测试，没有启动服务、没有做 OCR、也没有在麒麟上运行。
- 本机 CPU 跑 7B 等模型的速度是估算值。
