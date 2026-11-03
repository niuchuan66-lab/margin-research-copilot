<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import GraphCanvas from '@/components/GraphCanvas.vue'
import { api } from '@/api/endpoints'
import { errorMessage } from '@/lib/format'
import { usePapersStore } from '@/stores/papers'
import type { FutureWorkItem, GraphResponse } from '@/types'

const papers = usePapersStore()
const graph = ref<GraphResponse | null>(null)
const survey = ref('')
const futureWork = ref<FutureWorkItem[]>([])
const loading = ref(false)
const futureLoading = ref(false)
const failure = ref('')

const cornerstones = computed(
  () =>
    graph.value?.nodes
      .filter((node) => node.is_cornerstone)
      .sort((left, right) => right.centrality - left.centrality) ?? [],
)

onMounted(() => {
  void papers.fetchPapers()
})

async function build(): Promise<void> {
  const ids = papers.readyPapers.map((paper) => paper.id)
  if (!ids.length) {
    failure.value = '书架里还没有已解析的论文。'
    return
  }
  loading.value = true
  failure.value = ''
  survey.value = ''
  futureWork.value = []
  try {
    graph.value = await api.buildGraph(ids)
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function generateSurvey(): Promise<void> {
  if (!graph.value) {
    return
  }
  loading.value = true
  failure.value = ''
  try {
    const result = await api.survey(graph.value.graph_id)
    survey.value = result.markdown
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function generateFutureWork(): Promise<void> {
  if (!graph.value) {
    return
  }
  futureLoading.value = true
  failure.value = ''
  try {
    const result = await api.futureWork(graph.value.graph_id)
    futureWork.value = result.items
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    futureLoading.value = false
  }
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">图谱</h1>
        <p class="page-meta">局部引用网络 · NetworkX PageRank · 基石节点</p>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="build">
        {{ loading ? '计算中…' : '构建图谱' }}
      </button>
    </header>

    <p v-if="failure" class="error-line">{{ failure }}</p>

    <div v-if="!graph" class="empty">
      <div>
        <p class="empty-title">把书架里的论文连起来</p>
        <p class="muted">
          解析至少一篇论文后构建图谱；引用边来自 References，未入库的引用会作为灰色节点出现。
        </p>
        <RouterLink class="btn" to="/library">去书架</RouterLink>
      </div>
    </div>

    <template v-else>
      <div class="summary panel">
        <div>
          <strong>{{ graph.summary }}</strong>
          <p class="mono faint">
            algorithm: {{ graph.algorithm }} · nodes: {{ graph.nodes.length }} · edges:
            {{ graph.edges.length }}
          </p>
        </div>
        <div class="row">
          <button class="btn btn-ghost btn-small" type="button" :disabled="loading" @click="generateSurvey">
            生成综述草稿
          </button>
          <button
            class="btn btn-ghost btn-small"
            type="button"
            :disabled="futureLoading"
            @click="generateFutureWork"
          >
            {{ futureLoading ? '提取中…' : '提取未来方向' }}
          </button>
        </div>
      </div>

      <div class="graph-layout">
        <div class="panel graph-panel">
          <div class="panel-head">
            <span class="panel-title">引用网络</span>
            <span class="mono faint">拖动 / 缩放</span>
          </div>
          <GraphCanvas :nodes="graph.nodes" :edges="graph.edges" />
        </div>

        <aside class="panel cornerstone-panel">
          <div class="panel-head">
            <span class="panel-title">基石节点</span>
            <span class="mono faint">{{ cornerstones.length }}</span>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>论文</th>
                  <th>被引</th>
                  <th>中心度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="node in cornerstones" :key="node.id">
                  <td>
                    <div class="node-title">{{ node.title }}</div>
                    <div class="mono faint">{{ node.year ?? '年份未明确' }}</div>
                  </td>
                  <td class="mono">{{ node.citations }}</td>
                  <td class="mono">{{ node.centrality }}</td>
                </tr>
                <tr v-if="!cornerstones.length">
                  <td colspan="3" class="faint">还没有足够的引用边。</td>
                </tr>
              </tbody>
            </table>
          </div>
        </aside>
      </div>

      <div v-if="survey" class="panel survey-panel">
        <div class="panel-head">
          <span class="panel-title">综述草稿</span>
          <span class="mono faint">需人工核对</span>
        </div>
        <pre class="survey-text">{{ survey }}</pre>
      </div>
      <div v-if="futureWork.length" class="panel survey-panel">
        <div class="panel-head">
          <span class="panel-title">未来方向</span>
          <span class="mono faint">已按相似度合并 · 需人工核对</span>
        </div>
        <div class="future-list">
          <article v-for="item in futureWork" :key="`${item.paper_id}-${item.page}`" class="future-item">
            <div class="row">
              <strong>{{ item.paper_title ?? item.paper_id }}</strong>
              <span class="mono faint">p.{{ item.page }} · {{ item.year ?? '年份未明确' }}</span>
            </div>
            <p class="muted">{{ item.evidence }}</p>
          </article>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.error-line {
  margin-bottom: 12px;
  color: var(--oxblood);
  font-size: 13px;
}

.summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.summary strong {
  font-family: var(--font-serif);
  font-weight: 600;
}

.summary p {
  margin-top: 4px;
}

.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 14px;
  align-items: start;
}

.graph-panel {
  overflow: hidden;
}

.cornerstone-panel {
  max-height: 560px;
  overflow: auto;
}

.table-wrap {
  overflow: auto;
}

.node-title {
  max-width: 240px;
  font-family: var(--font-serif);
  font-size: 13px;
  line-height: 1.4;
}

.survey-panel {
  margin-top: 14px;
}

.future-list {
  display: grid;
  gap: 12px;
  padding: 14px 16px;
}

.future-item {
  padding: 10px 12px;
  border: 1px solid var(--line, #e6e8e2);
  border-radius: 6px;
  background: var(--paper-2, #faf9f5);
}

.future-item p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
}

.survey-text {
  margin: 0;
  padding: 16px;
  overflow: auto;
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.8;
  white-space: pre-wrap;
}

@media (max-width: 1100px) {
  .graph-layout {
    grid-template-columns: 1fr;
  }

  .cornerstone-panel {
    max-height: none;
  }
}
</style>
