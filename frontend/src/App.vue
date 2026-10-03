<script setup>
import { computed, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import stoneAiLogo from './assets/stone-ai-logo-no-headset.png'

const USER_KEY = 'shop-assistant-user-id'
const users = ['demo-user', 'user1']
const storedUser = localStorage.getItem(USER_KEY)
const currentUser = ref(users.includes(storedUser) ? storedUser : users[0])
const chatBusy = ref(false)
const route = useRoute()
const isTestLab = computed(() => route.name === 'tests')
const isKbLab = computed(() => route.name === 'kb')
const pageTitle = computed(() => {
  if (isKbLab.value) return '知识库测试台'
  if (isTestLab.value) return '功能测试台'
  return '石块 · AI助手'
})
const pageLevel = computed(() => {
  if (isKbLab.value) return '[ KNOWLEDGE BASE / LEVEL 03 ]'
  if (isTestLab.value) return '[ FUNCTION TEST LAB / LEVEL 02 ]'
  return '[ PURE CONVERSATION / LEVEL 01 ]'
})

watch(currentUser, (user) => localStorage.setItem(USER_KEY, user), { immediate: true })
provide('currentUser', currentUser)
provide('chatBusy', chatBusy)
</script>

<template>
  <main class="page-shell">
    <div class="top-rail" aria-hidden="true">
      <span>SHOP_ASSIST.EXE</span>
      <span>CH.01</span>
      <span>ONLINE</span>
    </div>

    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">
          {{ pageLevel }}
        </p>
        <div class="brand-lockup">
          <span class="title-logo-frame" aria-hidden="true">
            <img class="title-logo" :src="stoneAiLogo" alt="" />
          </span>
          <div class="brand-copy">
            <h1>{{ pageTitle }}</h1>
            <p class="subtitle online-label"><i></i> ONLINE</p>
          </div>
        </div>
      </div>
      <div class="hero-badge" aria-hidden="true">
        <span class="pixel-face">▦</span>
        <span>AI<br />HELPER</span>
      </div>
      <div class="system-stack">
        <span class="status"><i></i> SYSTEM READY</span>
        <label class="user-switcher">
          <span>CURRENT USER</span>
          <select v-model="currentUser" aria-label="更换当前用户" :disabled="chatBusy">
            <option v-for="user in users" :key="user" :value="user">{{ user }}</option>
          </select>
        </label>
      </div>
    </header>

    <nav class="page-nav" aria-label="页面导航">
      <RouterLink to="/">客服对话</RouterLink>
      <RouterLink to="/tests">功能测试</RouterLink>
      <RouterLink to="/kb">知识库</RouterLink>
    </nav>

    <RouterView />

    <footer class="pixel-footer" aria-hidden="true">
      <span>© SHOP ASSISTANT</span>
      <span>FASTAPI × LANGCHAIN × VUE3</span>
      <span>INSERT COIN TO CONTINUE</span>
    </footer>
  </main>
</template>
