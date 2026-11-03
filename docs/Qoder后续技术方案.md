# Margin 后续改进技术方案（交付 Qoder 执行）

> 项目：Margin 科研助手（2026 传智杯 AI 大模型创新应用挑战赛）  
> 工作目录：`E:\project\传智杯大赛`  
> 配合阅读：`README.md`、`docs/项目书.md`、`backend/app/`、`frontend/src/`  
> 文档日期：2026-11-03

---

## 0. 给 Qoder 的使用说明

这份文档是任务书，不是宣传材料。请**一次只做一个任务（T1–T6）**，不要顺手重构无关模块。

每个任务开始前：

1. 先读该任务对应的现有文件，确认行号与实现与本文一致；
2. 先跑一遍基线测试，确认改动前是绿的；
3. 只改任务列出的文件范围，需要扩大范围时先在回复里说明理由；
4. 完成后跑验收命令，贴出结果，并单独提交一个 commit。

每个任务结束的标准：

- `pytest`、`ruff`、`npm run typecheck`、`npm run build` 全部通过；
- 新增接口有 Pydantic 契约，前端类型同步更新；
- 不引入密钥、不引入 AGPL 组件、不破坏现有接口；
- 给出“改了什么、怎么验证、还有什么没做”的三段式总结。

---

## 1. 项目现状

### 1.1 技术栈

- 前端：Vue 3 + Vite + TypeScript + Pinia + Vue Router
- 后端：FastAPI + Pydantic v2 + Uvicorn
- Agent：LangGraph（`plan → retrieve → answer → verify`），缺失时顺序执行
- 解析：pypdfium2 文本层 + 字符坐标；RapidOCR 仅处理无文本页
- 检索：内存稀疏索引；Qdrant/BGE-M3 是可选适配器，本地未安装
- 图论：NetworkX PageRank；缺 SciPy 时纯 Python PageRank
- 存储：SQLite（WAL），`papers` + `parse_jobs` 两张表
- 模型：OpenAI 兼容接口，当前 DeepSeek `deepseek-chat`
- 部署：Docker 单容器，7860 端口，魔搭创空间

### 1.2 本地环境（Windows，务必按此路径）

Python 不在 PATH，必须用 embeddable 解释器：

```bash
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe"
```

后端启动（测试数据目录与默认数据隔离）：

```bash
cd "E:/project/传智杯大赛/backend"
DATA_DIR="E:/project/传智杯大赛/data/eval" \
UPLOAD_DIR="E:/project/传智杯大赛/data/eval/uploads" \
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe" \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端（开发代理默认指向 8000）：

```bash
cd "E:/project/传智杯大赛/frontend"
npm run dev
```

基线检查：

```bash
cd "E:/project/传智杯大赛/backend"
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe" -m pytest -q
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe" -m ruff check .

