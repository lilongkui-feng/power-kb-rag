> 开发日志（原 README，按 Day 3–16 顺序记录全部技术细节与实验过程）。文中相对路径均相对项目根目录 `power_kb/`。精简版介绍见 [../README.md](../README.md)。

# 电力设备运维知识库 RAG：Day 3，文档解析与切分

基于 `/workspace/power_docs/` 中已下载的公开资料，用 **PyMuPDF**（PDF）和 **python-docx**（DOCX）提取文本，并对比三种切分方式：

| 方法 | 文件 | 说明 |
|---|---|---|
| a) 固定长度 | `output/chunks_fixed.jsonl` | 按字符计数（中文友好），每块 500 字，重叠 50 字 |
| b) 章节标题 | `output/chunks_heading.jsonl` | 先按编号标题或字号标题分节；过长的节再切，过小的节合并 |
| c) 递归切分 | `output/chunks_recursive.jsonl` | 依次按段落、换行、句号/分号、逗号、单字切分，目标 500 字，重叠 50 字 |

## 1. 运行方法

```bash
cd /workspace/power_kb
python3 -m venv .venv                      # 系统 pip 受 PEP 668 限制，建议使用虚拟环境
.venv/bin/pip install -r requirements.txt  # pymupdf / python-docx / pdf2docx / rapidocr / onnxruntime
.venv/bin/python run.py                    # 全流程：PDF→DOCX 测试件、解析、三种切分、统计、对比样例（约 20 秒）
# 可选参数：--docs-root 指定资料目录；--skip-docx-convert 跳过 PDF→DOCX 转换；--size/--overlap 调整固定/递归块长
#           --ocr auto|off|force（默认 auto：无文本层页面自动 OCR）；--searchable-pdf 为 OCR 文档输出可搜索 PDF 到 ocr_out/
.venv/bin/python ocr_eval.py               # NM1 OCR 质量抽查 -> output/ocr_eval.md
```

单文件调试：

```bash
.venv/bin/python parse.py <file.pdf|file.docx> [--max-pages N] [--out parsed.json]   # 查看清洗后的文本与元数据
.venv/bin/python chunk.py <file> --method heading|fixed|recursive [--show 5]          # 查看切分结果
.venv/bin/python ocr.py <file.pdf> --pages 3,17 --show [--dpi 200] [--searchable out.pdf]  # 单独 OCR 若干页
```

依赖：Python 3.13.5、pymupdf 1.28.2、python-docx 1.2.0、pdf2docx 0.5.13（只用于生成 docx 测试件）、rapidocr 3.10.0 + onnxruntime 1.31.0（OCR，CPU 推理）。

- 首次运行 OCR 时，rapidocr 会自动下载 PP-OCR 中文检测、方向分类和识别的 ONNX 模型（共约 15 MB），需要联网。
- 未安装 rapidocr 时，`parse.py` 自动退化为“只标记无文本层页、不识别”。
- OCR 结果缓存在 `.ocr_cache/`，重复运行不会重新识别。全流程首次约 55 秒，其中 OCR 约 30 秒。

## 2. 目录结构

```
power_kb/
├── parse.py          # 统一解析接口 parse_document(path) -> ParsedDoc
├── chunk.py          # chunk_fixed / chunk_heading / chunk_recursive
├── ocr.py            # 无文本层页 OCR（RapidOCR）+ 版面排序 + 可搜索 PDF
├── ocr_eval.py       # OCR 质量抽查（置信度 + 人工转录对照 CER + 表格逐格对照）
├── run.py            # 选文档 + 批处理 + 统计 + 对比样例
├── embed_index.py    # bge-m3 向量化 + Chroma 建库（增量/重建）
├── retrieve.py       # retrieve() 纯向量 / hybrid_retrieve() 混合检索 + CLI（--mode/--fusion）
├── bm25_index.py     # jieba+电力词典分词、BM25 索引（pickle）、where 过滤
├── dict/power_terms.txt  # 电力术语/型号自定义词典
├── eval_set_50.jsonl/.md/.xlsx  # 50 题运维评测集（+5 拒答）
├── evalset/items.py  # 评测集源定义
├── build_eval_set.py / validate_eval_set.py / eval50_retrieval.py
├── evaluate.py       # 统一评测入口（检索/回答/引用/拒答/耗时，缓存续跑，--rescore）
├── app.py            # Streamlit 页面（上传入库/删除、参数、提供方、聊天+流式+出处）
├── kb_store.py       # 上传文档增量入库/去重/删除/列表（Chroma + BM25 同步）
├── app_selftest.py   # playwright 页面自测与截图
├── uploads/          # 上传文件(files/，不进 zip)、registry.json、chunks_uploaded.jsonl（进 zip，评测集依赖 DL/T 1555 切块）
├── rag.py            # 完整 RAG：search → Prompt → LLM → 回答 + 出处（本地 ollama / DeepSeek）
├── rag_eval.py       # 端到端测试 12 题
├── deploy/           # start_ollama.sh、Modelfile.qwen2.5-3b
├── rerank.py         # bge-reranker-v2-m3 CrossEncoder 重排（分数缓存、β 混合）
├── eval_rerank.py    # 重排评测（Top-N/β 扫描、延迟、候选召回）
├── eval_hybrid.py    # dense/bm25/RRF/加权 对比与参数扫描
├── eval_questions_keyword.jsonl  # 12 道关键词/数值/型号/条款号题
├── bm25_index/       # BM25 索引（不放进 zip，可重建）
├── eval_retrieval.py # Hit@k / MRR 评测
├── eval_questions.jsonl  # 32 道标注评测题
├── chroma_db/        # 向量库（不放进 zip，可重建）
├── emb_cache/        # 向量缓存（不放进 zip）
├── requirements.txt
├── docx_test/        # pdf2docx 生成的 3 份 docx 测试件（由受版权保护的 PDF 派生，不放进 zip）
├── ocr_out/          # 可搜索 PDF（原件派生，不放进 zip）
├── .ocr_cache/       # OCR 原始结果缓存（不放进 zip）
└── output/
    ├── chunks_fixed.jsonl / chunks_heading.jsonl / chunks_recursive.jsonl
    ├── parsed/*.json   # 每份文档清洗后的逐页文本与元数据
    ├── stats.json / stats.md   # 统计
    ├── comparisons.md  # 切分对比样例
    ├── ocr_eval.md     # NM1 OCR 质量评估
    ├── rag_results.md / rag_raw.json / rag_eval.log  # 端到端 RAG 测试
    ├── rerank_results.md / rerank_results.json / rerank_examples.md  # 重排评测
    ├── hybrid_results.md / hybrid_results.json / hybrid_examples.md  # 混合检索评测
    ├── eval_results.md / eval_results.json / retrieval_examples.md / index_info.json / index.log  # 检索评测
    └── run.log
```

## 3. 处理的文档（18 份 PDF + 3 份 DOCX 测试件）

| 类别 | 文档 |
|---|---|
| DL/T 标准（9 份，全文） | DL/T 664-2025 带电设备红外诊断、DL/T 587-2025 继电保护运行管理、DL/T 724-2021 蓄电池直流电源运维、DL/T 2228-2021 充气式开关柜运维检修、DL/T 2544-2022 继电保护状态检修、DL/T 595-2025 SF6 气体监督、DL/T 1359-2025 SF6 故障气体分析、DL/T 618-2022 GIS 现场交接试验、DL/T 2890-2025 断路器机械特性现场试验 |
| 电网企业文件 | 南方电网《设备运行质量评价规则（变电在线监测装置部分）》2025 |
| 中文厂商手册 | 平高 ZF12B-126 GIS、施耐德 RM6 SeT 中文、正泰 NM1（**20 页无文本层**：“Microsoft Print to PDF”打印生成，文字全部转成矢量路径，不是位图扫描。经 OCR 后参与切分） |
| 英文厂商手册 | ABB VD4 36–40.5 kV 真空断路器、ABB SafeRing/SafePlus 环网柜、Schneider SM6-24、Schneider Galaxy VS UPS、Siemens SIPROTEC 5 7SJ82/85（**只取前 150 页，全书共 2040 页**） |
| DOCX 测试件 | 由 pdf2docx 转换：DL/T 595（9 页）、南网评价规则（10 页）、ABB VD4 第 1–12 页 |

未处理的文档：
- `_preview_only/` 下的节选件，按要求排除。
- SIPROTEC 5 7SA87（2262 页）：内容与 7SJ82 手册的大量通用章节重复，体量过大，会挤占统计权重，所以跳过。
- 7SJ82 只取前 150 页（含 35 页目录和第 1–3 章），用来验证超长手册的处理方式。如需全量处理，在 `run.py` 的 `SELECTED` 中把 150 改成 `None`，单份手册约需 1 分钟。

## 4. 设计说明

### 4.1 parse.py：统一解析接口

`parse_document(path)` 对 PDF 和 DOCX 返回同一种 `ParsedDoc`。主要字段：

- `pages`：`[{page, text, chars, scanned}]`
- `scanned_pages` / `is_scanned`：扫描件标记
- `removed_header_footer`：被识别为页眉页脚的模板
- `toc_pages`：目录页
- `font_headings`：PDF 中按字号识别的标题候选
- `docx_headings`：DOCX 中使用 Heading 样式的段落

**PDF（PyMuPDF）**

- 用 `page.get_text("blocks", sort=True)` 按块读取。
- **双栏重排**：左右两栏各有 ≥3 个长文本块时，在整页宽的块之间按“先左栏、后右栏”排序。ABB 手册是双栏排版，重排前 7.2.2 会被排到 7.1 之下。
- **编号与标题分属两个块时合并**：例如 SIPROTEC 的 `1.1` 和 `General` 在同一行、分属左右两个块，合并为 `1.1 General`。

**页眉页脚清洗**

- 把数字统一替换为 `#` 得到行模板。
- 页面上下 8% 区域内的模板：在 ≥30% 的页面出现即删除（强规则）。短模板在 ≥3 页出现也删除，但保留首次出现，因为按章变化的书眉第一次出现时通常就是章标题本身（弱规则）。
- 页面任意位置的短行在 ≥50% 的页面重复出现（如版权声明、文档号框）时删除。
- 删除页码行，包括 `- 3 -`、`Page 3 of 40`、`第 2 页 共 11 页` 等形式。

**断行合并**

- 合并条件：上一行没有以句末标点结束、不是标题、长度 ≥15；下一行不是列表项、标题或页码。
- 中文直接拼接，英文之间加空格，英文连字符断词时去掉连字符。
- 块边界视为“软换行”：满足条件时合并，否则作为段落分隔。
- 去掉阴影或描边造成的重复字，并压缩多余空行。

**扫描件识别**

