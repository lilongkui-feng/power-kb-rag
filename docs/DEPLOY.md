# 部署教程：在一台干净的云服务器上跑起 PowerKB

面向第一次部署的同学，按顺序照做即可。全程大约 30–60 分钟，大部分时间在等镜像构建和模型下载。

> 约定：下文 `<服务器IP>`、`kb.example.com` 换成你自己的；以 `$` 开头的是在**服务器**上执行的命令，以 `local$` 开头的是在**你自己电脑**上执行的命令。

---

## 0. 你会得到什么

```
浏览器 ──► (Nginx + HTTPS + 基本鉴权，可选) ──► web 容器 :8501（Streamlit 前端）
                                                   │
                                                   ▼
                                    api 容器 :8000（FastAPI：检索 / 重排 / 问答 / 入库）
                                       │                     │
                          ollama 容器 :11434（本地 qwen2.5:3b）  云端 LLM（可选：硅基流动 / DeepSeek / OpenAI / xAI）
数据卷：./data（索引、切块、上传文件、日志）  ./power_docs（PDF 原件，只读挂载）  hf_cache（bge-m3 / reranker 模型）
```

## 1. 服务器选型

| 项目 | 建议 | 说明 |
|---|---|---|
| 系统 | **Ubuntu 22.04 或 24.04 LTS**（64 位 x86） | `deploy/bootstrap.sh` 只在 Ubuntu 上验证 |
| CPU | **至少 8 核** | 没有 GPU 也能跑；重排（bge-reranker-v2-m3）在 CPU 上每次问答约 4–5 s（8 核实测），核数越少越慢 |
| 内存 | **至少 16 GB** | 实测常驻：API 约 1.6 GB（空闲）、问答时重排有峰值；ollama qwen2.5:3b 约 2.4 GB；**首次建索引**（向量化 3500+ 块）时更高 |
| 磁盘 | **建议 100 GB**（最低 60 GB） | 应用镜像约 2.8 GB、ollama 镜像约 5.6 GB、HF 模型缓存约 5–8 GB、ollama 模型约 2 GB、索引约 1 GB，加上 Docker 构建缓存（会越积越多，见 §9） |
| 带宽 | 按量即可 | 首次要下载镜像 + 模型（合计 10+ GB） |
| GPU | 不需要 | 镜像是 CPU 版 torch |

国内可选阿里云 ECS、腾讯云 CVM 等，选“通用型 8 核 16 GB”一档、Ubuntu 22.04/24.04 镜像即可。**价格以各云厂商官网当时报价为准**，本文不给价格；短期试用建议选**按量付费**，用完即停（§10）。

> 如果只用云端大模型（不跑本地 ollama），内存压力会小一些，但 bge-m3 + reranker 仍需要 CPU 和内存，16 GB 仍是稳妥选择。

## 2. 安全组 / 防火墙端口

在云控制台的“安全组”（阿里云 ECS → 安全组；腾讯云 CVM → 安全组）里添加**入方向**规则：

| 端口 | 用途 | 建议 |
|---|---|---|
| 22 | SSH | 必开；来源尽量限定为你自己的公网 IP |
| 80、443 | Nginx（HTTP/HTTPS） | 配了 §8 之后开 |
| 8501 | Streamlit 前端 | **只在测试阶段**临时开，配好 Nginx 后关掉 |
| 8000 | API | 一般不对公网开；需要被其他系统调用时再开，并设置 `KB_API_TOKEN` |

⚠ **Docker 发布的端口会绕过 ufw**：即使 `ufw deny 8000`，容器端口仍然可以从公网访问。要真正只给本机 Nginx 用，在 `.env` 里设 `KB_BIND=127.0.0.1`（§8 会用到）。11434（ollama）在 compose 里没有映射到宿主机，不用管。

## 3. SSH 登录

```bash
local$ ssh ubuntu@<服务器IP>          # 腾讯云 Ubuntu 默认用户 ubuntu；阿里云多为 root（以控制台说明为准）
local$ ssh -i ~/.ssh/xxx.pem ubuntu@<服务器IP>   # 用密钥对登录时
```

首次登录后建议先更新系统：

```bash
$ sudo apt-get update && sudo apt-get -y upgrade
```

内存只有 16 GB 时，建议加 4–8 GB swap 防止首次建索引时 OOM：

