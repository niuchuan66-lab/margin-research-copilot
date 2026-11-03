<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AgentTrace from '@/components/AgentTrace.vue'
import BilingualPane from '@/components/BilingualPane.vue'
import CitationChip from '@/components/CitationChip.vue'
import PdfViewer from '@/components/PdfViewer.vue'
import { api } from '@/api/endpoints'
import { errorMessage } from '@/lib/format'
import type {
  Block,
  Citation,
  DedupCandidate,
  OutlineItem,
  Paper,
  ReferenceItem,
  TranslatedBlock,
  VersionChange,
  VersionDiffResponse,
} from '@/types'

const KIND_LABELS: Record<'added' | 'removed' | 'modified', string> = {
  added: '新增',
  modified: '改写',
  removed: '删除',
}
const DIFF_GROUP_ORDER = ['added', 'modified', 'removed'] as const

const route = useRoute()
const paper = ref<Paper | null>(null)
const outline = ref<OutlineItem[]>([])
const references = ref<ReferenceItem[]>([])
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
const highlightRefId = ref('')
const versions = ref<DedupCandidate[]>([])
const diffOpen = ref(false)
const diffTarget = ref('')
const diff = ref<VersionDiffResponse | null>(null)
const diffLoading = ref(false)
const diffError = ref('')

const groupedChanges = computed(() => {
  const groups: Record<'added' | 'removed' | 'modified', VersionChange[]> = {
    added: [],
    removed: [],
    modified: [],
  }
  for (const change of diff.value?.changes ?? []) {
    groups[change.kind].push(change)
  }
  return groups
})

const paperId = computed(() => String(route.params.id ?? ''))
const pageBlocks = ref<Block[]>([])
let pageRequest = 0

