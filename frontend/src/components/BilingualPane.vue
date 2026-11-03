<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { Block, TranslatedBlock } from '@/types'

interface TranslateResult {
  translation: string | null
  status: string
}

interface GroupBlock {
  id: string
  text: string
  translation: string | null
  status: string
  kind: string
}

interface Group {
  page: number
  blocks: GroupBlock[]
}

interface CitationPart {
  type: 'text' | 'ref'
  value: string
  index: number | null
}

interface HoverState {
  key: string
  x: number
  y: number
  text: string
  result: TranslateResult | null
  loading: boolean
}

const props = defineProps<{
  page: number
  blocks: Block[]
  translations: TranslatedBlock[]
  translating: boolean
  translateText: (text: string) => Promise<TranslateResult>
}>()

const emit = defineEmits<{
  'translate-page': []
  'sync-page': [page: number]
  'jump-reference': [index: number]
}>()

function hashText(text: string): string {
  let hash = 5381
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0
  }
  return `h${(hash >>> 0).toString(36)}${text.length}`
}

const hoverCache = new Map<string, TranslateResult>()

const translatedByPage = computed(() => {
  const map = new Map<number, TranslatedBlock[]>()
  for (const item of props.translations) {
    if (item.page == null) {
      continue
    }
    const list = map.get(item.page) ?? []
    list.push(item)
    map.set(item.page, list)
  }
  return map
})

const groups = computed<Group[]>(() => {
  const result: Group[] = []
  const kindById = new Map(props.blocks.map((block) => [block.id, block.kind]))
  for (const [pageNumber, items] of translatedByPage.value) {
    result.push({
      page: pageNumber,
      blocks: items.map((item) => ({
        id: item.block_id,
        text: item.source,
        translation: item.translation,
        status: item.status,
        kind: kindById.get(item.block_id) ?? '',
      })),
    })
  }
  if (props.blocks.length) {
    const current = result.find((group) => group.page === props.page)
    if (!current) {
      result.push({
        page: props.page,
        blocks: props.blocks.map((block) => ({
          id: block.id,
          text: block.text,
          translation: null,
          status: '',
          kind: block.kind,
        })),
      })
    } else {
      const known = new Set(current.blocks.map((block) => block.id))
      for (const block of props.blocks) {
        if (!known.has(block.id)) {
          current.blocks.push({
            id: block.id,
            text: block.text,
            translation: null,
            status: '',
            kind: block.kind,
          })
        }
      }
    }
  }
  result.sort((a, b) => a.page - b.page)
  return result
})

const translatedPages = computed(() => translatedByPage.value.size)

const KIND_LABELS: Record<string, string> = {
  table: '表格',
  formula: '公式',
  figure_caption: '图注',
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? ''
}

function citationParts(text: string): CitationPart[] {
  const parts: CitationPart[] = []
  const pattern = /\[(\d+)\]/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      parts.push({ type: 'text', value: text.slice(last, match.index), index: null })
    }
    parts.push({ type: 'ref', value: match[0], index: Number(match[1]) })
    last = match.index + match[0].length
  }
  if (last < text.length) {
    parts.push({ type: 'text', value: text.slice(last), index: null })
  }
  return parts.length ? parts : [{ type: 'text', value: text, index: null }]
}

// ---------- 页级 / 块级同步滚动 ----------

const listRef = ref<HTMLDivElement | null>(null)
let observer: IntersectionObserver | null = null
let suppressUntil = 0

function scrollToPage(target: number): void {
  const container = listRef.value
  if (!container) {
    return
  }
  const element = container.querySelector<HTMLElement>(`[data-page="${target}"]`)
  if (!element) {
    return
  }
  suppressUntil = Date.now() + 500
  container.scrollTop +=
    element.getBoundingClientRect().top - container.getBoundingClientRect().top - 10
}

function observeGroups(): void {
  observer?.disconnect()
  const container = listRef.value
  if (!container || !observer) {
    return
  }
  container.querySelectorAll('[data-page]').forEach((element) => {
    observer?.observe(element)
  })
}

function onIntersect(entries: IntersectionObserverEntry[]): void {
  if (Date.now() < suppressUntil) {
    return
  }
  let best: IntersectionObserverEntry | null = null
  for (const entry of entries) {
    if (!entry.isIntersecting) {
      continue
    }
    if (!best || entry.boundingClientRect.top < best.boundingClientRect.top) {
      best = entry
    }
  }
  if (!best) {
    return
  }
  const targetPage = Number((best.target as HTMLElement).dataset.page)
  if (Number.isFinite(targetPage) && targetPage !== props.page) {
    emit('sync-page', targetPage)
  }
}

watch(groups, () => {
  void nextTick(() => {
    scrollToPage(props.page)
    observeGroups()
  })
})

