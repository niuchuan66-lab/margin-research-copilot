import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/endpoints'
import type {
  DedupActionResponse,
  DedupResult,
  PaperSummary,
  ParseJob,
} from '@/types'

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

export const usePapersStore = defineStore('papers', () => {
  const papers = ref<PaperSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastDedup = ref<DedupResult | null>(null)
  const lastDedupPaperId = ref<string | null>(null)
  const jobs = ref<Record<string, ParseJob>>({})
  const polling = new Set<string>()

  const readyPapers = computed(() =>
    papers.value.filter((paper) => paper.status === 'ready'),
  )

  async function fetchPapers(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      papers.value = await api.listPapers()
      for (const paper of papers.value.filter((item) => item.status === 'parsing')) {
        try {
          const job = await api.parseStatus(paper.id)
          jobs.value[paper.id] = job
          if (job.status === 'queued' || job.status === 'running') {
            void pollJob(paper.id)
          }
        } catch {
          // The backend may have restarted and lost its in-memory job.
        }
      }
    } catch (cause) {
      error.value = messageOf(cause)
    } finally {
      loading.value = false
    }
  }

  async function uploadAndParse(file: File): Promise<ParseJob> {
    error.value = null
    const uploaded = await api.uploadPaper(file)
    await fetchPapers()
    const job = await api.parsePaper(uploaded.paper.id)
    jobs.value[job.paper_id] = job
    void pollJob(job.paper_id)
    return job
  }

  async function parsePaper(paperId: string): Promise<ParseJob> {
    error.value = null
    const job = await api.parsePaper(paperId)
    jobs.value[job.paper_id] = job
    void pollJob(job.paper_id)
    return job
  }

  async function pollJob(paperId: string): Promise<void> {
    if (polling.has(paperId)) {
      return
    }
    polling.add(paperId)
    try {
      for (;;) {
        await delay(1000)
        const job = await api.parseStatus(paperId)
        jobs.value[paperId] = job
        if (job.status === 'done') {
          if (job.dedup) {
            lastDedup.value = job.dedup
            lastDedupPaperId.value = job.paper_id
          }
          await fetchPapers()
          break
        }
        if (job.status === 'failed') {
          error.value = job.error ?? job.message
          await fetchPapers()
          break
        }
      }
    } catch (cause) {
      error.value = messageOf(cause)
    } finally {
      polling.delete(paperId)
    }
  }

  function jobFor(paperId: string): ParseJob | undefined {
    return jobs.value[paperId]
  }

  function isParsing(paperId: string): boolean {
    const job = jobs.value[paperId]
    return job?.status === 'queued' || job?.status === 'running'
  }

  async function removePaper(paperId: string): Promise<void> {
    await api.deletePaper(paperId)
    delete jobs.value[paperId]
    await fetchPapers()
  }

  function dismissDedup(): void {
    lastDedup.value = null
    lastDedupPaperId.value = null
  }

  async function resolveDedup(
    action: 'replace' | 'keep',
    candidateId?: string,
  ): Promise<DedupActionResponse> {
    const paperId = lastDedupPaperId.value
    if (!paperId) {
      throw new Error('没有待处理的重复提示')
    }
    const result = await api.resolveDedup(paperId, action, candidateId)
    dismissDedup()
    await fetchPapers()
    return result
  }

  return {
    papers,
    loading,
    error,
    lastDedup,
    lastDedupPaperId,
    jobs,
    readyPapers,
    fetchPapers,
    uploadAndParse,
    parsePaper,
    pollJob,
    jobFor,
    isParsing,
    removePaper,
    dismissDedup,
    resolveDedup,
  }
})