cd "E:/project/传智杯大赛/frontend"
npm run typecheck
npm run build
```

Windows 控制台输出中文/希腊字母时加 `-X utf8` 并设置 `PYTHONIOENCODING=utf-8`，否则会 `UnicodeEncodeError`。

### 1.3 关键代码地图

| 位置 | 作用 |
|---|---|
| `backend/app/services/parsing.py` | 逐页解析、bbox、章节栈、参考文献、标题提取 |
| `backend/app/services/dedup.py` | 5-gram Jaccard、版本判断 |
| `backend/app/services/indexing.py` | Chunk、内存稀疏索引、Qdrant 适配 |
| `backend/app/services/qa.py` | 检索、邻块扩展、多篇按篇召回、引用、grounded |
| `backend/app/agent/graph.py` | LangGraph 四节点与顺序回退 |
| `backend/app/agent/state.py` | `AgentState` TypedDict |
| `backend/app/agent/prompts.py` | 问答/翻译/大纲提示词 |
| `backend/app/api/v1/papers.py` | 上传、异步解析、去重动作、标题派生 |
| `backend/app/api/v1/reader.py` | anchors/outline/references/translate/translate-text |
| `backend/app/api/v1/graph.py` | 图谱构建、LLM 综述、Future Work |
| `backend/app/api/v1/writing.py` | 大纲、图脚本、CSV 图表 |
| `backend/app/services/writing.py` | 大纲 LLM、图表 option、图注 |
| `backend/app/services/jobs.py` | 解析任务与 SQLite 进度 |
| `backend/app/store.py` | 论文 SQLite 仓库与启动恢复 |
| `frontend/src/views/ChatView.vue` | 问答页，已渲染 `AgentTrace` |
| `frontend/src/views/ReaderView.vue` | PDF、目录、参考文献、翻译 |
| `frontend/src/views/GraphView.vue` | 图谱、基石节点、综述、Future Work |
| `frontend/src/views/WritingView.vue` | 大纲、图脚本、CSV 图表 |
| `frontend/src/api/endpoints.ts` | REST 封装 |
| `frontend/src/api/sse.ts` | SSE 封装 |
| `frontend/src/stores/chat.ts` | 问答状态与 trace |

### 1.4 当前明确缺口

1. 检索是关键词重叠，不是混合检索，同义改写召回弱。
2. Agent 是固定四步，没有意图路由、工具调用循环、Python 执行。
3. v1/v7 只做去重，没有版本差异总结。
4. 阅读器没有中英双栏同步滚动、正文 `[n]` 点击、PDF 悬停翻译。
5. 表格/公式只作为文本块，未结构化。
6. SSE 是算完后分片，不是真正的 token 流式。
7. 免费创空间可能被回收，需要保活/备用部署。

---

## 2. 改进目标与优先级

按赛题评分权重排序，不要平铺做：

| 优先级 | 任务 | 对应评分点 | 预计工期 |
|---|---|---|---|
| P0 | T3 工具调用 Agent | Agent 编排 9% + Function Calling 6% | 5–7 天 |
| P1 | T2 版本差异总结 | 技术创新 8% | 2 天 |
| P1 | T1 混合检索 | 抗幻觉 RAG 8% | 2 天 |
| P2 | T4 阅读交互 | 交互创新 7% | 3 天 |
| P3 | T5 解析增强（表格/公式） | 多模态解析 7% | 3–5 天，风险高 |
| P3 | T6 稳定性与保活 | 工程鲁棒 3% + 演示可用 | 2 天 |

建议顺序：**T1 → T2 → T3 → T4 → T6 → T5**。  
T1/T2 改动小、可快速提升；T3 是最大分值块，需要完整时间；T5 是加分项，不要在截止前动大手术。

---

## 3. 目标架构

```text
用户请求
  │
  ▼
Agent Router（新增）
  ├─ 规则优先：显式指令（下载/对比/画图/综述/大纲/图谱）
  └─ LLM Planner 兜底：输出最多 3 步工具调用 JSON
  │
  ▼
Tool Registry（新增）
  ├─ library.search / library.answer
  ├─ arxiv.search / arxiv.download
  ├─ graph.build / graph.survey / graph.future_work
  ├─ writing.outline / writing.chart
  └─ python.exec（受限沙箱）
  │
  ▼
Executor（新增）
  ├─ 顺序执行、上下文传递、超时与错误边界
  └─ 产出 trace 事件（plan/tool_start/tool_result/answer）
  │
  ▼
