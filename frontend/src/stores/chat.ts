import { ref } from 'vue'
import { defineStore } from 'pinia'

import { streamAgent, streamAnswer } from '@/api/sse'
import type { ChatArtifact, Citation } from '@/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  trace: string[]
  artifacts: ChatArtifact[]
  model?: string
  pending?: boolean
  agent?: boolean
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function argsSummary(args: Record<string, unknown>): string {
  const entries = Object.entries(args).filter(([, value]) => value !== undefined)
  if (entries.length === 0) {
    return ''
  }
  const text = JSON.stringify(Object.fromEntries(entries))
  const truncated = text.length > 120 ? `${text.slice(0, 120)}…` : text
  return `：${truncated}`
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const selectedPaperIds = ref<string[]>([])
  const streaming = ref(false)
  const error = ref<string | null>(null)
  const agentMode = ref(false)

  function togglePaper(paperId: string): void {
    const index = selectedPaperIds.value.indexOf(paperId)
    if (index >= 0) {
      selectedPaperIds.value.splice(index, 1)
    } else {
      selectedPaperIds.value.push(paperId)
    }
  }

  function clear(): void {
    messages.value = []
    error.value = null
  }

  function setSelectedPapers(paperIds: string[]): void {
    selectedPaperIds.value = [...paperIds]
  }

  function setAgentMode(agent: boolean): void {
    agentMode.value = agent
  }

  function pushAssistant(agent: boolean): ChatMessage {
    const assistant: ChatMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      citations: [],
      trace: [],
      artifacts: [],
      pending: true,
      agent,
    }
    messages.value.push(assistant)
    return assistant
  }

  async function ask(question: string): Promise<void> {
    const text = question.trim()
    if (!text || streaming.value) {
      return
    }
    error.value = null
    messages.value.push({
      id: uid(),
      role: 'user',
      content: text,
      citations: [],
      trace: [],
      artifacts: [],
    })
    const assistant = pushAssistant(agentMode.value)
    streaming.value = true
    try {
      if (agentMode.value) {
        await streamAgent(text, selectedPaperIds.value, {
          onPlan: ({ intent, steps }) => {
            assistant.trace.push(
              `计划：${intent}（${steps.map((step) => step.tool).join(' → ')}）`,
            )
          },
          onToolStart: ({ tool, args }) => {
            assistant.trace.push(`工具 ${tool} 开始${argsSummary(args)}`)
          },
          onToolResult: ({ tool, ok, summary, artifacts }) => {
            assistant.trace.push(`工具 ${tool} ${ok ? '完成' : '失败'}：${summary}`)
            assistant.artifacts = artifacts ?? []
          },
          onAnswer: ({ answer }) => {
            assistant.content = answer
          },
          onCitations: (citations) => {
            assistant.citations = citations
          },
          onDone: ({ trace, model }) => {
            assistant.trace = trace
            assistant.model = model
            assistant.pending = false
          },
          onError: ({ message }) => {
            assistant.content = `请求失败：${message}`
            error.value = message
          },
        })
      } else {
        await streamAnswer(text, selectedPaperIds.value, {
          onCitations: (citations) => {
            assistant.citations = citations
          },
          onToken: ({ text: piece }) => {
            assistant.content += piece
          },
          onDone: ({ trace, model }) => {
            assistant.trace = trace
            assistant.model = model
            assistant.pending = false
          },
        })
      }
    } catch (cause) {
      assistant.content = `请求失败：${messageOf(cause)}`
      error.value = messageOf(cause)
    } finally {
      assistant.pending = false
      streaming.value = false
    }
  }

  return {
    messages,
    selectedPaperIds,
    streaming,
    error,
    agentMode,
    togglePaper,
    clear,
    setSelectedPapers,
    setAgentMode,
    ask,
  }
})