onMounted(() => {
  observer = new IntersectionObserver(onIntersect, {
    root: listRef.value,
    threshold: [0, 0.25, 0.5, 0.75, 1],
  })
  void nextTick(() => {
    scrollToPage(props.page)
    observeGroups()
  })
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

// ---------- 悬停翻译（500ms + 缓存） ----------

const hover = ref<HoverState | null>(null)
let hoverTimer: number | null = null
let closeTimer: number | null = null

function startHover(event: MouseEvent, block: GroupBlock): void {
  if (block.translation) {
    return
  }
  hoverTimer = window.setTimeout(() => {
    void requestHover(hashText(block.text), block.text, event.clientX, event.clientY)
  }, 500)
}

function cancelHover(): void {
  if (hoverTimer !== null) {
    window.clearTimeout(hoverTimer)
    hoverTimer = null
  }
  scheduleClose()
}

function scheduleClose(): void {
  if (closeTimer !== null) {
    window.clearTimeout(closeTimer)
  }
  closeTimer = window.setTimeout(() => {
    hover.value = null
  }, 250)
}

function keepHover(): void {
  if (closeTimer !== null) {
    window.clearTimeout(closeTimer)
    closeTimer = null
  }
}

async function requestHover(
  key: string,
  text: string,
  x: number,
  y: number,
): Promise<void> {
  const cached = hoverCache.get(key)
  if (cached) {
    hover.value = { key, x, y, text, result: cached, loading: false }
    return
  }
  hover.value = { key, x, y, text, result: null, loading: true }
  try {
    const result = await props.translateText(text)
    hoverCache.set(key, result)
    if (hover.value?.key === key) {
      hover.value = { key, x, y, text, result, loading: false }
    }
  } catch {
    if (hover.value?.key === key) {
      hover.value = {
        key,
        x,
        y,
        text,
        result: { translation: null, status: 'error' },
        loading: false,
      }
    }
  }
}

function retryHover(): void {
  const current = hover.value
  if (!current) {
    return
  }
  hoverCache.delete(current.key)
  void requestHover(current.key, current.text, current.x, current.y)
}

// ---------- 局部翻译（选中 / 粘贴文本） ----------

const selectionText = ref('')
const selectionTranslation = ref('')
const selectionStatus = ref('')
const translatingSelection = ref(false)

function captureSelection(): void {
  const selected = window.getSelection()?.toString().trim() ?? ''
  if (selected.length >= 2 && selected.length <= 1200) {
    selectionText.value = selected
  }
}

async function translateSelection(): Promise<void> {
  const text = selectionText.value.trim()
  if (!text || translatingSelection.value) {
    return
  }
  translatingSelection.value = true
  selectionStatus.value = ''
  selectionTranslation.value = ''
  try {
    const result = await props.translateText(text)
    selectionTranslation.value = result.translation ?? ''
    selectionStatus.value = result.status
  } catch (error) {
    selectionStatus.value = error instanceof Error ? error.message : String(error)
  } finally {
    translatingSelection.value = false
  }
}
</script>

<template>
  <div class="panel bilingual-pane">
    <div class="panel-head">
      <span class="panel-title">双语对照</span>
      <span class="mono faint">已译 {{ translatedPages }} 页</span>
    </div>
    <div class="bilingual-body">
      <details class="selection-box">
        <summary class="selection-summary">局部翻译（选中或粘贴文本）</summary>
        <div class="stack">
          <div class="row">
            <input v-model="selectionText" class="input" placeholder="粘贴一段原文" />
            <button
              class="btn btn-small"
              type="button"
              :disabled="translatingSelection || !selectionText.trim()"
              @click="translateSelection"
            >
              {{ translatingSelection ? '翻译中…' : '翻译' }}
            </button>
          </div>
          <p v-if="selectionTranslation" class="bilingual-target">
            {{ selectionTranslation }}
          </p>
          <p v-else-if="selectionStatus" class="faint">
            {{
              selectionStatus === 'not_configured'
                ? '当前未配置 LLM，无法翻译。'
                : selectionStatus
            }}
          </p>
        </div>
      </details>
      <div ref="listRef" class="bilingual-list" @mouseup="captureSelection">
        <section
          v-for="group in groups"
          :key="group.page"
          class="bilingual-group"
          :data-page="group.page"
        >
          <h4 class="group-title">p.{{ group.page }}</h4>
          <div
            v-for="block in group.blocks"
            :key="block.id"
            :class="['bilingual-block', block.kind ? `kind-${block.kind}` : '']"
          >
            <span v-if="kindLabel(block.kind)" class="kind-tag">{{ kindLabel(block.kind) }}</span>
            <p
              class="bilingual-source"
              @mouseenter="startHover($event, block)"
              @mouseleave="cancelHover"
            >
              <template v-for="(part, partIndex) in citationParts(block.text)" :key="partIndex">
                <button
                  v-if="part.type === 'ref' && part.index !== null"
                  class="cite-ref"
                  type="button"
                  @click="emit('jump-reference', part.index)"
                >
                  {{ part.value }}
                </button>
                <span v-else>{{ part.value }}</span>
              </template>
            </p>
            <p v-if="block.translation" class="bilingual-target">{{ block.translation }}</p>
            <p v-else-if="block.status === 'error'" class="bilingual-failed">
              <span class="mono">翻译失败</span>
              <button class="btn btn-ghost btn-small" type="button" @click="emit('translate-page')">
                重试
              </button>
            </p>
            <p v-else-if="block.status === 'not_configured'" class="faint mono">
              未配置 LLM
            </p>
          </div>
        </section>
        <p v-if="!groups.length" class="faint bilingual-empty">本页没有可显示的文本块</p>
      </div>
      <div class="bilingual-foot">
        <button
          class="btn btn-small"
          type="button"
          :disabled="translating || !blocks.length"
          @click="emit('translate-page')"
        >
          {{ translating ? '翻译中…' : `翻译第 ${page} 页` }}
        </button>
      </div>
    </div>

    <div
      v-if="hover"
      class="hover-popover"
      :style="{ left: `${hover.x + 14}px`, top: `${hover.y + 14}px` }"
      @mouseenter="keepHover"
      @mouseleave="scheduleClose"
    >
      <p v-if="hover.loading" class="faint mono">翻译中…</p>
      <template v-else-if="hover.result">
        <p v-if="hover.result.translation" class="hover-text">
          {{ hover.result.translation }}
        </p>
        <p v-else class="hover-failed">
          {{
            hover.result.status === 'not_configured'
              ? '当前未配置 LLM，无法翻译。'
              : '翻译失败。'
          }}
          <button class="btn btn-ghost btn-small" type="button" @click="retryHover">
            重试
          </button>
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.bilingual-pane {
  display: flex;
  flex-direction: column;
  max-height: 80vh;
  overflow: hidden;
}

.bilingual-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.selection-box {
  padding: 8px 12px;
  border-bottom: 1px solid var(--rule-soft);
  font-size: 12px;
}

.selection-summary {
  color: var(--ink-3);
  cursor: pointer;
}

.bilingual-list {
  flex: 1;
  min-height: 120px;
  padding: 10px 12px;
  overflow: auto;
}

.bilingual-group + .bilingual-group {
  margin-top: 16px;
}

.group-title {
  margin: 0 0 6px;
  color: var(--ink-3);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
}

.bilingual-block {
  padding: 6px 0;
  border-bottom: 1px solid var(--rule-soft);
}

.bilingual-block:last-child {
  border-bottom: none;
}

.kind-table {
  padding-left: 8px;
  border-left: 2px solid var(--series-2);
  background: rgba(235, 104, 52, 0.06);
}

.kind-formula {
  padding-left: 8px;
  border-left: 2px solid var(--series-3);
  background: rgba(98, 80, 214, 0.05);
}

.kind-figure_caption {
  padding-left: 8px;
  border-left: 2px solid var(--petrol);
  background: rgba(47, 93, 98, 0.05);
}

.kind-table .bilingual-source,
.kind-formula .bilingual-source {
  font-family: var(--font-mono);
  font-size: 11px;
}

.kind-table .bilingual-source {
  white-space: pre-line;
}

.kind-tag {
  display: inline-block;
  margin-bottom: 4px;
  padding: 1px 6px;
  border: 1px solid var(--rule-soft);
  border-radius: 999px;
  color: var(--ink-3);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
}

.bilingual-source {
  margin: 0;
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 12px;
  line-height: 1.6;
}

.bilingual-target {
  margin: 5px 0 0;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.7;
}

.bilingual-failed {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 5px 0 0;
  color: var(--oxblood);
  font-size: 12px;
}

.bilingual-empty {
  padding: 12px;
  font-size: 12px;
}

.bilingual-foot {
  display: flex;
  justify-content: flex-end;
  padding: 10px 12px;
  border-top: 1px solid var(--rule-soft);
}

.cite-ref {
  padding: 0 3px;
  border: none;
  background: transparent;
  color: var(--petrol);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  vertical-align: baseline;
}

.cite-ref:hover {
  color: var(--oxblood);
  text-decoration: underline;
}

.hover-popover {
  position: fixed;
  z-index: 40;
  max-width: 340px;
  padding: 10px 12px;
  border: 1px solid var(--rule-soft);
  border-radius: 8px;
  background: var(--paper);
  box-shadow: 0 6px 20px rgba(29, 36, 32, 0.14);
  font-size: 13px;
}

.hover-text {
  margin: 0;
  line-height: 1.7;
}

.hover-failed {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  color: var(--oxblood);
  font-size: 12px;
}
</style>
