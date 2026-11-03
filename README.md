# Margin · 科研助手

面向「2026 第九届传智杯 · AI 大模型创新应用挑战赛」的全栈科研助手骨架。  
从文献导入开始，覆盖解析、抗幻觉问答、双语阅读、发现、引用图谱与写作辅助。

> 当前状态：**可运行原型**。已接入 DeepSeek、扫描件 OCR、长文档异步解析、语义去重与 SQLite 持久化。  
> 线上演示：<https://niuchuanbo-margin-research-copilot.ms.show>  
> 项目书：[docs/项目书.md](docs/项目书.md)  
> 后续改进方案：[docs/Qoder后续技术方案.md](docs/Qoder后续技术方案.md)

## 六个模块与页面

| 赛题模块 | 前端页面 | 后端入口 |
|---|---|---|
| PDF 管理与细粒度解析、语义去重 | `/library` | `POST /api/v1/papers`、`POST /api/v1/papers/{id}/parse` |
| 抗幻觉 RAG 与多文推理 | `/chat`、`/reader/:id` | `POST /api/v1/qa/ask`、`/qa/stream`、`/agent/run` |
| 版式阅读、引用跳转、双语联动 | `/reader/:id` | `GET /reader/{id}/anchors`、`POST /reader/translate`、`/reader/translate-text` |
| 论文检索、追踪与推荐 | `/discovery` | `POST /discovery/search`、`/discovery/recommend` |
| 引用图谱、基石节点、综述 | `/graph` | `POST /graph/build`、`POST /graph/{id}/survey` |
| 写作辅助、图脚本、CSV 出图 | `/writing` | `POST /writing/outline`、`/writing/figure`、`/writing/chart` |

## 架构

```text
Vue 3 + Vite + Pinia
  ├─ PDF.js            论文渲染 / 页码 / bbox 高亮
  ├─ ECharts           引用图谱 / CSV 图表
  ├─ KaTeX / Mermaid   公式 / 拓扑图
  └─ fetch + SSE       流式回答与 Agent 过程
            │  /api/v1
FastAPI（Python 3.11+）
  ├─ LangGraph         plan → retrieve → answer → verify
  ├─ LlamaIndex        chunk / index / query
  ├─ Qdrant + BGE-M3   向量检索与重排
  ├─ Docling           PDF 结构化解析（默认后端）
  ├─ RapidOCR / PaddleOCR  扫描件 OCR
  ├─ GROBID            References / 元数据
  ├─ pypdfium2         页面栅格化（避免 PyMuPDF）
  ├─ NetworkX          PageRank / 中心度
  └─ SQLite（本地）/ PostgreSQL / Valkey
```

解析层统一输出：

```json
{
  "paper_id": "…",
  "page": 3,
  "block_id": "b_…",
  "bbox": [72.0, 120.0, 480.0, 300.0],
  "bbox_space": "top-left",
  "section_path": ["3 Method", "3.2 Attention"]
}
```

页码与 bbox 从解析一路传到 RAG 引用、PDF 高亮和引用跳转，是整条链路的共同主线。

## 许可证链路

项目主许可证：**Apache-2.0**（见 [LICENSE](LICENSE)、[NOTICE](NOTICE)）。

| 层 | 选型 | 许可证 |
|---|---|---|
| 前端 | Vue 3 / Vite / Pinia / Vue Router | MIT |
| PDF 渲染 | PDF.js | Apache-2.0 |
| 图表 / 图谱 | ECharts | Apache-2.0 |
| 公式 / 拓扑图 | KaTeX / Mermaid | MIT |
| API | FastAPI / Uvicorn / Pydantic | MIT / BSD-3 / MIT |
| Agent | LangGraph | MIT |
| RAG | LlamaIndex | MIT |
| 向量库 | Qdrant | Apache-2.0 |
| 元数据 | PostgreSQL | PostgreSQL License |
| 本地持久化 | SQLite | Public Domain |
| 缓存队列 | Valkey | BSD-3-Clause |
| Embedding / Rerank | BGE-M3 / bge-reranker | MIT |
| PDF 解析 | Docling | MIT |
| OCR | RapidOCR / PaddleOCR | Apache-2.0 |
| OCR 运行时 | ONNX Runtime / OpenCV | MIT / Apache-2.0 |
| 参考文献 | GROBID | Apache-2.0 |
| 页面栅格 | pypdfium2 | Apache-2.0 / BSD-3 |
| 评测 | RAGAS（预留） | Apache-2.0 |
| 图表导出 | Matplotlib / ReportLab（预留） | PSF / BSD-3 |

