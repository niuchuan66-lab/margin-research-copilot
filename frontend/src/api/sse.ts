import type { AgentPlanStep, ChatArtifact, Citation } from '@/types'

import { API_BASE } from './client'

export interface StreamHandlers {
  onStatus?: (data: { stage: string; model?: string }) => void
  onCitations?: (data: Citation[]) => void
  onToken?: (data: { text: string }) => void
  onDone?: (data: { grounded: boolean; trace: string[]; model: string }) => void
}

export interface AgentStreamHandlers {
  onPlan?: (data: { intent: string; steps: AgentPlanStep[] }) => void
  onToolStart?: (data: { tool: string; args: Record<string, unknown> }) => void
  onToolResult?: (data: {
    tool: string
    ok: boolean
    summary: string
    artifacts: ChatArtifact[]
  }) => void
  onAnswer?: (data: { answer: string; model?: string }) => void
  onCitations?: (data: Citation[]) => void
  onDone?: (data: { trace: string[]; model: string }) => void
  onError?: (data: { message: string; detail?: string }) => void
}

type Dispatch = (event: string, data: unknown) => void

async function readSse(body: ReadableStream<Uint8Array>, dispatch: Dispatch): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const parseFrame = (raw: string) => {
    let event = 'message'
    const dataLines: string[] = []
    for (const line of raw.split('\n')) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
    }
    if (dataLines.length === 0) {
      return
    }
    dispatch(event, JSON.parse(dataLines.join('\n')))
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      if (frame.trim()) {
        parseFrame(frame)
      }
    }
  }
  if (buffer.trim()) {
    parseFrame(buffer)
  }
}

export async function streamAnswer(
  question: string,
  paperIds: string[],
  handlers: StreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/qa/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, paper_ids: paperIds, top_k: 6 }),
  })
  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败：HTTP ${response.status}`)
  }
  await readSse(response.body, (event, data) => {
    if (event === 'status') {
      handlers.onStatus?.(data as { stage: string; model?: string })
    } else if (event === 'citations') {
      handlers.onCitations?.(data as Citation[])
    } else if (event === 'token') {
      handlers.onToken?.(data as { text: string })
    } else if (event === 'done') {
      handlers.onDone?.(data as { grounded: boolean; trace: string[]; model: string })
    }
  })
}

export async function streamAgent(
  question: string,
  paperIds: string[],
  handlers: AgentStreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, paper_ids: paperIds }),
  })
  if (!response.ok || !response.body) {
    throw new Error(`Agent 请求失败：HTTP ${response.status}`)
  }
  await readSse(response.body, (event, data) => {
    if (event === 'plan') {
      handlers.onPlan?.(data as { intent: string; steps: AgentPlanStep[] })
    } else if (event === 'tool_start') {
      handlers.onToolStart?.(data as { tool: string; args: Record<string, unknown> })
    } else if (event === 'tool_result') {
      handlers.onToolResult?.(data as {
        tool: string
        ok: boolean
        summary: string
        artifacts: ChatArtifact[]
      })
    } else if (event === 'answer') {
      handlers.onAnswer?.(data as { answer: string; model?: string })
    } else if (event === 'citations') {
      handlers.onCitations?.(data as Citation[])
    } else if (event === 'done') {
      handlers.onDone?.(data as { trace: string[]; model: string })
    } else if (event === 'error') {
      handlers.onError?.(data as { message: string; detail?: string })
    }
  })
}
