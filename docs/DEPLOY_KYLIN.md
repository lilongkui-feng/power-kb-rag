# PowerKB 麒麟 V10 服务器部署实录（受限网络 · 32 核 CPU · Docker）

> 2026-10-14 在一台银河麒麟 V10 内网服务器上用 Docker Compose 部署 PowerKB，检索全部本地运行，生成接单位内网的 OpenAI 兼容大模型网关（`cn:glm-5.3-flash`）。
> 本文合并了「部署问题复盘」和「部署测试记录」两份现场记录：前半是环境与实测数据，后半是 11 个问题和对应的仓库修复。
> 内网地址统一写成 `<server-ip>`，网关令牌等敏感信息不写入文档。离线 / 隔离区打包脚本见 [deploy/kylin/](../deploy/kylin/)。

## 一、环境

| 项目 | 配置 |
|---|---|
| 操作系统 | 银河麒麟 Linux Advanced Server V10 (Halberd)，内核 4.19.90-89.11.v2401，x86_64 |
| CPU | Intel Xeon Gold 6142 @ 2.60GHz，32 核（无 GPU） |
| 内存 | 61 GB（测试期间可用约 29 GB） |
| Docker | docker-ce 26.1.3 + Compose v2.27.0（清华镜像 docker-ce el8 rpm 安装） |
| 系统自带 | Python 3.7、旧版 Docker 19.03（已升级替换） |
| 网络 | **受限网络**：GitHub、清华源、阿里源、魔搭 ModelScope 可达；hf-mirror、download.docker.com、Docker Hub 被拦 |
| 部署方式 | Docker Compose：api + web（+ ollama，被网关替代后闲置） |
| 知识库 | heading_v2 集合：向量 3543 条 + BM25 3543 条，源文档 19 份；bge-m3 向量 + bge-reranker-v2-m3 重排，CPU 推理 |
| 大模型 | 内网 OpenAI 兼容网关 `http://<server-ip>:7863/v1`，模型 `cn:glm-5.3-flash` |
| 服务 | 问答页面 `:8501`，API `:8000`，开机自启（docker enable + restart: unless-stopped） |

知识库数据用 13 个分卷（`kb_data.tar.gz.p00…p12` + `SHA256SUMS`）拷入，合并校验后直接复用已建好的索引，没有重建。

## 二、实测结果

### 2.1 数据完整性（/health）

```json
{"status":"ok","models_loaded":true,"load_secs":18.8,
 "vector_count":3543,"chroma_count":3543,"bm25_docs":3543,"documents":19}
```

向量 / BM25 / 文档数与源数据包一致：**3543 / 3543 / 19**。

### 2.2 检索准确率（retrieval-only）

评测集：eval_set_v3 共 144 题（库内 139 + 库外 5），下表只统计库内 139 题。
配置：heading_v2 + hybrid(weighted, α=0.5) + rerank@20 β=0.8，top_k=5。

| 分组 | 题数 | 块 Hit@1 | 块 Hit@3 | 块 Hit@5 | 块 MRR | 文档 Hit@1 | 文档 Hit@5 | 文档 MRR |
|---|---|---|---|---|---|---|---|---|
| **全部** | 139 | **84%** | 95% | **97%** | **0.893** | 99% | **100%** | 0.992 |
| 查参数 | 55 | 80% | 94% | 96% | 0.873 | 98% | 100% | 0.988 |
| 故障排查 | 41 | 85% | 98% | 98% | 0.915 | 98% | 100% | 0.988 |
| 操作步骤 | 43 | 86% | 93% | 98% | 0.899 | 100% | 100% | 1.000 |
| 中文 | 113 | 85% | 96% | 98% | 0.904 | 98% | 100% | 0.990 |
| 英文 | 26 | 77% | 92% | 92% | 0.845 | 100% | 100% | 1.000 |

