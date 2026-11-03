<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ busy?: boolean }>()
const emit = defineEmits<{ file: [File] }>()
const dragging = ref(false)

function pick(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('file', file)
  }
  input.value = ''
}

function drop(event: DragEvent): void {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) {
    emit('file', file)
  }
}
</script>

<template>
  <label
    class="dropzone"
    :class="{ dragging, busy }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="drop"
  >
    <input
      class="sr-only"
      type="file"
      accept="application/pdf"
      :disabled="busy"
      @change="pick"
    />
    <span class="drop-title">{{ busy ? '正在解析…' : '把 PDF 放到这里' }}</span>
    <span class="drop-note">单篇上传，解析后可检索、问答与建图谱</span>
  </label>
</template>

<style scoped>
.dropzone {
  display: grid;
  place-items: center;
  gap: 4px;
  min-height: 150px;
  border: 1px dashed var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.dropzone:hover,
.dropzone.dragging {
  border-color: var(--oxblood);
  background: var(--paper-2);
}

.dropzone.busy {
  cursor: progress;
  opacity: 0.7;
}

.drop-title {
  font-family: var(--font-serif);
  font-size: 20px;
}

.drop-note {
  color: var(--ink-3);
  font-size: 12px;
}
</style>
