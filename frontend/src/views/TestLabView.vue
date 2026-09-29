<script setup>
import { ref } from 'vue'

import { extractAfterSales } from '../api.js'

const afterSalesText = ref('订单 20260928001 的鞋子尺码小了，我想换成 42 码。')
const extractionResult = ref(null)
const extracting = ref(false)
const extractionError = ref('')

async function runExtraction() {
  const text = afterSalesText.value.trim()
  if (!text || extracting.value) return
  extracting.value = true
  extractionError.value = ''
  extractionResult.value = null
  try {
    extractionResult.value = await extractAfterSales(text)
  } catch (error) {
    extractionError.value = error instanceof Error ? error.message : '抽取请求失败'
  } finally {
    extracting.value = false
  }
}
</script>

<template>
  <section class="workspace test-workspace">
    <header class="lab-intro">
      <p class="section-label">FUNCTION TEST LAB</p>
      <h2>功能测试台</h2>
      <p>这里用于验证独立功能，不影响主页面的客服对话。</p>
    </header>

    <article class="panel extract-panel">
      <div class="panel-heading">
        <div>
          <p class="section-label">STRUCTURED OUTPUT</p>
          <h2><span>02</span> 售后信息抽取</h2>
        </div>
      </div>

      <label for="after-sales">售后描述</label>
      <textarea id="after-sales" v-model="afterSalesText" rows="7"></textarea>
      <button
        class="primary-button wide"
        type="button"
        :disabled="extracting || !afterSalesText.trim()"
        @click="runExtraction"
      >
        {{ extracting ? '抽取中…' : '生成结构化 JSON ▶' }}
      </button>

      <p v-if="extractionError" class="error-message">{{ extractionError }}</p>
      <div class="result-card">
        <span><i></i> JSON_RESULT.LOG</span>
        <pre>{{ extractionResult ? JSON.stringify(extractionResult, null, 2) : '等待抽取结果…' }}</pre>
      </div>
    </article>
  </section>
</template>
