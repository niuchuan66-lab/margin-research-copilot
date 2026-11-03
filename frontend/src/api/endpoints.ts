import type {
  Anchor,
  AnswerResponse,
  Block,
  ChartResponse,
  DedupActionResponse,
  DedupCandidate,
  DiscoveryHit,
  FigureResponse,
  FutureWorkResponse,
  GraphResponse,
  HealthResponse,
  OutlineItem,
  OutlineResponse,
  Paper,
  PaperSummary,
  ParseJob,
  ReferenceItem,
  TextTranslationResponse,
  TranslatedBlock,
  UploadResponse,
  VersionDiffResponse,
} from '@/types'

import { apiFetch } from './client'

export const api = {
  health: () => apiFetch<HealthResponse>('/health'),

  listPapers: () => apiFetch<PaperSummary[]>('/papers'),
  getPaper: (paperId: string, includeBlocks = true) =>
    apiFetch<Paper>(`/papers/${paperId}?include_blocks=${includeBlocks}`),
  pageBlocks: (paperId: string, page: number) =>
    apiFetch<Block[]>(`/papers/${paperId}/blocks?page=${page}`),
  uploadPaper: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<UploadResponse>('/papers', { method: 'POST', body: form })
  },
  parsePaper: (paperId: string) =>
    apiFetch<ParseJob>(`/papers/${paperId}/parse`, { method: 'POST' }),
  parseStatus: (paperId: string) =>
    apiFetch<ParseJob>(`/papers/${paperId}/parse-status`),
  resolveDedup: (
    paperId: string,
    action: 'replace' | 'keep',
    candidateId?: string,
  ) =>
    apiFetch<DedupActionResponse>(`/papers/${paperId}/dedup`, {
      method: 'POST',
      body: JSON.stringify({
        action,
        candidate_id: candidateId ?? null,
      }),
    }),
  paperVersions: (paperId: string) =>
    apiFetch<DedupCandidate[]>(`/papers/${paperId}/versions`),
  paperDiff: (newId: string, oldId: string) =>
    apiFetch<VersionDiffResponse>(`/papers/${newId}/diff/${oldId}`),
  deletePaper: (paperId: string) =>
    apiFetch<{ deleted: boolean }>(`/papers/${paperId}`, { method: 'DELETE' }),
  paperFileUrl: (paperId: string) => `/api/v1/papers/${paperId}/file`,

  ask: (question: string, paperIds: string[], topK = 6) =>
    apiFetch<AnswerResponse>('/qa/ask', {
      method: 'POST',
      body: JSON.stringify({ question, paper_ids: paperIds, top_k: topK }),
    }),

  anchors: (paperId: string) => apiFetch<Anchor[]>(`/reader/${paperId}/anchors`),
  readerOutline: (paperId: string) =>
    apiFetch<OutlineItem[]>(`/reader/${paperId}/outline`),
  readerReferences: (paperId: string) =>
    apiFetch<ReferenceItem[]>(`/reader/${paperId}/references`),
  translate: (paperId: string, blockIds: string[], targetLang = 'zh-CN') =>
    apiFetch<TranslatedBlock[]>('/reader/translate', {
      method: 'POST',
      body: JSON.stringify({
        paper_id: paperId,
        block_ids: blockIds,
        target_lang: targetLang,
      }),
    }),
  translateText: (text: string, targetLang = 'zh-CN') =>
    apiFetch<TextTranslationResponse>('/reader/translate-text', {
      method: 'POST',
      body: JSON.stringify({ text, target_lang: targetLang }),
    }),

  discovery: (query: string, source: 'arxiv' | 'openalex' = 'arxiv', limit = 10) =>
    apiFetch<DiscoveryHit[]>('/discovery/search', {
      method: 'POST',
      body: JSON.stringify({ query, source, limit }),
    }),
  recommend: (paperIds: string[], limit = 8) =>
    apiFetch<DiscoveryHit[]>('/discovery/recommend', {
      method: 'POST',
      body: JSON.stringify({ paper_ids: paperIds, limit }),
    }),

  buildGraph: (paperIds: string[] = []) =>
    apiFetch<GraphResponse>('/graph/build', {
      method: 'POST',
      body: JSON.stringify({ paper_ids: paperIds }),
    }),
  survey: (graphId: string) =>
    apiFetch<{ graph_id: string; markdown: string }>(`/graph/${graphId}/survey`, {
      method: 'POST',
    }),
  futureWork: (graphId: string) =>
    apiFetch<FutureWorkResponse>(`/graph/${graphId}/future-work`, {
      method: 'POST',
    }),

  writingOutline: (idea: string, paperIds: string[] = [], language: 'zh' | 'en' = 'zh') =>
    apiFetch<OutlineResponse>('/writing/outline', {
      method: 'POST',
      body: JSON.stringify({ idea, paper_ids: paperIds, language }),
    }),
  figure: (kind: 'mermaid' | 'graphviz' | 'tikz', spec: string) =>
    apiFetch<FigureResponse>('/writing/figure', {
      method: 'POST',
      body: JSON.stringify({ kind, spec }),
    }),
  chart: (csv: string, title: string, chartType: 'line' | 'bar' | 'radar' = 'line') =>
    apiFetch<ChartResponse>('/writing/chart', {
      method: 'POST',
      body: JSON.stringify({ csv, title, chart_type: chartType }),
    }),
}