与开发环境的基准（块 Hit@5 约 97%）一致，换到麒麟 + 32 核 CPU 后检索精度没有变化。评测时检索平均 5.01 s/题，其中重排 4.71 s。

### 2.3 端到端耗时（网页实测，3 题 × 2 遍，glm-5.3-flash 生成）

| # | 问题 | 检索 | 重排 | 生成 | 总耗时 | 备注 |
|---|---|---|---|---|---|---|
| 1 | SF6 灭弧气室湿度限值 | 0.13s | 4.42s | 3.35s | 7.92s | 服务启动后首问（服务端日志） |
| 2 | SF6 灭弧气室湿度限值 | 2.52s | 4.65s | 3.37s | 10.63s | 重启后首问（服务端日志） |
| 3 | SF6 灭弧气室湿度限值 | 0.13s | 4.59s | 3.89s | 8.63s | 改为非流式之后 |
| 4 | 阀控蓄电池核对性放电周期 | 0.13s | 4.43s | 2.41s | 7.00s | |
| 5 | 阀控蓄电池核对性放电周期 | 0.13s | 4.92s | 2.38s | 7.45s | |
| 6 | GIS 抽真空检漏步骤 | 0.12s | 5.06s | 3.03s | 8.23s | |
| 7 | GIS 抽真空检漏步骤 | 0.12s | 5.59s | 3.96s | 9.69s | |

**热态约 8.5 s/题**（检索约 0.5 s + 重排约 4.9 s + 生成约 3.2 s）。模型随服务启动预加载（18.8 s，不计入问答），首问没有明显额外开销。重排是 CPU 上的主要开销。
对比 Windows 16 GB 纯 CPU 机器（非冷态 Top-10 约 30 s，见 [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)）。

### 2.4 回答质量抽检（人工对照原文）

| 问题 | 系统回答 | 核对 |
|---|---|---|
| SF6 湿度限值 | 运行中断路器气室 ≤300 μL/L，出厂 ≤150，检测按 DL/T 506 | ✅ 与说明书表 2-3、DL/T 595 一致 |
| 蓄电池放电周期 | 新装/大修后全容量核对性放电，以后每 2 年至少一次；运行 4 年后每年一次 | ✅ 与 DL/T 724-2021 §7.4.1.2 一致 |
| GIS 抽真空检漏 | 133 Pa 起算、维持 30 min、静观 30 min 读 A、5 h 后读 B、B−A ≤ 67 Pa 合格；含真空泵防倒吸注意事项 | ✅ 与 DL/T 618-2022 §10 及说明书一致 |

三题都带条款级引用（文件、章节、页码、原文摘录），没有编造数值，引用校验零告警。

> 说明：README 中的回答正确率（如 86%）是用 **DeepSeek-V3** 测的；本次部署生成用的是 **glm-5.3-flash**，上面只有 3 题人工抽检，没有跑全量回答评测。

## 三、问题清单、现场处理与仓库修复