**不进入主进程的 AGPL/GPL 组件**：MinerU、PDFMathTranslate / BabelDOC、PyMuPDF、gpt_academic。若使用，必须作为独立进程/容器并在 `THIRD_PARTY_NOTICES.md` 中声明，不能 import 到 Apache-2.0 代码中。

模型权重有各自的 Hugging Face 许可证，和代码许可证分开核对。

## 快速开始

### 1. 环境变量

```bash
cp .env.example .env
```

Windows：

```bash
copy .env.example .env
```

至少填写 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 才会有生成式回答；不填时走抽取式降级。

常用服务商（都是 OpenAI 兼容接口，改这三项即可）：

| 服务商 | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:7b`（Key 可填 `ollama`） |

改完 `.env` 需要重启后端。连通性检查（不会打印 Key）：

```bash
cd backend && python check_llm.py
```

### 2. Docker（推荐先跑通服务）

```bash
docker compose up --build
```

- 前端：http://localhost:5173
- API 文档：http://localhost:8000/docs
- Qdrant：http://localhost:6333
- GROBID：http://localhost:8070

生产构建：

```bash
docker compose -f docker-compose.prod.yml up --build
```

前端在 http://localhost:8080。

### 3. 本地开发

后端需要 Python 3.11+：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

装上重型能力（可选，首次安装较大）：

```bash
pip install -e ".[parsing,rag,agent]"
```

启动：

```bash
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 长文档处理

541 页《Understanding Deep Learning》实测：

| 指标 | 结果 |
|---|---|
| 页数 / 文本块 | 541 页 / 2120 块 |
| 解析引擎 | `pypdfium2+rapidocr`（537 页走文本层，4 页无文本走 OCR） |
| 解析总耗时 | 约 14 秒 |
| 后端内存 | 约 165 MB |
| 目录 | 442 个标题节点（1–3 级） |
| 定位锚点 | 2120/2120 块带 bbox，2092 块带章节路径 |
| 单页 QA | `deepseek-chat`，bias-variance 问题引用第 139–147 页 |

实现方式：

- `POST /api/v1/papers/{id}/parse` 立即返回 `job`，不阻塞请求；`GET /api/v1/papers/{id}/parse-status` 轮询进度。
- 解析逐页进行；`pypdfium2` 有文本层时不跑 OCR，只有无文本页才走 RapidOCR。
- 超过 100 页的文档，References 兜底只扫描末尾 60 页；OCR 默认最多 80 页（`OCR_MAX_PAGES`）。
- 阅读器不拉整篇 blocks：`GET /papers/{id}?include_blocks=false` + `GET /papers/{id}/blocks?page=N`。
- 前端刷新后会对 `parsing` 状态的论文重新查询任务并恢复轮询。

可调参数：

```text
DOCLING_MAX_PAGES=60   # 不超过该页数才尝试 Docling
OCR_MAX_PAGES=80       # 长扫描件最多 OCR 的页数；0 表示不限制
```

## 去重处理

- 解析任务完成时返回 `dedup`：相似度、候选论文、建议动作（`replace` / `keep` / `warn`）。
- 内容相似度使用 5-gram Jaccard，阈值 0.62；`1706.03762v1` 与 `v7` 实测相似度 **0.7174**。
- 版本号从文件名/标题中提取，较新版本会建议覆盖，较旧版本会建议保留。
- 前端提示条提供三个操作：**用新版覆盖**、**保留两者**、**稍后处理**；覆盖前有二次确认。
- `POST /api/v1/papers/{id}/dedup` 执行动作：
  - `replace`：删除旧论文文件、从内存索引/ Qdrant 中移除旧块，只保留新版本。
  - `keep`：两个版本都保留。

