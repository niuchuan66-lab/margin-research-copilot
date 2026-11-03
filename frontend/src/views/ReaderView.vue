<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AgentTrace from '@/components/AgentTrace.vue'
import CitationChip from '@/components/CitationChip.vue'
import PdfViewer from '@/components/PdfViewer.vue'
import { api } from '@/api/endpoints'
import { errorMessage } from '@/lib/format'
import type { Block, Citation, OutlineItem, Paper, TranslatedBlock } from '@/types'

const route = useRoute()
const paper = ref<Paper | null>(null)
const outline = ref<OutlineItem[]>([])
const page = ref(1)
const numPages = ref(0)
const highlight = ref<{
  bbox: number[]
  space: 'bottom-left' | 'top-left'
} | null>(null)
const question = ref('')
const answer = ref('')
const citations = ref<Citation[]>([])
const trace = ref<string[]>([])
const asking = ref(false)
const loading = ref(false)
const failure = ref('')
const translations = ref<TranslatedBlock[]>([])
const translating = ref(false)

const paperId = computed(() => String(route.params.id ?? ''))
const pageBlocks = ref<Block[]>([])
let pageRequest = 0
const notConfigured = computed(
  () =>
    translations.value.length > 0 &&
    translations.value.every((item) => item.status === 'not_configured'),
)