async function load(): Promise<void> {
  if (!paperId.value) {
    paper.value = null
    return
  }
  loading.value = true
  failure.value = ''
  try {
    const [detail, tree, refs] = await Promise.all([
      api.getPaper(paperId.value, false),
      api.readerOutline(paperId.value),
      api.readerReferences(paperId.value).catch(() => [] as ReferenceItem[]),
    ])
    paper.value = detail
    outline.value = tree
    references.value = refs
    versions.value = []
    diffOpen.value = false
    diffTarget.value = ''
    diff.value = null
    diffError.value = ''
    translations.value = []
    highlightRefId.value = ''
    const queryPage = Number(route.query.page)
    page.value = Number.isFinite(queryPage) && queryPage > 0 ? queryPage : 1
    await loadPageBlocks()
    void loadVersions()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function loadVersions(): Promise<void> {
  if (!paperId.value || paper.value?.status !== 'ready') {
    versions.value = []
    return
  }
  try {
    versions.value = await api.paperVersions(paperId.value)
  } catch {
    versions.value = []
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

function selectReference(item: ReferenceItem): void {
  if (!item.page) {
    return
  }
  page.value = item.page
  highlight.value = item.bbox
    ? { bbox: item.bbox, space: 'bottom-left' }
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

async function translateTextForHover(
  text: string,
): Promise<{ translation: string | null; status: string }> {
  const result = await api.translateText(text)
  return { translation: result.translation, status: result.status }
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
    const results = await api.translate(
      paperId.value,
      blocks.map((block) => block.id),
    )
    const translatedIds = new Set(results.map((item) => item.block_id))
    translations.value = [
      ...translations.value.filter((item) => !translatedIds.has(item.block_id)),
      ...results,
    ]
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    translating.value = false
  }
}

function syncPage(target: number): void {
  goTo(target)
}

function jumpReference(index: number): void {
  const item = references.value.find((ref) => ref.index === index)
  if (!item) {
    return
  }
  highlightRefId.value = item.block_id
  window.setTimeout(() => {
    if (highlightRefId.value === item.block_id) {
      highlightRefId.value = ''
    }
  }, 1800)
  const element = document.getElementById(`ref-${item.block_id}`)
  const list = element?.closest<HTMLElement>('.ref-list')
  if (element && list) {
    list.scrollTop += element.getBoundingClientRect().top - list.getBoundingClientRect().top - 8
  }
  selectReference(item)
}

function openDiffPanel(): void {
  diffOpen.value = !diffOpen.value
  if (diffOpen.value) {
    if (!versions.value.some((item) => item.paper_id === diffTarget.value)) {
      diffTarget.value = versions.value[0]?.paper_id ?? ''
      diff.value = null
      diffError.value = ''
    }
  } else {
    diff.value = null
    diffError.value = ''
  }
}

async function runDiff(): Promise<void> {
  if (!paperId.value || !diffTarget.value || diffLoading.value) {
    return
  }
  diffLoading.value = true
  diffError.value = ''
  try {
    diff.value = await api.paperDiff(paperId.value, diffTarget.value)
  } catch (error) {
    diff.value = null
    diffError.value = errorMessage(error)
  } finally {
    diffLoading.value = false
  }
}

function selectChange(change: VersionChange): void {
  if (change.new_page == null) {
    return
  }
  page.value = change.new_page
  highlight.value = change.new_bbox
    ? { bbox: change.new_bbox, space: 'bottom-left' }
    : null
}

function trimmedChangeText(change: VersionChange): string {
  const text = (change.new_text ?? change.old_text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
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
        <div class="panel-head ref-head">
          <span class="panel-title">参考文献</span>
          <span class="mono faint">{{ references.length }}</span>
        </div>
        <div class="outline-list ref-list">
          <button
            v-for="item in references"
            :id="`ref-${item.block_id}`"
            :key="item.block_id"
            class="outline-item ref-item"
            :class="{ 'ref-flash': highlightRefId === item.block_id }"
            type="button"
            :disabled="!item.page"
            @click="selectReference(item)"
          >
            <span class="mono faint ref-index">{{ item.index ?? '·' }}</span>
            <span class="ref-text">{{ item.text }}</span>
            <span v-if="item.page" class="mono faint">p.{{ item.page }}</span>
          </button>
          <p v-if="!references.length" class="faint outline-empty">
            解析后显示参考文献
          </p>
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
          <div class="row">
            <button
              v-if="versions.length"
              class="btn btn-ghost btn-small"
              type="button"
              @click="openDiffPanel"
            >
              {{ diffOpen ? '收起版本差异' : '版本差异' }}
            </button>
          </div>
        </div>

        <div class="reader-main">
          <div class="panel pdf-panel">
            <PdfViewer
              v-if="paper"
              :url="api.paperFileUrl(paper.id)"
              :page="page"
              :highlight="highlight"
              @loaded="onLoaded"
            />
          </div>
          <BilingualPane
            :page="page"
            :blocks="pageBlocks"
            :translations="translations"
            :translating="translating"
            :translate-text="translateTextForHover"
            @translate-page="translatePage"
            @sync-page="syncPage"
            @jump-reference="jumpReference"
          />
        </div>

        <div v-if="diffOpen" class="panel diff-panel">
          <div class="panel-head">
            <span class="panel-title">版本差异</span>
            <span v-if="diff" class="mono faint">
              相似度 {{ (diff.similarity * 100).toFixed(1) }}% ·
              {{ diff.changes.length }} 处变化
            </span>
          </div>
          <div class="panel-body stack">
            <div class="row">
              <select v-model="diffTarget" class="input diff-select">
                <option
                  v-for="candidate in versions"
                  :key="candidate.paper_id"
                  :value="candidate.paper_id"
                >
                  {{ candidate.title ?? candidate.paper_id }}（相似度
                  {{ (candidate.similarity * 100).toFixed(0) }}%）
                </option>
              </select>
              <button
                class="btn btn-small"
                type="button"
                :disabled="diffLoading || !diffTarget"
                @click="runDiff"
              >
                {{ diffLoading ? '对比中…' : '开始对比' }}
              </button>
            </div>
            <p v-if="diffError" class="error-line">{{ diffError }}</p>
            <div v-if="diff" class="stack">
              <p class="diff-summary">{{ diff.summary }}</p>
              <details
                v-for="kind in DIFF_GROUP_ORDER"
                :key="kind"
                class="diff-group"
                :open="kind !== 'removed'"
              >
                <summary class="diff-group-head">
                  {{ KIND_LABELS[kind] }}
                  <span class="mono faint">{{ groupedChanges[kind].length }}</span>
                </summary>
                <div class="diff-group-body">
                  <button
                    v-for="(change, index) in groupedChanges[kind]"
                    :key="index"
                    class="diff-item"
                    type="button"
                    :disabled="change.new_page == null"
                    @click="selectChange(change)"
                  >
                    <span class="mono faint diff-page">
                      {{
                        change.new_page != null
                          ? `p.${change.new_page}`
                          : change.old_page != null
                            ? `旧版 p.${change.old_page}`
                            : '—'
                      }}
                    </span>
                    <span class="diff-text">{{ trimmedChangeText(change) }}</span>
                  </button>
                  <p v-if="!groupedChanges[kind].length" class="faint diff-empty">
                    无
                  </p>
                </div>
              </details>
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

.ref-head {
  margin-top: 10px;
  border-top: 1px solid var(--line, #e6e8e2);
}

.ref-list {
  max-height: 260px;
  overflow: auto;
}

.ref-item {
  align-items: flex-start;
}

.ref-index {
  min-width: 22px;
}

.ref-text {
  flex: 1;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.45;
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

.reader-main {
  display: flex;
  align-items: stretch;
  gap: 12px;
  min-width: 0;
}

.pdf-panel {
  flex: 1.15;
  min-width: 0;
  overflow: hidden;
}

.reader-main > .bilingual-pane {
  flex: 1;
  min-width: 0;
}

.ref-flash {
  animation: ref-flash 1.8s ease;
}

@keyframes ref-flash {
  0% {
    background: rgba(232, 199, 122, 0.55);
  }

  100% {
    background: transparent;
  }
}

.diff-panel {
  margin-top: 12px;
}

.diff-select {
  flex: 1;
  min-width: 0;
}

.diff-summary {
  padding: 10px 12px;
  border: 1px solid var(--line, #e6e8e2);
  border-radius: 6px;
  background: var(--paper-2, #faf9f5);
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.diff-group {
  border: 1px solid var(--line, #e6e8e2);
  border-radius: 6px;
  overflow: hidden;
}

.diff-group + .diff-group {
  margin-top: 8px;
}

.diff-group-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  background: var(--paper-2, #faf9f5);
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  list-style: none;
}

.diff-group-head::-webkit-details-marker {
  display: none;
}

.diff-group-body {
  max-height: 240px;
  overflow: auto;
  padding: 4px;
}

.diff-item {
  display: flex;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  background: transparent;
  color: var(--ink-2);
  font-size: 12px;
  text-align: left;
}

.diff-item:hover:not(:disabled) {
  background: var(--paper-2, #faf9f5);
  color: var(--ink);
}

.diff-item:disabled {
  opacity: 0.55;
  cursor: default;
}

.diff-page {
  flex: none;
  min-width: 30px;
}

.diff-text {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.5;
}

.diff-empty {
  padding: 8px;
  font-size: 12px;
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

@media (max-width: 1100px) {
  .reader-main {
    flex-direction: column;
  }

  .reader-main > .bilingual-pane {
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
