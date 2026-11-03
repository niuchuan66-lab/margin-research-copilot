<script setup lang="ts">
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ option: Record<string, unknown> }>()
const container = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function render(): void {
  chart?.setOption(props.option as echarts.EChartsOption, true)
}

onMounted(async () => {
  await nextTick()
  if (!container.value) {
    return
  }
  chart = echarts.init(container.value, undefined, { renderer: 'canvas' })
  render()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(container.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})

watch(() => props.option, render, { deep: true })
</script>

<template>
  <div ref="container" class="chart-canvas" role="img" aria-label="数据图表"></div>
</template>

<style scoped>
.chart-canvas {
  width: 100%;
  height: 380px;
}
</style>