```bash
$ sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
$ echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 4. 一键准备环境（推荐）：`deploy/bootstrap.sh`

脚本做的事：检查 CPU/内存 → 安装 git/curl → 安装 Docker（官方 get.docker.com 脚本，国内默认用阿里云镜像源）→ 拉代码到 `/opt/power-kb-rag` → 生成 `.env`（权限 600，**已存在则不覆盖**）和 `config.yaml` → 建 `data/`、`power_docs/` → `sh deploy/up.sh` 启动并等待 `/health`。**可以重复运行**（已装的跳过、已有的 .env 不动、代码有本地修改时不 pull）。

第一次建议先**只准备、不启动**，等放好 PDF、填好 .env 再启动：

```bash
$ curl -fsSL https://raw.githubusercontent.com/lilongkui-feng/power-kb-rag/main/deploy/bootstrap.sh -o bootstrap.sh
$ sudo START=0 bash bootstrap.sh
```

> raw.githubusercontent.com 在国内偶尔连不上：可以本地下载后 `scp bootstrap.sh ubuntu@<服务器IP>:~`，或先 `git clone` 再运行 `sudo START=0 bash deploy/bootstrap.sh`（APP_DIR 默认 /opt/power-kb-rag，如果你 clone 在别处，加 `APP_DIR=$(pwd)`）。

常用参数（写在 `bash` 前面）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `CN_MIRROR` | `1` | 1 = 阿里云镜像源装 Docker，并在新生成的 .env 中写 `HF_ENDPOINT=https://hf-mirror.com`；海外服务器设 0 |
| `DOCKER_REGISTRY_MIRROR` | 空 | Docker Hub 镜像加速地址（见 §4.2） |
| `APP_DIR` | `/opt/power-kb-rag` | 安装目录 |
| `PROFILE` | `chroma` | `milvus` = 同时启动 Milvus Standalone |
| `HOSTNET` | `0` | 1 = 宿主机网络模式（§9“bridge 网络问题”） |
| `START` | `1` | 0 = 只准备环境不启动 |
| `SKIP_DOCKER` | `0` | 1 = 不装/不动 Docker（测试用） |
| `REPO_URL` / `BRANCH` | GitHub 仓库 / `main` | 用自己的 fork 或国内镜像仓库时修改 |

脚本结束后，重新登录一次 SSH（脚本把你的用户加进了 docker 组，重新登录后 `docker` 命令不用加 sudo）。

### 4.1 手动安装 Docker（不想用脚本时）

```bash
$ curl -fsSL https://get.docker.com -o get-docker.sh
$ sudo sh get-docker.sh                      # 海外服务器
$ sudo sh get-docker.sh --mirror Aliyun      # 国内服务器：从阿里云镜像源安装
$ sudo systemctl enable --now docker
$ sudo usermod -aG docker $USER && exit      # 重新登录生效
$ docker --version && docker compose version # 两条都能输出版本号即可
```

### 4.2 国内拉镜像慢 / 失败：配置镜像加速

国内直连 Docker Hub 经常超时。在云厂商控制台获取镜像加速地址（阿里云：容器镜像服务 ACR → 镜像工具 → 镜像加速器，会给你一个专属地址；腾讯云 CVM 可参考其文档提供的加速地址），然后：

```bash
$ sudo DOCKER_REGISTRY_MIRROR=https://<你的加速地址> START=0 bash bootstrap.sh   # 脚本会写 /etc/docker/daemon.json 并重启 Docker
# 或手动：
$ echo '{ "registry-mirrors": ["https://<你的加速地址>"] }' | sudo tee /etc/docker/daemon.json
$ sudo systemctl restart docker && docker info | grep -A1 "Registry Mirrors"
```

> daemon.json 已经有内容时脚本不会改它，会提示你手动合并。

## 5. 配置 `.env` 与 `config.yaml`

```bash
$ cd /opt/power-kb-rag
$ nano .env
```

**密钥只放 `.env`（或环境变量），绝不要写进 config.yaml**——写了服务会直接报 `ConfigError` 拒绝启动。