- 某页有效字符 <30 且含图片，或该页 0 字符时，标记为 scanned。
- 扫描页 ≥50% 时整份文档标记为 `is_scanned`。正泰 NM1 的 20 页全部被正确标出。
- 无文本层页面默认自动 OCR（见 4.3）。页面字典里会标记 `ocr: true` 和 `ocr_conf`，`doc.ocr_pages` 记录每页的置信度和文本框数。只有在没有 OCR 结果时（`--ocr off` 或未安装引擎），整份文档才会跳过切分。

**DOCX（python-docx）**

- 按文档顺序遍历段落和表格；表格按“单元格 | 单元格”逐行输出。
- 页码由显式分页符和非 continuous 的分节符推算。
- 没有显式分页时，退而使用 `lastRenderedPageBreak`。pdf2docx 会为每个分栏区域插入一个 continuous 分节符，不能计为一页。修正后，3 份测试件的页数都与原 PDF 一致（9/10/12）。
- 记录 Heading 样式段落。pdf2docx 生成的段落没有 Heading 样式，所以 docx 也走编号正则识别。

### 4.2 chunk.py

**a) 固定长度（`chunk_fixed`）**

- 把全文拼接后按字符滑窗切分（500/50），并按偏移量回查起止页码。
- 实现最简单、块长最均匀，可作为对照基线。

**b) 章节标题（`chunk_heading`）**

1. **标题识别**（`detect_heading`），支持以下格式：
   - `1 范围`、`5.2.1 xxx`
   - `第X章/节/条`
   - `附录A`、`A.1`
   - 英文 `3.1 Title`
   - `前言`、`Foreword`

   同时过滤以下误识别：目录点引导线、带单位的数值行（如 `10 kV`）、以标点开头的行、含冒号的长句、文档编号等。
2. **编号连续性校验**（`HeadingTracker`），这是降低误识别的关键：
   - 一级编号只允许 +1 或 +2 递增；文档的第一个一级编号必须 ≤2，或字号明显偏大。
   - 二级及以下标题的父编号必须已在栈中。
   - 重新从 1 开始（多册合订的手册）只在“短标题，且为大字号、位于页顶或标题曾出现过”时允许。
   - 附录内部的“1 xxx”只在字号偏大时才算标题，因为通常是记录表格的条目。
   - **图注/零件表过滤**：同一页连续 ≥3 个“一级编号短行”且中间没有正文长段落时，判定为图例，不作为标题。
3. **自动选择模式**：编号标题足够多（≥0.4 个/页，或不少于字号标题数）时使用 `numbered` 模式。否则退回 `font` 模式，即按字号或加粗识别标题（≥1.18 倍正文字号，或加粗且 ≥1.05 倍、≤40 字），并排除 DANGER、危险等警示标签。施耐德 SM6、Galaxy VS 和 RM6 中文版的标题没有编号，自动走 `font` 模式。
4. **目录页和目录行不进入 heading 块**：目录对检索没有价值，而且与正文标题重复。固定切分和递归切分保留这部分作为基线。
5. **后处理**：
   - 小节（<120 字）向后合并，直到合并后 ≤800 字；被合并的小节路径记录在 `merged_sections`。
   - 超过 800 字的节用递归切分再切，每片 ≤750 字、重叠 50 字，并且合并 <20% 的碎片，避免出现只含标题行的孤块。
6. **块元数据**：
   - `chunk_id`，格式为 `{文件名}#{method}#{序号}`
   - `source`、`file_type`、`category`、`lang`
   - `heading_path`，如 `8 诊断方法 > 8.2 相对温差法`
   - `title`、`section_number`、`page_start`/`page_end`、`part`（如 `2/3`）、`char_len`、`text`
   - `embed_text`：在 `text` 前加上 `【来源｜章节路径】`，供向量化时使用，让块带上上下文

**c) 递归切分（`chunk_recursive`）**

- 分隔符优先级：`\n\n` → `\n` → `。` → `；` → `. ` → `; ` → `，` → `, ` → 单字。
- 目标 500 字，碎片合并后的上限为 600 字，再加上 ≤50 字的重叠。
- 重叠部分尽量从句子边界开始；英文至少从词边界开始，避免截出半个单词。

### 4.3 ocr.py：无文本层页面 OCR

**引擎选择**

- 使用 **RapidOCR**，即 PaddleOCR 的 PP-OCR 中英文模型转成 ONNX，用 onnxruntime 在 CPU 上推理。中文识别效果与 PaddleOCR 相同，不需要安装 paddlepaddle，Python 3.13 可以直接用 pip 安装。
- tesseract chi_sim 作为备选：它对中文小字号和表格的效果明显较差，而且需要系统包，所以没有采用。

**流程**

1. **渲染**：PyMuPDF 以 `page.get_pixmap(dpi=200)` 渲染页面。NM1 的页面约为 A5 尺寸，在 200 DPI 下正文字高约 30 px，正好落在 PP-OCR 的最佳区间。每页约 1–2 秒。
2. **识别**：输出文本框、文字和置信度，框坐标换算回 PDF 坐标（pt）。
3. **版面排序**：
   - 先过滤：丢弃置信度 <0.6 的框和竖排小字（多为图中标注）。
   - 再用**简化版递归 XY-cut**确定阅读顺序：
     - 竖向切：存在贯穿区域的竖缝，且左右两侧行基线不对齐（区别于表格的列）时，先读左栏再读右栏。
     - 侧栏：竖缝中有矢量竖线分隔，且右侧是中文文字行时，也按侧栏切开。NM1 第 4 页的“注意事项”侧栏就是这样被分出来的。
     - 横向切：在最大的空白处上下切开。
   - 区域内按基线聚合成行。行内有 ≥3 个相距较远的框时视为表格行，单元格用 ` | ` 连接；表格行不参与断行合并。
4. **后处理**：
   - 过滤图中的尺寸标注行（如 `W1 | W1 | W1`、`H2`）和图形误识别（如“电由由 由由由油”）。
   - 大字号行的章编号纠正：色块反白的数字常被认成形近字母或圈码，例如 `B外形` → `3 外形`、`⑥维护` → `6 维护`、`4 | 安装 | 接线` → `4 安装、接线`。
   - 列表序号纠错：紧跟在 `k）` 之后的 `1）` 改为 `l）`。
5. **接入解析流程**：OCR 行按 `(y0, y1, [text])` 的块格式交回 `parse_pdf`，之后与普通文本页走同一套页眉页脚、页码清洗和断行合并。
6. **字号标题**：行高 ≥1.3 倍页内中位数的 OCR 行作为字号标题候选。由于 OCR 行高会混入图中的大号文字，可靠性较低，OCR 为主的文档只要有 ≥5 个编号标题就用编号模式。
7. **可搜索 PDF**：`make_searchable_pdf` 在原页上按文本框位置叠加不可见文字层（`render_mode=3`，内置 `china-s` 字体）。原页面外观不变，文字可以搜索、选择和复制。运行 `run.py --searchable-pdf` 会输出到 `ocr_out/`。

## 5. 统计结果（完整数据见 `output/stats.md` / `stats.json`）

总体统计包含 3 份 docx 测试件和经 OCR 的正泰 NM1：

| 方法 | 块数 | 平均长度 | 最大 | 句中截断% | 一块混入多个编号条款% |
|---|---|---|---|---|---|
| fixed | 2226 | 498.2 | 500 | **77.7** | 13.0 |
| heading | 1657 | 470.1 | 797 | **36.1** | 13.6 |
| recursive | 2619 | 419.1 | 644 | 57.5 | 12.1 |

标准类文档（9 份 DL/T）的情况：

- fixed 的句中截断率为 82.5%，每 3 块中就有 1 块以上（37.5%）混入两个及以上条款。
- heading 的句中截断率降到 29.2%。它的“混入多条款”比例为 24.4%，主要来自有意合并的短小节（例如 4.2 安全要求和 4.3 环境和设备要求合成一块），合并路径记录在 `merged_sections` 里。

标题识别率：

- heading 法中带章节路径的块占 **96.9%**。
- 以目录为参照的召回率：在 11 份有可解析目录的文档上，宏平均 **95.0%**，微平均 **93.4%**。其中 DL/T 664、2228、2544、618、1359 为 100%，ABB VD4 为 87.1%，SafeRing 为 92.9%。

DOCX 路径测试（与同一份 PDF 对比）：

| 测试件 | 文本相似度 |
|---|---|
| DL/T 595 | 0.926 |
| 南网评价规则 | 0.927 |
| ABB VD4 | 0.571 |

ABB VD4 相似度低，原因是双栏版面：pdf2docx 的段落顺序与 PDF 栏序不同，图注也被转成了文本框。

## 6. 对比结论与建议（样例见 `output/comparisons.md`）

**样例 1：DL/T 664 第 4.3 条“环境和设备要求”**

- fixed：块从上一条的半句“测人员应严格执行…”开始，结尾截断在 4.4.1 的半句“管理范”。
- heading：4.2 和 4.3 两个短条款合并为一块（466 字），首尾完整，并带有 `4 现场检测 > 4.2…/4.3…` 路径。

**样例 2：DL/T 664 第 8.2 条“相对温差法”**

- fixed：公式和变量说明被切到两个块里。
- heading：整条（455 字，含公式 6 和适用条件）是一个完整的块，路径为 `8 诊断方法 > 8.2 相对温差法`。

**样例 3：ABB VD4 第 3.3.2 节“Closing procedure”**

- fixed 和 recursive 都会命中第 5 页目录中的“3.3.2 Closing procedure …14”，这对检索是噪声。
- heading 去掉了目录，正文是一个完整块，带 `3 Structure and function > 3.3 Function > 3.3.2 Closing procedure` 路径。

**建议**

- **标准（DL/T、GB/T、Q/GDW）和电网企业规程**：首选**章节标题切分**。条款编号规范，识别可靠（目录召回 90–100%），每块对应一个或几个完整条款，回答时可以直接引用“DL/T 664-2025 第 8.2 条”。超长条款（大表格、附录）用递归切分兜底。
- **厂商手册**：
  - 有编号标题（ABB、平高、SIPROTEC）时用章节切分。
  - 无编号标题（施耐德 SM6、Galaxy VS）时用字号标题模式，再用递归切分控制块长。
  - 手册里步骤、警示和表格多，`embed_text` 中的章节路径对检索帮助很大。
- **固定长度切分**：只适合作基线或兜底（例如 OCR 后版式混乱的文本），会频繁切断句子和条款。
- **递归切分**：在没有结构信息时是不错的通用方案，块边界比 fixed 好，但不带章节语义。
- **下一步可做**：
  - OCR 表格改用版面/表格结构识别（如 RapidTable、PP-Structure），输出 Markdown/HTML 表格。
  - 表格改为单独抽取（`page.find_tables()`），并转成 Markdown。
  - 给 heading 块加 parent-child 检索：命中小块后返回整节。

