# 调参/核对进度（中断后从这里续）
- [21:52] 开始。停掉 streamlit 释放内存（结束时 deploy/start_app.sh 重启）。
- [21:50] 启动 deploy/tune_chunks.sh（日志 logs_tune_chunks.log）；续跑时直接再执行该脚本，已 DONE 的组会跳过
- [21:52] 核对 20 张表后发现可修问题，暂停调参链，先修 tables.py（假表过滤/页框行/跨页续表）再重跑
- [21:55] tables.py 修复完成（230→175 张），heading_v2 已重切；重启 tune_chunks.sh：先重建 heading_v2 向量/BM25 + retrieval-only，再 4 组变体
- [21:55] 任务1 完成：output/table_audit.md
- [21:57] 任务2 before_after.py 后台运行（logs_before_after.log）
- [22:02] DONE heading_v2（切分 max=800 overlap=50，retrieval-only 完成，见 baseline_scores.md retr_heading_v2）
- [22:04] 任务2 完成：output/table_before_after.md + png
- [22:04] 启动生成 G1 gen_v2fix_p0_k5（logs_gen_g1.log）
- [22:04] 内存不足（可用 2GB），G1 取消，等切分扫描结束再串行跑
- [22:04] G1 排队：deploy/gen_run.sh gen_v2fix_p0_k5 --collection heading_v2
- [22:05] 发现生成缓存只按配置键、未含切块版本 → G1 误用了修复前缓存；evaluate.py 加 kb_sig（切块文件指纹）入缓存键，作废该结果，G1 仍在排队
- [22:21] DONE v2s400o50（切分 max=400 overlap=50，retrieval-only 完成，见 baseline_scores.md retr_v2s400o50）
- [22:36] DONE v2s1200o50（切分 max=1200 overlap=50，retrieval-only 完成，见 baseline_scores.md retr_v2s1200o50）
- [22:40] 续跑：v2s800o0 进行中；排队 G2 gen_v2_p1_k5、G3 gen_v2_p2_k5（G1 之后串行，logs_gen_g23.log）；G4 = 最佳 prompt + top_k 8，待定
- [22:44] DONE v2s800o0（切分 max=800 overlap=0，retrieval-only 完成，见 baseline_scores.md retr_v2s800o0）
- [22:56] DONE v2s800o150（切分 max=800 overlap=150，retrieval-only 完成，见 baseline_scores.md retr_v2s800o150）
- [23:05] 切分扫描结束：最佳 = heading_v2（800/50，Hit@1 78% MRR 0.873）；G1 生成中
- [23:22] DONE gen_v2fix_p0_k5（--collection heading_v2）
- [23:29] DONE G1 gen_v2fix_p0_k5：正确56% 得分0.70 库外拒答80% 误拒4%；G2 p1 开始
- [23:31] 发现排队脚本 pgrep 自匹配导致 G2 未启动，已杀掉并直接串行启动 G2→G3
- [23:48] DONE gen_v2_p1_k5（--collection heading_v2 --prompt p1）
- [23:50] DONE G2 gen_v2_p1_k5：正确56% 得分0.70 引用66% 库外拒答100% 误拒2% 18.7s/题；G3 p2 开始
- [00:21] 人工抽查 p1 版 10 题完成：output/manual_check_best.md，一致率 10/10
- [00:22] 默认 Prompt 改为 p1（rag.DEFAULT_PROMPT，可用 RAG_PROMPT 覆盖；app.py 走这个默认值）；evaluate.py 仍显式默认 p0，所以历史缓存可复现
- [00:28] DONE gen_v2_p2_k5（--collection heading_v2 --prompt p2）
- [00:29] DONE G3 gen_v2_p2_k5：正确60% 得分0.73 引用76% 库外拒答80% 误拒4% 43.4s/题；G4 按指示不跑
- [00:29] version_scores.md/xlsx 写完，推荐 v2 + p1；README 已加 Day 14 一节
- [00:30] 打包 power_kb.zip（226 个文件，9.4MB，含 paddle_worker.py）；streamlit 已重启，curl 8501 返回 200。全部完成
- [00:44] 加了硅基流动 provider（rag.py/app.py），evaluate.py 加 --workers 并发；call_llm 遇 429/5xx 退避重试；冒烟测试开始
- [00:45] 冒烟 3 题通过；启动 deploy/sf_run.sh（V3 p1 → Qwen72B p1 → V3 p2）
- [00:54] DONE sf_v3_p1_k5（--prompt p1）
- [00:56] V3 p1：正确78% 得分0.89 引用96% 拒答100% 误拒0；Qwen72B 进行中；开始人工抽查 V3
- [00:56] V3 人工抽查完成：output/manual_check_v3.md，10/10 一致
- [01:02] DONE sf_q72_p1_k5（--prompt p1 --model Qwen/Qwen2.5-72B-Instruct）
- [01:04] Qwen72B p1：正确80% 得分0.90 引用92% 拒答100%；V3 p2 进行中；judge_eval.py 后台启动
- [01:07] DONE sf_v3_p2_k5（--prompt p2）
- [01:09] V3 p2：正确86% 得分0.93 引用98%；评委：与人工一致率 67%（自动规则 77%）
- [01:09] version_scores 加了云端 3 行和费用；rag.py 云端默认用 p2
- [01:09] 打包 253 个文件 / 10.3MB（已确认 zip 里没有 key）；streamlit 已重启，返回 200，进程能读到 SILICONFLOW_API_KEY。全部完成
- [01:20] ① 写好 context_expand.py（none/neighbor/parent，父条款上升一级，单条上限 2000 字，总预算 8000），rag.answer 加 expand/refuse_below；启动 deploy/expand_run.sh（V3 p2 parent→neighbor）
- [01:21] 修复：expand 索引漏了上传文档 chunks_uploaded_v2.jsonl（DL/T 1555），已重启 expand_run.sh
- [01:22] ② 启动 gen_eval_items.py（V3 起草，每份文档 5 题，evidence 自动校验）
- [01:26] 库外题核查：原 N01/N05/N06/N07/N08/N12 在库中能找到或有歧义（如 ZF12B 机械寿命 5000 次、DL/T 595 矿物油 ≤10μg/g），已替换并重跑检索确认
- [01:30] 第 1 轮 73 题草稿，人工审阅删 15 题（琐碎/与旧题重复/疑似编造/偏题）；第 2 轮补题（故障/操作为主，英文文档每份 4 题）
- [01:37] 合并后库内 133 题，但类别不均（查参数61/操作43/故障29）、综合题只有 2 道 → 第 3 轮补故障排查（一半为多条款综合）
- [01:38] evaluate.py 加 --hits-from（复用旧运行的检索结果，检查检索配置一致）；parent 那轮已在跑，neighbor 那轮之后用 --hits-from sf_v3_p2_k5 单独启动
- [01:39] 原 parent 那轮卡在检索阶段（CPU 争用），已杀掉，改用 --hits-from 重跑
- [01:40] DONE sf_v3_p2_ex_neighbor
- [01:40] DONE sf_v3_p2_ex_parent
- [01:42] ① 父子块结论：none 86%/0.93 > neighbor 84%/0.92 = parent 84%/0.92；P13/P15 缺的要点在不扩展时已在 Top-5 上下文里 → 是生成端问题；parent 输入 token 多 57%。默认保持 expand=none
- [01:42] ② eval_set_v3.jsonl：库内 139（查参数55/故障41/操作43），英文 19%，综合题 7，覆盖 19 份文档；validate_eval_set_v3.py 通过
- [01:46] 库外集复核：N13/N19/N20 其实库里能答（LLM 正确作答），已移出 → eval_ood 剩 22 题（evalset/ood_removed.json 记录原因）
- [01:46] 启动新基线：eval_set_v3 + V3 + p2 + expand none + 规则 v3（旧 55 题复用检索结果）
- [02:09] 新基线 O23/O25/O26 三题的 API 请求挂起 >10min；杀掉后从缓存续跑（已完成 141 题不重算）
- [02:09] DONE v3set_sf_v3_p2
- [02:11] 新基线：英文 62% 判错，怀疑是评分问题（回答要求中文，新英文题只有英文要点）→ 用 V3 把新英文题要点译成中文（key_points_zh）后重算
- [02:12] 补中文要点后重算：正确 85%/部分 12%/错误 3%，得分 0.91（英文 77% 正确）
- [02:13] 规则 v3 人工校准（新题，未参与定规则）：自动判正确的抽 8 题 8/8 一致；判部分/错误的 19 题 9/19 一致，其中 8 题人工判得更高（规则偏严：条件数值括注、M4×45 解析、“单位”类要点）；按总体加权估计一致率约 89%；output/manual_labels_v3.jsonl
- [02:13] 阈值扫描（库内 139 + 库外 22+R5）：≤0.35 库内误拒 0%，0.4–0.85 为 1%（只有 F40=0.395），选保守值 0.3（拦掉库外 44%）；接着用本地 3B p1 跑库外 22 题看阈值收益
- [02:14] version_scores.md/xlsx 已更新（expand 两行 + 新评测集基线 + 费用）
- [02:14] README 已加 Day 16 一节
- [02:16] DONE local3b_p1_ood
- [02:17] 阈值效果：V3 自身 22/22、3B 21/22；阈值 0.3 拦掉 7/22，都是本来就会拒的 → 价值在省调用；写入 threshold_scan.md
- [02:18] 打包 303 个文件 / 12.0MB（无 key，含 eval_set_v3 和 paddle_worker）；streamlit 已重启

