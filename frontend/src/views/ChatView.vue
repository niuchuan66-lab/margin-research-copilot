<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import AgentTrace from '@/components/AgentTrace.vue'
import CitationChip from '@/components/CitationChip.vue'
import { formatAnswer } from '@/lib/format'
import { useChatStore } from '@/stores/chat'
import { usePapersStore } from '@/stores/papers'
import type { Citation } from '@/types'

const papers = usePapersStore()
const chat = useChatStore()
const router = useRouter()
const draft = ref('')

const selectedCount = computed(() => chat.selectedPaperIds.length)

onMounted(async () => {
  await papers.fetchPapers()
  if (chat.selectedPaperIds.length === 0) {
    chat.setSelectedPapers(papers.readyPapers.map((paper) => paper.id))
  }
})

function send(): void {
  const text = draft.value
  draft.value = ''
  void chat.ask(text)
}

function openCitation(citation: Citation): void {
  void router.push({
    path: `/reader/${citation.paper_id}`,
    query: { page: String(citation.page) },
  })
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">问答</h1>
        <p class="page-meta">
          已选 {{ selectedCount }} 篇 · 回答必须带原文页码与片段
        </p>
      </div>
      <button class="btn btn-ghost btn-small" type="button" @click="chat.clear()">
        清空对话
      </button>
    </header>

    <div class="chat-layout">
      <aside class="panel paper-picker">
        <div class="panel-head">
          <span class="panel-title">检索范围</span>
          <span class="mono faint">{{ papers.readyPapers.length }}</span>
        </div>
        <div class="picker-list">
          <button
            v-for="paper in papers.readyPapers"
            :key="paper.id"
            class="picker-item"
            :class="{ selected: chat.selectedPaperIds.includes(paper.id) }"
            type="button"
            @click="chat.togglePaper(paper.id)"
          >
            <span class="picker-title">{{ paper.title ?? paper.filename }}</span>
            <span class="mono faint">{{ paper.pages }} 页</span>
          </button>
          <p v-if="!papers.readyPapers.length" class="faint picker-empty">
            还没有可检索的论文，先去书架解析。
          </p>
        </div>
      </aside>

      <div class="chat-main">
        <div v-if="!chat.messages.length" class="empty chat-empty">
          <div>
            <p class="empty-title">问一个能被原文回答的问题</p>
            <p class="muted">
              试试“BERT 与 Transformer Encoder 的承袭关系是什么？”
              或“训练用了多少块 GPU？”
            </p>
          </div>
        </div>

        <div v-else class="message-list">
          <article
            v-for="message in chat.messages"
            :key="message.id"
            class="message"
            :class="message.role"
          >
            <div class="message-role mono">
              {{ message.role === 'user' ? '你' : 'Margin' }}
              <span v-if="message.model" class="faint">· {{ message.model }}</span>
            </div>
            <p class="message-content" v-html="formatAnswer(
              message.content ||
              (message.pending ? (message.agent ? '正在执行任务…' : '正在检索原文…') : ''),
            )"></p>
            <div v-if="message.citations.length" class="citation-list">
              <CitationChip
                v-for="citation in message.citations"
                :key="`${citation.paper_id}-${citation.block_id}`"
                :citation="citation"
                @select="openCitation"
              />
            </div>
            <div v-if="message.artifacts.length" class="artifact-list">
              <RouterLink
                v-for="(artifact, index) in message.artifacts"
                :key="`${artifact.paper_id ?? 'library'}-${index}`"
                class="artifact-link"
                to="/library"
              >
                {{ artifact.label }}
              </RouterLink>
            </div>
            <AgentTrace :trace="message.trace" />
          </article>
        </div>

        <form class="composer panel" @submit.prevent="send">
          <textarea
            v-model="draft"
            class="textarea"
            rows="2"
            :placeholder="
              chat.agentMode
                ? 'Agent 模式：可直接说「下载这篇 arXiv 论文」「帮我画个雷达图」…'
                : '问一个具体问题，越具体越容易定位到原文…'
            "
            @keydown.enter.exact.prevent="send"
          ></textarea>
          <div class="composer-row">
            <div class="mode-toggle" role="group" aria-label="回答模式">
              <button
                class="mode-btn"
                :class="{ active: !chat.agentMode }"
                type="button"
                @click="chat.setAgentMode(false)"
              >
                快速问答
              </button>
              <button
                class="mode-btn"
                :class="{ active: chat.agentMode }"
                type="button"
                @click="chat.setAgentMode(true)"
              >
                Agent 模式
              </button>
            </div>
            <span class="faint mono">
              {{ selectedCount ? `检索 ${selectedCount} 篇` : '未选择论文时检索全部' }}
            </span>
            <button
              class="btn"
              type="submit"
              :disabled="chat.streaming || !draft.trim()"
            >
              {{ chat.streaming ? '生成中…' : '提问' }}
            </button>
          </div>
        </form>
        <p v-if="chat.error" class="error-line">{{ chat.error }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.paper-picker {
  position: sticky;
  top: 76px;
  max-height: calc(100vh - 100px);
  overflow: auto;
}

.picker-list {
  padding: 6px 0;
}

.picker-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--ink-2);
  text-align: left;
}

.picker-item:hover {
  background: var(--paper-2);
}

.picker-item.selected {
  border-left-color: var(--oxblood);
  background: rgba(122, 46, 53, 0.05);
  color: var(--ink);
}

.picker-title {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-empty {
  padding: 12px;
  font-size: 12px;
  line-height: 1.6;
}

.chat-main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.chat-empty {
  min-height: 320px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 320px;
  max-height: 56vh;
  padding-right: 6px;
  overflow: auto;
}

.message {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--rule-soft);
}

.message:last-child {
  border-bottom: none;
}

.message-role {
  margin-bottom: 6px;
  color: var(--ink-3);
}

.message.user .message-content {
  color: var(--ink-2);
}

.message.assistant .message-content {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 10px 0;
}

.artifact-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0;
}

.artifact-link {
  padding: 4px 10px;
  border: 1px solid var(--rule-soft);
  border-radius: 14px;
  color: var(--ink-2);
  font-size: 12px;
  text-decoration: none;
}

.artifact-link:hover {
  border-color: var(--oxblood);
  color: var(--oxblood);
}

.mode-toggle {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--rule-soft);
  border-radius: 16px;
  background: var(--paper-2);
}

.mode-btn {
  padding: 3px 12px;
  border: none;
  border-radius: 13px;
  background: transparent;
  color: var(--ink-3);
  font-size: 12px;
  cursor: pointer;
}

.mode-btn.active {
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.composer {
  padding: 12px;
}

.composer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
}

.error-line {
  color: var(--oxblood);
  font-size: 13px;
}

@media (max-width: 900px) {
  .chat-layout {
    grid-template-columns: 1fr;
  }

  .paper-picker {
    position: static;
    max-height: 220px;
  }
}
</style>
