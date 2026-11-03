<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import { errorMessage } from '@/lib/format'
import { usePapersStore } from '@/stores/papers'
import type { DiscoveryHit } from '@/types'

const papers = usePapersStore()
const query = ref('retrieval augmented generation')
const source = ref<'arxiv' | 'openalex'>('arxiv')
const hits = ref<DiscoveryHit[]>([])
const loading = ref(false)
const failure = ref('')

onMounted(() => {
  void papers.fetchPapers()
})

async function search(): Promise<void> {
  if (!query.value.trim()) {
    return
  }
  loading.value = true
  failure.value = ''
  try {
    hits.value = await api.discovery(query.value.trim(), source.value, 10)
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function recommend(): Promise<void> {
  const ids = papers.readyPapers.map((paper) => paper.id)
  if (!ids.length) {
    failure.value = '书架里还没有已解析的论文，先上传几篇再做推荐。'
    return
  }
  loading.value = true
  failure.value = ''
  try {
    hits.value = await api.recommend(ids, 8)
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">发现</h1>
        <p class="page-meta">arXiv / OpenAlex 检索，下载 PDF 后在书架入库</p>
      </div>
      <button
        class="btn btn-ghost btn-small"
        type="button"
        :disabled="loading"
        @click="recommend"
      >
        按书架推荐
      </button>
    </header>

    <form class="search-bar panel" @submit.prevent="search">
      <input v-model="query" class="input" placeholder="主题、论文名或关键词" />
      <select v-model="source" class="select source-select" aria-label="数据源">
        <option value="arxiv">arXiv</option>
        <option value="openalex">OpenAlex</option>
      </select>
      <button class="btn" type="submit" :disabled="loading || !query.trim()">
        {{ loading ? '检索中…' : '检索' }}
      </button>
    </form>

    <p v-if="failure" class="error-line">{{ failure }}</p>
    <div v-if="loading" class="empty">正在检索学术源…</div>
    <div v-else-if="!hits.length" class="empty">
      <div>
        <p class="empty-title">输入一个主题开始</p>
        <p class="muted">结果只做发现；把 PDF 下载后到书架上传，才能进入问答与图谱。</p>
      </div>
    </div>

    <div v-else class="hit-list">
      <article v-for="hit in hits" :key="`${hit.source}-${hit.title}`" class="hit panel">
        <div class="hit-head">
          <h2 class="hit-title">{{ hit.title }}</h2>
          <span class="tag">{{ hit.source }}</span>
        </div>
        <p class="hit-meta mono">
          {{ hit.authors.slice(0, 4).join('、') || '作者未明确' }} ·
          {{ hit.year ?? '年份未明确' }}
        </p>
        <p v-if="hit.abstract" class="hit-abstract">{{ hit.abstract }}</p>
        <div class="hit-actions">
          <a v-if="hit.url" class="btn btn-ghost btn-small" :href="hit.url" target="_blank" rel="noreferrer">
            打开原文
          </a>
          <a v-if="hit.github_url" class="btn btn-ghost btn-small" :href="hit.github_url" target="_blank" rel="noreferrer">
            GitHub
          </a>
          <span v-if="hit.reason" class="faint mono">{{ hit.reason }}</span>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.search-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 140px auto;
  gap: 8px;
  padding: 10px;
}

.source-select {
  width: 100%;
}

.error-line {
  margin-top: 12px;
  color: var(--oxblood);
  font-size: 13px;
}

.hit-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 18px;
}

.hit {
  padding: 16px;
}

.hit-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hit-title {
  font-size: 19px;
  line-height: 1.35;
}

.hit-meta {
  margin-top: 5px;
  color: var(--ink-3);
}

.hit-abstract {
  margin-top: 10px;
  color: var(--ink-2);
  font-family: var(--font-serif);
  font-size: 13px;
  line-height: 1.7;
}

.hit-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

@media (max-width: 700px) {
  .search-bar {
    grid-template-columns: 1fr;
  }
}
</style>