## 本地持久化

本机没有 PostgreSQL/Qdrant 服务，默认使用 **SQLite**（Python 标准库，零额外服务）：

- 数据库：`DATA_DIR/margin.db`（默认 `./data/margin.db`，WAL 模式）
- `papers` 表：论文、blocks、references、metadata 的 JSON payload
- `parse_jobs` 表：解析任务与进度
- 启动时：加载论文与任务；把中断的 `parsing/running` 标记为失败；对 ready 论文重建检索索引
- 上传、解析完成、去重删除都会立即落盘
- 正常停止服务时关闭 SQLite 连接并合并 WAL；备份时拷贝整个 `data/` 目录
- PostgreSQL / Qdrant 仍是生产替换项：`PaperStore`、`JobStore`、`IndexStore` 的接口保持不变，后续替换实现即可

## 降级行为

骨架在依赖未就绪时仍可启动：

- 没有 Docling → 尝试 `pypdfium2` 文本层 → 再尝试 RapidOCR（本地 ONNX）→ PaddleOCR。
- 没有 GROBID → 从 `References` 段落做正则抽取。
- 没有 Qdrant / BGE-M3 → 使用内存关键词索引。
- 没有 LangGraph → 顺序执行 plan → retrieve → answer → verify。
- 没有 LLM → 抽取式回答，仍带页码/片段引用。
- 没有 PostgreSQL → 使用内存 `PaperStore`；数据库模型已放在 `app/db/models.py`。

## 目录

```text
backend/
  app/
    api/v1/          papers / qa / reader / discovery / graph / writing / health
    agent/           LangGraph 状态机、工具注册表、意图路由与沙箱执行器
    services/        parsing / dedup / indexing / qa / translation / discovery / graph / writing
    models/          Pydantic 数据契约
    db/              PostgreSQL 模型与会话（可选）
    workers/         离线解析 CLI
  tests/
frontend/
  src/
    views/           六个模块页面
    components/      PDF 阅读器、图谱、图表、引用、Mermaid
    stores/          Pinia
    api/             REST + SSE
pdf/                 官方测试 PDF 放置说明（*.pdf 不进仓库）
```

## API 速查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 能力探测与降级状态 |
| GET | `/api/v1/papers` | 论文列表 |
| POST | `/api/v1/papers` | 上传 PDF |
| POST | `/api/v1/papers/{id}/parse` | 启动解析任务（返回 job，不阻塞） |
| GET | `/api/v1/papers/{id}/parse-status` | 解析进度 |
| POST | `/api/v1/papers/{id}/dedup` | 处理重复：`action=replace/keep` |
| GET | `/api/v1/papers/{id}/versions` | 同源旧版本列表（相似度 ≥0.45） |
| GET | `/api/v1/papers/{id}/diff/{old_id}` | 两版段落级差异 + LLM 修订总结 |
| GET | `/api/v1/papers/{id}?include_blocks=false` | 论文元数据（长文档用） |
| GET | `/api/v1/papers/{id}/blocks?page=N` | 按页取文本块 |
| GET | `/api/v1/papers/{id}/file` | 原始 PDF |
| POST | `/api/v1/qa/ask` | 带引用的回答 |
| POST/GET | `/api/v1/qa/stream` | SSE 流式回答 |
| POST | `/api/v1/agent/run` | SSE Agent 工具调用（plan → tool_* → answer） |
| GET | `/api/v1/reader/{id}/anchors` | 文本块 + 页码 + bbox |
| GET | `/api/v1/reader/{id}/outline` | 标题树（1–3 级） |
| GET | `/api/v1/reader/{id}/references` | 参考文献条目 + 页码 + bbox |
| POST | `/api/v1/reader/translate` | 双语块翻译 |
| POST | `/api/v1/reader/translate-text` | 局部划词翻译 |
| POST | `/api/v1/discovery/search` | arXiv / OpenAlex |
| POST | `/api/v1/discovery/recommend` | 基于书架推荐 |
| POST | `/api/v1/graph/build` | 引用图谱 |
| POST | `/api/v1/graph/{id}/survey` | 综述草稿（LLM，带证据约束） |
| POST | `/api/v1/graph/{id}/future-work` | 提取 Future Work 并合并相似方向 |
| POST | `/api/v1/writing/outline` | 论文大纲 |
| POST | `/api/v1/writing/figure` | Mermaid / Graphviz / TikZ |
| POST | `/api/v1/writing/chart` | CSV → 折线/柱状/雷达图 + LLM 图注 |

