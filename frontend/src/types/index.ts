export type PaperStatus = 'uploaded' | 'parsing' | 'ready' | 'failed'

export interface PaperSummary {
  id: string
  filename: string
  title: string | null
  status: PaperStatus
  pages: number
  parse_engine: string | null
  created_at: string
}

export interface Block {
  id: string
  page: number
  text: string
  bbox: number[] | null
  bbox_space: 'bottom-left' | 'top-left'
  kind: string
  section_path: string[]
}

export interface Reference {
  id: string
  title: string | null
  authors: string[]
  year: number | null
  venue: string | null
  doi: string | null
  arxiv_id: string | null
  raw: string | null
}

export interface Paper extends PaperSummary {
  blocks: Block[]
  references: Reference[]
  metadata: Record<string, unknown>
  updated_at: string
}

export interface DedupCandidate {
  paper_id: string
  title: string | null
  similarity: number
  reason: string
  newer_version: boolean
}

export interface DedupResult {
  is_duplicate: boolean
  similarity: number
  action: 'accept' | 'warn' | 'replace' | 'keep'
  candidates: DedupCandidate[]
}

export interface UploadResponse {
  paper: PaperSummary
  dedup: DedupResult | null
}

export interface ParseJob {
  job_id: string
  paper_id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  stage: string
  current: number
  total: number
  percent: number
  message: string
  error: string | null
  dedup: DedupResult | null
  started_at: string
  finished_at: string | null
}

export interface DedupActionResponse {
  action: 'replace' | 'keep'
  kept: string
  removed: string | null
}

export interface Citation {
  paper_id: string
  paper_title: string | null
  page: number
  block_id: string
  quote: string
  score: number
  bbox: number[] | null
  bbox_space: 'bottom-left' | 'top-left'
}

export interface AnswerResponse {
  answer: string
  citations: Citation[]
  trace: string[]
  model: string
  grounded: boolean
}

export interface DiscoveryHit {
  source: string
  title: string
  authors: string[]
  year: number | null
  abstract: string | null
  url: string | null
  doi: string | null
  arxiv_id: string | null
  github_url: string | null
  reason: string | null
}

export interface GraphNode {
  id: string
  title: string
  year: number | null
  citations: number
  centrality: number
  is_cornerstone: boolean
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
}

export interface GraphResponse {
  graph_id: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  algorithm: string
  summary: string
}

export interface OutlineSection {
  heading: string
  intent: string
  citations: Citation[]
}

export interface OutlineResponse {
  title: string
  sections: OutlineSection[]
  references: Reference[]
}

export interface FigureResponse {
  code: string
  format: string
}

export interface ChartResponse {
  option: Record<string, unknown>
  caption: string
  columns: string[]
  rows: Record<string, string>[]
}

export interface TranslatedBlock {
  block_id: string
  page: number
  bbox: number[] | null
  source: string
  translation: string | null
  status: 'ok' | 'not_configured' | 'error'
}

export interface Anchor {
  block_id: string
  page: number
  bbox: number[] | null
  bbox_space: 'bottom-left' | 'top-left'
  kind: string
  section_path: string[]
  text: string
}

export interface OutlineItem {
  block_id: string
  title: string
  page: number
  level: number
}

export interface ReferenceItem {
  index: number | null
  page: number | null
  block_id: string
  bbox: number[] | null
  text: string
}

export interface FutureWorkItem {
  idea: string
  paper_id: string
  paper_title: string | null
  year: number | null
  page: number
  evidence: string
}

export interface FutureWorkResponse {
  graph_id: string
  items: FutureWorkItem[]
}

export interface TextTranslationResponse {
  translation: string | null
  status: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  capabilities: Record<string, boolean>
  degraded: string[]
}
