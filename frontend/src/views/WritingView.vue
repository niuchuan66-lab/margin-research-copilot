<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import ChartPreview from '@/components/ChartPreview.vue'
import CitationChip from '@/components/CitationChip.vue'
import MermaidBlock from '@/components/MermaidBlock.vue'
import { api } from '@/api/endpoints'
import { errorMessage } from '@/lib/format'
import { usePapersStore } from '@/stores/papers'
import type {
  ChartResponse,
  Citation,
  FigureResponse,
  OutlineResponse,
} from '@/types'

const SAMPLE_CSV = `year,accuracy,latency_ms
2023,0.81,120
2024,0.85,110
2025,0.88,95
2026,0.90,88
`

const papers = usePapersStore()
const router = useRouter()
const idea = ref('')
const outline = ref<OutlineResponse | null>(null)
const outlineLoading = ref(false)
const figureKind = ref<'mermaid' | 'graphviz' | 'tikz'>('mermaid')
const figureSpec = ref('Idea -> Retrieval -> Grounded answer -> Citation check')
const figure = ref<FigureResponse | null>(null)
const figureLoading = ref(false)
const csvText = ref(SAMPLE_CSV)
const chartTitle = ref('Model quality')
const chartType = ref<'line' | 'bar' | 'radar'>('line')
const chart = ref<ChartResponse | null>(null)
const chartLoading = ref(false)
const showTable = ref(false)
const failure = ref('')

onMounted(() => {
  void papers.fetchPapers()
})

async function generateOutline(): Promise<void> {
  if (!idea.value.trim()) {
    failure.value = '先写一句研究想法。'
    return
  }
  outlineLoading.value = true
  failure.value = ''
  try {
    outline.value = await api.writingOutline(
      idea.value.trim(),
      papers.readyPapers.map((paper) => paper.id),
    )
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    outlineLoading.value = false
  }
}

async function generateFigure(): Promise<void> {
  if (!figureSpec.value.trim()) {
    failure.value = '先描述要画的流程或结构。'
    return
  }
  figureLoading.value = true
  failure.value = ''
  try {
    figure.value = await api.figure(figureKind.value, figureSpec.value.trim())
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    figureLoading.value = false
  }
}

async function generateChart(): Promise<void> {
  if (!csvText.value.trim()) {
    failure.value = '先粘贴 CSV 数据。'
    return
  }
  chartLoading.value = true
  failure.value = ''
  try {
    chart.value = await api.chart(
      csvText.value,
      chartTitle.value || 'Figure',
      chartType.value,
    )
    showTable.value = false
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    chartLoading.value = false
  }
}