## 6.1 OCR 结果（正泰 NM1，详见 `output/ocr_eval.md`）

**置信度**

- 20 页、1624 个文本框，平均置信度 0.979（按字数加权的页均值为 0.989），中位数 0.9999。
- <0.8 的框有 67 个（4.1%），几乎都是尺寸图中的字母/数字标注和端子图形。
- 最低的是第 8 页（0.959），那一页全是外形图。

**与人工转录对照**

- 第 3 页正文 412 字：CER 0.24%，唯一错误是漏掉“+40℃”中的小号“+”。
- 第 17 页正文 150 字：CER 0%。
- 第 6 页尺寸表（9 行 × 7 列）：
  - 53/63 个单元格的数值和位置完全正确（84%）。
  - 7 行完全正确。W3 行漏识别一个“--”，导致后两格错位；A 行漏掉末尾的“--”。
  - Φd 行的数值全对，但行名被识别成“pφ”。

**表格效果**

- 规则的数值表基本可用。
- 表头的合并单元格和两行表头会被拆成多行，例如“NM1-”与“63S”分在上下两行。
- 合并单元格的分组名（外形尺寸、安装尺寸）位置会漂移。
- 第 17 页“维护”表中，项目列和内容列间距小的行会被并成一行文字（文字本身正确，但没有 ` | ` 分隔）。

**结构**

- 编号模式识别出 6 个章标题：1 使用信息、2 检查测试、3 外形安装尺寸、4 安装接线、6 维护、7 质保期。
- 第 5 章“附件信息”的章号色块没有被识别出来，这一章的内容并入了第 4 章。

**切分结果**：NM1 共 7600 字，fixed 23 块、heading 16 块、recursive 21 块。

## 7. 向量检索（Day 4：bge-m3 + Chroma）

### 7.1 运行与重建

```bash
export HF_HOME=/workspace/hf_cache            # 模型缓存目录（bge-m3 约 2.2 GB，不在 zip 内）
# 国内网络可选：export HF_ENDPOINT=https://hf-mirror.com
.venv/bin/python embed_index.py               # 增量建库：heading / fixed / recursive 三个集合 -> chroma_db/
.venv/bin/python embed_index.py --rebuild     # 删除集合后全部重建
.venv/bin/python embed_index.py --methods heading   # 只建主集合
.venv/bin/python retrieve.py "阀控蓄电池核对性放电周期" -k 5                  # 检索（默认 heading 集合）
.venv/bin/python retrieve.py "How to close VD4" -c recursive --category 厂商手册
.venv/bin/python retrieve.py "SF6 检测周期" --where '{"$and":[{"lang":"zh"},{"category":"厂商手册"}]}' --json
.venv/bin/python eval_retrieval.py            # 评测 -> output/eval_results.md / eval_results.json / retrieval_examples.md
```

- zip 包内**不含** `chroma_db/`、`emb_cache/`、`bm25_index/` 和模型。
- BM25 索引的重建方法：运行 `python bm25_index.py`，约 2 秒。
- 解压后执行 `pip install -r requirements.txt`，再运行 `embed_index.py`，即可从 `output/chunks_*.jsonl` 重建向量库。
- 首次运行会下载模型。在 8 核 CPU 上，三个集合的向量化共约 25 分钟。
- 向量按文本哈希缓存在 `emb_cache/`：重建集合时直接复用缓存，只需几秒。
- 增量更新：以 `chunk_id` 为主键，元数据中保存 `text_hash`。重新切分后再运行 `embed_index.py`，只会对新增或内容变化的块计算向量，并删除已不存在的块；没有变化时约 1 秒完成。

### 7.2 设计

- **模型**：`BAAI/bge-m3`，用 sentence-transformers 在 CPU 上运行。
  - 只使用 dense 向量（1024 维），`normalize_embeddings=True`。
  - Chroma 集合设置 `hnsw:space=cosine`，返回的分数为 `1 - distance`，即余弦相似度。
  - `max_seq_length=1024`：最长块 800 字，加上来源前缀也不会被截断。
  - 查询不加指令前缀（bge-m3 不需要）。
- **向量化的文本**：heading 块使用 `embed_text`，即 `【文件名｜章节路径】\n正文`。fixed/recursive 块同样加上 `【文件名】` 前缀，保证三种方法的比较公平。Chroma 的 documents 字段只存正文。
- **元数据**：`chunk_id`、`source`、`heading_path`、`title`、`page_start`/`page_end`、`category`（标准/厂商手册/电网企业文件）、`lang`、`method`、`part`、`merged_sections`、`char_len`、`text_hash`。
- **过滤**：`retrieve(query, k=5, collection="heading", filters=None)` 的 `filters` 使用 Chroma 的 `where` 语法；传入的简写 dict 有多个键时，自动用 `$and` 组合。
- **入库范围**：docx 测试件的块与对应 PDF 内容重复，默认不入库；需要时加 `--include-docx`。
- **集合规模**：`power_heading` 1578 块，`power_fixed` 2152 块，`power_recursive` 2532 块。

### 7.3 评测

**评测集**：`eval_questions.jsonl`，共 32 题（中文 25 题、英文 7 题，其中 2 题跨语言）。

- 覆盖的主题：
  - 红外诊断：相对温差法、环境要求、检测周期
  - SF6：气瓶、故障气体判据、检测周期
  - 直流电源：核对性放电、均衡充电、鼓胀故障
  - GIS 交接试验：回路电阻、漏气率、老炼
  - 断路器机械特性：同期性、脱扣电压、弹跳
  - 继电保护：停用整套保护、定值单、严重状态检修
  - 充气柜：验电、湿度
  - RM6：合闸、撞击器
  - NM1：维护周期、使用环境
  - VD4：合闸、检修周期
  - SafeRing、SM6、Galaxy VS、SIPROTEC
- 每题标注了期望的 `source`、章节和若干 **anchor**（目标条款中的特征原文）。

**相关性判定**：返回块的 `source` 与标注一致，且块正文（去掉空白后）包含任一 anchor。这个判定与切分方式无关，因此可以直接比较三个集合。

标注修订说明：第一轮评测后修订了 2 题的标注。

- q14 的目标是整个第 9 章，补上了 9.2 试验步骤。
- q29 中 Galaxy VS 有两种滤网型号，补上了另一种的正文 anchor。

修订原因是检查 Top-1 结果时，发现它们确实回答了问题，只是没有命中原先的 anchor。修订对三个集合同等适用。

| 集合 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | 中文 Hit@5 | 英文 Hit@5 | 文件级 Hit@1 |
|---|---|---|---|---|---|---|---|---|
| **heading** | **0.812** | **0.969** | **1.000** | 1.000 | **0.881** | 1.000 | 1.000 | 0.969 |
| fixed | 0.562 | 0.812 | 0.875 | 0.938 | 0.691 | 0.920 | 0.714 | 0.969 |
| recursive | 0.656 | 0.875 | 0.906 | 0.969 | 0.776 | 0.920 | 0.857 | 1.000 |

结论：

- 章节切分在所有指标上最好。它的块对应完整条款，标题路径又进入了向量，与提问的意图更吻合。
- fixed 的块经常截断条款，或混入相邻条款，排名普遍后移。
- 跨语言题差距最大：q31 用英文问相对温差法，heading 排第 1，recursive 排第 10，fixed 在前 10 内未命中。
- Chroma 单次查询约 3–14 ms；查询向量编码在 CPU 上约 0.1–0.3 s。

### 7.4 失败案例（heading 集合中未排第 1 的 6 题，详见 `output/eval_results.md`）

| 题 | 现象 | 原因 |
|---|---|---|
| q06 SF6 分解物检测周期 | 第 2（第 1 是同一标准的“6 判断依据”） | 两节都含 SO2/H2S 等词，语义相近；dense 向量对“周期”这类关键约束不敏感 |
| q19 充气柜母线验电 | 第 5（第 1 是父节点“4.4.2 验电依据”） | 4.4.2.4 很短，与相邻小节合并或单独成块后信息量少，父节点的块更“像”问题 |
| q25 VD4 怎样合闸 | 第 2（第 1 是正文中的“6.3.2 Closing and opening”） | 标题识别遗漏了第 6 章，这段被挂到“5.2 Assembly…”下，章节路径错误；内容本身其实相关，属于标注范围偏窄 |
| q26 VD4 检修周期由什么决定 | 第 3 | “1 Summary”和“Quenching principle”中也有 maintenance-free、life 等词，概括性段落抢分 |
| q27 SafeRing 维护周期 | 第 3（第 1 是“18.1 General warnings”） | 18.2 正文的前半段是工具清单，周期表格在 PDF 中被拆散，表格信息丢失 |
| q32 SM6 定期维护（中文问） | 第 3 | 跨语言，加上 SM6 使用字号标题模式，章节路径是“Operating Safety”，不准确；中文语料中的“维护”章节抢分 |

### 7.5 改进建议

1. **混合检索**：
   - 用 bge-m3 的 sparse（lexical）向量或 BM25，与 dense 结果做 RRF 融合。
   - 对“300A”“0.5%”“30%额定电压”等数值和条款号类查询提升明显，可解决 q06、q14 这类关键词约束问题。
   - bge-m3 用同一个模型就能输出 sparse 和 ColBERT 多向量，可以用 FlagEmbedding 的 `BGEM3FlagModel(..., return_sparse=True)` 实现。
2. **重排**：召回 Top-20 后，用 `BAAI/bge-reranker-v2-m3` 做 cross-encoder 重排，通常能把 Hit@1 再提高 5–15 个百分点，对概括段落抢分（q26、q27）尤其有效。
3. **父子块（small-to-big）**：
   - 用小粒度块（如 300 字）检索，命中后返回所在的整节或父节。
   - 这样可以解决 q19 这类短小节信息量不足、被父节点压过的问题。
4. **完善标题与元数据**：
   - 修正 VD4 第 6 章、SM6 和 Galaxy VS 的字号标题识别（q25、q29 的标题路径都有错位）。
   - 加上设备类型标签（GIS、开关柜、蓄电池、继保……），检索时先按设备或文档类型过滤，可以减少跨文档的干扰，例如 q06 中平高 GIS 手册的干扰。
5. **表格**：表格单独抽取成 Markdown，或为表格行生成描述，提升 SafeRing 维护周期表、尺寸表这类问题的效果。
6. **查询改写**：把中英混合的设备名称和缩写（VD4、RM6、SF6、阀控）规范化或扩展同义词；对中文提问、英文手册的场景，可以同时检索中文问题和它的英文翻译。
7. **评测**：继续扩充到 100 题以上，加入多跳问题（需要合并多个条款）和“库中没有答案应拒答”的负例，再配合 LLM 生成答案，做端到端评测。

### 7.6 混合检索（BM25 + 向量）

