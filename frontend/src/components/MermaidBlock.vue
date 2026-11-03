<script setup lang="ts">
import mermaid from 'mermaid'
import { onMounted, ref, watch } from 'vue'

const props = defineProps<{ code: string }>()
const host = ref<HTMLDivElement | null>(null)
const error = ref('')

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'base',
  themeVariables: {
    fontFamily: 'Public Sans, Segoe UI, sans-serif',
    primaryColor: '#FCFCFB',
    primaryTextColor: '#1D2420',
    primaryBorderColor: '#7A2E35',
    lineColor: '#5A625C',
    secondaryColor: '#EEF1EC',
    tertiaryColor: '#F7F8F5',
  },
})

async function render(): Promise<void> {
  if (!host.value) {
    return
  }
  error.value = ''
  try {
    const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`
    const { svg } = await mermaid.render(id, props.code)
    host.value.innerHTML = svg
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(render)
watch(() => props.code, render)
</script>

<template>
  <div class="mermaid-block">
    <div v-if="error" class="mermaid-error">{{ error }}</div>
    <div v-else ref="host" class="mermaid-host"></div>
  </div>
</template>

<style scoped>
.mermaid-block {
  min-height: 160px;
  padding: 14px;
  overflow: auto;
  border: 1px solid var(--rule-soft);
  background: var(--surface);
}

.mermaid-host :deep(svg) {
  max-width: 100%;
  height: auto;
}

.mermaid-error {
  color: var(--oxblood);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
}
</style>