function openCitation(citation: Citation): void {
  void router.push({
    path: `/reader/${citation.paper_id}`,
    query: { page: String(citation.page) },
  })
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">写作</h1>
        <p class="page-meta">
          大纲、图脚本、CSV 出图；References 只从书架取
        </p>
      </div>
      <span class="tag">无幻觉模板</span>
    </header>

    <p v-if="failure" class="error-line">{{ failure }}</p>

    <div class="writing-grid">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">从想法到大纲</span>
            <span class="mono faint">library-only refs</span>
          </div>
          <div class="panel-body stack">
            <textarea
              v-model="idea"
              class="textarea"
              rows="4"
              placeholder="例如：把 citation graph 的 PageRank 用作 RAG 重排信号，验证是否降低跨文献问答的幻觉率。"
            ></textarea>
            <button class="btn" type="button" :disabled="outlineLoading" @click="generateOutline">
              {{ outlineLoading ? '生成中…' : '生成大纲' }}
            </button>
          </div>
        </div>

        <div v-if="outline" class="panel">
          <div class="panel-head">
            <span class="panel-title">{{ outline.title }}</span>
            <span class="mono faint">{{ outline.sections.length }} 节</span>
          </div>
          <div class="panel-body stack">
            <section
              v-for="section in outline.sections"
              :key="section.heading"
              class="outline-section"
            >
              <h2 class="outline-heading">{{ section.heading }}</h2>
              <p class="outline-intent">{{ section.intent }}</p>
              <div v-if="section.citations.length" class="citation-list">
                <CitationChip
                  v-for="citation in section.citations.slice(0, 3)"
                  :key="`${citation.paper_id}-${citation.block_id}`"
                  :citation="citation"
                  @select="openCitation"
                />
              </div>
            </section>
            <div class="hairline"></div>
            <div>
              <h3 class="outline-heading">References</h3>
              <ol class="reference-list">
                <li v-for="reference in outline.references.slice(0, 30)" :key="reference.id">
                  {{ reference.title ?? reference.raw ?? '未命名条目' }}
                  <span v-if="reference.year" class="faint">({{ reference.year }})</span>
                </li>
              </ol>
            </div>
          </div>
        </div>
      </div>

      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">拓扑图脚本</span>
            <span class="mono faint">{{ figureKind }}</span>
          </div>
          <div class="panel-body stack">
            <select v-model="figureKind" class="select" aria-label="图形类型">
              <option value="mermaid">Mermaid</option>
              <option value="graphviz">Graphviz</option>
              <option value="tikz">TikZ</option>
            </select>
            <textarea v-model="figureSpec" class="textarea" rows="3"></textarea>
            <button class="btn btn-ghost" type="button" :disabled="figureLoading" @click="generateFigure">
              {{ figureLoading ? '生成中…' : '生成图脚本' }}
            </button>
            <MermaidBlock
              v-if="figure && figure.format === 'mermaid'"
              :code="figure.code"
            />
            <pre v-else-if="figure" class="code-block">{{ figure.code }}</pre>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">CSV 出图</span>
            <span class="mono faint">单轴 · 可查表</span>
          </div>
          <div class="panel-body stack">
            <input v-model="chartTitle" class="input" placeholder="图标题" />
            <select v-model="chartType" class="select" aria-label="图表类型">
              <option value="line">折线图</option>
              <option value="bar">柱状图</option>
              <option value="radar">雷达图</option>
            </select>
            <textarea v-model="csvText" class="textarea code-textarea" rows="7"></textarea>
            <div class="row">
              <button class="btn" type="button" :disabled="chartLoading" @click="generateChart">
                {{ chartLoading ? '生成中…' : '生成图表' }}
              </button>
              <button class="btn btn-ghost btn-small" type="button" @click="csvText = SAMPLE_CSV">
                载入示例
              </button>
            </div>

            <template v-if="chart">
              <ChartPreview :option="chart.option" />
              <p class="caption">{{ chart.caption }}</p>
              <button class="btn btn-ghost btn-small" type="button" @click="showTable = !showTable">
                {{ showTable ? '隐藏数据表' : '查看数据表' }}
              </button>
              <div v-if="showTable" class="table-wrap panel">
                <table class="table">
                  <thead>
                    <tr>
                      <th v-for="column in chart.columns" :key="column">{{ column }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, index) in chart.rows" :key="index">
                      <td v-for="column in chart.columns" :key="column" class="mono">
                        {{ row[column] }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.error-line {
  margin-bottom: 12px;
  color: var(--oxblood);
  font-size: 13px;
}

.writing-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.outline-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--rule-soft);
}

.outline-section:last-of-type {
  border-bottom: none;
}

.outline-heading {
  font-size: 16px;
}

.outline-intent {
  margin-top: 4px;
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.6;
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.reference-list {
  margin: 8px 0 0;
  padding-left: 20px;
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 12px;
  line-height: 1.7;
}

.code-block,
.code-textarea {
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.65;
}

.code-block {
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--rule-soft);
  background: var(--paper-2);
  white-space: pre-wrap;
}

.caption {
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 12px;
  line-height: 1.6;
}

.table-wrap {
  margin-top: 8px;
  overflow: auto;
}

@media (max-width: 1100px) {
  .writing-grid {
    grid-template-columns: 1fr;
  }
}
</style>
