<script setup lang="ts">
defineProps<{ trace: string[] }>()
</script>

<template>
  <details v-if="trace.length" class="trace">
    <summary>Agent 过程 · {{ trace.length }} 步</summary>
    <ol>
      <li v-for="(step, index) in trace" :key="index">{{ step }}</li>
    </ol>
  </details>
</template>

<style scoped>
.trace {
  border-top: 1px solid var(--rule-soft);
  padding-top: 8px;
  color: var(--ink-3);
  font-size: 12px;
}

.trace summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 10px;
}

.trace ol {
  margin: 8px 0 0;
  padding-left: 18px;
  line-height: 1.7;
}
</style>