| 变量 | 什么时候填 |
|---|---|
| `SILICONFLOW_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY` | 想用对应云端大模型时（不填也能用本地 ollama） |
| `KB_API_TOKEN` | **对公网开放 8000 端口时必须填**（任意长随机串，如 `openssl rand -hex 24` 的输出）；web 容器读的是同一个 .env，会自动带上 |
| `HF_ENDPOINT` | 国内服务器：`https://hf-mirror.com`（bootstrap 已自动写入） |
| `KB_BIND` | 配 Nginx 后设 `127.0.0.1` |
| `LLM_FALLBACK` | 云端失败时的降级：`retrieval`（默认，返回仅检索结果）/ `local`（改用本地模型）/ `local_then_retrieval` / `none`（直接报错） |
| `PIP_MIRROR` | 国内构建镜像慢时填 `https://mirrors.aliyun.com/pypi/simple/` |
| `OLLAMA_MODEL` | 默认 `qwen2.5:3b-instruct` |
| `KB_API_PORT` / `KB_WEB_PORT` | 端口冲突时修改（默认 8000 / 8501） |

非敏感参数（检索/重排/切分/日志格式等）在 `config.yaml`（由 config.example.yaml 复制而来，里面每项都有注释）。**优先级：环境变量 > .env > config.yaml > 代码默认值**。改完可以校验：

```bash
$ docker compose run --rm --no-deps api python config.py      # 打印生效配置（密钥只显示“已设置/未设置”）；镜像构建好之后可用
```

## 6. 准备数据（PDF 原件不在仓库里）

仓库里只有代码，**不含任何标准/说明书原件**（版权原因）。原件放到 `power_docs/`（可以有子目录），api 容器首次启动时发现索引为空会自动解析 + 建索引。

**方式 A：从自己电脑上传**

```bash
local$ scp -r ./power_docs/* ubuntu@<服务器IP>:/opt/power-kb-rag/power_docs/
local$ rsync -avP ./power_docs/ ubuntu@<服务器IP>:/opt/power-kb-rag/power_docs/   # 文件多时更稳，可断点续传
```

**方式 B：在服务器上按 `docs/sources.md` 下载**

`docs/sources.md` 列出了全部文档的来源页面（行业标准信息服务平台、厂商官网等）。能直接下载的 PDF 用 wget：

```bash
$ cd /opt/power-kb-rag/power_docs
$ wget -O "DL_T_xxx.pdf" "<sources.md 中该文档的 PDF 链接>"
```

部分平台只能在线阅读或需要登录，这类文档请在本地浏览器下载后用方式 A 上传。

**方式 C：先不放原件**——照常启动，`/health` 会显示 `load_error`（索引为空）；之后在网页侧栏上传 PDF/DOCX 入库也可以。

**方式 D：迁移已有索引**——在一台已经建好索引的机器上，把它的 `data/` 目录整体拷过来（`rsync -avP data/ ubuntu@<服务器IP>:/opt/power-kb-rag/data/`），可跳过首次建索引。`data/` 里的切块含原文，**不要公开分发**。

> 首次建索引在 8 核 CPU 上约 10–30 分钟（含模型下载）；镜像里的 OCR 用 RapidOCR，扫描件表格识别不如宿主机 PaddleOCR 环境（已知限制，见 README）。

## 7. 启动与验证

### 7.1 启动

```bash
$ cd /opt/power-kb-rag
$ sh deploy/up.sh              # = docker compose up -d --build（api + web + ollama，向量库 Chroma）
$ sh deploy/up.sh milvus       # 可选：改用 Milvus Standalone（多起 etcd + minio + milvus 三个容器）
$ make up                      # 装了 make 时等价于 sh deploy/up.sh
```

首次会：构建 powerkb 镜像（几分钟到十几分钟）→ ollama-pull 拉 qwen2.5:3b（约 2 GB）→ api 下载 bge-m3 / bge-reranker-v2-m3（约 4–5 GB，`HF_ENDPOINT` 镜像加速）→ 建索引 → 健康检查通过后 web 才启动。

看进度：

```bash
$ docker compose ps                      # STATUS 出现 (healthy) 即就绪
$ docker compose logs -f api             # 跟踪 api 日志（Ctrl+C 退出跟踪，不会停服务）
$ docker compose logs ollama-pull        # 本地模型下载情况
```

### 7.2 验证

```bash
$ curl -s http://127.0.0.1:8000/health
# 期望："status":"ok"、"models_loaded":true、vector_count 与 bm25_docs 相等且 > 0

$ curl -s -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' \
    -d '{"question":"运行中SF6设备灭弧气室的湿度限值是多少？","provider":"local"}'
# 期望：answer 中有“300 μL/L”，citations 非空

$ curl -s http://127.0.0.1:8000/jobs/nope
# 期望统一错误体：{"error":{"code":"not_found","message":"...","detail":null,"request_id":"..."}}
```