| # | 问题 | 现场处理 | 仓库修复（本次） |
|---|---|---|---|
| 1 | `prepare_on_online_machine.sh` 报「不是 power_kb 目录」：只认默认路径 | `--src` 传真实路径 | 脚本移入 `deploy/kylin/`，`--src` 默认取仓库根 → 当前目录 → `./power_kb`，报错提示用 `--src` |
| 2 | `huggingface-cli download` 不存在（Python 3.7 只能装 huggingface_hub 0.16.4） | 用 `snapshot_download` | 部署指南写明老版等效命令 |
| 3 | hf-mirror 连接超时 | 先 `curl -sI` 测连通性，改走 ModelScope | 指南加连通性自检一行命令 |
| 4 | modelscope 新版要求 Python ≥ 3.8；老版 1.9.5 的依赖大包下载被掐断 | 自写脚本直连魔搭 API 下载，存成 HF 缓存格式（2.2 GB × 2） | 新增 `deploy/kylin/modelscope_to_hf_cache.py`（只用标准库、兼容 3.7、断点续传、sha256 校验） |
| 5 | download.docker.com 不通；麒麟源 docker-engine 18.09 太旧；残留 19.03 | 清华镜像 docker-ce centos/8 rpm，`rpm -ivh --nodeps` | 新增 `deploy/kylin/install_docker_tuna_rpm.sh`（26.1.3 + compose 2.27.0，可只下载供离线用）；`prepare --docker-source tuna` |
| 6 | Docker Hub 拉镜像慢/失败 | `daemon.json` 配多个加速站 | 见下文 §4.2 |
| 7 | 镜像构建卡在下载依赖：torch 行没用上国内源，PIP_MIRROR 未生效 | 把三处源写死进 Dockerfile | Dockerfile 新增 `PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL` / `APT_MIRROR` 构建参数，**torch 行也会用 PIP_INDEX_URL 拉依赖**；compose 从 `.env` 传入 |
| 8 | SSH 断开把前台构建掐死 | `nohup sh deploy/up.sh > /root/up.log 2>&1 &` | 指南与本文统一要求长任务 nohup |
| 9 | API 起不来（health 500），三层原因：① HF 缓存在 `/root` 下，容器内 uid 1000 进不去；② `output/` 没放进 `data/`；③ 套成 `data/output/output` | 缓存挪到 `/opt/hf_cache`，补挪文件 | 入口脚本自动处理 `output/output` 嵌套、在 data 下找回切块文件；启动时检查目录可写、HF 缓存可读并给出修复命令；`seed_data.sh` 自动 chown 1000 |
| 10 | 网页打不开：上一轮 `up -d` 卡在等 api 健康，web 只创建未启动 | 再跑一次 `docker compose up -d` | （设计如此：web 依赖 api 健康）排障表已写 |
| 11 | 接内网网关反复三轮：网页 OpenAI 档写死官方地址；`LLM_BASE_URL` 只在 provider 留空时生效，而网页总会传 provider；占位 key 未替换 | `docker-compose.override.yml` 把「本地」档改指网关 | 新增 provider **`custom`**：网页下拉「自定义网关（OpenAI 兼容）」并显示地址；compose 不再写死 `LOCAL_LLM_URL` |
| — | 评测写 `output/eval_runs` 报权限错误 | `chown -R app:app /data/output/eval_runs` | 入口脚本创建并检查 `eval_runs` 可写 |
| — | 网页流式输出偶发卡死（链路闪断，服务端其实已完成） | 前端临时改成非流式 `/ask` | 前端「流式输出」开关（`KB_STREAMING`），服务端每 10 s 发 SSE 保活，流式中断/空闲超时自动回退非流式 |
| — | 大模型网关偶发卡顿 | `LLM_FALLBACK=retrieval` | 已有：LLM 失败自动降级为仅检索结果 |

## 四、推荐部署步骤（按本次经验）

### 4.1 先测连通性

```bash
for u in https://github.com https://pypi.tuna.tsinghua.edu.cn https://mirrors.aliyun.com https://www.modelscope.cn \
         https://hf-mirror.com https://download.docker.com https://registry-1.docker.io; do
  curl -sI -m 8 -o /dev/null -w "%{http_code} $u\n" "$u"; done
```
方案跟着连通性走：本次 hf-mirror / Docker 官方全不通，所以模型走魔搭、Docker 走清华 rpm、镜像走加速站。

### 4.2 Docker

```bash
sudo bash deploy/kylin/install_docker_tuna_rpm.sh        # docker-ce 26.1.3 + compose 2.27.0
sudo tee /etc/docker/daemon.json <<'J'
{ "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io", "https://dockerproxy.net"],
  "log-driver": "json-file", "log-opts": {"max-size": "50m", "max-file": "3"} }
J
sudo systemctl restart docker
```
加速站高峰期会慢，失败就重试或调整顺序。