async function load(): Promise<void> {
  if (!paperId.value) {
    paper.value = null
    return
  }
  loading.value = true
  failure.value = ''
  try {
    const [detail, tree] = await Promise.all([
      api.getPaper(paperId.value, false),
      api.readerOutline(paperId.value),
    ])
    paper.value = detail
    outline.value = tree
    const queryPage = Number(route.query.page)
    page.value = Number.isFinite(queryPage) && queryPage > 0 ? queryPage : 1
    await loadPageBlocks()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function loadPageBlocks(): Promise<void> {
  if (!paperId.value) {
    pageBlocks.value = []
    return
  }
  const request = ++pageRequest
  try {
    const blocks = await api.pageBlocks(paperId.value, page.value)
    if (request === pageRequest) {
      pageBlocks.value = blocks
    }
  } catch (error) {
    if (request === pageRequest) {
      pageBlocks.value = []
      failure.value = errorMessage(error)
    }
  }
}

onMounted(load)
watch(() => route.params.id, load)
watch(() => page.value, () => {
  void loadPageBlocks()
})

function onLoaded(total: number): void {
  numPages.value = total
  if (page.value > total) {
    page.value = total
  }
}

function goTo(target: number): void {
  page.value = Math.min(Math.max(target, 1), numPages.value || target)
  highlight.value = null
}

function chooseOutline(item: OutlineItem): void {
  page.value = item.page
  highlight.value = null
}

function selectCitation(citation: Citation): void {
  page.value = citation.page
  highlight.value = citation.bbox
    ? { bbox: citation.bbox, space: citation.bbox_space }
    : null
}

async function ask(): Promise<void> {
  const text = question.value.trim()
  if (!text || !paperId.value || asking.value) {
    return
  }
  asking.value = true
  failure.value = ''
  try {
    const response = await api.ask(text, [paperId.value])
    answer.value = response.answer
    citations.value = response.citations
    trace.value = response.trace
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    asking.value = false
  }
}

async function translatePage(): Promise<void> {
  if (!paperId.value || translating.value) {
    return
  }
  const blocks = pageBlocks.value.slice(0, 20)
  if (!blocks.length) {
    return
  }
  translating.value = true
  failure.value = ''
  try {
    translations.value = await api.translate(
      paperId.value,
      blocks.map((block) => block.id),
    )
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    translating.value = false
  }
}
</script>

<template>
  <section v-if="!paperId" class="empty">
    <div>
      <p class="empty-title">还没有选择论文</p>
      <p class="muted">先到书架上传并解析一篇 PDF。</p>
      <RouterLink class="btn" to="/library">去书架</RouterLink>
    </div>
  </section>

  <section v-else>
    <header class="page-head">
      <div>
        <RouterLink class="mono faint" to="/library">← 书架</RouterLink>
        <h1 class="page-title">{{ paper?.title ?? '加载中…' }}</h1>
        <p class="page-meta">
          {{ paper?.filename }} · {{ paper?.pages || 0 }} 页 ·
          {{ paper?.parse_engine ?? '未解析' }}
        </p>
      </div>
      <span class="tag">{{ paper?.status ?? 'loading' }}</span>
    </header>

    <p v-if="failure" class="error-line">{{ failure }}</p>
    <div v-if="loading" class="empty">正在打开论文…</div>

    <div v-else class="reader-grid">
      <aside class="panel reader-outline">
        <div class="panel-head">
          <span class="panel-title">目录</span>
          <span class="mono faint">{{ outline.length }}</span>
        </div>
        <div class="outline-list">
          <button
            v-for="item in outline"
            :key="item.block_id"
            class="outline-item"
            type="button"
            :style="{ paddingLeft: `${10 + (item.level - 1) * 10}px` }"
            @click="chooseOutline(item)"
          >
            <span>{{ item.title }}</span>
            <span class="mono faint">p.{{ item.page }}</span>
          </button>
          <p v-if="!outline.length" class="faint outline-empty">解析后显示标题树</p>
        </div>
      </aside>

      <div class="pdf-column">
        <div class="pdf-toolbar">
          <div class="row">
            <button
              class="btn btn-ghost btn-small"
              type="button"
              :disabled="page <= 1"
              @click="goTo(page - 1)"
            >
              上一页
            </button>
            <span class="mono">{{ page }} / {{ numPages || paper?.pages || '—' }}</span>
            <button
              class="btn btn-ghost btn-small"
              type="button"
              :disabled="numPages > 0 && page >= numPages"
              @click="goTo(page + 1)"
            >
              下一页
            </button>
          </div>
          <button
            class="btn btn-small"
            type="button"
            :disabled="translating || !pageBlocks.length"
            @click="translatePage"
          >
            {{ translating ? '翻译中…' : '翻译本页' }}
          </button>
        </div>

        <div class="panel pdf-panel">
          <PdfViewer
            v-if="paper"
            :url="api.paperFileUrl(paper.id)"
            :page="page"
            :highlight="highlight"
            @loaded="onLoaded"
          />
        </div>

        <div v-if="translations.length" class="panel translation-panel">
          <div class="panel-head">
            <span class="panel-title">双语对照</span>
            <span class="mono faint">p.{{ page }}</span>
          </div>
          <div class="panel-body stack">
            <p v-if="notConfigured" class="faint">
              当前未配置 LLM。在 .env 中设置 LLM_API_KEY 后重新请求。
            </p>
            <div
              v-for="item in translations"
              :key="item.block_id"
              class="translation-row"
            >
              <p class="translation-source">{{ item.source }}</p>
              <p v-if="item.translation" class="translation-text">
                {{ item.translation }}
              </p>
              <p v-else class="faint mono">{{ item.status }}</p>
            </div>
          </div>
        </div>
      </div>

      <aside class="panel reader-assistant">
        <div class="panel-head">
          <span class="panel-title">问这篇论文</span>
          <span class="mono faint">RAG</span>
        </div>
        <div class="panel-body stack">
          <form class="stack" @submit.prevent="ask">
            <textarea
              v-model="question"
              class="textarea"
              rows="3"
              placeholder="例如：作者用了多少块 GPU？β₁/β₂ 设为多少？"
            ></textarea>
            <button class="btn" type="submit" :disabled="asking || !question.trim()">
              {{ asking ? '检索中…' : '提问' }}
            </button>
          </form>

          <div v-if="answer" class="answer-block">
            <p class="answer-text">{{ answer }}</p>
            <div v-if="citations.length" class="citation-list">
              <CitationChip
                v-for="citation in citations"
                :key="`${citation.paper_id}-${citation.block_id}`"
                :citation="citation"
                @select="selectCitation"
              />
            </div>
            <AgentTrace :trace="trace" />
          </div>
          <p v-else class="faint">
            回答会带页码与原文片段，点击引用可跳回 PDF。
          </p>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.error-line {
  margin-bottom: 12px;
  color: var(--oxblood);
  font-size: 13px;
}

.reader-grid {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: start;
}

.reader-outline,
.reader-assistant {
  position: sticky;
  top: 76px;
  max-height: calc(100vh - 100px);
  overflow: auto;
}

.outline-list {
  padding: 6px 0;
}

.outline-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--ink-2);
  font-size: 12px;
  text-align: left;
}

.outline-item:hover {
  border-left-color: var(--petrol);
  background: var(--paper-2);
  color: var(--ink);
}

.outline-empty {
  padding: 12px;
  font-size: 12px;
}

.pdf-column {
  min-width: 0;
}

.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.pdf-panel {
  overflow: hidden;
}

.translation-panel {
  margin-top: 12px;
}

.translation-row {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule-soft);
}

.translation-row:last-child {
  border-bottom: none;
}

.translation-source {
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 12px;
  line-height: 1.6;
}

.translation-text {
  margin-top: 5px;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.7;
}

.answer-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.answer-text {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

@media (max-width: 1200px) {
  .reader-grid {
    grid-template-columns: 200px minmax(0, 1fr);
  }

  .reader-assistant {
    position: static;
    grid-column: 1 / -1;
    max-height: none;
  }
}

@media (max-width: 860px) {
  .reader-grid {
    grid-template-columns: 1fr;
  }

  .reader-outline {
    position: static;
    max-height: 220px;
  }
}
</style>