## Day 17：本地提准 5 项（不调云端）

- [11:55] 第1项 跨语言：开始 xling 36 题 none/dict/llm + v3 全集 dict
- [11:58] DONE xl_none
- [12:01] DONE xl_dict
- [12:09] DONE xl_llm
- [12:28] DONE v3_xl_dict
- [12:28] 第1项批跑结束
- [12:28] 第2项：建 heading_v2_ctx 向量+BM25
- [12:40] 第4项 数值校验 v2 完成：numcheck.py + tests/（回归集 258 例，pytest 9 项通过）；误报 120/120→4/120，漏报 1/138→12/138（均为合成篡改）；见 output/numcheck_eval.md；rag 默认 RAG_NUMCHECK=v2
- [12:40] 第5项 评测拆分完成：evaluate.py 增 ctx_recall/faithfulness/attribution；rescore v3set_sf_v3_p2 → 正确 85% / 检索失败 5% / 生成漏写 10%（output/eval_runs/v3set_sf_v3_p2_attr_*）
- [12:40] 第3项 rag.py 增 p3（要点清单先行）与 --reflect（自检+补检 1 轮），排队本地 3B 22 题子集
- [12:45] DONE 建索引 heading_v2_ctx
- [12:51] DONE v3_ctx
- [13:00] DONE v3_mq_rule
- [13:03] DONE xl_ctx
- [13:03] 第2项批跑结束
- [13:04] 第1项追加：xlang=dict 让中文题退步（Hit@1 85.0%→76.1%），改为 auto 门控 + 改写权重 0.7
- [13:09] DONE xl_auto
- [13:12] DONE xl_auto_llm
- [13:21] DONE v3_xl_auto
- [13:21] 第3项：本地 3B 子集 22 题 p1 / p3 / p3+reflect
- [13:24] DONE rf3b_p1
- [13:34] DONE rf3b_p3
- [13:43] 收尾：version_extra 已加 Day17 各运行；等 rf3b_p3_reflect
- [13:47] DONE rf3b_p3_reflect
- [13:47] 第3项批跑结束
- [13:48] 收尾：DEVLOG/README 已更新
- [13:48] 收尾：make_zip + git push 完成
- [13:49] 收尾：Streamlit 已重启

