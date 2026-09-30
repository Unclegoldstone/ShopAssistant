<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'

import {
  getConfiguredModel,
  getConversationHistory,
  listConversations,
  streamChat,
} from '../api.js'
import stoneAiLogo from '../assets/stone-ai-logo-no-headset.png'
import { formatConversationTime } from '../time.js'

const SESSION_KEY_PREFIX = 'shop-assistant-conversation-id:'
const modelName = ref('')
const currentUser = inject('currentUser', ref('demo-user'))
const chatBusy = inject('chatBusy', ref(false))
const conversations = ref([])
const loadingConversations = ref(false)
const loadingHistory = ref(false)
const conversationError = ref('')
let conversationListRequest = 0
let historyRequest = 0

function newConversationId() {
  return `web-${crypto.randomUUID()}`
}

function initialMessages() {
  return [
    {
      role: 'assistant',
      content: '您好，我是电商智能客服。请告诉我您遇到的问题。',
      toolName: null,
    },
  ]
}

function sessionKey(user) {
  return `${SESSION_KEY_PREFIX}${user}`
}

const conversationId = ref(newConversationId())

const messages = ref(initialMessages())
const input = ref('')
const sending = ref(false)
const chatError = ref('')
const canSend = computed(
  () => input.value.trim().length > 0 && !sending.value && Boolean(modelName.value),
)

function historyMessages(payload) {
  if (!payload.messages.length) return initialMessages()
  return payload.messages.map((message) => ({
    role: message.role,
    content: message.content,
    toolName: message.tool_name,
  }))
}

async function refreshConversations(user = currentUser.value) {
  const requestId = ++conversationListRequest
  loadingConversations.value = true
  conversationError.value = ''
  try {
    const result = await listConversations(user)
    if (requestId !== conversationListRequest || user !== currentUser.value) return null
    conversations.value = result
    return result
  } catch (error) {
    if (requestId !== conversationListRequest || user !== currentUser.value) return null
    conversationError.value = error instanceof Error ? error.message : '会话列表加载失败'
    return null
  } finally {
    if (requestId === conversationListRequest) loadingConversations.value = false
  }
}

async function selectConversation(selectedId, user = currentUser.value) {
  if (sending.value || loadingHistory.value) return
  const requestId = ++historyRequest
  loadingHistory.value = true
  chatError.value = ''
  try {
    const history = await getConversationHistory(selectedId, user)
    if (requestId !== historyRequest || user !== currentUser.value) return
    conversationId.value = selectedId
    localStorage.setItem(sessionKey(user), selectedId)
    messages.value = historyMessages(history)
  } catch (error) {
    if (requestId !== historyRequest || user !== currentUser.value) return
    chatError.value = error instanceof Error ? error.message : '历史消息加载失败'
  } finally {
    if (requestId === historyRequest) loadingHistory.value = false
  }
}

function resetConversation() {
  historyRequest += 1
  loadingHistory.value = false
  conversationId.value = newConversationId()
  localStorage.setItem(sessionKey(currentUser.value), conversationId.value)
  messages.value = initialMessages()
  chatError.value = ''
}

async function initializeUser(user) {
  historyRequest += 1
  conversations.value = []
  conversationError.value = ''
  messages.value = initialMessages()
  const result = await refreshConversations(user)
  if (!result || user !== currentUser.value) {
    resetConversation()
    return
  }
  const storedId = localStorage.getItem(sessionKey(user))
  if (storedId && result.some((item) => item.id === storedId)) {
    await selectConversation(storedId, user)
    return
  }
  resetConversation()
}

onMounted(async () => {
  const modelPromise = getConfiguredModel()
    .then((name) => { modelName.value = name })
    .catch((error) => {
      chatError.value = error instanceof Error ? error.message : '无法读取模型配置'
    })
  await Promise.all([modelPromise, initializeUser(currentUser.value)])
})