开了 `KB_API_TOKEN` 时，除 `/health` 外都要加 `-H "Authorization: Bearer <你的token>"`。

浏览器打开 `http://<服务器IP>:8501`（需安全组临时放行 8501），侧栏选 provider、提问即可；API 文档在 `http://<服务器IP>:8000/docs`（需放行 8000）。

## 8. Nginx 反向代理 + HTTPS + 基本鉴权

目标：公网只开 80/443，浏览器 → Nginx（HTTPS + 用户名密码）→ 本机 8501。

**8.1 只让本机访问容器端口**

```bash
$ cd /opt/power-kb-rag
$ grep -q '^KB_BIND=' .env && sed -i 's/^KB_BIND=.*/KB_BIND=127.0.0.1/' .env || echo 'KB_BIND=127.0.0.1' >> .env
$ sh deploy/up.sh              # 重新创建容器使端口绑定生效
$ ss -lntp | grep -E ':8000|:8501'   # 应显示 127.0.0.1:8000 / 127.0.0.1:8501
```

**8.2 安装 Nginx 与密码工具，创建登录账号**

```bash
$ sudo apt-get install -y nginx apache2-utils
$ sudo htpasswd -c /etc/nginx/.htpasswd admin       # 按提示输入密码；再加用户时去掉 -c
```

**8.3 站点配置**（Streamlit 需要 WebSocket，下面的 Upgrade 头不能少）

```bash
$ sudo tee /etc/nginx/sites-available/powerkb >/dev/null <<'NGINX'
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
server {
    listen 80;
    server_name kb.example.com;            # 换成你的域名；没有域名时写 _
    client_max_body_size 60m;              # 与 KB_MAX_UPLOAD_MB（默认 50）匹配
    auth_basic "PowerKB";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;           # 长回答 / 流式输出
    }
    # 可选：对外暴露 API（仍建议同时设置 KB_API_TOKEN）
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Request-ID $request_id;
        proxy_buffering off;               # SSE 流式 /ask/stream
        proxy_read_timeout 600s;
    }
}
NGINX
$ sudo ln -sf /etc/nginx/sites-available/powerkb /etc/nginx/sites-enabled/powerkb
$ sudo rm -f /etc/nginx/sites-enabled/default
$ sudo nginx -t && sudo systemctl reload nginx
```

此时 `http://<服务器IP>/` 应弹出用户名密码框，登录后看到界面。

**8.4 HTTPS（需要域名）**

先在域名 DNS 里加一条 A 记录指向服务器 IP。⚠ 国内（中国大陆）服务器用域名对外提供网站服务需要先完成 ICP 备案，未备案时 80/443 可能被云厂商拦截，请按云厂商的备案指引办理。

```bash
$ sudo apt-get install -y certbot python3-certbot-nginx
$ sudo certbot --nginx -d kb.example.com          # 按提示填邮箱、同意条款；自动改写 Nginx 配置并开启 HTTP→HTTPS 跳转
$ sudo certbot renew --dry-run                    # 验证自动续期（certbot 安装时已自带定时任务）
```

完成后访问 `https://kb.example.com`，并在安全组里关掉 8501/8000。

> 没有域名时只能用 HTTP + 基本鉴权（密码明文传输），仅适合临时演示。

## 9. 常见故障排查

先看这三样：`docker compose ps`、`docker compose logs --tail 200 api`、`curl -s 127.0.0.1:8000/health`。应用日志另外写在 `data/logs/powerkb.log`（自动轮转，已对 key/Authorization 打码；默认不记录问句原文）。每个错误响应都带 `request_id`，用它在日志里定位：

```bash
$ grep "<request_id>" data/logs/powerkb.log
$ LOG_FORMAT=json sh deploy/up.sh        # 想要 JSON 日志（接 ELK/Loki）时；或写进 .env
```