## 检索（混合打分）

问答检索默认使用**三路混合打分**（无需外部服务）：

- **BM25**：纯 Python 实现（k1=1.5, b=0.75），文档频率随入库/删除增量维护；
- **关键词重叠**：沿用原稀疏重叠分（含整串命中加成）；
- **向量余弦**（可选）：配置 `EMBEDDING_BASE_URL` 后调用 OpenAI 兼容 `/embeddings`，补齐同义改写召回；未配置时自动跳过，BM25 与重叠按 0.6/0.4 加权，向量开启后按 0.5/0.3/0.2 加权。

三路候选各自 min-max 归一化后合并，同一 `(paper_id, block_id)` 只保留最高分。多篇问答仍按篇召回后合并，避免单一论文占满上下文。

金标回归（21 条问题，页码均取自真实解析数据）：

```bash
cd backend
python scripts/eval_golden.py            # 期望 Top-5 页面命中率 >= 80%
python scripts/eval_golden.py --legacy   # A/B 对比旧的重叠检索
```

## 版本差异

同一论文的不同版本（如 arXiv v1/v7）入库后，阅读器工具栏出现「版本差异」入口：

- **同源发现**：基于标题/文件名与正文重叠度（≥0.45）自动列出旧版本；
- **段落对齐**：5-gram Jaccard + 倒排 shingle 索引做段落级贪心对齐，按相似度分类为新增（<0.35）、改写（0.35–0.85）、删除，未变化段落（≥0.85）不展示；
- **LLM 修订总结**：将差异清单交给 LLM 生成中文总结，页码标签（`[新版 p.X]`/`[旧版 p.Y]`）经正则校验后展示；未配置 LLM 时回退到确定性统计总结；
- **交互**：三组折叠列表，点击条目跳转对应页并高亮 bbox。

验证（真实数据 v1/v7）：整体相似度 0.7174，47 处变化（25 改写 / 14 新增 / 8 删除），每条差异均带页码锚点。

## Agent 工具调用

问答页提供「快速问答 / Agent 模式」开关。Agent 模式把自然语言请求编排成工具计划执行：

- **意图路由**：规则优先（arXiv 下载/检索、CSV 出图、版本对比、大纲、综述、未来方向、图谱、Python 计算），未命中时由 LLM Planner 生成计划（严格 JSON，最多 3 步），仍失败则回退到库内问答 `library.answer`；
- **工具注册表**（10 个）：`library.search` / `library.answer`、`arxiv.search` / `arxiv.download`、`graph.build` / `graph.survey` / `graph.future_work`、`writing.outline` / `writing.chart`、`python.exec`；
- **Python 沙箱**：AST 白名单（仅 `math/statistics/csv/json/io/re`，禁 `open/eval/exec`、下划线属性、装饰器等）+ 独立子进程（`python -I`）+ 8 秒超时 + 8KB 输出截断，用户代码绝不进入 API 进程；
- **SSE 过程**：`plan → tool_start/tool_result* → answer → citations → done`，前端实时追加工具名、参数摘要与结果摘要到过程面板，不展示内部数据；
- **去书架**：`arxiv.download` 成功后自动解析入库（后台任务），回答中给出「去书架查看」入口；
- **占位符**：计划支持 `$graph_id` 等上一步产出引用（如 `graph.build → graph.survey`）。