现有 QA / 图谱 / 写作能力（复用，不重写）
```

原则：**不要另起一套 RAG**。T3 的工具内部调用现有 `retrieve_hits`、`answer_from_hits`、`build_citation_graph`、`build_outline_llm`、`csv_to_chart_llm`。

---

## 4. 任务清单

### T1 混合检索（BM25 + 稀疏重叠 + 可选向量）

**目标**：在不引入外部服务的前提下，提高同义改写与长句查询的召回。

**改动文件**

- `backend/app/services/indexing.py`
- `backend/app/services/qa.py`
- `backend/app/core/config.py`
- `backend/tests/test_indexing.py`

**实现步骤**

1. 在 `indexing.py` 增加纯 Python BM25：
   - `k1=1.5`, `b=0.75`；
   - 复用现有 `_tokens()`；
   - 维护 `df`、`avgdl`，在 `upsert_paper/remove_paper` 时增量更新；
   - 提供 `search_bm25(query, paper_ids, top_k)`。
2. 增加 `search_hybrid`：
   - 现有重叠分数与 BM25 分数分别 min-max 归一化；
   - `score = 0.6 * bm25 + 0.4 * overlap`；
   - 同一 `(paper_id, block_id)` 去重，保留最高分；
   - 可选 `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL`：配置后调用 OpenAI 兼容 `/embeddings`，用余弦相似度做第三路，未配置则跳过，不引入新依赖。
3. `qa.retrieve_hits` 改为调用 `search_hybrid`；多篇按篇召回逻辑保持不变。
4. 增加 `backend/tests/test_indexing.py`：
   - BM25 对精确术语的排序；
   - 混合分数对同义改写的排序（构造两条块，一条关键词命中、一条语义相近）；
   - `paper_ids` 过滤生效。

**验收**

- 20 条金标问题（见 7.2）Top-5 页面命中率 ≥ 80%；
- 现有 19 个测试全绿；
- 没有新增第三方依赖。

**禁止**

- 不要在此任务里改前端；
- 不要强行安装 `rank_bm25`、`sentence-transformers`、`qdrant-client`。

---

### T2 v1/v7 版本差异总结

**目标**：赛题明确要求的“高级表现”——自动对比并总结两个版本的主要修订差异。

**改动文件**

- 新增 `backend/app/services/version_diff.py`
- `backend/app/api/v1/papers.py`
- `backend/app/models/schemas.py`
- `backend/app/services/llm.py`（如需新增 `chat_json` 辅助）
- `frontend/src/api/endpoints.ts`
- `frontend/src/types/index.ts`
- `frontend/src/views/ReaderView.vue` 或 `LibraryView.vue`（二选一，建议阅读器）

**实现步骤**

1. 段落对齐：
   - 取 `kind in {paragraph, heading}` 的块；
   - 归一化后 5-gram Jaccard；
   - 贪心匹配：每段找相似度最高的未匹配段；
   - 分类：`added`（<0.35）、`modified`（0.35–0.85）、`removed`（<0.35 且未被匹配）、`unchanged`（≥0.85，不输出）。
2. 差异对象必须带锚点：

```python
class VersionChange(BaseModel):
    kind: Literal["added", "removed", "modified"]
    new_page: int | None
    new_bbox: list[float] | None
    old_page: int | None
    old_bbox: list[float] | None
    new_text: str | None
    old_text: str | None
    similarity: float
```

3. LLM 总结：
   - 输入只给差异列表（每条截断 500 字），要求输出中文 Markdown；
   - 必须按“新增 / 删除 / 改写”分组，每条后用 `[新版 p.X]` 或 `[旧版 p.Y]` 标注；
   - 不得编造差异；证据不足写“未检测到明确差异”；
   - 失败时回退到确定性摘要（计数 + 前 5 条差异）。
4. API：`GET /papers/{new_id}/diff/{old_id}`，返回 `{new_id, old_id, similarity, changes, summary}`。
5. 前端：
   - 阅读器顶部增加“版本差异”按钮（仅当库中存在同源版本时显示）；
   - 三组折叠列表，点击条目跳对应页并高亮 bbox；
   - 显示 LLM 总结。

**验收**

- 对 `1706.03762v1.pdf` 与 `1706.03762v7.pdf` 返回至少 5 条差异；
- 每条差异至少一侧有页码；
- 总结中出现的页码都能在 changes 中找到；
- 前端 typecheck/build 通过。

---

### T3 工具调用 Agent（核心任务）

**目标**：把固定四步问答升级为“意图识别 → 工具调用 → 结果汇总”的可观测 Agent，覆盖赛题的 Tool Use 与 Environment Interaction。

#### T3.1 目录与契约

新增：

```text
backend/app/agent/tools/__init__.py
backend/app/agent/tools/base.py
backend/app/agent/tools/library.py
backend/app/agent/tools/arxiv.py
backend/app/agent/tools/graph.py
backend/app/agent/tools/writing.py
backend/app/agent/tools/python_exec.py
backend/app/agent/router.py
backend/app/agent/executor.py
backend/app/api/v1/agent.py
```

`base.py`：

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str
    data: dict[str, Any] = {}
    citations: list[dict] = []
    artifacts: list[dict] = []

class Tool(BaseModel):
    name: str
    description: str
    args_model: type[BaseModel]
    async def run(self, args, context) -> ToolResult: ...
```