| 现象 | 可能原因 | 处理 |
|---|---|---|
| api 容器反复重启，`docker compose logs api` 末尾无报错；`dmesg \| grep -i kill` 有 `Out of memory` | 内存不足（多发生在首次建索引） | 加 swap（§3）；或换 16 GB+ 机型；暂时不用本地模型时 `docker compose stop ollama` |
| `/health` 中 `load_error` 含 `huggingface` / `Connection` / `MaxRetryError` | 模型下载失败 | 确认 .env 有 `HF_ENDPOINT=https://hf-mirror.com` 后 `docker compose restart api`；或在能联网的机器上下载好 `BAAI/bge-m3`、`BAAI/bge-reranker-v2-m3` 的 HF 缓存，拷到 hf_cache 卷 |
| `/health` 中 `load_error` 提示集合不存在 / 索引为空 | power_docs 为空，没建索引 | 按 §6 放原件后 `docker compose restart api`（会自动建索引），或用网页上传 |
| 回答显示“⚠ 大模型暂时不可用…以下是检索到的资料” | LLM 调用失败，已按 `LLM_FALLBACK=retrieval` 降级 | 看日志 `llm.failed code=...`：`llm_unavailable`（ollama 没起来 / 模型没拉下来：`docker compose logs ollama-pull`）、`llm_auth_failed`（云端 key 错）、`llm_rate_limited`（限流，稍后重试）、`llm_timeout`（调大 `LLM_TIMEOUT`） |
| `ollama-pull` 报错退出 | 拉取 qwen 模型失败（网络） | `docker compose up -d ollama-pull` 重试；实在拉不下来可只用云端模型（填 key，侧栏选 siliconflow） |
| 浏览器打不开 `<IP>:8501` | 安全组没放行 / 设了 `KB_BIND=127.0.0.1` / web 还没启动（等 api healthy） | `ss -lntp \| grep 8501` 看监听地址；`docker compose ps` 看 web 状态 |
| `port is already allocated` | 端口被占用 | `.env` 里改 `KB_API_PORT` / `KB_WEB_PORT` 后重新 `sh deploy/up.sh` |
| 容器之间连不上（api 日志 `llm_unavailable`，ollama 正常）、拉模型时 DNS 超时 | Docker bridge 网络异常（部分精简内核 / 安全加固 / 沙箱环境） | 改用宿主机网络：`sh deploy/up.sh --hostnet`（或 `sudo HOSTNET=1 bash bootstrap.sh`）；此时端口直接占用宿主机，`KB_BIND` 不生效，注意安全组 |
| 网页提示“前端与 API 的 KB_API_TOKEN 不一致” | 改了 token 但只重启了 api | `docker compose up -d --force-recreate api web` |
| 服务启动即退出，日志 `ConfigError: config.yaml 中不允许出现密钥类配置` | 把 key 写进了 config.yaml | 挪到 .env |
| 磁盘被占满 | Docker 构建缓存 / 旧镜像越积越多 | `docker system df` 查看；`docker builder prune -af` 和 `docker image prune -f` 清理（不会删除数据卷） |
| 构建镜像时 pip 下载很慢 / 超时 | PyPI 访问慢 | `.env` 里设 `PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/` 后重新 `sh deploy/up.sh` |

## 10. 更新、备份与成本控制

**更新代码**

```bash
$ cd /opt/power-kb-rag
$ git pull --ff-only            # 或重新运行 sudo bash bootstrap.sh（幂等，会自动 pull 并重启）
$ sh deploy/up.sh               # 重新构建并滚动重启；数据卷不受影响
```

**备份**（索引、上传文件、日志都在 `data/`；原件在 `power_docs/`；配置在 `.env`、`config.yaml`）

```bash
$ cd /opt/power-kb-rag
$ docker compose stop api                      # 停写，保证索引一致
$ sudo tar czf ~/powerkb-backup-$(date +%F).tgz data .env config.yaml
$ docker compose start api
local$ scp ubuntu@<服务器IP>:~/powerkb-backup-*.tgz .   # 拉回本地保存（含 key 和原文切块，妥善保管）
```

恢复：解压到新服务器的 `/opt/power-kb-rag/` 后 `sh deploy/up.sh`。模型缓存（hf_cache 卷）和 ollama 模型不用备份，丢了会自动重新下载。

**成本控制**

- 不用时停服务：`sh deploy/up.sh down`（容器停止删除，数据卷与 data/ 保留；下次 `sh deploy/up.sh` 秒级恢复，不用重新建索引）。
- 长时间不用：在云控制台**关机**。按量付费实例关机后，部分厂商对计算资源停止计费（如“停机不收费”模式），但**云盘和公网 IP 通常仍收费**，具体以厂商计费规则为准。
- 不再使用：先做好备份，再在控制台**释放实例**（并检查云盘、快照、弹性公网 IP 是否一起释放）。
- 云端大模型按 token 计费：日志里每次问答都有 `prompt_tokens / completion_tokens`（`grep rag.answer data/logs/powerkb.log`），可据此估算用量；只想零 API 成本时全用 `local`。
