# PowerKB · 电力设备运维知识库 RAG

> 面向变电运维场景：把电力行业标准（DL/T）、厂商说明书、扫描件“读懂”，回答时给出**可点开核对的出处**；资料里没有就拒答。

![Python](https://img.shields.io/badge/Python-3.13-blue)
![Embedding](https://img.shields.io/badge/Embedding-bge--m3-orange)
![Reranker](https://img.shields.io/badge/Reranker-bge--reranker--v2--m3-orange)
![VectorDB](https://img.shields.io/badge/VectorDB-Chroma-green)
![UI](https://img.shields.io/badge/UI-Streamlit-red)
![LLM](https://img.shields.io/badge/LLM-DeepSeek--V3%20%7C%20Qwen2.5-purple)
![License](https://img.shields.io/badge/License-MIT%20(code%20only)-lightgrey)

## 核心成果

数字均出自 `output/` 下的评测结果文件，统计口径见[评测方法](#评测方法)。

| 维度 | 结果 | 来源 |
|---|---|---|
| 知识库 | 19 份文档（DL/T 标准、南网文件、ABB/施耐德/西门子/平高/正泰手册，含 1 份扫描件），754 页 → 3499 个检索块，抽出 175 张结构化表格 | `output/tables_stats.md` |
| 检索 | 44 题评测：MRR **0.658 → 0.911**，Hit@1 **50% → 84%**（定长切分纯向量 → 章节切分 + BM25 混合 + 重排） | `output/rerank_results.md` |
| 回答 | 139 题新评测集，DeepSeek-V3：正确 **85%**，综合得分 0.91，引用命中标注块 94% | `output/version_scores.md` |
| 表格题 | 本地 3B 模型、9 道表格题：正确 33% → **56%**（表格父子块切分） | `output/baseline_scores.md` |
| 拒答 | 库外题拒答 **100%**；重排分阈值 0.3 在库内 139 题上误拒 0%，44% 的库外题在调用 LLM 之前就被拦下 | `output/threshold_scan.md` |
| 成本 | 云端跑 144 题评测约 ¥0.68（硅基流动 DeepSeek-V3，按公开价估算） | `output/version_scores.md` |
| 部署 | 前后端分离：FastAPI 服务（检索 / 问答 / SSE 流式 / 异步入库，可选 Token 鉴权）+ Streamlit 纯前端；CPU 可跑，本地 3B / 云端接口一键切换；API 集成测试 14 项通过 | `api.py`、`app.py`、`tests/test_api.py` |

## 界面截图

![Streamlit 问答界面：硅基流动 DeepSeek-V3 回答 + 出处](docs/images/app_siliconflow.png)

左侧：上传 PDF/DOCX 增量入库，调重排、Top-k、上下文扩展、拒答阈值，选 LLM 提供方。右侧：流式回答，带 `[n]` 引用；展开“出处”可看到文件、章节路径、页码、原文片段、检索分和重排分，以及各阶段耗时。

## 系统架构

```mermaid
flowchart LR
    U[Streamlit 前端 app.py<br/>/ curl / 其他客户端] -- HTTP + SSE<br/>KB_API_URL --> API[FastAPI 服务 api.py<br/>lifespan 一次加载模型 · 鉴权 · 写锁 · 线程池]
    API -- POST /documents<br/>异步任务 --> A
    API -- /search /ask /ask/stream --> Q
    subgraph 入库
        A[PDF / DOCX] --> B{文字层?}
        B -- 有 --> C[PyMuPDF 正文 + find_tables 表格]
        B -- 扫描页 --> D[OCR：RapidOCR 文字 / PaddleOCR PP-StructureV3 表格]
        C --> E[章节识别 + 表格占位]
        D --> E
        E --> F[heading_v2 切分<br/>正文块 · 整表块 · 表格行描述块]
        F --> G[(向量库接口 vector_store.py<br/>Chroma 默认 / Milvus 可切换<br/>bge-m3 稠密向量)]
        F --> H[(BM25<br/>jieba + 电力词典)]
    end
    subgraph 问答
        Q[问题] --> G & H
        G & H --> I[加权融合 α=0.5<br/>Top-50]
        I --> J[bge-reranker-v2-m3<br/>重排 Top-20 β=0.8]
        J --> K{Top-1 重排分 < 0.3?}
        K -- 是 --> R[直接拒答<br/>不调用 LLM]
        K -- 否 --> L[行级命中展开为整表<br/>编号资料 Top-5]
        L --> M[LLM<br/>DeepSeek-V3 / Qwen2.5 / 本地 3B]
        M --> N[引用校验<br/>编号合法 + 数值有出处]
        N --> O[答案 + 出处]
    end
```

## 技术栈

| 环节 | 选型 | 说明 |
|---|---|---|
| 解析 | PyMuPDF、python-docx | 文字层 PDF 直接取字和表格（`page.find_tables()`） |
| OCR | RapidOCR（ONNX）、PaddleOCR 3.x PP-StructureV3 | 扫描页自动 OCR；Paddle 放在独立 Python 3.11 环境，作为常驻子进程运行 |
| 切分 | 自研 `chunk.py` / `tables.py` | 识别“1.2.3 / 第X章 / 附录A / 表N”等标题；表格父子块 |
| 向量 | BAAI/bge-m3（sentence-transformers，CPU） | 归一化后用 cosine，带向量缓存 |
| 向量库 | Chroma（默认）/ Milvus（Lite 或 Standalone） | `vector_store.py` 抽象接口，用 `VECTOR_STORE` 切换；metadata：source / 章节路径 / page / chunk_type / table_id |
| 部署 | Docker Compose | api + web + ollama，`--profile milvus` 再加 etcd/minio/milvus；首次启动自动建索引或自动迁移 |
| 关键词 | rank_bm25 + jieba | 自定义电力词典，数值和单位不拆开（`dict/`） |
| 重排 | BAAI/bge-reranker-v2-m3（CrossEncoder） | 一阶段 Top-20 重排，最终分 = 0.8·重排分 + 0.2·一阶段分 |
| LLM | OpenAI 兼容接口：硅基流动、DeepSeek、OpenAI、xAI、本地 Ollama | 429/5xx/超时分类重试（指数退避 + Retry-After）；失败可降级到本地模型或“仅检索结果” |
| 配置 / 日志 / 异常 | pydantic-settings、logging | `config.py` 集中配置（环境变量 > .env > config.yaml > 默认，密钥只认环境变量）；`kblog.py` text/json 日志 + 轮转 + request_id + 自动打码；`errors.py` 异常体系 → 统一错误体 |
| 服务 | FastAPI + uvicorn | lifespan 预加载模型；Pydantic 模型 + OpenAPI 文档；SSE 流式；入库异步任务 + 写锁；可选 `KB_API_TOKEN` 鉴权、CORS、上传大小限制、统一错误格式、请求日志 |
| 界面 | Streamlit（纯前端，httpx 调 API） | 流式输出、出处展开、上传进度轮询、按哈希去重；不加载任何模型 |
| 评测 | 自研 `evaluate.py` | 检索 Hit@k/MRR、要点覆盖自动评分、引用、拒答、耗时；支持缓存续跑和并发 |

## 快速开始

### 1. 环境

```bash
cd power_kb
python3.13 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU 版，避免下载 CUDA
pip install -r requirements.txt
# 可选：Streamlit 自测截图
python -m playwright install chromium
```

- 首次运行会自动下载 bge-m3（约 2.2 GB）和 bge-reranker-v2-m3（约 2.2 GB），可设置 `HF_HOME` 指定缓存目录。
- PaddleOCR 是可选项，需要单独的 Python 3.11 环境（安装命令见 `requirements.txt` 末尾）。没装时扫描页自动改用 RapidOCR，可用 `OCR_ENGINE=rapid|paddle` 强制指定。

### 2. 准备文档并重建索引

本仓库**不含**任何标准原文或 PDF。按 [`docs/sources.md`](docs/sources.md)（即 power_kb_sources.md） 列出的公开地址自行下载，放到 `/workspace/power_docs/`（其它路径用 `--docs-root` 指定）。

```bash
python build_v2.py --docs-root /workspace/power_docs     # 解析 + OCR + 表格 + heading_v2 切分 → output/chunks_heading_v2.jsonl
python embed_index.py --methods heading_v2                # bge-m3 向量 → chroma_db/（增量；--rebuild 全量重建）
python bm25_index.py  --methods heading_v2                # BM25 → bm25_index/
```

`build_v2.py` 可用 `--max-size 800 --overlap 50` 调切分长度（默认就是这组值），`--name` 指定集合名，`--ocr-engine` 指定 OCR 引擎。

### 3. 配置 LLM（任选其一）

```bash
cp .env.example .env              # 密钥写这里（.env 已被 .gitignore 忽略）；程序启动时自动读取项目根目录的 .env
cp config.example.yaml config.yaml   # 可选：非敏感参数（检索/重排/切分/端口/模型名/日志）
python config.py                  # 校验并打印生效配置（密钥只显示“已设置/未设置”）
```

| 提供方 | 需要的环境变量 | 说明 |
|---|---|---|
| 硅基流动（推荐） | `SILICONFLOW_API_KEY`，可选 `SILICONFLOW_MODEL` | 默认 `deepseek-ai/DeepSeek-V3`，备选 `Qwen/Qwen2.5-72B-Instruct` |
| DeepSeek 官方 | `DEEPSEEK_API_KEY` | `--provider deepseek` |
| 本地 Ollama | 无 | 先 `sh deploy/start_ollama.sh`（端口 11434），再 `ollama pull qwen2.5:3b-instruct`（或用 `deploy/Modelfile.qwen2.5-3b` 从 GGUF 创建同名模型） |
| 任意兼容接口 | `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` | 不传 `--provider` 时生效 |

其它常用项：`RAG_PROMPT`（p0–p3，默认本地 p1、云端 p2）、`RAG_EXPAND`（默认 none）、`RAG_REFUSE_BELOW`（默认 0.3，off 关闭）、`LLM_TIMEOUT`（默认 180 秒）、`LLM_FALLBACK`（默认 retrieval）。全部配置项及注释见 [`config.example.yaml`](config.example.yaml)。

#### 配置优先级与密钥规则

**环境变量 > `.env` > `config.yaml` > 代码默认值**（`config.py`，pydantic-settings）。

- 字段名与环境变量同名（不区分大小写），以前的环境变量写法全部继续有效；值为空字符串视为未设置。`config.yaml` 可以按小节写（`retrieval:`、`llm:` …），加载时拍平；用 `CONFIG_FILE` 指定其他路径。
- **API Key / Token（`SILICONFLOW_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`XAI_API_KEY`、`LLM_API_KEY`、`KB_API_TOKEN`、`MILVUS_TOKEN`）只能来自环境变量或 `.env`**，类型是 `SecretStr`；`config.yaml` 里出现 `*api_key / *token / secret / password` 这类键会直接报 `ConfigError` 拒绝启动。拼错的配置项和非法取值（如 `log_format: xml`）同样会在启动时报错，错误信息不回显输入值。
- API 启动时在日志里打一条脱敏的 `config.summary`；`python config.py get kb_api_port` 可在脚本里读取单项（`deploy/start_api.sh` 就是这样取 host/port 的）。

#### LLM 失败时的处理（`LLM_FALLBACK`）

| 取值 | 云端调用失败（重试用尽后） |
|---|---|
| `retrieval`（默认） | 不报错，返回检索到的 Top-3 资料（`degraded: true`），前端提示“大模型暂时不可用” |
| `local` | 改用本地 Ollama 重新生成（`fallback: {from, to: "local", reason}`），本地也失败则报错 |
| `local_then_retrieval` | 先本地，再仅检索结果 |
| `none` | 直接返回错误（504/429/502/503，见下方错误码表） |

重试：429、5xx、网络错误最多 `LLM_MAX_RETRIES`（默认 5）次，退避 `min(LLM_BACKOFF_CAP, LLM_BACKOFF_BASE·2^n)` 秒并遵守 `Retry-After`；超时单独计 `LLM_TIMEOUT_RETRIES`（默认 1）次；401/403 不重试；流式已输出部分内容后不再重试（避免重复）。

### 4. 启动 API 服务与 Web 前端

```bash
sh deploy/start_api.sh      # 后台 uvicorn api:app :8000（启动时加载 bge-m3 / 重排 / BM25 / Chroma，约 15 s），日志 /workspace/api.log
sh deploy/start_app.sh      # 若 API 未运行先启动它，再后台起 Streamlit :8501（纯前端），日志 /workspace/streamlit.log
# 前台运行：uvicorn api:app --port 8000   和   KB_API_URL=http://127.0.0.1:8000 streamlit run app.py
```

浏览器打开 `http://localhost:8501`（前端），接口文档在 `http://127.0.0.1:8000/docs`。云端 key 只需配置在 **API 进程**的环境变量里，前端拿不到 key；API 开了鉴权时，前端进程设置同一个 `KB_API_TOKEN` 即可。
API 没启动时，前端会提示“后端 API 不可达”并给出启动命令。

容器化部署见下文“[一键部署](#一键部署docker)”。

### 5. 命令行问答 / 检索

```bash
python rag.py --provider siliconflow --stream "运行中SF6设备灭弧气室的湿度限值是多少？"
python rag.py --provider siliconflow --model Qwen/Qwen2.5-72B-Instruct --expand parent --refuse-below off "问题"
python rag.py "问题"                         # 不传 provider：用 LLM_BASE_URL，未设置时用本地 Ollama
python retrieve.py "阀控蓄电池核对性放电周期" -k 5      # 只看检索结果（默认集合 heading_v2、hybrid + 重排）
python retrieve.py "SF6 湿度" --mode bm25 --no-rerank --source DL_T_595-2025_六氟化硫电气设备气体监督导则.pdf
```

### 6. 跑评测

```bash
python validate_eval_set_v3.py                                  # 校验评测集：evidence 必须能在原切块中找到
python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --retrieval-only --tag retr   # 只评检索，不需要 LLM
python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --provider siliconflow \
       --prompt p2 --rules 3 --workers 4 --tag v3set              # 完整评测；有缓存，中断后可续跑
python version_scores.py                                        # 汇总 → output/version_scores.md / .xlsx
python evaluate.py --input eval_xling.jsonl --collection heading_v2 --retrieval-only --xlang llm --tag xl   # 可选：跨语言改写
python evaluate.py --rescore output/eval_runs/<run> --rules 3   # 重算分数 + Context Recall/忠实度/归因，不调 LLM
python -m pytest tests/test_numcheck.py -q                      # 数值校验回归测试
python -m pytest tests/test_api.py -v                           # API 集成测试（需先 start_api.sh）
```

每次运行输出到 `output/eval_runs/<tag>_<时间>/`（`per_item.jsonl`、`summary.json`、`report.md`），摘要追加到 `output/baseline_scores.md`。
注意：`evaluate.py` 的 `--collection` 默认是 `heading`、`--prompt` 默认是 `p0`，这是为了能复现历史结果，评当前推荐配置时要显式传参（见上）。

## 向量库选择

向量库通过 `vector_store.py` 抽象（`upsert / delete / query / get / count / list_sources / all_metadata`，过滤条件统一用 Chroma 风格的 `where`，Milvus 侧自动转成布尔表达式）。`embed_index.py`、`retrieve.py`、`kb_store.py`、`api.py` 全部通过这个接口访问，代码里不再直接调用 chromadb。

| | Chroma（默认） | Milvus Lite | Milvus Standalone |
|---|---|---|---|
| 形态 | 嵌入式，本地目录 | 嵌入式，单个 `.db` 文件 | 服务（etcd + minio + milvus） |
| 适用规模 | ≤ 百万级，单机 | 原型、单机 | 百万到十亿级，可水平扩展 |
| 索引 / 度量 | HNSW / cosine | HNSW / COSINE | HNSW（可换 IVF、DiskANN 等）/ COSINE |
| 运维 | 无 | 无 | 3 个容器，需要监控与备份 |
| 本项目实测：检索指标（eval_set_v3 139 题） | MRR 0.893，Hit@5 97.1% | **与 Chroma 逐题名次完全相同** | `/search`、`/ask` 已验证可用 |
| Top-50 稠密检索 p50 | 4.5 ms | 9.3 ms | — |
| 内存增量 | ≈ 190 MB | ≈ 470 MB | 另外 3 个容器 |

结论：3.5k 块规模下，向量检索只占端到端耗时的不到 1%（重排约 2.5 s/题才是大头），所以**默认保留 Chroma**；需要扩展或多服务共享时再切 Milvus。详见 [`output/vs_compare.md`](output/vs_compare.md)。

```bash
pip install "pymilvus[milvus_lite]"
python migrate_chroma_to_milvus.py --methods heading_v2 --drop                                  # 迁移到 Milvus Lite（milvus_db/power_kb.db），复用向量，约 3 s
python migrate_chroma_to_milvus.py --methods heading_v2 --uri http://localhost:19530 --drop     # 或迁移到 Standalone
export VECTOR_STORE=milvus MILVUS_URI=$PWD/milvus_db/power_kb.db                                 # 切换（Standalone 用 http://host:19530）
sh deploy/start_api.sh                                                                            # /health 会显示 "vector_store": "milvus"
VECTOR_STORE=milvus python evaluate.py --input eval_set_v3.jsonl --collection heading_v2 --retrieval-only --tag vs_milvus
```

注意：Milvus Lite 的 `.db` 文件同一时间只能被一个进程打开（API 运行时，不要再用另一个进程打开同一个文件跑评测）。

## 一键部署（Docker）

> 第一次在云服务器上部署？看 **[docs/DEPLOY.md](docs/DEPLOY.md)**：服务器选型、安全组、Docker 安装与国内镜像加速、数据准备、HF 镜像、Nginx + HTTPS + 基本鉴权、故障排查、备份与成本控制。干净的 Ubuntu 上可以直接 `sudo bash deploy/bootstrap.sh`（装 Docker → 拉代码 → 生成 .env → 启动，可重复运行）。

```bash
cp .env.example .env            # 可选：填写 SILICONFLOW_API_KEY、KB_API_TOKEN 等（key 只会传给 api 容器）
docker compose up -d            # 或 make up / sh deploy/up.sh：api :8000 + web :8501 + ollama（首次自动拉取 qwen2.5:3b-instruct）
docker compose --profile milvus up -d     # 加 Milvus Standalone；需要在 .env 里设 VECTOR_STORE=milvus、MILVUS_URI=http://milvus:19530
sh deploy/up.sh milvus                    # 等价的一条命令（自动设置上面两个变量）
sh deploy/up.sh down
```

- **镜像**：`python:3.12-slim` 多阶段构建；torch 用 CPU 版（2.75 GB）；依赖层放在代码层之前，改代码不会重装依赖；以非 root（uid 1000）运行，用 tini 作 init 进程；api 的健康检查要求 `models_loaded=true`。
- **卷**：`./data`（`KB_DATA_DIR`：索引、切块、上传文件、Milvus Lite 文件）、`./power_docs`（`POWER_DOCS_DIR`，只读，存放原件）、`hf_models`（`HF_CACHE_DIR`，模型约 4.5 GB）、`ollama_models`（`OLLAMA_MODELS_DIR`）。
- **首次启动时自动建索引**（`deploy/docker-entrypoint.sh`）：如果索引为空且原件目录里有 PDF/DOCX，依次运行 `build_v2.py`、`embed_index.py`、`bm25_index.py`；如果用的是 Milvus 而集合为空，但已有 Chroma 索引，就直接迁移（不重新 embedding）；两样都没有则照常启动，`/health` 会报错。**没有原件时**，可以用 `sh deploy/seed_data.sh` 把宿主机已建好的索引拷进 `./data`。也可以手动重建：`docker compose run --rm api build`。
- **bridge 网络不可用的环境**（例如本开发沙箱：自定义网络里 DNS 和容器间 TCP 都超时）：`sh deploy/up.sh --hostnet [milvus]`，即叠加 `docker-compose.hostnet.yml`，改用宿主机网络。
- **实测（docker 26.1.5 + compose v2.39.4，hostnet 模式）**：Chroma 栈 4 个服务全部 healthy，`/health` 正常，`/ask`（容器内 ollama qwen2.5:3b）21 s 返回带引用的答案，web 返回 200；`--profile milvus` 栈 7 个服务启动，api 自动迁移 3543 条向量到 Standalone，`/search`、`/ask` 正常；用空数据目录 + 只读挂载原件测试首次自动建索引：129 s 生成 3355 块（预置了向量缓存；镜像里只有 RapidOCR，扫描件 NM1 的块数和表格少于宿主机的 PaddleOCR 结果）。**默认的 bridge 网络模式在本机无法验证**（沙箱网络限制），配置已通过 `docker compose config` 校验。

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 状态、模型是否已加载、Chroma / BM25 块数、文档数、运行中任务数（不鉴权） |
| GET | `/config` | 各 provider 是否可用（只报告有没有 key，不返回 key）、默认 Prompt / 跨语言 / Top-k / 阈值、检索配置、上传限制 |
| POST | `/search` | `query, top_k, rerank, sources, filters, xlang, include_text` → 命中块 + 一阶段分 + 重排分 + 元数据 |
| POST | `/ask` | `question, provider, model, prompt, top_k, rerank, expand, refuse_below, sources, xlang` → `answer, citations, invalid_citations, warnings, retrieved, timing, usage` |
| POST | `/ask/stream` | 同 `/ask`，SSE：`start` → 多个 `token`（`{"t": "..."}`）→ `done`（完整结果，与 `/ask` 相同）；出错为 `error` 事件 |
| POST | `/documents` | multipart 上传 PDF/DOCX → 202 + `job_id`；后台单线程入库（写锁） |
| GET | `/jobs/{job_id}` | 入库进度 `queued/running/done/duplicate/failed`、`progress` 0–1、`message`、`result`；`failed` 时带 `error: {code, message}`（解析失败不影响服务） |
| GET | `/documents` | 库中文档（上传文档 `id` 为 sha256 前 12 位；基础库为 `base:<文件名>`） |
| DELETE | `/documents/{id}` | 删除上传文档（同时删 Chroma、切块文件，重建 BM25）；基础库文档返回 403 |

`refuse_below`：不传 = 服务端默认 0.3；`null` = 关闭阈值拒答。`/ask` 结果里的 `degraded`、`fallback` 表示是否发生了降级。
相关配置：`KB_API_TOKEN`（非空即开启鉴权，`Authorization: Bearer` 或 `X-API-Key`）、`KB_CORS_ORIGINS`、`KB_MAX_UPLOAD_MB`（默认 50）、`KB_MAX_CONCURRENCY`（同时执行的检索/问答数，默认 2）。

### 错误码

所有错误统一为 `{"error": {"code", "message", "detail", "request_id"}}`，响应头带 `X-Request-ID`（客户端传入的会沿用）。message 面向用户，不包含堆栈和 key；未预期的异常一律返回 `internal_error`，堆栈只写进（已打码的）服务端日志。异常类定义在 [`errors.py`](errors.py)。

| HTTP | code | 异常类 | 场景 |
|---|---|---|---|
| 400 | `provider_not_ready` | ProviderNotReady | 选了云端 provider 但服务端没配置对应 key；未知 provider |
| 400 / 422 | `bad_request` / `empty_file` | BadRequest | 请求不合法、空文件 |
| 401 | `unauthorized` | AuthError | 开启鉴权后缺少或错误的 token |
| 403 | `forbidden` | Forbidden | 删除基础库文档 |
| 404 | `not_found` | NotFound | 任务 / 文档不存在 |
| 409 | `busy` | Busy | 入库任务正在写索引时删除文档 |
| 413 | `payload_too_large` | FileTooLarge | 超过 `KB_MAX_UPLOAD_MB` |
| 415 | `unsupported_type` | UnsupportedFile | 不是 .pdf/.docx，或文件头与扩展名不符 |
| 422 | `validation_error` | — | 请求参数校验失败（detail 列出字段） |
| 422 | `document_parse_error` | DocumentParseError | 文档损坏/加密（入库任务里以 `failed` 状态体现） |
| 429 | `llm_rate_limited` | LLMRateLimited | 上游限流，重试用尽 |
| 500 | `retrieval_error` | RetrievalError | 检索内部错误 |
| 500 | `config_error` | ConfigError | 配置非法 |
| 500 | `internal_error` | — | 未预期异常 |
| 502 | `llm_auth_failed` | LLMAuthError | 上游 401/403（服务端 key 无效） |
| 502 | `llm_error` | LLMError | 上游其他 4xx、返回格式异常 |
| 503 | `llm_unavailable` | LLMUnavailable | 连不上 LLM 或上游 5xx，重试用尽 |
| 503 | `index_not_ready` | IndexNotReady | 模型未加载完 / 索引不存在 |
| 504 | `llm_timeout` | LLMTimeout | 上游超时 |

流式接口在已经开始输出后出错时，以 SSE `error` 事件给出同样的 `code / message / status / request_id`。前端（`app.py`）按错误码显示中文处理建议。

### 日志

`kblog.py` 统一配置：`LOG_LEVEL`（默认 INFO）、`LOG_FORMAT=text|json`、`LOG_DIR`（默认 `logs/`，容器内为 `data/logs/`）、`LOG_FILE`（off 关闭文件日志）、按大小轮转（`LOG_MAX_BYTES` 10 MB × `LOG_BACKUP_COUNT` 5）。

- **request_id** 用 contextvar 贯穿：中间件生成（或沿用客户端的 `X-Request-ID`），带进线程池（检索、生成、流式、入库任务），每行日志都有 `[rid=…]`。
- **结构化事件**：`request`（方法、路径、状态码、耗时）、`rag.answer`（provider、model、检索/重排/生成/首 token/总耗时、prompt/completion tokens、Top-1 重排分、是否拒答/阈值拒答、引用数、降级）、`llm.retry` / `llm.failed` / `llm.fallback`、`ingest.job`、`request.error`、启动时的 `config.summary`。
- **打码**：输出前统一过滤——已配置的密钥原值、`Authorization: Bearer …`、`X-API-Key`、`sk-…`/`xai-…`、`api_key=…`/`token: …`，包括异常堆栈；问句默认只记长度和哈希，`LOG_QUESTIONS=true` 才记原文（截断 200 字）。uvicorn 的日志也走同一套格式。

```text
2026-10-11 19:47:38,561 INFO powerkb.rag [rid=demo-ask-1] rag.answer provider=local model=qwen2.5:3b-instruct q=<len=16 sha1=41aec0a4a6> retrieval_secs=0.08 rerank_secs=4.31 generation_secs=5.37 total_secs=9.76 prompt_tokens=2137 completion_tokens=42 total_tokens=2179 top_rerank=0.997 refused=False threshold_refused=False n_citations=2 ...
2026-10-11 19:47:38,561 INFO powerkb.api [rid=demo-ask-1] request method=POST path=/ask status=200 ms=9764
```

```bash
curl -s localhost:8000/health
curl -s localhost:8000/search -H 'Content-Type: application/json' \
     -d '{"query": "运行中SF6设备灭弧气室湿度限值", "top_k": 3}'
curl -s localhost:8000/ask -H 'Content-Type: application/json' \
     -d '{"question": "阀控蓄电池多久做一次核对性放电？", "provider": "local", "top_k": 4}'
curl -N localhost:8000/ask/stream -H 'Content-Type: application/json' \
     -d '{"question": "SafeRing压力表指针在红区时怎么办？", "provider": "siliconflow"}'
curl -s -F file=@某手册.pdf localhost:8000/documents          # → {"job_id": "...", "status": "queued"}
curl -s localhost:8000/jobs/<job_id>
curl -s -X DELETE localhost:8000/documents/<sha12>
# 开启鉴权后每个请求加：-H "Authorization: Bearer $KB_API_TOKEN"
```

测试：`python -m pytest tests -q`。`test_api.py` 需要先启动 API 和本地 Ollama（否则自动跳过），`KB_TEST_CLOUD=1` 额外跑 1 次硅基流动端到端；`test_errors.py` 用 `httpx.MockTransport` 模拟超时 / 429 / 401 / 5xx 和降级，不调用任何真实云端接口。

![前端经 API 问答](output/app_api_screenshot.png)

## 目录结构

```text
power_kb/
├── parse.py / ocr.py / tables.py      # 解析、OCR（rapid|paddle）、表格抽取与跨页合并
├── paddle/paddle_worker.py            # PaddleOCR 常驻子进程（独立 Python 3.11 环境）
├── chunk.py / build_v2.py / run.py    # 切分（fixed / heading / recursive / heading_v2）
├── embed_index.py / bm25_index.py     # Chroma 向量索引、BM25 索引（增量 + 重建）
├── retrieve.py / rerank.py            # 混合检索、融合、重排、表格行→整表展开
├── context_expand.py                  # 上下文扩展 none|neighbor|parent（实验用，默认关闭）
├── rag.py                             # Prompt、LLM 调用、引用校验、拒答阈值、CLI
├── api.py                             # FastAPI 服务（/health /config /search /ask /ask/stream /documents /jobs）
├── kb_store.py / app.py               # 上传增量入库 / 删除；Streamlit 纯前端（只调 API）
├── config.py / config.example.yaml    # 集中配置（pydantic-settings；密钥只认环境变量 / .env）
├── errors.py / kblog.py               # 异常体系（→ HTTP 状态码与错误码）；统一日志（request_id、打码、轮转）
├── tests/                             # test_api（集成）、test_errors（异常映射/LLM 模拟/降级）、test_config、test_logging、test_vector_store、test_numcheck
├── vector_store.py                    # 向量库抽象：ChromaStore / MilvusStore（Lite / Standalone）
├── migrate_chroma_to_milvus.py        # Chroma → Milvus 迁移（复用向量）
├── Dockerfile / docker-compose*.yml   # 一键部署（api / web / ollama / milvus profile）；deploy/up.sh、Makefile
├── evaluate.py / judge_eval.py        # 统一评测入口；LLM 评委对比
├── threshold_scan.py / sf_cost.py     # 拒答阈值扫描；云端 token 与费用统计
├── eval_set_50.* / eval_set_v3.*      # 评测集（jsonl / md / xlsx）
├── eval_ood.jsonl / evalset/          # 库外与边界题、出题与审阅脚本
├── dict/                              # jieba 电力词典
├── deploy/                            # bootstrap.sh（干净 Ubuntu 一键部署）、up.sh、启动脚本、批量评测脚本、make_zip.py
├── docs/DEPLOY.md                     # 新手部署教程（云服务器 + Nginx/HTTPS + 排障）
├── docs/DEVLOG.md                     # 完整开发日志（Day 3–16 的全部技术细节）
├── docs/images/                       # README 用图
└── output/                            # 评测报告、统计、人工核对记录（切块原文不入库，见版权说明）
```

## 效果演进

![检索效果演进](docs/images/retrieval_evolution.png)
![回答正确率演进](docs/images/answer_evolution.png)

**检索**（44 题，heading 集合，块级命中；`output/hybrid_results.md`、`output/rerank_results.md`）

| 版本 | Hit@1 | Hit@5 | MRR@10 | 说明 |
|---|---|---|---|---|
| 定长切分 500 字 + 纯向量 | 50.0% | 86.4% | 0.658 | 对照组 |
| 章节切分 + 纯向量 | 72.7% | 90.9% | 0.807 | 块边界与条款对齐 |
| + BM25 加权混合（α=0.5） | 75.0% | 100% | 0.850 | 型号、编号、数值类问题召回更好 |
| + bge-reranker-v2-m3（Top-20，β=0.8） | **84.1%** | **100%** | **0.911** | 当前默认配置 |

**回答**（eval_set_50：库内 50 题 + 库外 5 题，自动评分规则 v2；检索固定为混合 + 重排）

| 版本 | 块MRR | 正确 | 得分 | 引用命中 | 库外拒答 | 误拒 | 秒/题 |
|---|---|---|---|---|---|---|---|
| 基线：heading v1 + qwen2.5:3b + p0 | 0.892 | 50% | 0.68 | 56% | 100% | 2% | 26.1 |
| 表格父子块 heading_v2（核对修复后） | 0.873 | 56% | 0.70 | 60% | 80% | 4% | 28.0 |
| + Prompt p1（逐条作答、步骤编号、数值照抄） | 0.873 | 56% | 0.70 | 66% | 100% | 2% | 18.7 |
| 换云端 DeepSeek-V3 + p1 | 0.873 | 78% | 0.89 | 96% | 100% | 0% | 15.8 |
| 云端 Qwen2.5-72B + p1 | 0.873 | 80% | 0.90 | 92% | 100% | 0% | 13.0 |
| **DeepSeek-V3 + p2（要点先行 + 总结句）** | 0.873 | **86%** | **0.93** | **98%** | 100% | 0% | 11.8 |
| 新评测集 v3（139 + 5 题，规则 v3）DeepSeek-V3 + p2 | 0.893 | 85% | 0.91 | 94% | 100% | 1% | 14.0 |

最后一行换了评测集和评分规则，不能和上面各行直接比较。云端“秒/题”是 4 路并发下的平均值。

## 关键设计与取舍

- **为什么按章节切分**：标准是按条款写的，一个条款就是一个完整的规定。在同样 32 题上，章节切分的 Hit@1 为 0.812，定长切分 0.562，递归切分 0.656（`output/eval_results.md`）。在 v2 管线上调切分长度：max 400 时 MRR 降到 0.813，max 1200 为 0.852，overlap 0 或 150 都不如默认的 800/50（0.873），所以保留默认值。
- **为什么加 BM25**：只看原 32 道语义题时，混合检索略差于纯向量（MRR 0.854 vs 0.881）。加入 12 道关键词型题（型号、表号、数值）后，44 题整体 MRR 从 0.807 提高到 0.850，Hit@5 达到 100%。实际运维提问里有大量这类问法，所以保留 BM25，并在融合后用重排把语义题的排序补回来。
- **表格父子块**：表格单独抽成 Markdown 父块，每行再生成一句自然语言描述作为子块（例如“表3 断路器灭弧气室 SO2 3～20 μL/L…”）。检索命中子块后，送给 LLM 的是带表头的整表。效果：9 道表格题的正确率从 33% 提高到 56%；全集正确率 50% → 56%，代价是块 MRR 从 0.892 降到 0.873（行级子块会挤占排名）。人工核对 20 张表：修复后 9 张完全正确、5 张有小错、2 张严重错误，4 张误识别为表格的已被过滤（`output/table_audit.md`）。前后对比见 `output/table_before_after.md`。
- **为什么默认不开上下文扩展**：用 DeepSeek-V3 + p2 实测，不扩展 86%，neighbor 84%，parent 84%，差异在噪声范围内，而输入 token 分别多 42% 和 57%。逐题检查发现，漏掉的要点其实已经在 Top-5 上下文里，问题出在生成阶段，不在召回。
- **拒答阈值主要用来省调用**：DeepSeek-V3 本身就能拒掉全部 22 道库外题，本地 3B 能拒掉 21/22。阈值 0.3 是保守取值（库内最低的 Top-1 分为 0.395），作用是让 44% 的库外题不必调用 LLM，节省时间和费用，并不是拒答能力的主要来源。阈值拦不住“看起来相关”的边界题，例如 N22 的重排分达到 0.561。
- **OCR 双引擎**：在正泰 NM1 扫描件上，RapidOCR 的正文字符错误率（CER）为 0.18%，PaddleOCR 为 0.53%，RapidOCR 也更快（0.92 vs 5.24 s/页）。但只有 PaddleOCR 能还原表格结构，所以默认用 PaddleOCR（检测到 Paddle 环境时），代价是子进程峰值内存约 4.5 GB（`output/ocr_compare.md`）。
- **Prompt 按模型分档**：p2 在 3B 上得分最高（0.73），但慢 2.3 倍，库外拒答还从 100% 降到 80%，所以本地默认用 p1；在 V3 上 p2 没有这些副作用，云端默认用 p2。

- **本地提准实验（Day 17，不调云端）**：归因拆分显示 V3 新基线未答对的 15% 中，检索失败 5%、生成漏写 10%（Context Recall 95%），瓶颈在生成。据此做的检索侧改进都没有在全集上胜出：跨语言改写在 36 道跨语言题上 MRR 0.657→0.716（3B 翻译 0.726），但在 139 题上让中文题 Hit@1 85.0%→76.1%；Contextual 前缀中性（MRR 0.893→0.890）；规则多查询退步（0.852）。因此检索默认不变，只把数值校验 v2 设为默认。Day 18 用云端 V3 复验：问句翻译 + “译句候选 ≤30% 重排池”（`xlang=cap`）在 36 道跨语言题上 MRR 0.657→0.745、Hit@5 75.0%→86.1%，139 题全集 MRR 0.893→0.896、中文题持平，已设为**云端默认**；p3（要点清单先行）自动评分持平（得分 0.910→0.906，人工抽查净 +5 题但新增 1 道误拒），未设默认。详见 `docs/DEVLOG.md` Day 17–18。

![拒答阈值扫描](docs/images/threshold_curve.png)

## 评测方法

- **评测集**
  - `eval_set_50`：50 道库内题（查参数 18 / 故障排查 16 / 操作步骤 16，英文 8 题）+ 5 道拒答题，全部人工编写。
  - `eval_set_v3`：139 道库内题（55 / 41 / 43，英文 19%，跨条款综合题 7 道，覆盖 19 份文档）+ 5 道拒答题。其中 89 道新题由 **DeepSeek-V3 根据切块起草，再经人工审阅**（第一轮 73 道草稿删掉 15 道）。
  - `eval_ood.jsonl`：22 道库外题和边界题，每道都经过检索核查，确认库内确实答不了。
  - 每道题都标注了来源文件、章节、页码，以及 `evidence` 原文片段。`validate_eval_set_v3.py` 会检查 evidence 是否是对应切块原文的子串。
- **检索指标**：块级和文档级的 Hit@1/3/5、MRR，按题型和语言分组统计。
- **回答指标**
  - 自动评分：把 key_points 逐条与回答比对（数值做单位归一化后精确匹配，其余做关键词匹配），给出“正确 / 部分 / 错误”三档。规则 v3 把要点分为 core 和 minor，core 覆盖率 ≥ 0.75 判为正确，得分 = 0.8·core + 0.2·minor。
  - 引用：引用编号是否合法、引用的资料里是否包含标注的依据块。
  - 拒答：库外题的拒答率、库内题的误拒率。
  - 耗时：检索、重排、生成分别计时。
- **自动评分与人工判断的一致率**
  - 规则 v2，30 题：总体 77%，但其中用来调规则的 18 题是 94%，调完规则后另抽的 12 题只有 50%（`docs/DEVLOG.md`）。
  - 规则 v3：在没参与定规则的新题上抽查 27 题。自动判“正确”的 8/8 一致；判“部分/错误”的 19 题中 9 题一致，另有 8 题人工判得更高（规则偏严）。按分布加权估计一致率约 89%（`output/manual_labels_v3.jsonl`）。
  - 用 DeepSeek-V3 做 LLM 评委，与人工的一致率只有 67%，低于自动规则的 77%，所以没有采用（`output/judge_eval.md`）。
- **口径说明**：库内只有 50 或 139 题，在 50 题集上 1 题就是 2 个百分点，正确率相差 8 个百分点以内基本在噪声范围内。新题由 V3 起草，可能偏向 V3 擅长的问法。切分和检索的结论只对这 19 份文档成立。

## 已知局限与后续计划

**局限**
- 自动评分偏严：数值带条件括注、“M4×45”这类写法、单位类要点容易误判为“部分”。正确率在 80% 以上时，最好结合人工抽查来看。
- 数值引用校验 v2（`numcheck.py`）在 258 例人工标注回归集上误报率 3.3%（v1 为 100%），但漏报率 8.7%：表头声明单位时篡改值若以裸数值出现在同块别处会被放过。
- 表格抽取：无框线的三线表（ABB VD4）和扫描件复杂表头（NM1 第 5 页）仍有严重错误；跨页续表和多行表头的归属偶尔不准。
- 剩下的错误主要是**漏要点**（多条件、附加注意事项），不是数值写错；本地 3B 模型只适合联调。
- 全部在 CPU 上运行：重排约 4 s/问，首次加载模型约 1 分钟；PaddleOCR 峰值内存约 4.5 GB。
- 评测集规模小，没有做多次重复运行的方差估计。

- 跨语言检索（云端默认 `xlang=cap`）、Contextual 前缀、多查询、p3、reflect 自检均已实现为开关；后四项未在 139 题全集上明确超过基线，默认关闭。英文问中文标准的 Hit@5 仍只有 70%。

**后续计划**
- 生成端：p3（要点清单先行）在本地 3B 难题子集上得分 0.455→0.545，需用云端模型在全集上正式验证；reflect 需更强的模型判断缺失点。
- 表格：加入无框线表算法，尝试多模态模型直接读表格截图。
- 评测：扩展到 300 题以上并邀请领域人员复核；做多次运行取置信区间；评分改为规则和 LLM 评委相结合。
- 工程：重排换成 GPU 或 ONNX 量化；加权限控制和文档版本管理（标准新旧版本并存的问题）。

## 数据与版权声明

- 本仓库**只包含代码、评测题目和统计结果**，不含任何标准原文、厂商手册 PDF/DOCX，也不包含由它们生成的全文切块（`output/chunks*.jsonl`、`uploads/chunks_uploaded*.jsonl`、`output/parsed/` 等已写入 `.gitignore`）。这些文件可以按[快速开始](#2-准备文档并重建索引)第 2 步在本地重新生成。
- 文档来源和公开下载地址见 [`docs/sources.md`](docs/sources.md)（即 power_kb_sources.md）。标准文本版权归各发布机构所有，手册版权归各厂商所有。
- 评测集的 `evidence` 字段和截图中只有少量原文片段，用于学习研究和效果核对；如有不妥请联系删除。
- 代码以 [MIT License](LICENSE) 开源，许可**只适用于代码**。

---

完整开发过程（每天的设计、实验、踩坑）见 [docs/DEVLOG.md](docs/DEVLOG.md)。