async function sendMessage() {
  const content = input.value.trim()
  if (!content || sending.value) return

  const activeConversationId = conversationId.value
  const activeUser = currentUser.value

  input.value = ''
  chatError.value = ''
  sending.value = true
  chatBusy.value = true
  messages.value.push({ role: 'user', content })
  messages.value.push({ role: 'assistant', content: '', toolName: null })
  const assistantIndex = messages.value.length - 1

  try {
    await streamChat({
      model: modelName.value,
      conversationId: activeConversationId,
      content,
      user: activeUser,
      onTool: (toolName) => {
        messages.value[assistantIndex].toolName = toolName
      },
      onContent: (chunk) => {
        messages.value[assistantIndex].content += chunk
      },
    })
    if (!messages.value[assistantIndex].content) {
      messages.value[assistantIndex].content = '本次未生成文字回复。'
    }
  } catch (error) {
    messages.value[assistantIndex].content ||= '抱歉，回复暂时中断。'
    chatError.value = error instanceof Error ? error.message : '对话请求失败'
  } finally {
    sending.value = false
    chatBusy.value = false
    if (activeUser === currentUser.value) await refreshConversations(activeUser)
  }
}

watch(currentUser, (user, previousUser) => {
  if (user === previousUser) return
  initializeUser(user)
})
</script>

<template>
  <section class="workspace chat-workspace">
    <aside class="panel conversation-panel" aria-label="会话选择">
      <div class="panel-heading conversation-heading">
        <div>
          <p class="section-label">CONVERSATIONS</p>
          <h2>会话记录</h2>
        </div>
        <button class="ghost-button" type="button" :disabled="loadingConversations || sending" @click="refreshConversations()">
          刷新
        </button>
      </div>

      <p class="conversation-user">USER // {{ currentUser }}</p>
      <p v-if="conversationError" class="error-message">{{ conversationError }}</p>
      <div class="conversation-list">
        <p v-if="loadingConversations" class="conversation-empty">正在加载会话…</p>
        <p v-else-if="conversations.length === 0" class="conversation-empty">暂无历史会话</p>
        <button
          v-for="conversation in conversations"
          v-else
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === conversationId }"
          type="button"
          :disabled="sending || loadingHistory"
          :aria-label="`选择会话：${conversation.preview || conversation.id}`"
          @click="selectConversation(conversation.id)"
        >
          <span class="conversation-preview">{{ conversation.preview || '空会话' }}</span>
          <span class="conversation-meta">
            <b>{{ conversation.status }}</b>
            <time>{{ formatConversationTime(conversation.last_message_at) }}</time>
          </span>
          <small>{{ conversation.message_count }} 条可见消息</small>
        </button>
      </div>
    </aside>

    <article class="panel chat-panel">
      <div class="panel-heading">
        <div>
          <p class="section-label">CUSTOMER CHAT</p>
          <h2>
            <span class="section-logo-frame" aria-hidden="true">
              <img :src="stoneAiLogo" alt="" />
            </span>
            石块
          </h2>
        </div>
        <button class="ghost-button" type="button" :disabled="sending || loadingHistory" @click="resetConversation">
          新会话
        </button>
      </div>

      <div class="session-id"><span>SESSION_ID</span> {{ conversationId }}</div>

      <div class="message-list" aria-live="polite">
        <p v-if="loadingHistory" class="conversation-empty">正在加载历史消息…</p>
        <div
          v-for="(message, index) in loadingHistory ? [] : messages"
          :key="`${message.role}-${index}`"
          class="message-row"
          :class="message.role"
        >
          <div class="avatar">
            <img
              v-if="message.role === 'assistant'"
              :src="stoneAiLogo"
              alt=""
              aria-hidden="true"
            />
            <template v-else>我</template>
          </div>
          <div class="message-content">
            <div v-if="message.toolName" class="tool-call-notice">
              <span>TOOL CALL</span>
              调用了 {{ message.toolName }} 工具
            </div>
            <p class="message-bubble">
              {{ message.content || '思考中…' }}
            </p>
          </div>
        </div>
      </div>

      <p v-if="chatError" class="error-message">{{ chatError }}</p>

      <form class="composer" @submit.prevent="sendMessage">
        <textarea
          v-model="input"
          rows="3"
          placeholder="输入消息, 和石块说说看遇到什么问题了吧"
          :disabled="sending"
          @keydown.ctrl.enter="sendMessage"
        ></textarea>
        <div class="composer-footer">
          <span>Ctrl + Enter 发送</span>
          <button class="primary-button" type="submit" :disabled="!canSend">
            {{ sending ? '回复中…' : '发送 ▶' }}
          </button>
        </div>
      </form>
    </article>
  </section>
</template>
