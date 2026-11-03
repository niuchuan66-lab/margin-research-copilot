<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { API_BASE } from '@/api/client'

const route = useRoute()

const remoteApi = computed(() => /^https?:\/\//.test(API_BASE))
const workspaceLabel = computed(() => (remoteApi.value ? '云端工作区' : '本地工作区'))
const apiLabel = computed(() => (remoteApi.value ? 'API 在线' : 'API 本地'))

const nav = [
  { to: '/library', label: '书架' },
  { to: '/reader', label: '阅读' },
  { to: '/chat', label: '问答' },
  { to: '/discovery', label: '发现' },
  { to: '/graph', label: '图谱' },
  { to: '/writing', label: '写作' },
]

const currentTitle = computed(() => String(route.meta.title ?? 'Margin'))
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <RouterLink class="brand" to="/library">
        <span class="brand-mark">M</span>
        <span>
          <span class="brand-name">Margin</span>
          <span class="brand-sub">科研助手</span>
        </span>
      </RouterLink>

      <nav class="rail-nav" aria-label="主导航">
        <RouterLink v-for="item in nav" :key="item.to" class="rail-link" :to="item.to">
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="rail-foot">
        <span class="rail-note">{{ workspaceLabel }}</span>
        <span class="rail-version">v0.1</span>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div class="topbar-title">{{ currentTitle }}</div>
        <div class="topbar-actions">
          <span class="status-dot" aria-hidden="true"></span>
          <span class="muted">{{ apiLabel }}</span>
          <RouterLink class="btn btn-ghost" to="/library">上传 PDF</RouterLink>
        </div>
      </header>

      <main class="surface">
        <slot />
      </main>
    </div>
  </div>
</template>
