# 第三方组件与 Skill 声明

本项目使用的第三方 Skill 保留其原始许可证与版权声明。分发本项目时请一并保留本文件及各目录下的 LICENSE。

## 本地开发 Skill（不随仓库分发）

以下 Skill 安装在本地 `.claude/skills/`，`.claude/` 已被 `.gitignore` 排除，不作为参赛作品的一部分分发。列出仅用于说明开发过程中的工具来源与许可证。

| Skill | 来源 | 许可证 | 版权 |
|---|---|---|---|
| paper-analyst | https://github.com/flyer-li/paper-analyst | MIT | Copyright (c) 2026 Yifei Li |
| shidi | https://github.com/IcyCreamDAS/shidi-skill | MIT | Copyright (c) 2026 Zixiang Yin |
| translate-pdf | https://github.com/wshuyi/translate-pdf-skill | MIT | Copyright (c) 2025 wshuyi |
| pdf-translate | https://github.com/L27z18328742/pdf-translate | README 声明 MIT，仓库未附 LICENSE 文件 | 版权归原作者 |

### 关于 pdf-translate

该 Skill 仅作为本地开发/翻译工具使用，**不并入产品运行时**。它调用的 `pdf2zh_next` / PDFMathTranslate-next 采用 **AGPL-3.0**，首次运行会通过 `uv` 安装该工具并下载模型。若将本 Skill 随作品仓库公开，请保留本说明；若在产品中调用其能力，需自行评估 AGPL 的网络服务开源义务。

## 仅作参考、不随作品分发

以下仓库已移至项目目录外的 `传智杯大赛-参考资料/`，仅用于阅读架构与提示词，不复制其代码进参赛作品：

| 仓库 | 许可证 | 原因 |
|---|---|---|
| Imbad0202/academic-research-skills | CC BY-NC 4.0 | 禁止商业使用，且 CC 许可证不适合直接并入软件代码 |
| lingzhi227/agent-research-skills | 未提供许可证 | 无许可证即默认保留所有权利，不能复制/再分发 |
| O0000-code/awesome-academic-skills | CC0 1.0 | 仅索引，可自由参考 |
| Trae1ounG/PaperPlotHub | MIT | 绘图脚本市场，可按 MIT 借用并保留声明 |

## 运行时依赖（产品本身）

| 组件 | 许可证 |
|---|---|
| Vue 3 / Vite / Pinia / Vue Router | MIT |
| PDF.js | Apache-2.0 |
| Apache ECharts | Apache-2.0 |
| KaTeX / Mermaid | MIT |
| FastAPI | MIT |
| Uvicorn / Starlette | BSD-3-Clause |
| Pydantic | MIT |
| LangGraph / LlamaIndex | MIT |
| Qdrant | Apache-2.0 |
| PostgreSQL | PostgreSQL License |
| Valkey | BSD-3-Clause |
| BGE-M3 / bge-reranker | MIT |
| Docling | MIT |
| PaddleOCR | Apache-2.0 |
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |
| OpenCV | Apache-2.0 |
| NumPy | BSD-3-Clause（含 0BSD/MIT/Zlib/CC0 组件） |
| Shapely | BSD-3-Clause |
| wordninja | 包元数据未声明（仅用于 OCR 连写词还原） |
| GROBID | Apache-2.0 |
| pypdfium2 / PDFium | Apache-2.0 / BSD-3-Clause |
| NetworkX | BSD-3-Clause |
| RAGAS（预留） | Apache-2.0 |

上述组件均与项目主许可证 Apache-2.0 兼容；分发时保留各自的版权与许可证文本。

## 许可证兼容性提示

- MIT / BSD / Apache-2.0 代码可以并入 Apache-2.0 项目，但必须保留原版权与许可证文本。
- GPL / AGPL 代码不能并入 Apache-2.0 项目；只能作为独立进程/工具调用，并单独声明。
- CC BY-NC 与“无许可证”内容不要复制进公开仓库。
