import type { Citation } from '@/types'

import { API_BASE } from './client'

export interface StreamHandlers {
  onStatus?: (data: { stage: string; model?: string }) => void
  onCitations?: (data: Citation[]) => void
  onToken?: (data: { text: string }) => void
  onDone?: (data: { grounded: boolean; trace: string[]; model: string }) => void
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

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (raw: string) => {
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
    const data = JSON.parse(dataLines.join('\n'))
    if (event === 'status') {
      handlers.onStatus?.(data)
    } else if (event === 'citations') {
      handlers.onCitations?.(data as Citation[])
    } else if (event === 'token') {
      handlers.onToken?.(data as { text: string })
    } else if (event === 'done') {
      handlers.onDone?.(data as { grounded: boolean; trace: string[]; model: string })
    }
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
        dispatch(frame)
      }
    }
  }
  if (buffer.trim()) {
    dispatch(buffer)
  }
}
