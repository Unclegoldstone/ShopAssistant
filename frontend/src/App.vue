<script setup>
import stoneAiLogo from './assets/stone-ai-logo-no-headset.png'
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
        <p class="eyebrow">[ PURE CONVERSATION / LEVEL 01 ]</p>
        <div class="brand-lockup">
          <span class="title-logo-frame" aria-hidden="true">
            <img class="title-logo" :src="stoneAiLogo" alt="" />
          </span>
          <div class="brand-copy">
            <h1>石块 · AI助手</h1>
            <p class="subtitle online-label"><i></i> ONLINE</p>
          </div>
        </div>
      </div>
      <div class="hero-badge" aria-hidden="true">
        <span class="pixel-face">▦</span>
        <span>AI<br />HELPER</span>
      </div>
      <span class="status"><i></i> SYSTEM READY</span>
    </header>

    <nav class="page-nav" aria-label="页面导航">
      <RouterLink to="/">客服对话</RouterLink>
      <RouterLink to="/tests">功能测试</RouterLink>
    </nav>

    <RouterView />

    <footer class="pixel-footer" aria-hidden="true">
      <span>© SHOP ASSISTANT</span>
      <span>FASTAPI × LANGCHAIN × VUE3</span>
      <span>INSERT COIN TO CONTINUE</span>
    </footer>
  </main>
</template>