`context` 至少包含：`paper_ids`、`question`、`user_language`、`history`（上一工具结果摘要）。

#### T3.2 工具定义（复用现有服务）

| 工具 | 参数 | 内部调用 | 返回 |
|---|---|---|---|
| `library.search` | query, paper_ids?, top_k? | `retrieve_hits` | 命中片段 + 页码 |
| `library.answer` | question, paper_ids? | `answer_from_hits` | answer + citations + grounded |
| `arxiv.search` | query, limit? | `discovery.search_arxiv` | 论文列表 |
| `arxiv.download` | arxiv_id 或 title | `discovery.search_arxiv` → 下载 PDF → 走现有上传/解析逻辑 | paper_id + 解析状态 |
| `graph.build` | paper_ids | `build_citation_graph` | graph_id + 摘要 |
| `graph.survey` | graph_id | `_llm_survey` 的公开封装 | markdown |
| `graph.future_work` | graph_id | `_future_work_items` | 方向列表 |
| `writing.outline` | idea, paper_ids? | `build_outline_llm` | 大纲 |
| `writing.chart` | csv, title?, chart_type? | `csv_to_chart_llm` | option + caption |
| `python.exec` | code, stdin? | 受限子进程 | stdout + 结构化结果 |

`arxiv.download` 限制：

- 只允许 `https://arxiv.org/pdf/<id>`；
- 文件 ≤ 40MB；
- 下载后保存到 `UPLOAD_DIR`，复用 `parse_pdf` 与 `paper_store.update`；
- 解析可同步等待 ≤ 120 秒，超时返回 job，不阻塞 HTTP 太久。

`_llm_survey` 与 `_future_work_items` 目前在 `app/api/v1/graph.py`。开始 T3 前先把它们抽到 `backend/app/services/research_tools.py`，让 API 与工具层共用，禁止在工具里 import API 模块。

#### T3.3 Python 执行沙箱

这是唯一有安全风险的工具，必须按下面实现，**不要简化**：

- 独立子进程：`sys.executable -I -c <runner>`；
- 超时 8 秒，超时杀进程；
- 输出 stdout 最大 8KB，超出截断；
- 工作目录为临时目录，任务结束删除；
- AST 白名单：只允许 `ast.Expression/Module`, 赋值、算术、比较、循环、函数定义、`math/statistics/csv/json/io/re` 导入；
- 禁止：`import os/sys/subprocess/socket/urllib/requests/httpx/pathlib/shutil`, `open`, `eval`, `exec`, `compile`, `__import__`, 属性名以 `_` 开头；
- 不做网络访问；
- 失败返回结构化错误，不把 traceback 原样抛给前端。

验收用例：

```python
# 允许
data = [1,2,3,4]
print(sum(data)/len(data))
```

```python
# 拒绝
import os
os.system("dir")
```

#### T3.4 路由与规划

`router.py`：

1. 规则优先（覆盖 80% 明确指令）：
   - 含“下载 / 入库 / 抓取” → `arxiv.download`
   - 含“对比 / 差异 / 版本” → 版本差异或 `library.answer`
   - 含“画图 / 图表 / CSV” → `writing.chart`
   - 含“综述 / 基石 / 图谱 / 未来方向” → graph 工具
   - 含“大纲 / 参考文献格式” → `writing.outline`
   - 其余 → `library.answer`
