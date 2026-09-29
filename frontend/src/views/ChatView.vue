<script setup>
import { computed, onMounted, ref } from 'vue'

import { getConfiguredModel, streamChat } from '../api.js'
import stoneAiLogo from '../assets/stone-ai-logo-no-headset.png'

const SESSION_KEY = 'shop-assistant-conversation-id'
const modelName = ref('')

function newConversationId() {
  return `web-${crypto.randomUUID()}`
}

function initialMessages() {
  return [
    {
      role: 'assistant',
      content: '您好，我是电商智能客服。请告诉我您遇到的问题。',
    },
  ]
}

const storedConversationId = localStorage.getItem(SESSION_KEY)
const conversationId = ref(storedConversationId || newConversationId())
localStorage.setItem(SESSION_KEY, conversationId.value)

const messages = ref(initialMessages())
const input = ref('')
const sending = ref(false)
const chatError = ref('')
const canSend = computed(
  () => input.value.trim().length > 0 && !sending.value && Boolean(modelName.value),
)

onMounted(async () => {
  try {
    modelName.value = await getConfiguredModel()
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : '无法读取模型配置'
  }
})

async function sendMessage() {
  const content = input.value.trim()
  if (!content || sending.value) return

  input.value = ''
  chatError.value = ''
  sending.value = true
  messages.value.push({ role: 'user', content })
  messages.value.push({ role: 'assistant', content: '' })
  const assistantIndex = messages.value.length - 1

  try {
    await streamChat({
      model: modelName.value,
      conversationId: conversationId.value,
      content,
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
  }
}

function resetConversation() {
  conversationId.value = newConversationId()
  localStorage.setItem(SESSION_KEY, conversationId.value)
  messages.value = initialMessages()
  chatError.value = ''
}
</script>

<template>
  <section class="workspace chat-workspace">
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
        <button class="ghost-button" type="button" :disabled="sending" @click="resetConversation">
          新会话
        </button>
      </div>

      <div class="session-id"><span>SESSION_ID</span> {{ conversationId }}</div>

      <div class="message-list" aria-live="polite">
        <div
          v-for="(message, index) in messages"
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
          <p class="message-bubble">
            {{ message.content || '思考中…' }}
          </p>
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
