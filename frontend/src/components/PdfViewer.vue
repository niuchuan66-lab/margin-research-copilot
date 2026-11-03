<script setup lang="ts">
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

interface Highlight {
  bbox: number[]
  space: 'bottom-left' | 'top-left'
}

const props = withDefaults(
  defineProps<{
    url: string
    page?: number
    scale?: number
    highlight?: Highlight | null
  }>(),
  { page: 1, scale: 1.45, highlight: null },
)

const emit = defineEmits<{ loaded: [number] }>()
const canvasRef = ref<HTMLCanvasElement | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const error = ref('')
const highlightStyle = ref<Record<string, string> | null>(null)

let pdf: PDFDocumentProxy | null = null
let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null

async function load(): Promise<void> {
  state.value = 'loading'
  error.value = ''
  try {
    if (pdf) {
      await pdf.destroy()
      pdf = null
    }
    pdf = await pdfjsLib.getDocument({ url: props.url }).promise
    emit('loaded', pdf.numPages)
    await render()
  } catch (cause) {
    state.value = 'error'
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function render(): Promise<void> {
  if (!pdf || !canvasRef.value) {
    return
  }
  try {
    const pageNumber = Math.min(Math.max(props.page, 1), pdf.numPages)
    const page = await pdf.getPage(pageNumber)
    const viewport = page.getViewport({ scale: props.scale })
    const canvas = canvasRef.value
    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('当前浏览器不支持 Canvas 2D')
    }
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    renderTask?.cancel()
    renderTask = page.render({ canvasContext: context, viewport })
    await renderTask.promise
    applyHighlight(page.view, viewport)
    state.value = 'ready'
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'RenderingCancelledException') {
      return
    }
    state.value = 'error'
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function applyHighlight(
  pageView: number[],
  viewport: { convertToViewportRectangle: (rect: number[]) => number[] },
): void {
  const highlight = props.highlight
  if (!highlight || highlight.bbox.length !== 4) {
    highlightStyle.value = null
    return
  }
  const [x0, y0, x1, y1] = highlight.bbox
  let pdfY0 = y0
  let pdfY1 = y1
  if (highlight.space === 'top-left') {
    const height = pageView[3] - pageView[1]
    pdfY0 = height - y0
    pdfY1 = height - y1
  }
  const rect = viewport.convertToViewportRectangle([x0, pdfY0, x1, pdfY1])
  const left = Math.min(rect[0], rect[2])
  const top = Math.min(rect[1], rect[3])
  const width = Math.abs(rect[2] - rect[0])
  const height = Math.abs(rect[3] - rect[1])
  highlightStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
  }
}

onMounted(load)
onBeforeUnmount(() => {
  renderTask?.cancel()
  void pdf?.destroy()
})

watch(() => props.url, load)
watch(() => props.page, render)
watch(() => props.highlight, render, { deep: true })
</script>

<template>
  <div class="pdf-shell">
    <div v-if="state === 'loading'" class="pdf-status">正在渲染 PDF…</div>
    <div v-else-if="state === 'error'" class="pdf-status pdf-error">
      {{ error || 'PDF 加载失败' }}
    </div>
    <div class="pdf-page">
      <canvas ref="canvasRef" class="pdf-canvas" aria-label="PDF 页面"></canvas>
      <div v-if="highlightStyle" class="pdf-highlight" :style="highlightStyle"></div>
    </div>
  </div>
</template>

<style scoped>
.pdf-shell {
  position: relative;
  display: grid;
  place-items: start center;
  min-height: 420px;
  padding: 16px;
  background: var(--paper-2);
  overflow: auto;
}

.pdf-page {
  position: relative;
  line-height: 0;
  box-shadow: 0 1px 3px rgba(29, 36, 32, 0.12);
}

.pdf-canvas {
  display: block;
  max-width: 100%;
  height: auto;
  background: #fff;
}

.pdf-highlight {
  position: absolute;
  border: 1px solid rgba(122, 46, 53, 0.55);
  background: rgba(232, 199, 122, 0.32);
  pointer-events: none;
}

.pdf-status {
  position: absolute;
  inset: 16px;
  display: grid;
  place-items: center;
  color: var(--ink-3);
  font-size: 13px;
}

.pdf-error {
  color: var(--oxblood);
}
</style>