2. 规则未命中时调用 LLM Planner：
   - 输出严格 JSON：`{"intent":"...","steps":[{"tool":"...","args":{...}}]}`；
   - 最多 3 步；
   - 工具名必须在注册表中，参数用对应 `args_model` 校验；
   - 解析失败回退 `library.answer`。
3. 不要在 Planner 里透传完整论文正文；只给论文标题、摘要前 200 字、可用工具清单。

#### T3.5 执行器与 SSE

`executor.py`：

```python
async def run_plan(plan, context, emit) -> AgentRunResult:
    for step in plan.steps:
        await emit("tool_start", {"tool": step.tool, "args": step.args})
        result = await registry[step.tool].run(step.args, context)
        await emit("tool_result", {"tool": step.tool, "summary": result.summary})
        context.history.append(result.summary)
        if not result.ok:
            break
    return ...
```

新增 `POST /api/v1/agent/run`（SSE）：

- 事件顺序：`plan` → `tool_start` / `tool_result`（可多次）→ `answer` → `citations` → `done`；
- `done` 中包含 `trace`（字符串数组），前端直接复用 `AgentTrace`；
- 保留 `POST /qa/ask` 不变，`/agent/run` 是增量能力。

#### T3.6 前端

- `ChatView.vue` 增加开关“Agent 模式 / 快速问答”；
- Agent 模式调用 `agent/run`，把 `tool_start/tool_result` 追加到 message.trace；
- 显示工具名、参数摘要、结果摘要；不展示完整内部数据；
- 下载类工具成功后提供“去书架”链接。

#### T3.7 验收

- 12 条意图测试中 ≥ 10 条路由正确（见 7.3）；
- “下载 arXiv 1706.03762 并入库”能完成：搜索 → 下载 → 解析 → 返回 paper_id；
- “把这段 CSV 画成雷达图”能返回 ECharts option + 图注；
- 恶意 Python 用例被拒绝；
- 原有 `/qa/ask`、`/qa/stream` 测试不回归。

---

### T4 阅读交互

**目标**：补齐赛题明确要求的“中英双栏 + 同步滚动 + 正文引用跳转 + 划词翻译”。

**改动文件**

- `frontend/src/views/ReaderView.vue`
- `frontend/src/components/PdfViewer.vue`（如需滚动事件）
- `frontend/src/api/endpoints.ts`
- 可能新增 `frontend/src/components/BilingualPane.vue`

**实现步骤**

1. 双栏布局：PDF 左、双语右；窄屏（<1100px）回退为上下布局。
2. 同步滚动：
   - 先做页级同步：PDF 翻页时，右侧滚动到对应页码的翻译组；
   - 再做块级同步：用 `IntersectionObserver` 监听右侧块，当前块对应的 `page` 变化时切换 PDF 页；
   - 避免双向循环触发：用 `syncing` 标志位。
3. 正文 `[n]` 点击：
   - 在翻译面板的原文中，用正则把 `\[\d+\]` 渲染成按钮；
   - 点击后滚动到参考文献面板对应条目并高亮；若条目有 bbox，同时跳 PDF 页。
4. 悬停翻译：
   - 鼠标在英文原文块上停留 500ms，或选中文本后，调用 `translate-text`；
   - 结果缓存 `Map<hash, translation>`，同一段不重复请求；
   - 用 popover 展示，不遮挡正文。
5. 错误边界：翻译失败显示原文 + “翻译失败，重试”，不整页报错。

**验收**

- 1280px 与 1440px 下无横向溢出；
- 翻页后右侧自动定位；
- 点击 `[3]` 能定位到第 3 条参考文献；
- 悬停 500ms 出译文，缓存生效（Network 面板只请求一次）；
- typecheck/build 通过。

