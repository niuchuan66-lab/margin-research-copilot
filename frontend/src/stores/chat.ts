import { ref } from 'vue'
import { defineStore } from 'pinia'

import { streamAnswer } from '@/api/sse'
import type { Citation } from '@/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  trace: string[]
  model?: string
  pending?: boolean
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const selectedPaperIds = ref<string[]>([])
  const streaming = ref(false)
  const error = ref<string | null>(null)

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
    })
    const assistant: ChatMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      citations: [],
      trace: [],
      pending: true,
    }
    messages.value.push(assistant)
    streaming.value = true
    try {
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
    togglePaper,
    clear,
    setSelectedPapers,
    ask,
  }
})