```bash
.venv/bin/python bm25_index.py                      # 建 BM25 索引 -> bm25_index/{heading,fixed,recursive}.pkl（约 2 s；未变化自动跳过）
.venv/bin/python bm25_index.py --tokenize "GIS 回路电阻不小于300A，见8.2条"   # 查看分词
.venv/bin/python retrieve.py "DL/T 664 第 8.2 条"                          # 默认 hybrid、加权融合、alpha=0.5
.venv/bin/python retrieve.py "REF615" --mode bm25                           # 只用 BM25；--mode dense 只用向量
.venv/bin/python retrieve.py "SF6 检测周期" --fusion rrf --rrf-k 60 --category 标准
.venv/bin/python eval_hybrid.py                     # -> output/hybrid_results.md / .json / hybrid_examples.md
```

**分词（`bm25_index.tokenize`）**

- 先做 NFKC 归一化和小写，再用正则把以下内容保护成整体 token：
  - 数值+单位：`300a`、`0.5%`、`500μl/l`、`1.5m/s`。这类 token 会额外输出纯数值，例如 `300`。
  - 型号：`rm6`、`vd4`、`nm1-250h`（同时拆出子部件 `nm1`、`250h`）、`ref615`、`gvsopt014`、`dc200/100cs`、`sf6`。
  - 条款号：`8.2`、`7.4.1.2`、`a.2`。
  - 电流倍率：`3i10`。
- 其余部分：中文用 `jieba.cut_for_search` 切分，加载自定义词典 `dict/power_terms.txt`（约 90 个电力术语和型号）；英文按单词切分，并做简单的复数还原。
- 最后去掉中英文停用词和标点。

**索引同步**

- BM25 和 Chroma 用同一份 `chunks_*.jsonl`、同一套 `chunk_id`、同样的 `_meta()` 元数据，也同样默认排除 docx。
- 建索引的文本与向量一致，都是“来源｜章节前缀 + 正文”。
- 过滤条件实现了 Chroma `where` 语法的一个子集（`$and/$or/$eq/$ne/$in/$nin/$gt/$gte/$lt/$lte`），所以 `filters` 对两路检索的效果一致。
- 索引用 pickle 保存，同时记录每块的 `text_hash` 和分词器签名（代码+词典的哈希）。切块、分词规则或词典有任何变化，都会自动重建。BM25 的 idf 是全局统计量，所以采用整体重建，耗时约 2 秒。

**融合（`hybrid_retrieve`）**

- 两路各取 Top-N（`top_n=50`）。
- `fusion='rrf'`：`Σ w/(rrf_k+rank)`。
- `fusion='weighted'`：每一路在自己的 Top-N 内做 min-max 归一化，再按 `alpha·dense + (1-alpha)·bm25` 合并，没进某一路 Top-N 的记 0。
- 返回结果带 `dense_rank/dense_score/bm25_rank/bm25_score`，CLI 输出也会打印这些字段，便于调试。

**评测**（两路各取 Top-50 后离线融合；相关性判定与 7.3 相同）

- 原有 32 题：`main32`。
- 新增 12 道关键词、数值、型号、条款号类题目：`eval_questions_keyword.jsonl`，即 `keyword12`。例如“300A”“DL/T 664 第 8.2 条”“REF615”“DC200/100CS”“7.4.1.2 条”“3I10”。

heading 集合的结果（三个集合的完整扫描见 `output/hybrid_results.md`）：

| 配置 | main32 Hit@1/Hit@5/MRR | keyword12 Hit@1/Hit@5/MRR | 全部 44 题 Hit@1/Hit@5/MRR |
|---|---|---|---|
| dense | **0.812** / 1.000 / 0.881 | 0.500 / 0.667 / 0.608 | 0.727 / 0.909 / 0.807 |
| bm25 | 0.719 / 0.906 / 0.784 | 0.750 / 0.917 / 0.804 | 0.727 / 0.909 / 0.789 |
| RRF k=10 | 0.750 / 0.969 / 0.850 | 0.667 / 1.000 / 0.787 | 0.727 / 0.977 / 0.833 |
| RRF k=60 | 0.750 / 0.969 / 0.839 | 0.667 / 0.917 / 0.780 | 0.727 / 0.955 / 0.823 |
| **weighted α=0.5（默认）** | 0.750 / **1.000** / 0.854 | **0.750 / 1.000 / 0.840** | 0.750 / **1.000** / 0.850 |
| weighted α=0.7 | 0.812 / 1.000 / 0.885 | 0.750 / 0.833 / 0.806 | **0.795** / 0.955 / **0.864** |

全部 44 题的 MRR，三个集合对比：

| 集合 | dense | bm25 | RRF k=60 | weighted α=0.5 |
|---|---|---|---|---|
| heading | 0.807 | 0.789 | 0.823 | **0.850** |
| fixed | 0.658 | 0.729 | 0.761 | **0.791** |
| recursive | 0.729 | 0.730 | 0.785 | 0.780 |

**参数扫描与过拟合说明**

- 扫描范围：`rrf_k` ∈ {10, 30, 60, 100}，RRF 中 BM25 的权重 ∈ {0.3, 0.5, 1, auto}，α ∈ {0.3…0.8}。
- 题目只有 44 道，相邻配置之间的差距大多只有 1–2 题，也就是 2–5 个百分点，不能认为有统计意义。
- 规律：
  - α 在 0.5–0.7 之间形成一个平台。α 越大，对自然语言问句越有利；α 越小，对型号、条款号类查询越有利。α=0.8 时关键词题明显崩掉。
  - `rrf_k` 影响很小。
  - 按查询类型自动调整 BM25 权重（auto）没有带来收益：自然语言问句里也常带“RM6”“VD4”这类型号，规则会被误触发。
- 默认参数选 **weighted α=0.5**，原因是它在两个题集上 Hit@5 都等于 1.0，最稳健。它不是任何单一题集上的最优值。
- 如果库里以自然语言问句为主，可以把 α 调到 0.6–0.7；如果不想调参，RRF 可以作为参数不敏感的备选。

**旧的 6 个失败题（heading 集合，dense 名次 → weighted α=0.5 名次）**

- q26（VD4 检修周期）：3→1。BM25 命中了 “servicing intervals” 这个原词。
- q27（SafeRing 维护周期）：3→2。
- q19（充气柜母线验电）：5→4。
- q06（SF6 分解物检测周期）：2→2，没变。
- q25（VD4 合闸）：2→2，没变；根因是标题路径错误，见 7.4。
- q32（中文问英文手册 SM6）：3→4，退步。BM25 的中文词无法匹配英文文档，反而把中文文档里的“维护”章节推了上去；纯 RRF k=60 下甚至掉出前 10。

**新出现的退步（main32）**

- q03（500kV 红外检测周期）：1→2。
- q21（RM6 F 功能合闸）：1→3。BM25 在 RM6 手册里给“合闸”“熔断器”等词频高的块打了高分。
- q31（英文问中文标准）：1→2。

这三题都仍在 Top-3 以内，Hit@5 不受影响。

**keyword12 的改善与退步**

- 改善 5 题，没有退步：
  - k02“8.2 条”：6→1。
  - k03“REF615”：2→1。
  - k05“DC200/100CS”：前 10 外 →1。
  - k09“7.4.1.2 条”：前 10 外 →3。
  - k04“54.2”：8→4。
- 剩余问题：
  - k09 用纯 BM25 排第 1，融合后变成第 3。
  - k04 中“54.2”在图例和正文里出现了 7 次，BM25 自己也只排到第 3。

**已知的融合缺陷**

- 加权融合中，只出现在一路 Top-N 里的结果，也能拿到最多 0.5 分。例如 k05 的第 2 名是 dense 排第 1 的无关块。
- 后续可以加 cross-encoder 重排，或者引入分数阈值来缓解。
- 跨语言查询下，BM25 基本不起作用。改进方向：先识别查询语言和文档语言，语言不一致时自动降低 BM25 权重；或者把查询翻译后，用双语查询分别做 BM25。

### 7.7 重排（bge-reranker-v2-m3）

```bash
.venv/bin/python retrieve.py "充气式开关柜母线验电要满足哪些条件？"   # 默认：heading + hybrid(α=0.5) + 重排 Top-20 + β=0.8
.venv/bin/python retrieve.py "REF615" --no-rerank                     # 关闭重排
.venv/bin/python retrieve.py "..." --rerank-top-n 10 --rerank-beta 1.0 --rerank-model BAAI/bge-reranker-base
.venv/bin/python eval_rerank.py      # 全量评测，约 30 分钟（CPU）-> output/rerank_results.md / .json / rerank_examples.md
```

**实现（`rerank.py`）**

- 使用 sentence-transformers 的 `CrossEncoder`，CPU、fp32，`max_length=512`，`batch=8`。
- 输入是一对文本：`(query, "【来源｜章节路径】\n正文")`。
- 取原始 logit，再做一次 sigmoid，得到 0 到 1 之间的重排分。
  - 注意：`activation_fn=None` 会套用模型默认的 Sigmoid。如果自己再套一次 sigmoid，分数会被压缩到 0.5–0.73。代码里已经显式改用 Identity 取原始 logit。
- 最终分数：`β·重排分 + (1-β)·一阶段分数`，其中一阶段分数在候选集内做 min-max 归一化。
- 重排分数缓存在 `emb_cache/rerank_*.json`。
- 统一入口：`retrieve.search()`。每条结果都同时带重排前的 `stage1_rank/stage1_score` 和重排后的 `rerank_score/rank/score`。

**评测结果**：44 题，heading 集合（完整结果见 `output/rerank_results.md`）

| 配置 | Hit@1 | Hit@3 | Hit@5 | MRR@10 | 每问重排耗时 |
|---|---|---|---|---|---|
| dense | 0.727 | 0.886 | 0.909 | 0.807 | – |
| hybrid α=0.5 | 0.750 | 0.932 | 1.000 | 0.850 | – |
| dense+rerank@20 | 0.818 | 0.955 | 0.955 | 0.886 | 4.2 s |
| hybrid+rerank@10 | 0.841 | 0.977 | 0.977 | 0.911 | 2.6 s |
| hybrid+rerank@20（β=1） | 0.841 | 0.977 | 0.977 | 0.909 | 4.2 s |
| **hybrid+rerank@20，β=0.8（默认）** | **0.841** | **0.977** | **1.000** | **0.911** | 4.2 s |
| hybrid+rerank@20，β=0.5 | 0.795 | 1.000 | 1.000 | 0.894 | 4.2 s |
| hybrid+bge-reranker-base@20 | 0.750 | 0.909 | 0.977 | 0.847 | 1.2 s |

说明：

- 重排 Top-30 的结果与 Top-20 相同，耗时 5.7 s。
- fixed 和 recursive 集合加上重排后，MRR 提升更大：
  - fixed：0.791 → 0.868（β=1）
  - recursive：0.780 → 0.881（β=1）