### 4.3 模型（HF 缓存不要放在 /root 下）

```bash
nohup python3 deploy/kylin/modelscope_to_hf_cache.py --cache /opt/hf_cache > /root/ms_dl.log 2>&1 &
tail -f /root/ms_dl.log                                   # 断了就重跑，已下完的文件跳过、未完成的续传
chmod -R a+rX /opt/hf_cache                               # 容器内 uid 1000 要能读
```

### 4.4 数据目录

期望布局（`KB_DATA_DIR`，默认 `./data`，挂载到容器 `/data`）：

```
data/
├── chroma_db/          # 向量库（chroma.sqlite3 + 段文件）
├── bm25_index/         # heading_v2.pkl
├── output/             # chunks_heading_v2.jsonl（必需）、eval_runs/、报告
├── emb_cache/  uploads/  logs/  milvus_db/
```
注意 `output/` 要直接在 `data/` 下，不要套成 `data/output/output`（入口脚本现在会自动纠正）。拷完后：

```bash
sudo chown -R 1000:1000 ./data                           # 容器以 uid 1000（app）运行
```

### 4.5 .env 与启动

```ini
HF_CACHE_DIR=/opt/hf_cache
HF_HUB_OFFLINE=1
# 内网网关（provider=custom，网页下拉「自定义网关」默认选中）
LLM_BASE_URL=http://<server-ip>:7863/v1
LLM_MODEL=cn:glm-5.3-flash
LLM_API_KEY=<网关令牌>
LLM_FALLBACK=retrieval
# 不需要本地 ollama：留空即不启动 ollama 容器
COMPOSE_PROFILES=
# 构建镜像时的国内源（对 torch 行和依赖行都生效）
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
APT_MIRROR=mirrors.aliyun.com
# 浏览器到服务器链路不稳时可关闭流式（流式中断也会自动回退）
# KB_STREAMING=false
```

```bash
nohup sh deploy/up.sh > /root/up.log 2>&1 &              # SSH 断开不影响
tail -f /root/up.log
curl -s http://127.0.0.1:8000/health                     # models_loaded:true，3543 / 3543 / 19
curl -s http://127.0.0.1:8000/config | grep -o '"default_provider":"[a-z]*"'   # 应为 custom
```
测试网关时记得把命令里的 key 占位符换成真令牌（否则 `invalid_api_key`）。`OPENAI_API_KEY` 不用就留空，免得网页把 OpenAI 档显示成「可用」。

### 4.6 排障三步

`docker ps -a` 看状态 → `docker logs --tail 30 <容器>` 看报错 → `docker exec <容器> env` 核对配置是否真的进了容器。每改一处就重启看一次日志。

## 五、经验

1. 受限网络先测连通性再定方案，本次换了几轮方案，根子都在网络。
2. 老系统（Python 3.7）装新工具必踩版本坑：优先找老版本的等效功能，或者绕开安装直接下载文件。
3. 长任务一律 nohup 后台跑。
4. 报错日志整段看：api 起不来那次是三层原因叠加。
5. 配置问题先确认值是否真的到了容器里（`docker exec … env`）。

## 六、遗留

| 事项 | 说明 |
|---|---|
| 网页端最终验证 | 用「自定义网关」档提问，确认 glm-5.3-flash 正常生成带引用的回答（现场是用 override 改「本地」档验证的） |
| 隔离区交付 | 完全断网的服务器按 [deploy/kylin/KYLIN_OFFLINE_DEPLOY.md](../deploy/kylin/KYLIN_OFFLINE_DEPLOY.md) 打离线包 |
| 本地 qwen 模型 | 现场已随 compose 下载（1.9 GB），被网关替代后闲置，可删除 |
| 本次仓库修复的现场复验 | 新的 custom 档、构建参数、入口脚本容错、流式回退都是在开发机上测试的，尚未回到麒麟服务器复验 |