## Day 18：云端验证 p3 与 V3 跨语言翻译

- [15:37] 云端验证①：V3 + p3 全集（检索复用 v3set_sf_v3_p2）
- [15:37] 云端验证②：V3 翻译问句 xlang=llm / mismatch / cap
- [15:42] DONE xl_v3llm
- [15:42] DONE v3set_sf_v3_p3
- [15:54] 修复 _stage1_gated 参数冲突；xling 的 mismatch/cap 排队重跑
- [16:08] DONE v3set_sf_v3_p3_reflect
- [16:23] DONE v3_xl_v3llm
- [16:31] DONE v3_xl_v3mismatch
- [16:42] DONE v3_xl_v3cap
- [16:47] DONE xl_v3mismatch
- [16:51] DONE xl_v3cap
- [16:53] Day18 收尾：cap 设为云端默认；p3 不默认；文档已更新
- [16:54] Day18 收尾：zip/push/streamlit 完成
- [17:15] API：api.py + app.py 纯前端 + tests/test_api.py，开始跑测试
- [17:20] API 测试 14 passed/1 skipped（云端 1 次通过），截图完成，README/DEVLOG/Docker 已写
- [17:41] vs_compare 开始：chroma
- [17:45] docker.io 26.1.5 安装成功（dockerd vfs），compose v2.39.4；开始 docker build
- [17:48] chroma 完成，开始 milvus(Lite)
- [17:55] vs_compare 完成
- [17:57] docker 实测：seed ./data，暂停宿主机 API/ollama，compose up（端口 8000/8502）
- [18:10] docker chroma 栈通过（/health ok，/ask local 21s）；开始 --profile milvus
- [18:16] docker milvus profile 通过（自动迁移 3543、/search /ask ok）；已 down，宿主机 API/前端/ollama 已恢复
- [18:18] docker 首次建索引实测：空数据目录 + 只读挂载 /workspace/power_docs（emb_cache 预置）
- [18:26] Day 20 完成：zip 1.8MB（按 gitignore），已 push

## Day: 日志/异常/配置 + 部署教程（2026-10-11 19:48:26）
- config.py/errors.py/kblog.py 完成；pytest 90 passed 1 skipped；宿主机 API 已用新代码重启
[2026-10-11 19:48:26] docker build start
[2026-10-11 19:48:50] build done, up
[2026-10-11 19:50:44] health: {"status":"ok","version":"1.0.0","models_loaded":true,"load_secs":24.0,"load_error":null,"collection":"heading_v2","vector_store":"chroma","vector_count":3543,"chroma_count":3543,"bm25_docs":3543,"documents":19,"uptime_secs":27.9,"jobs_running":0}
[2026-10-11 19:57:02] rebuild (build args) start
[2026-10-11 19:57:03] rebuild FAILED
[2026-10-11 20:00:14] 构建失败（磁盘写满后遗留孤立 layer），已移走孤立 layerdb 条目，重新构建
[2026-10-11 20:15:27] rebuild（PIP_MIRROR 构建参数 + 显式 pydantic-settings/PyYAML）start