**候选集召回率**（相关块出现在一阶段 Top-N 内的比例，也就是重排能达到的上限）

| 集合 | dense@10 | dense@20 | hybrid@10 | hybrid@20 |
|---|---|---|---|---|
| heading | 0.955 | 0.977 | 1.000 | 1.000 |
| fixed | 0.909 | 0.909 | 0.909 | 0.955 |

结论：

- 重排找不回候选集外的结果，所以一阶段用 hybrid 更合适。
- 例如 k09（“7.4.1.2 条”）在 dense Top-20 里根本没有相关块，dense+rerank 也无能为力。

**逐题变化**（heading 集合，排名依次为：hybrid → 重排 β=1 → 重排 β=0.8）

- 改善的题：
  - q06：2→1→2
  - q19：4→2→2
  - q21：3→2→1
  - q25：2→1→2
  - q31：2→1→1
  - q32：4→1→1
  - k04：4→1→3
  - k08：2→1→1
  - k09：3→1→1
- q03 没有变化，仍是 2。
- 退步的题：
  - q30（SIPROTEC 采样频率跟踪）：1→前 10 未命中→4
    - 重排后的前几名都是同一节 3.3.2/3.3.3 的其他分块，语义上同样相关。
    - 但标注的 anchor 只出现在这一节的第一个分块中，所以这次退步有一部分是标注过严造成的。
    - 另一部分原因：英文长块超过 512 token 被截断，导致关键句丢失。
  - q05、k06 在 β=1 时从 1 降到 2，β=0.8 时恢复到 1。

**推荐默认配置**

heading 集合 + hybrid(α=0.5) + bge-reranker-v2-m3 重排 Top-20 + β=0.8。

- 这个配置在 44 题上 Hit@5=1.0，MRR=0.911。
- 把一阶段分数混入 20%，可以兜住 q30、q05、k06 这类重排误判。

如果对延迟敏感：

- 改用重排 Top-10，每问约 2.6 s，指标几乎不变。
- 或者使用 `--no-rerank`。
- bge-reranker-base 速度快 3.5 倍，但效果反而低于不重排，**不推荐**；它对中文电力文本的判断力不足。

**局限**

- 在 CPU 上每问要多花约 4 秒；GPU 或 ONNX 量化可以降到亚秒级。
- 题目只有 44 道，β 和 N 的选择存在过拟合风险。β 在 0.7–1.0 之间的差异只有 1–2 题。
- 正文超过 512 token 会被截断，对英文长块尤其不利。可以把 `max_length` 提到 1024，或者对长块做分段重排后取最大分，代价是更慢。
- 重排分数只用于排序。不同查询之间的分数不可比，不能直接当作“拒答”阈值，需要另外校准。

### 7.8 完整 RAG（检索 + 本地大模型生成 + 出处）

#### 本地模型安装（8 核 CPU、无 GPU、约 6 GB 可用内存）

```bash
# 1) 安装 ollama（安装包需要 zstd 解压）
sudo apt-get install -y zstd && curl -fsSL https://ollama.com/install.sh | sh

# 2) 启动后台服务：模型存放在 /workspace/ollama_models，OpenAI 兼容接口为 http://127.0.0.1:11434/v1
sh deploy/start_ollama.sh

# 3) 获取模型
ollama pull qwen2.5:3b-instruct
# 本机代理拦截了 ollama 仓库的 CDN，pull 失败，所以改从 HF 下载官方 GGUF 后在本地创建模型：
python -c "from huggingface_hub import hf_hub_download as d; d('Qwen/Qwen2.5-3B-Instruct-GGUF','qwen2.5-3b-instruct-q4_k_m.gguf',local_dir='/workspace/gguf')"
ollama create qwen2.5:3b-instruct -f deploy/Modelfile.qwen2.5-3b   # ChatML 模板，num_ctx=4096，temperature=0.1
```

内存占用：

| 组件 | 占用 |
|---|---|
| qwen2.5-3b Q4_K_M | 约 2.3 GB（模型文件 2.0 GB） |
| bge-m3 + bge-reranker-v2-m3（fp32） | 约 4.5 GB |

整个 RAG 进程运行时，系统剩余可用内存最低约 3.2 GB，可以共存。如果内存不足，换成 `qwen2.5:1.5b-instruct`，或者使用 `--no-rerank`。

#### 使用

```bash
python rag.py "阀控蓄电池多久做一次核对性放电？"        # 默认本地 qwen2.5:3b-instruct
python rag.py "GIS 气室年漏气率要求是多少？" --stream   # 流式输出
python rag.py "..." -k 4 --no-rerank --json
python rag_eval.py                                      # 端到端测试（12 题），结果见 output/rag_results.md
```

#### 切换 DeepSeek

DeepSeek 接口与 OpenAI 兼容，不用改代码。以下两种方式任选其一：

```bash
export DEEPSEEK_API_KEY=sk-...
python rag.py "问题" --provider deepseek          # base_url=https://api.deepseek.com，model=deepseek-chat

# 或者使用通用环境变量
export LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-chat LLM_API_KEY=$DEEPSEEK_API_KEY
python rag.py "问题"
```

在当前环境里没有调用过 DeepSeek，只验证了缺少 key 时程序会直接退出。

#### 流程（rag.py）

1. 调用 `answer(question)`。
2. `search()` 检索：heading 集合 + hybrid(α=0.5) + 重排 Top-20、β=0.8，取前 5 条。
3. 组装 Prompt：
   - 系统提示要求：只依据资料作答；先写句子，再在句末标 [n]；资料不足时只回答“根据现有资料无法回答该问题。”；用简体中文回答。
   - 每条资料带编号、文件名、章节路径和页码，正文最多 700 字。整个 Prompt 约 3000–4000 字。
4. 通过 OpenAI 兼容的 `/chat/completions` 接口调用 LLM，支持 SSE 流式输出。
5. 后处理：
   - 校验引用编号，删除不存在的编号。
   - 只列出被引用的资料，原文摘录取与回答重合度最高的一句。
   - 识别短拒答句：判为拒答时清空出处。
   - 回答为空、只有编号时，自动重试一次。
   - `support_check` 数值校验：句中的数值如果不在它引用的资料里，就提示“引用可能错配”或“数值无出处”。
6. 返回结果中包含 `timing`（检索、重排、生成、总计）、`usage`、`retrieved` 等字段。

#### 测试结论（详见 `output/rag_results.md`）

**测试结果**（10 道可回答题 + 2 道库外题）
- 6 题正确，3 题部分正确（漏条件、误译）。
- 1 题错误：q14 把“30% 时应不动作”歪曲成“不应小于30%”。
- 2 道库外题都正确拒答，没有编造数值。

**引用问题**
- 共 4 处：错配、引用了前言、多余引用、引用不支持回答。
- 自动校验发现了其中 2 处。

**耗时**
- 平均 8.36 s/问，其中检索 0.2 s、重排 4.32 s、生成 3.84 s。

**稳定性**
- 3B 模型对 prompt 措辞很敏感，多次运行的结果也有波动。具体情况见 rag_results.md 的“稳定性”一节。

#### 局限

- 3B 小模型的问题：
  - 会漏掉条件（q07、q23）。
  - 会把系统提示里的示例句式套进回答（q14）。
  - 英文术语会误译（closing 被译成“关闭”）。
  - 多次运行结果不完全一致。
- 小模型的引用编号经常不准，需要后处理校验。正式使用时建议换成 DeepSeek 这类更大的模型，或 7B 以上的本地模型。
- 数值校验按句子进行，只覆盖带引用的句子，不做语义层面的蕴含判断。
- 每问约 8.36 s，主要耗在 CPU 重排上。追求速度可以用 `--no-rerank` 或重排 Top-10。

### 7.9 Web 界面（Streamlit）

```bash
sh deploy/start_ollama.sh          # 本地 LLM（已在运行时会跳过）
sh deploy/start_app.sh             # 后台启动：streamlit run app.py --server.port 8501 --server.headless true
# 前台调试用：.venv/bin/streamlit run app.py --server.port 8501
# 浏览器打开 http://localhost:8501 。日志：/workspace/streamlit.log
python app_selftest.py <某个.pdf>   # 用 headless chromium 自测：上传、提问、展开出处，截图保存到 output/app_screenshot.png
```

**侧栏**

- **上传入库**：上传 PDF 或 docx（可多选）后，由 `kb_store.ingest()` 依次完成：
  1. 复用 `parse_document` 解析，扫描页自动 OCR。
  2. 用 `chunk_heading` 切分。
  3. 用 bge-m3 计算向量，增量 upsert 进 Chroma 的 `power_heading` 集合。
  4. 切块追加到 `uploads/chunks_uploaded.jsonl`。
  5. 重建 BM25（heading）索引，约 1 秒。
  - 界面显示进度条和最终块数。
- **去重**：
  - 文件 sha256 与已上传的文件相同时，跳过。
  - 文件名与基础库中的文档重名时，同样跳过。
- **文档列表**：显示每份文档和它的块数。只有上传的文档能删除（🗑），删除时会同步清理 Chroma、jsonl、BM25 和原文件。
- **一致性**：`embed_index.py` 和 `bm25_index.py` 重建时会读取 `uploads/chunks_uploaded.jsonl`，上传的文档不会在重建时丢失。
- **检索参数**：可以设置是否重排、Top-k（2–8），以及只在指定文档中检索（Chroma 和 BM25 都使用 `source $in` 过滤）。
- **LLM 提供方**：

  | 提供方 | base_url | 模型 | 需要的环境变量 |
  |---|---|---|---|
  | 本地 ollama（默认） | 本机 | qwen2.5:3b-instruct | 无 |
  | DeepSeek | https://api.deepseek.com | deepseek-chat | `DEEPSEEK_API_KEY` |
  | OpenAI | https://api.openai.com/v1 | `OPENAI_MODEL`，默认 gpt-4o-mini | `OPENAI_API_KEY` |
  | xAI | https://api.x.ai/v1 | `XAI_MODEL`，默认 grok-3-mini | `XAI_API_KEY` |

  - 缺少 key 时，侧栏显示红色提示，提问也会被拦下，不会发出请求。
  - 切换方法：在**启动 streamlit 之前** export 对应的 key，然后在下拉框里选择提供方。
  - 命令行用法：`python rag.py "问题" --provider deepseek|openai|xai`。

**主区**

- 聊天式问答，保留对话历史，回答流式显示。
- 每条回答下面有可展开的“📎 出处”，内容包括：
  - 每个出处的文件名、章节、页码、融合分数、重排分数和原文摘录；
  - 引用校验的提示；
  - 检索、重排、生成（含首 token）各环节耗时；
  - 检索结果的 Top-k 表格。
- bge-m3、重排模型和 BM25 通过 `st.cache_resource` 在每个服务进程里只加载一次。

