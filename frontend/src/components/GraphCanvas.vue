<script setup lang="ts">
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { GraphEdge, GraphNode } from '@/types'

const props = defineProps<{ nodes: GraphNode[]; edges: GraphEdge[] }>()
const container = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function render(): void {
  if (!chart) {
    return
  }
  const chartNodes = props.nodes.map((node) => {
    const isReferenceOnly = node.id.startsWith('ref:')
    return {
      id: node.id,
      name: node.title,
      value: node.citations,
      category: isReferenceOnly ? 1 : 0,
      symbolSize:
        10 +
        Math.min(
          26,
          Math.sqrt(Math.max(node.centrality, 0)) * 150 + Math.min(node.citations, 10) * 1.8,
        ),
      label: { show: node.is_cornerstone },
      itemStyle: node.is_cornerstone
        ? { borderColor: '#7A2E35', borderWidth: 2 }
        : undefined,
      meta: node,
    }
  })
  const chartEdges = props.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
  }))

  chart.setOption(
    {
      backgroundColor: 'transparent',
      color: ['#2a78d6', '#8a8f98'],
      tooltip: {
        backgroundColor: '#FCFCFB',
        borderColor: '#D8D4C8',
        textStyle: { color: '#1D2420', fontSize: 12 },
        formatter: (params: { data?: { meta?: GraphNode } }) => {
          const meta = params.data?.meta
          if (!meta) {
            return ''
          }
          return [
            `<strong>${escapeHtml(meta.title)}</strong>`,
            `年份：${meta.year ?? '未明确'}`,
            `被引：${meta.citations}`,
            `中心度：${meta.centrality}`,
          ].join('<br/>')
        },
      },
      legend: {
        data: ['库内论文', '引用文献'],
        bottom: 0,
        icon: 'roundRect',
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#5A625C', fontSize: 11 },
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories: [{ name: '库内论文' }, { name: '引用文献' }],
          data: chartNodes,
          links: chartEdges,
          force: { repulsion: 200, edgeLength: [60, 130], gravity: 0.08 },
          lineStyle: { color: '#B9BDB6', width: 1, curveness: 0.08 },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: 6,
          label: {
            position: 'right',
            color: '#1D2420',
            fontSize: 11,
            formatter: (params: { name?: string }) => {
              const name = params.name ?? ''
              return name.length > 20 ? `${name.slice(0, 18)}…` : name
            },
          },
          emphasis: { focus: 'adjacency', lineStyle: { width: 2 } },
        },
      ],
    } as echarts.EChartsOption,
    true,
  )
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

watch(() => [props.nodes, props.edges], render, { deep: true })
</script>

<template>
  <div ref="container" class="graph-canvas" role="img" aria-label="引用关系图谱"></div>
</template>

<style scoped>
.graph-canvas {
  width: 100%;
  height: 520px;
}
</style>
