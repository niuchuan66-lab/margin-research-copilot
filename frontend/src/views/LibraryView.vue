<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import StatusTag from '@/components/StatusTag.vue'
import UploadDropzone from '@/components/UploadDropzone.vue'
import { errorMessage, formatDate } from '@/lib/format'
import { usePapersStore } from '@/stores/papers'

const store = usePapersStore()
const router = useRouter()
const busy = ref(false)
const resolvingDedup = ref(false)
const notice = ref('')
const failure = ref('')

const dedup = computed(() => store.lastDedup)
const dedupTitle = computed(() => dedup.value?.candidates[0]?.title ?? '已有论文')
const dedupPercent = computed(() => Math.round((dedup.value?.similarity ?? 0) * 100))

onMounted(() => {
  void store.fetchPapers()
})

async function handleFile(file: File): Promise<void> {
  busy.value = true
  notice.value = ''
  failure.value = ''
  try {
    const job = await store.uploadAndParse(file)
    notice.value = `已开始解析（任务 ${job.job_id}）`
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    busy.value = false
  }
}

async function parse(paperId: string): Promise<void> {
  busy.value = true
  failure.value = ''
  try {
    await store.parsePaper(paperId)
    notice.value = '已开始解析'
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    busy.value = false
  }
}

function actionLabel(action?: string): string {
  if (action === 'replace') {
    return '用较新版本覆盖'
  }
  if (action === 'keep') {
    return '保留库中较新版本'
  }
  return '人工确认版本'
}

function openPaper(paperId: string): void {
  void router.push(`/reader/${paperId}`)
}

async function handleDedup(action: 'replace' | 'keep'): Promise<void> {
  const candidate = store.lastDedup?.candidates[0]
  if (!candidate) {
    return
  }
  if (action === 'replace') {
    const title = candidate.title ?? candidate.paper_id
    if (!window.confirm(`将删除旧版《${title}》，保留刚解析的版本。继续？`)) {
      return
    }
  }
  resolvingDedup.value = true
  failure.value = ''
  try {
    const result = await store.resolveDedup(action, candidate.paper_id)
    notice.value =
      result.action === 'replace' ? '已用新版覆盖旧版' : '已保留两个版本'
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    resolvingDedup.value = false
  }
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">书架</h1>
        <p class="page-meta">
          {{ store.papers.length }} 篇 · {{ store.readyPapers.length }} 篇可读
        </p>
      </div>
      <RouterLink class="btn btn-ghost btn-small" to="/discovery">去发现新论文</RouterLink>
    </header>

    <UploadDropzone :busy="busy" @file="handleFile" />

    <p v-if="notice" class="notice-line">{{ notice }}</p>
    <p v-if="failure" class="error-line">{{ failure }}</p>

    <div v-if="dedup?.is_duplicate" class="dedup">
      <div>
        <strong>检测到重复论文</strong>
        <p class="muted">
          与《{{ dedupTitle }}》相似度 {{ dedupPercent }}%。建议：{{ actionLabel(dedup.action) }}。
        </p>
      </div>
      <div class="dedup-actions">
        <button
          class="btn btn-small"
          type="button"
          :disabled="resolvingDedup"
          @click="handleDedup('replace')"
        >
          用新版覆盖
        </button>
        <button
          class="btn btn-ghost btn-small"
          type="button"
          :disabled="resolvingDedup"
          @click="handleDedup('keep')"
        >
          保留两者
        </button>
        <button
          class="btn btn-ghost btn-small"
          type="button"
          :disabled="resolvingDedup"
          @click="store.dismissDedup()"
        >
          稍后处理
        </button>
      </div>
    </div>

    <div v-if="store.loading" class="empty">正在读取书架…</div>
    <p v-else-if="!store.papers.length" class="empty-hint">
      书架是空的。解析、问答、图谱都会从这一篇 PDF 开始。
    </p>
    <div v-else class="table-wrap panel">
      <table class="table">
        <thead>
          <tr>
            <th>论文</th>
            <th>状态</th>
            <th>页数</th>
            <th>解析器</th>
            <th>加入时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="paper in store.papers" :key="paper.id">
            <td>
              <div class="paper-title">{{ paper.title ?? paper.filename }}</div>
              <div class="mono faint">{{ paper.filename }}</div>
            </td>
            <td>
              <div class="status-cell">
                <StatusTag :status="paper.status" />
                <div
                  v-if="store.jobFor(paper.id) && store.jobFor(paper.id)?.status !== 'done'"
                  class="job"
                >
                  <div class="job-line mono">
                    {{ store.jobFor(paper.id)?.stage }} ·
                    {{ store.jobFor(paper.id)?.percent }}%
                  </div>
                  <div class="progress">
                    <span :style="{ width: `${store.jobFor(paper.id)?.percent ?? 0}%` }"></span>
                  </div>
                  <div class="faint job-message">{{ store.jobFor(paper.id)?.message }}</div>
                </div>
              </div>
            </td>
            <td class="mono">{{ paper.pages || '—' }}</td>
            <td class="mono">{{ paper.parse_engine ?? '—' }}</td>
            <td class="mono">{{ formatDate(paper.created_at) }}</td>
            <td>
              <button
                v-if="paper.status === 'ready'"
                class="btn btn-small"
                type="button"
                @click="openPaper(paper.id)"
              >
                阅读
              </button>
              <button
                v-else
                class="btn btn-ghost btn-small"
                type="button"
                :disabled="busy || paper.status === 'parsing' || store.isParsing(paper.id)"
                @click="parse(paper.id)"
              >
                解析
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.notice-line {
  margin-top: 10px;
  color: var(--petrol);
  font-size: 13px;
}

.error-line {
  margin-top: 10px;
  color: var(--oxblood);
  font-size: 13px;
}

.dedup {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid rgba(122, 46, 53, 0.35);
  border-left: 3px solid var(--oxblood);
  background: rgba(122, 46, 53, 0.04);
}

.dedup strong {
  font-family: var(--font-serif);
  font-size: 15px;
}

.dedup p {
  margin-top: 3px;
  font-size: 13px;
}

.dedup-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.table-wrap {
  margin-top: 20px;
  overflow: auto;
}

.empty-hint {
  margin-top: 16px;
  color: var(--ink-3);
  font-size: 13px;
}

.paper-title {
  max-width: 520px;
  font-family: var(--font-serif);
  font-size: 15px;
}

.status-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 150px;
}

.job {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.job-line {
  color: var(--ink-3);
  font-size: 10px;
}

.progress {
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--rule-soft);
}

.progress span {
  display: block;
  height: 100%;
  background: var(--petrol);
  transition: width 240ms ease;
}

.job-message {
  font-size: 11px;
  line-height: 1.4;
}
</style>