**自测结果**（2026-10-10，见 `output/app_screenshot.png`）

- 上传了未入库的 `DL_T_1555-2025_SF6气体泄漏在线监测报警装置运行维护导则.pdf`：14 页，切成 25 块。
  - 首次用命令行入库耗时 20 s；在网页上再次入库时，向量已有缓存，耗时 1.7 s。
- 提问“SF6气体泄漏在线监测报警装置的报警值应如何设置？”
  - 回答：“装置设定的报警值应按DL/T 408 规定执行。[1]”
  - 出处为 8.2 报警监督，p12-13。
  - 总耗时 18.9 s，其中重排 8.6 s。重排期间 CPU 被 LLM 服务分走一部分，所以比单独运行时慢。

### 7.10 运维问答评测集 eval_set_50（50 题 + 5 道拒答）

```bash
python build_eval_set.py      # evalset/items.py → eval_set_50.jsonl / .md / .xlsx（按 evidence 自动定位 chunk_id、页码）
python validate_eval_set.py   # 校验：字段齐全、evidence 是 chunk 原文子串（去空白比较）、类别数量、文档覆盖；退出码 0=通过
python eval50_retrieval.py    # 默认检索（heading+hybrid+rerank）跑 Hit@1/3/5、MRR，写 output/eval50_retrieval.md（不调 LLM，约 5 分钟）
```

**题目构成**

- 50 道库内题：查参数 18 道，故障排查 16 道，操作步骤 16 道。另有 5 道库外拒答题，不计入 50。
- 语言：中文 42 道，英文 8 道。
- 覆盖：19 份已入库 PDF 每份至少 1 题，包括网页上传的 DL/T 1555。

**每题字段**

- 题目与答案：id、category、difficulty（易/中/难）、lang、device、question、reference_answer、key_points（评分要点列表）。
- 出处：
  - source、section、page、evidence（原文摘录）、chunk_id；
  - chunk_heading：切块自带的章节路径；
  - all_chunk_ids：包含 evidence 的所有块。

**答案核实**

- 答案只取原文信息，逐条对照 chunk 原文核实。
- 表格类答案对照 PDF 原件版面（`pdftotext -layout`）核实列对应关系，例如 DL/T 1359 表 3、DL/T 595 表 3、DL/T 724 表 2。

**section 与页码的定位方式**

- **section**：有 15 题手工指定了真实条款。原因是这些切块的 heading_path 有偏差（合并小节或英文手册标题层级不全），原值保留在 chunk_heading 中。
- **page**：在 PDF 原件中搜索 evidence 得到精确页码。正泰 NM1 是扫描件，没有文本层，按 OCR 结果手工指定为第 2 页。

**检索结果**（默认配置，2026-10-10）

| 分组 | Hit@1 | Hit@5 | MRR |
|---|---|---|---|
| 全部 50 题（块级） | 0.80 | 1.00 | 0.892 |
| 文档级 | 0.98 | 1.00 | — |
| 查参数 | 0.72 | 1.00 | 0.861 |
| 故障排查 | 0.94 | 1.00 | 0.969 |
| 操作步骤 | 0.75 | 1.00 | 0.849 |
| 英文 | 0.50 | 1.00 | 0.750 |

- **拒答题**：Top-1 重排分为 0.001–0.065；库内题命中时 Top-1 重排分最低为 0.859。可以考虑设一个重排分阈值（例如 0.3），低于阈值直接拒答，阈值需另行评测确定。

### 7.11 统一评测 evaluate.py 与基线成绩

```bash
python evaluate.py --tag baseline                         # 默认配置全量 55 题（约 26 s/题，约 23 分钟）
python evaluate.py --retrieval-only --tag ret_x --mode dense --no-rerank
python evaluate.py --limit 5 --tag smoke | --refuse-below 0.3 | --provider deepseek --model deepseek-chat | --judge local
python evaluate.py --rescore output/eval_runs/<run目录>   # 改评分规则或人工标注后重算，不重跑生成
```

**输出与缓存**

- 每次运行在 `output/eval_runs/<tag>_<时间>/` 下生成：
  - run_config.json：运行配置；
  - records.jsonl：原始检索和生成结果；
  - per_item.jsonl：逐题评分；
  - summary.json、report.md：汇总与报告。
- 汇总行会追加到 `output/baseline_scores.md`。
- 生成结果缓存在 `output/eval_cache/gen_<配置哈希>.jsonl`。同一配置重跑时会从缓存续跑；配置哈希包含 prompt 哈希，改了 prompt 会自动失效。

**检索指标**

- 块级和文档级的 Hit@1/3/5、MRR（取 Top-10），按类别和语言分组。
- 块级命中：返回块的 chunk_id 属于标注块，或该块来自同一文档且包含 evidence 原文。

**回答自动规则分（v2）**

- 要点评分：
  - 每个 key_point 抽取数值（排除 SO2/T1 这类化学式、符号里的数字；中文数词会换算，如“每五年”）和关键词（jieba 分词，并做同义词归一）。
  - 数值全对且关键词命中达标（有数值时关键词 ≥1/3，纯文字 ≥1/2）记 1 分。
  - 多数值要点答对一半以上记 0.5 分。
- 判定：平均分 ≥0.75 为正确，≥0.4 为部分，否则为错误。
- 拒答的处理：库内题拒答记错误；先作答后又拒答记为“部分”。
- 英文题同时比对中文要点 key_points_zh 和英文要点，取较高分。

**其他指标**

- 引用：引用中是否包含标注文档/标注块、无引用率、引用有效率。
- 拒答：库外题正确拒答率、库内题误拒率。
- 耗时：检索、重排、生成、端到端。

**可选项**

- `--refuse-below`：重排分阈值拒答，默认关闭。
- `--judge`：LLM-as-judge 接口，默认关闭。本地 3B 模型充当评委不可靠，可接 DeepSeek 等，但同样需要人工校准。

**人工标注**

- 人工标注写在 `output/manual_labels.jsonl`。
- 报告中会给出自动评分与人工判定的一致率，并分别列出校准集和留出集。

**基线成绩**（heading+hybrid α=0.5+rerank@20 β=0.8，top_k=5，qwen2.5:3b，2026-10-10；明细见 `output/baseline_scores.md`）

| 分组 | 块 Hit@1 | 块 Hit@5 | 正确 | 部分 | 错误 | 得分 | 引用含标注块 |
|---|---|---|---|---|---|---|---|
| 全部 50 | 80% | 100% | 50% | 36% | 14% | 0.68 | 56% |
| 查参数 | 72% | 100% | 39% | 50% | 11% | 0.64 | 56% |
| 故障排查 | 94% | 100% | 50% | 44% | 6% | 0.72 | 50% |
| 操作步骤 | 75% | 100% | 62% | 12% | 25% | 0.69 | 62% |

- 拒答：库外题拒答率 100%（5/5），库内题误拒率 2%。
- 耗时：平均 26 s/题，其中检索 5.3 s（重排 4.7 s）、生成 20.8 s。

**自动评分可信度**

| 抽查集 | 题数 | 三档一致率 | 二分类一致率 |
|---|---|---|---|
| 校准集（用于调规则，属于样本内） | 18 | 94% | 94% |
| 留出集（调规则后另抽） | 12 | 50% | 67% |
| 合计 | 30 | 77% | 83% |

- 规则偏严：要点里含次要条款时，核心答对也只给“部分”。
- 规则偏松：冗长堆砌或编造的回答，可能因关键词命中而得“部分”。
- 结论：只适合比较不同实验的相对好坏，不能当作绝对准确率。

### 7.12 表格与扫描件（v2 管线：PaddleOCR + 表格结构化 + 表格父子块）

**运行**
```bash
# PaddleOCR 独立环境（主环境 3.13 没有 paddle 轮子），见 requirements.txt 末尾
python ocr.py <扫描件.pdf> --pages 6 --ocr-engine paddle --show     # 单页 OCR + 表格 HTML
python ocr_eval.py --engine rapid --no-cache; python ocr_eval.py --engine paddle --no-cache; python ocr_eval.py --compare
python build_v2.py                       # -> output/chunks_heading_v2.jsonl、uploads/chunks_uploaded_v2.jsonl、output/tables_v2.json、tables_stats.md
python embed_index.py --methods heading_v2 && python bm25_index.py --methods heading_v2   # 新集合 power_heading_v2（旧 power_heading 保留对照）
python evaluate.py --retrieval-only --collection heading_v2 --tag v2_heading_retr
python evaluate.py --ids table --collection heading_v2 --tag v2_table_gen       # 9 道表格题生成评测
```
**OCR 引擎**：`ocr.py --ocr-engine paddle|rapid`（或环境变量 `OCR_ENGINE`），paddle 环境存在时默认 paddle。paddle 以常驻子进程 `paddle/paddle_worker.py` 运行 PP-StructureV3
（PP-OCRv5_server 识别 + PP-DocLayout 版面 + SLANeXt/SLANet_plus 表格结构），表格输出 HTML；表格区域内的文字框不进正文行。入库/建库结束后子进程自动关闭（峰值 RSS ≈4.5 GB）。
正泰 NM1 对比（`output/ocr_compare.md`）：正文 CER Rapid 0.18% / Paddle 0.53%（都 <1%，差 2–3 个字）；第 6 页 63 格尺寸表 Rapid 53/63、Paddle **63/63**；20 页耗时 18 s vs 105 s；内存 0.6 GB vs 4.5 GB。表格是扫描件的主要难点，故默认 Paddle。

**文字型 PDF 表格**（`tables.py`）：PyMuPDF `find_tables()`，按单元格矩形重建网格（被覆盖格判断来自左侧=跨列 / 上方=跨行并复制文字）、合并被细碎线段切开的伪列、
单元格内按基线聚类拼接上下标（SO₂ 不再拆成 "SO\n2"）、多行表头识别（最多 4 行，列名用 "/" 连接）、通栏表注行、跨页续表合并（下页顶部、列数相同、无表题/续表/表号相同/表头相同）。
表题取表格上方 45pt 内的『表N / 表B.3 / Table N』行。表格区域文字从正文流移除，正文中留 `[表N 表题]` 引用。pdfplumber 在 DL/T 724 上碎成 16–38 列且把 "±0.05" 拆成 "±0.0"+"5"，未采用。

**表格切分**：整表 Markdown ≤1200 字一块（chunk_type=table）；更大的表按行组 ≤800 字切，每块重复「表题+页码+章节+表头」；
另为每行生成自然语言描述块（chunk_type=table_row，parent_id 指向所属表格块），如
`表3 SO2 和H2S 的注意值（6 判断依据）：气室类别：断路器灭弧气室；故障组分（μL/L）/SO2：>20；参考组分 （μL/L）/H2S：>20；跟踪要求：2天内复测一次，每月跟踪一次；诊断结果：可能存在故障。`
`retrieve.search(expand_parent=True)` 命中行级块时换成父表（同一父表只保留一次）；`rag.py` 对表格块保留换行与表头（上限 1500 字，超长优先保留命中行），并在有表格时追加“对应行列、写明表头含义”的规则。

