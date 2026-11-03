<script setup lang="ts">
import type { PaperStatus } from '@/types'

defineProps<{ status: PaperStatus }>()

const labels: Record<PaperStatus, string> = {
  uploaded: '待解析',
  parsing: '解析中',
  ready: '可阅读',
  failed: '失败',
}
</script>

<template>
  <span class="tag" :class="`tag-${status}`">{{ labels[status] }}</span>
</template>
