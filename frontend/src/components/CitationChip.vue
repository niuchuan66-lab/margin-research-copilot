<script setup lang="ts">
import type { Citation } from '@/types'

defineProps<{ citation: Citation }>()
const emit = defineEmits<{ select: [Citation] }>()
</script>

<template>
  <button class="citation" type="button" @click="emit('select', citation)">
    <span class="citation-page">p.{{ citation.page }}</span>
    <span class="citation-title">{{ citation.paper_title ?? citation.paper_id }}</span>
    <span class="citation-quote">{{ citation.quote.slice(0, 90) }}</span>
  </button>
</template>

<style scoped>
.citation {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 2px 10px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--rule-soft);
  border-left: 2px solid var(--petrol);
  border-radius: var(--radius);
  background: var(--surface);
  text-align: left;
}

.citation:hover {
  border-left-color: var(--oxblood);
  background: var(--paper-2);
}

.citation-page {
  color: var(--petrol);
  font-family: var(--font-mono);
  font-size: 10px;
  white-space: nowrap;
}

.citation-title {
  overflow: hidden;
  color: var(--ink);
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-quote {
  grid-column: 1 / -1;
  display: -webkit-box;
  overflow: hidden;
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 12px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
</style>