**统计**（`output/tables_stats.md`）：19 份文档 230 张表（有表题 93，跨页合并 50）；块数 1410 正文 + 406 表格 + 2046 行级 = 3862。

**评测**（`output/baseline_scores.md`）：
| 集合 | 块Hit@1 | 块Hit@5 | MRR | 9 道表格题 Hit@1 / MRR | 表格题生成 正确/部分/得分 |
|---|---|---|---|---|---|
| heading（v1） | 80% | 100% | 0.892 | 8/9 / 0.944 | 33% / 33% / 0.50 |
| heading_v2 | 78% | 100% | 0.870 | 7/9 / 0.870 | 56% / 11% / 0.61 |
检索名次略降（行级块与整表互相挤占 Top-1），但送进 LLM 的是带表头的完整表，表格题答案明显变好。全量生成见 baseline_scores.md 中 v2_full_gen 一行。

**局限**：find_tables 对无框线/三线表、PDF 里画成图的表无能为力；部分厂商手册的版式框被识别成表（230 张中有一部分是假表，会产生无用的行级块）；
上标单位（10⁻⁶）顺序可能错乱（DL/T 618 表1）；Paddle 在 NM1 第 5 页漏了表头型号并错位一行；Paddle 表题靠版面块判断，仍有 5 张漏标；docx 表格仍按旧方式进正文。

## 8. 已知局限

- 部分厂商手册的图注或零件编号仍可能被误判为标题，例如平高第 37 页的“7 机构外拐臂…”。表格行被拆成多行，表格结构没有保留。
- 正文中的源文件笔误保持原样，例如 DL/T 664 中 6.2.3 下出现的“6.3.3.1”。
- pdf2docx 有时会把标题和正文合进同一段，例如南网 docx 中的“…cy3=0.8;4.2.3 设备…”，这时该标题会漏识别。
- docx 测试件没有 Heading 样式，只能靠编号正则识别标题。用真实 Word 原件（带样式）时，应优先使用样式。
- “句中截断率”的口径是块末字符不是句末标点。标题行和表格行本身就没有标点，所以这个指标只适合在方法之间做相对比较。
- 字号标题模式依赖版式，换一家厂商的手册可能需要调整阈值。
- OCR 的局限：
  - 小号符号容易漏识别（如“+”）。
  - 色块反白的章号偶尔识别不出。
  - 图中标注只做了启发式过滤，第 8、10–13 页这类外形图页仍有少量“十”“一”之类的噪声行。
  - 表格不保留结构。
  - XY-cut 依赖版面空白和竖线，复杂图文混排的页面阅读顺序可能不理想。
  - 平高等文档中“文字很少且含图片”的页同样会触发 OCR；这类页多为照片或图，OCR 后通常只有零星标注。

## 9. 版权说明

- `power_docs/` 中的 PDF 原件不在压缩包内，也不应二次分发。
- `docx_test/` 和 `ocr_out/`（可搜索 PDF）由受版权保护的 PDF 派生，同样不打包。
- `output/` 中的 jsonl 和 parsed 包含原文文本，**仅供个人学习和内部研究使用**，请勿公开发布。
- DL/T 标准的版权归标准出版方所有，厂商手册的版权归各厂商所有。正式上线知识库前，需要确认授权，或者改为只保存索引和链接。

## 表格核对、切分/Prompt 调参与推荐默认（Day 14）

- 表格人工核对：`output/table_audit.md`（抽 18 张表，对照 `output/table_audit/` 下的页面截图）；切分前后对照：`output/table_before_after.md` 和 `table_before_after_page.png`（DL/T 1359 表 3）
- 切分调参：`deploy/tune_chunks.sh`（用 `build_v2.py --max-size --overlap --name` 建独立集合 `power_v2sXXXoYY`，然后跑 retrieval-only），可断点续跑
- 生成评测：`deploy/gen_run.sh <tag> --collection heading_v2 --prompt p0|p1|p2`（缓存键包含 kb_sig，切块文件一变就重新生成）
- 汇总：`python version_scores.py` → `output/version_scores.md` / `.xlsx`；推荐版本的人工抽查见 `output/manual_check_best.md`
- Prompt 版本：p0 是基础规则；p1 在 p0 上加"多子问题逐条作答、步骤按 1.2.3. 编号、数值单位照抄原文"；p2 在 p1 上再加"要点先行 + 总结句 + 格式示例"
- **推荐默认**：heading_v2（max 800 / overlap 50，表格父子块）+ hybrid α0.5 + bge-reranker-v2-m3 Top-20 β0.8 + top_k 5 + Prompt **p1**。`rag.py` / `app.py` 已改为默认 p1，可用 `RAG_PROMPT=p0` 切回 p0；`evaluate.py --prompt` 的默认值仍是 p0，为了能复现历史结果
- 打包：`python deploy/make_zip.py`（会排除 .venv、chroma_db、bm25_index、emb_cache、缓存、pdf/docx、uploads/files）；解压后重建索引：`python build_v2.py && python embed_index.py --methods heading_v2 && python bm25_index.py --methods heading_v2`

## 云端大模型：硅基流动（SiliconFlow）

- 设置环境变量 `SILICONFLOW_API_KEY`（**不要写进代码或文件**），可选 `SILICONFLOW_MODEL`（默认 `deepseek-ai/DeepSeek-V3`，备选 `Qwen/Qwen2.5-72B-Instruct`）
- 命令行：`python rag.py --provider siliconflow "问题"`
- 界面：`app.py` 侧栏"LLM 提供方"选"硅基流动 · DeepSeek-V3"或"硅基流动 · Qwen2.5-72B-Instruct"。Streamlit 进程要能读到这个环境变量，也就是在设置了它的 shell 里运行 `deploy/start_app.sh`
- 评测：`python evaluate.py --tag sf_v3 --collection heading_v2 --prompt p1 --provider siliconflow --workers 4 [--model Qwen/Qwen2.5-72B-Instruct]`
  - 检索和重排串行做，生成按 `--workers` 并发
  - `call_llm` 遇到 429 / 5xx / 网络错误会按 Retry-After 或指数退避重试，最多 6 次
- 三轮串行：`deploy/sf_run.sh`；token 和费用：`python sf_cost.py sf_v3_p1_k5 ...` → `output/sf_usage.json`（按国内站公开价估算，以账单为准）
- LLM 评委：`python judge_eval.py <运行名...>` → `output/judge_eval.md`（DeepSeek-V3 评分，与 manual_labels 对比一致率）
- 默认：本地 p1；云端 provider 未设 RAG_PROMPT 时自动用 p2

## 父子块扩展、拒答阈值、评测集 v3（Day 16）

**上下文扩展**（`context_expand.py`）
- `rag.answer(..., expand="none|neighbor|parent")`，默认取 `RAG_EXPAND`，未设时为 `none`
- `parent`：取命中块所在条款的连续正文块；若本条款只有一块，就上升一级取父条款。单条资料最多 2000 字，超长时以命中块为中心截取；同一父块去重合并；全部资料总长不超过 8000 字
- `neighbor`：命中块加前后相邻块
- 表格块照旧展开为整表
- 评测参数：`evaluate.py --expand parent`。V3+p2 下 none 86% / neighbor 84% / parent 84%，扩展没有收益，输入 token 多 42–57%，所以默认关闭

**拒答阈值**
- `rag.answer(..., refuse_below=0.3)`：重排 Top-1 分低于阈值时直接拒答，不调用 LLM
- 默认 0.3（`RAG_REFUSE_BELOW=off` 关闭，或设成其它数值）
- 扫描结果：`python threshold_scan.py v3set_sf_v3_p2 sf_v3_p2_ood` → `output/threshold_scan.md`、`threshold_curve.png`
- app 侧栏可以调"上下文扩展"、开关阈值、调阈值大小
- 库外 / 边界题：`eval_ood.jsonl`（22 题，`evalset/ood_items.py`；检索核查过程见 `ood_check.py` 和 `output/ood_check.txt`；发现库里其实能答而移出的题记录在 `evalset/ood_removed.json`）

**评测集 v3**（`eval_set_v3.jsonl/.md/.xlsx`）
- 库内 139 题（查参数 55 / 故障排查 41 / 操作步骤 43，英文 19%，多条款综合题 7），另有拒答 5 题
- 题目来源：旧 50 题 + DeepSeek-V3 起草（`gen_eval_items.py`）后人工审阅的 89 题（审阅记录在 `build_eval_v3.py` 的 REVIEW 里）
- 校验：`python validate_eval_set_v3.py`（evidence 必须是原块原文的子串）
- key_points 分 core/minor（`core` 字段是下标）。旧题由 V3 建议、人工复核（`label_core_old.py`）；英文题的中文要点由 `add_kp_zh.py` 生成
- 规则 v3：`evaluate.py --rules 3`，正确 = core 覆盖 ≥0.75，minor 缺失不降级；得分 = 0.8·core + 0.2·minor
- 新基线：`evaluate.py --input eval_set_v3.jsonl --tag v3set --provider siliconflow --prompt p2 --rules 3 --workers 4`
- `--hits-from <旧运行>` 可以复用检索结果，只换 LLM / Prompt / expand 时省掉重排耗时
- `LLM_TIMEOUT`（默认 180 秒）：请求挂起时超时后自动重试

## Day 17：本地提准 5 项（不调云端 API）

全部开关独立、默认关闭（数值校验 v2 除外），均用 `evaluate.py` 体系评测；明细见 `output/xling_retrieval.md`、`output/numcheck_eval.md`、`output/version_scores.md`。

### 1. 跨语言检索（`qx.py` + `dict/term_zh_en.tsv` 344 条）
查询语言检测 → 词典最长匹配翻译（或本地 3B 翻译，缓存于 `emb_cache/qx_llm.json`）→ 原句与译句各跑 dense+BM25 → RRF 合并 → 用原问题统一重排。`--xlang none|dict|llm|auto|auto_llm`。
跨语言集 `eval_xling.jsonl`（36 题，人工把英文原题译成中文、中文原题译成英文，gold 不变），块级 Hit@1 / Hit@5 / MRR：