## 阅读交互

阅读页采用「PDF 左 + 双语右」双栏（<1100px 回退为上下布局）：

- **双语对照**：右侧按页码分组展示原文块与译文，可逐页翻译并累积（跨页保留）；未配置 LLM 时逐块提示，不整页报错；
- **同步滚动**：PDF 翻页时右侧自动定位到对应页码分组；手动滚动右侧分组时经 `IntersectionObserver` 反驱 PDF 翻页（`syncing` 抑制回环）；
- **正文 `[n]` 引用**：原文中的 `[数字]` 渲染为按钮，点击后滚动参考文献面板并高亮对应条目；条目带 bbox 时同步跳转 PDF 页并高亮；
- **悬停翻译**：鼠标在未翻译原文块停留 500ms 即出 popover 译文（`translate-text`），结果按文本哈希缓存，同一段不重复请求，失败可点重试；
- **局部翻译**：选中或粘贴文本翻译，与悬停翻译共用缓存。

## 测试数据

把组委会 `pdf/` 目录中的文件放到本仓库 `pdf/`（已 gitignore）：

- `1706.03762v1.pdf` / `v7.pdf`：去重与版本对比
- `1706.03762v1_img.pdf`：扫描件 OCR

本地没有官方扫描件时，可用 `pdf/1706.03762v1_img_test.pdf`（由 v1 渲染的无文本层代理样本，3 页）验证 RapidOCR；该文件已被 gitignore。
- `UnderstandingDeepLearning_02_09_26_C.pdf`：541 页长文档

离线验证解析：

```bash
cd backend
python -m app.workers.parse_cli ../pdf/1706.03762v1.pdf --blocks 5
```

## 官方测试集回归（2026-11-03）

本地以组委会 `pdf/` 目录的 39 篇论文跑通六大模块：

| 用例 | 结果 |
|---|---|
| 批量导入 | 39/39 解析成功（38 篇文本层 + 1 篇纯扫描） |
| v1 / v7 语义去重 | 5-gram Jaccard **0.7174**；上传旧版时建议保留新版 |
| 扫描件 `1706.03762v1_img.pdf` | RapidOCR 15/15 页、955 块、161.7 秒，全部带 bbox |
| 文本层 `1706.03762v1.pdf` | 101 块；101/101 带 bbox，100/101 有章节路径 |
| 541 页 UDL | 2120 块、约 14 秒；537 页文本层 + 4 页 OCR；442 个标题节点 |
| 单篇问答 | β1=0.9、β2=0.98、ε=1e-9、28.4 BLEU、8×P100/3.5 天，均带页码与 bbox |
| 多篇问答 | GPT-1 / GPT-3 / BERT / Transformer 四篇联合检索；按论文分别召回后合并，避免单一论文占满上下文 |
| 引用图谱 | 39 篇 → 361 节点 / 803 条边；PageRank 3.0 秒 |
| 综述 / 未来方向 | LLM 综述 6845 字符；Future Work 抽取 10 条并按相似度合并 |
| 写作 | LLM 大纲 7 节并绑定库内引用；折线/柱状/雷达图 + LLM 图注 |
| 检索推荐 | arXiv / OpenAlex 各 5 条；推荐结果优先展示带 GitHub 链接的论文 |

## 测试与检查

```bash
cd backend && pytest
cd backend && ruff check .
cd frontend && npm run typecheck
cd frontend && npm run build
```

## 开发说明

界面设计按 `frontend-design` 的“阅读桌 / 边际注记”方向实现；图表配色使用 `dataviz` 校验过的分类色板（前三个槽位通过 all-pairs 检查，后续槽位配数据表）。问答提示词中的来源标记与不确定性约定参考了本地 `paper-analyst` 技能（MIT），文献调研流程参考了本地 `shidi` 技能（MIT）。这些技能是本地开发工具，不随仓库分发。

## 许可证

Apache-2.0，Copyright 2026 niuchuanbo。第三方组件与技能声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
