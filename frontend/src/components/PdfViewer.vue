<script setup lang="ts">
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
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
    zoom?: number
    highlight?: Highlight | null
  }>(),
  { page: 1, zoom: 1, highlight: null },
)

const emit = defineEmits<{ loaded: [number] }>()
const shellRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const error = ref('')
const highlightStyle = ref<Record<string, string> | null>(null)

let pdf: PDFDocumentProxy | null = null
let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null
let resizeObserver: ResizeObserver | null = null
let renderToken = 0
let lastWidth = 0

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

function shellWidth(): number {
  const shell = shellRef.value
  const padding = 32
  return shell ? Math.max(shell.clientWidth - padding, 240) : 640
}

async function render(reason: 'page' | 'zoom' | 'resize' = 'page'): Promise<void> {
  if (!pdf || !canvasRef.value) {
    return
  }
  const token = ++renderToken
  try {
    const pageNumber = Math.min(Math.max(props.page, 1), pdf.numPages)
    const page: PDFPageProxy = await pdf.getPage(pageNumber)
    if (token !== renderToken) {
      return
    }
    const baseViewport = page.getViewport({ scale: 1 })
    const fitScale = shellWidth() / baseViewport.width
    const cssViewport = page.getViewport({ scale: fitScale * props.zoom })
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const deviceViewport = page.getViewport({ scale: fitScale * props.zoom * ratio })

    const canvas = canvasRef.value
    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('当前浏览器不支持 Canvas 2D')
    }
    canvas.width = Math.floor(deviceViewport.width)
    canvas.height = Math.floor(deviceViewport.height)
    canvas.style.width = `${Math.floor(cssViewport.width)}px`
    canvas.style.height = `${Math.floor(cssViewport.height)}px`

    renderTask?.cancel()
    renderTask = page.render({ canvasContext: context, viewport: deviceViewport })
    await renderTask.promise
    if (token !== renderToken) {
      return
    }
    applyHighlight(page.view, cssViewport)
    state.value = 'ready'
    if (reason === 'resize') {
      lastWidth = shellWidth()
    }
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'RenderingCancelledException') {
      return
    }
    if (token !== renderToken) {
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

onMounted(() => {
  void load()
  const shell = shellRef.value
  if (shell && typeof ResizeObserver !== 'undefined') {
    lastWidth = shellWidth()
    resizeObserver = new ResizeObserver(() => {
      const width = shellWidth()
      if (state.value === 'ready' && Math.abs(width - lastWidth) >= 2) {
        lastWidth = width
        void render('resize')
      }
    })
    resizeObserver.observe(shell)
  }
})

onBeforeUnmount(() => {
  renderToken += 1
  renderTask?.cancel()
  resizeObserver?.disconnect()
  void pdf?.destroy()
})

watch(() => props.url, load)
watch(() => props.page, () => void render('page'))
watch(() => props.zoom, () => void render('zoom'))
watch(() => props.highlight, () => void render('page'), { deep: true })
</script>

<template>
  <div ref="shellRef" class="pdf-shell">
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
  display: block;
  min-height: 420px;
  max-height: 80vh;
  padding: 16px;
  background: var(--paper-2);
  overflow: auto;
}

.pdf-page {
  position: relative;
  width: max-content;
  margin: 0 auto;
  line-height: 0;
  box-shadow: 0 1px 3px rgba(29, 36, 32, 0.12);
}

.pdf-canvas {
  display: block;
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