| 配置 | 全部 36 | 中文问英文档 26 | 英文问中文档 10 |
|---|---|---|---|
| 原语言提问（上界参考） | 69.4% / 88.9% / 0.782 | 76.9% / 92.3% / 0.845 | 50.0% / 80.0% / 0.617 |
| 无改写 | 58.3% / 75.0% / 0.657 | 65.4% / 84.6% / 0.731 | 40.0% / 50.0% / 0.464 |
| xlang=dict | 63.9% / 80.6% / 0.716 | 69.2% / 92.3% / 0.788 | 50.0% / 50.0% / 0.527 |
| xlang=llm（本地 3B） | 63.9% / 83.3% / 0.726 | 69.2% / 96.2% / 0.801 | 50.0% / 50.0% / 0.530 |
| xlang=auto（门控，译句权重 0.7） | 61.1% / 75.0% / 0.666 | 65.4% / 84.6% / 0.726 | 50.0% / 50.0% / 0.512 |

但在 eval_set_v3（139 库内题）上始终开启会让中文题退步：Hit@1 85.0%→76.1%、MRR 0.904→0.837（21 题变差、6 题变好）——译句把英文块挤进重排候选池。门控版本中性（全体 MRR 0.893→0.888），但跨语言收益也一并消失。**结论：不默认**；需要时对“中文问英文手册”场景显式开 `--xlang llm`。

### 2. Contextual 块前缀 + 多查询
`ctx_prefix.py`：规则生成前缀（规范文档名/标准号、设备中英名、章节路径、表题、TF-IDF 关键词 + 词典双语术语），写入新集合 `heading_v2_ctx` 的 embed_text（向量与 BM25 共用；chunk_id 不变）。本地 3B 写主题句实测 7.2 s/块，全库约 7 小时且产出空泛（“片段描述了…”），放弃。
多查询 `--multiq rule`：按问号/分号/连接词拆子问题 + 按意图补“步骤/限值/周期/注意事项”子查询，RRF 合并后统一重排。

| v3 139 题（块级 Hit@1 / Hit@5 / MRR） | 全部 | 中文 | 英文 |
|---|---|---|---|
| 基线 heading_v2 | 83.5% / 97.1% / 0.893 | 85.0% / 98.2% / 0.904 | 76.9% / 92.3% / 0.845 |
| ctx 前缀集合 | 82.0% / 97.8% / 0.890 | 85.0% / 97.3% / 0.900 | 69.2% / 100% / 0.846 |
| 多查询 rule | 77.7% / 95.7% / 0.852 | 79.6% / 96.5% / 0.864 | 69.2% / 92.3% / 0.796 |

ctx 前缀在 v3 上中性（4 题变好 7 题变差），在跨语言集上把中文问英文档的 Hit@5 从 84.6% 提到 96.2%（Hit@1 反降 65.4%→61.5%）；规则多查询退步（子查询主语丢失、噪声候选挤占重排池）。**均不默认**。

### 3. 生成前自检 + 迭代补检（reflect）与 p3
`rag.py --reflect`：LLM 判断资料是否足够并列出 ≤2 个缺失点 → 每点补检 Top-2（≤3 条）追加到上下文。`p3`：先输出【要点清单】再按清单逐条作答（清单不展示、不计分）。
本地 3B、22 题难题子集（V3 基线中“生成漏写/检索失败”的 18 题 + P05/P13/P15/O03），复用同一检索结果，规则 v3：

| 配置 | 正确 | 部分 | 错误 | 得分 | 引用命中 | 生成 s/题 |
|---|---|---|---|---|---|---|
| p1 | 23% | 46% | 32% | 0.455 | 41% | 11.5 |
| p3 | 27% | 55% | 18% | 0.545 | 50% | 26.7 |
| p3 + reflect | 27% | 50% | 23% | 0.523 | 46% | 27.8（+reflect） |

p3 在子集上得分 +0.09（1 题 ≈ 4.5 个百分点，样本小）；reflect 在 9/22 题触发补检，但 3B 的缺失判断粗糙，未带来额外收益、耗时翻倍。**均不默认**，需用云端 V3 在全集上正式评测。

### 4. 数值校验重做（`numcheck.py`，`RAG_NUMCHECK=v2` 默认）
抽“量”（数值+量纲+基准值）：全半角、中文数字、科学计数（含上标）、范围/±（单位作用到两端）、单位换算（kV/V、mA/A、μL/L=ppm、MPa/kPa、h/min/s、年/月、英文 years 等）；忽略标准号、型号、条款号、步骤号、信号编号；表头/“单位：V”/“in years”声明的单位可配裸数值单元格。
回归集 `tests/numcheck_cases.jsonl`：历史全部旧告警 197 条逐条人工标注（120 误报 / 77 真）+ 63 条合成篡改；`pytest tests/test_numcheck.py` 9 项通过。

| 指标 | v1 | v2 |
|---|---|---|
| 误报率 | 120/120 = 100% | 4/120 = 3.3% |
| 漏报率（全部真用例） | 1/138 = 0.7% | 12/138 = 8.7%（历史真告警 0/75，合成 12/63） |
| v3 基线 138 条回答告警数 | 66 | 21 |
| 有告警的回答 | 20% | 9% |

“≤ 300（灭弧气室）+ 表头 μL/L”类误报已消除。漏报来自“整段声明单位 + 裸数值”的宽松匹配。

### 5. 评测拆分
`evaluate.py` 新增 Context Recall（core 要点在 Top-k 上下文中的覆盖）、忠实度（回答实质句数值+关键词能否在上下文中找到，中文词可经词典对上英文上下文）、归因（正确 / 检索失败 / 生成漏写），按中英、表格/文本、题型分桶。`--rescore` 重算 v3 新基线（无 API）：

| 分桶 | 题数 | 正确 | 检索失败 | 生成漏写 | Context Recall | 忠实度 |
|---|---|---|---|---|---|---|
| 全部 | 139 | 85% | 5% | 10% | 95% | 82% |
| 中文 | 113 | 87% | 4% | 9% | 95% | 94% |
| 英文 | 26 | 77% | 8% | 15% | 91% | 31%* |
| 表格题 | 33 | 85% | 12% | 3% | 88% | 78% |
| 文本题 | 106 | 85% | 3% | 12% | 97% | 84% |

*英文题中文作答、英文上下文，规则忠实度只能靠 344 条词典对齐，严重低估。结论：当前瓶颈主要在生成（漏写 10% > 检索失败 5%），表格题则以检索失败为主。

## Day 18：云端验证 p3 与跨语言检索（SiliconFlow DeepSeek-V3）

### ① V3 + p3 / p3 + reflect（eval_set_v3 139 库内 + 5 库外，检索复用 v3set_sf_v3_p2，规则 v3）

| 配置 | 正确 | 部分 | 错误 | 得分 | 引用命中 | 生成漏写 | 检索失败 | 库外拒答 | 误拒 | 生成 s/题 | 费用 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| p2（基线） | 84.9% | 12.2% | 2.9% | 0.910 | 93.5% | 10.1% | 5.0% | 100% | 0.7% | 7.0 | ¥0.68 |
| p3 | 85.6% | 10.1% | 4.3% | 0.906 | 89.2% | 9.4% | 5.0% | 100% | 1.4% | 8.6 | ¥0.76 |
| p3 + reflect | 86.3% | 10.8% | 2.9% | 0.917 | 89.9% | 9.4% | 4.3% | 100% | 0.7% | 11.6 | ≈¥1.24（含自检 ¥0.48） |

逐题（自动评分）：p3 变好 7（P37、F26、F28、F34、F39、O06、O13）/ 变差 8（P20、P31、P35、P47、F05、F24、O03、O40）；p3+reflect 变好 6 / 变差 6，仅 5 题触发补检。
人工核对 p3 全部 15 道变化题：真变好 7（P47 p3 给出正确的 200 kV，p2 的“2007kV”是脚注粘连的错误值却被自动判对；F26 补上“机构未连本体/未充气”核心原因；F28、F34、O06、P37、O13 补全要点），真变差 2（P31 误拒、F05 漏“补气符合 GB/T 12022”），其余 6 道实质相同（自动评分偏严或措辞差异）。人工口径净 +5 题（≈+3.6 个百分点），但新增 1 道误拒、费用 +12%、生成耗时 +23%。
**结论：不设为默认**（自动评分无提升、存在误拒退步，未达到“明确提升且无明显退步”）；作为可选 `--prompt p3`。reflect 收益不抵成本，不默认。

### ② 跨语言检索（问句翻译用 V3，缓存 emb_cache/qx_llm.json）

块级 Hit@1 / Hit@5 / MRR：

| 配置 | 跨语言 36 题 | 其中中文问英文档 26 | 英文问中文档 10 | v3 139 题 | v3 中文 113 |
|---|---|---|---|---|---|
| none | 58.3% / 75.0% / 0.657 | 65.4% / 84.6% / 0.731 | 40% / 50% / 0.464 | 83.5% / 97.1% / 0.893 | 85.0% / 98.2% / 0.904 |
| dict（权重 1.0） | 63.9% / 80.6% / 0.716 | 69.2% / 92.3% / 0.788 | 50% / 50% / 0.527 | 77.0% / 93.5% / 0.841 | 76.1% / 94.7% / 0.837 |
| 本地 3B llm（权重 1.0） | 63.9% / 83.3% / 0.726 | 69.2% / 96.2% / 0.801 | 50% / 50% / 0.530 | 未跑 | — |
| auto 门控（词典，0.7） | 61.1% / 75.0% / 0.666 | 65.4% / 84.6% / 0.726 | 50% / 50% / 0.512 | 82.7% / 96.4% / 0.888 | 85.0% / 97.3% / 0.905 |
| V3 llm（权重 0.7） | 61.1% / 75.0% / 0.667 | 65.4% / 84.6% / 0.731 | 50% / 50% / 0.500 | 81.3% / 95.0% / 0.875 | 81.4% / 95.6% / 0.878 |
| V3 mismatch（Top-5 同语言 <3 才加译句） | 55.6% / 77.8% / 0.644 | 61.5% / 88.5% / 0.718 | 40% / 50% / 0.450 | 82.7% / 97.1% / 0.889 | 85.0% / 98.2% / 0.904 |
| **V3 cap（译句独有候选 ≤30% 重排池）** | **66.7% / 86.1% / 0.745** | **73.1% / 92.3% / 0.814** | **50% / 70% / 0.566** | **84.2% / 97.1% / 0.896** | 85.0% / 98.2% / 0.903 |

注意：V3 llm 一行的译句融合权重是 0.7（Day 17 门控改动时全局改了），与 dict/本地 llm 的 1.0 不可直接比；mismatch/cap 不使用该权重。
cap 在 139 题上逐题：变好 1（F40 未命中→1）、变差 2（P17 2→未进 Top-10、O03 2→3）；中文题持平。
**结论：cap 设为云端默认**（`rag.py`：provider 为 siliconflow/deepseek/openai/xai 且未设 `RAG_XLANG` 时 `xlang=cap`，翻译走同一云端模型；本地默认 none）。成本：每问多 1 次短翻译调用（数十 token，可忽略）+ 1 路检索（CPU 上约 +1–2 s）。