---

### T5 解析增强（可选，风险高）

只在 T1–T4 完成后做，且不要动现有 `Block` 契约。

**可做的低风险部分**

1. 表格检测：同一页中连续 2 行以上、列 x 坐标对齐的文本块，标记 `kind=table`，保留原始行文本；
2. 公式检测：以 `=` 为主、包含数学符号、行高较小的行，标记 `kind=formula`；
3. 图表标题：以 `Figure/Table N` 开头的行标记 `kind=figure_caption`；
4. 前端按 kind 渲染不同底色与图标。

**不建议在赛前做**

- 单元格结构还原；
- LaTeX 公式识别；
- 图片抽取与 OCR 版面分析。

这些需要 Docling/MinerU 级别模型，容易在截止前引入不稳定依赖。

---

### T6 稳定性、性能与保活

**改动文件**

- `backend/app/main.py`（中间件、请求 ID）
- `backend/app/api/v1/health.py`（深度检查）
- 新增 `scripts/keepalive.py`
- `docs/deploy.md`（可选）

**实现步骤**

1. `/api/v1/health` 增加 `llm_latency_ms`（可选，带 2 秒超时）与索引块数；
2. 上传校验：MIME、文件头 `%PDF`、大小、页数上限；
3. 解析并发上限：同一时间最多 2 个解析任务，其余排队；
4. 统一异常处理：500 返回 `request_id`，日志可追踪；
5. 保活脚本：
   - 每 10 分钟 GET 公网 `/api/v1/health`；
   - 连续 3 次失败时打印告警；
   - 提供 Windows 任务计划程序配置说明；
6. 压测：5 个并发解析、20 个并发问答，记录 P95 与内存。

**验收**

- 非法文件被 400 拒绝；
- 并发解析不会打满 CPU；
- 保活脚本可手动运行一次并输出状态。

---

## 5. 接口与数据契约变更

新增（保持旧接口不变）：

```text
POST /api/v1/agent/run                 SSE，Agent 模式
GET  /api/v1/papers/{new}/diff/{old}   版本差异
GET  /api/v1/health                    增加字段（向后兼容）
```

新增模型（`backend/app/models/schemas.py`）：

- `ToolCall`、`ToolResult`、`AgentRunRequest`、`AgentRunResponse`
- `VersionChange`、`VersionDiffResponse`
- `HybridSearchHit`（如需要）

前端同步更新：

- `frontend/src/types/index.ts`
- `frontend/src/api/endpoints.ts`
- `frontend/src/api/sse.ts`（新增 agent 事件类型）

---

## 6. 约束与禁区

1. **不改许可证链路**：不引入 AGPL/GPL 组件到主进程；不引入 PyMuPDF、MinerU、PDFMathTranslate。
2. **不提交密钥**：不把 `.env`、`.env.modelscope`、DeepSeek Key、ModelScope Token 写入任何文件或日志。
3. **不破坏现有接口**：`/qa/ask`、`/qa/stream`、`/papers/*`、`/reader/*`、`/graph/*`、`/writing/*` 的请求/响应保持兼容；新增字段必须可选。
4. **不重写 RAG**：T3 工具复用现有 `retrieve_hits` / `answer_from_hits`。
5. **不引入重型依赖**：新增 Python 包前先在回复里说明理由、许可证、体积；优先标准库。
6. **不把用户代码直接 `eval`**：Python 工具必须走子进程 + AST 白名单。
7. **不删除测试**：可以新增，不能为了过测试而删断言。
8. **不跨任务重构**：T1 不要改 T3 的文件，T2 不要顺手改解析器。
9. **保持中文 UI 文案一致**：新增按钮/提示使用现有语气，不引入 emoji。
10. **Windows 兼容**：路径用 `Path`，命令用完整解释器路径，输出显式 UTF-8。

---

## 7. 测试与验收

### 7.1 每次提交必跑

```bash
cd "E:/project/传智杯大赛/backend"
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe" -m pytest -q
"C:/Users/11240/AppData/Local/Programs/Python312-embed/python.exe" -m ruff check .

cd "E:/project/传智杯大赛/frontend"
npm run typecheck
npm run build
```

### 7.2 检索金标集（T1）

在 `backend/tests/data/golden_qa.json` 建 20 条：

```json
[
  {"paper": "1706.03762v1.pdf", "question": "warmup steps 是多少", "page": 7},
  {"paper": "1706.03762v1.pdf", "question": "big model 用多少块 P100", "page": 7},
  {"paper": "1706.03762v1.pdf", "question": "英德 BLEU", "page": 8}
]
```

验收：Top-5 命中金标页 ≥ 80%，且不能比改动前下降。

### 7.3 Agent 路由集（T3）

至少 12 条，覆盖：

1. 单篇事实问答 → `library.answer`
2. 多篇对比 → `library.answer`（多 paper_ids）
3. “下载 arXiv 1706.03762” → `arxiv.download`
4. “找 5 篇 flash attention 论文” → `arxiv.search`
5. “画成雷达图” → `writing.chart`
6. “生成综述” → `graph.survey`
7. “提取未来方向” → `graph.future_work`
8. “写一个大纲” → `writing.outline`
9. “算一下这组数的均值” → `python.exec`
10. 模糊问题 → `library.answer`
11. 恶意代码 → 拒绝
12. 超长输入 → 截断或 400

验收：≥10/12 正确。

### 7.4 版本差异（T2）

- v1 vs v7 至少 5 条差异；
- 每条至少一侧有页码；
- 总结中无编造的页码/章节；
- 无 LLM 时回退摘要仍可读。

### 7.5 UI（T4）

- 1280 / 1440 宽度无溢出；
- 翻页同步、`[n]` 跳转、悬停翻译缓存；
- 控制台无 error。

---

## 8. 建议排期

| 天 | 任务 | 产出 |
|---|---|---|
| D1 | 基线 + T1 | 混合检索 + 测试 + 金标集 |
| D2–D3 | T2 | 版本差异 API + UI |
| D4–D8 | T3 | 工具注册表、路由、执行器、沙箱、SSE、前端 |
| D9–D10 | T4 | 双栏、同步滚动、引用跳转、悬停翻译 |
| D11 | T6 | 校验、并发、保活 |
| D12 | 回归 + 文档 + 录屏 | 演示视频素材、技术文档更新 |
| 机动 | T5 | 表格/公式/图注标记（只做低风险部分） |

---

## 9. 给 Qoder 的提示词模板

每次复制一段，替换 `<任务>`。

```text
你是 Margin 科研助手项目的主程，工作目录 E:\project\传智杯大赛。

请先读：
- README.md
- docs/项目书.md
- docs/Qoder后续技术方案.md 的 <任务> 一节

本次只做 <任务>，不要修改其他任务的代码。

开始前：
1. 阅读该任务列出的现有文件，确认实现与文档一致；
2. 运行基线测试（见文档 7.1），确认改动前全绿。

实现要求：
- 遵循文档中的接口契约、目录和约束；
- 不引入密钥、不引入 AGPL 组件、不破坏现有 API；
- 新增代码补测试；前端类型同步更新。

完成后：
1. 运行文档 7.1 的全部命令，贴出结果；
2. 给出“改了什么 / 怎么验证 / 没做什么”的总结；
3. 只提交本次任务的 commit，提交信息用英文说明动机与验收结果。
```

---

## 10. 交付定义（Definition of Done）

一个任务算完成，必须同时满足：

- 代码在 `main` 分支可运行；
- 新增/修改接口有 Pydantic 契约与前端类型；
- 新增逻辑有测试或可复现的验收命令；
- 不回归现有 19 个测试；
- 不把密钥、临时文件、`data/` 提交进仓库；
- 文档（README 或本方案）同步更新；
- Qoder 的总结能让人不看 diff 也知道改了什么。
