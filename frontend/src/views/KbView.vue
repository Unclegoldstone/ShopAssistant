<script setup>
import { computed, onMounted, ref } from 'vue'

import {
  getKnowledgeSnapshot,
  ingestKnowledgeMarkdown,
  previewKnowledgeMarkdown,
  searchKnowledge,
  vectorizeTestKnowledge,
} from '../api.js'

const file = ref(null)
const preview = ref(null)
const ingestResult = ref(null)
const vectorResult = ref(null)
const searchText = ref('邮费是多少')
const topK = ref(5)
const searchResult = ref(null)
const cardResults = ref(true)
const snapshot = ref(null)
const busyAction = ref('')
const error = ref('')
const hasFile = computed(() => Boolean(file.value))
const normalizedTopK = computed(() => Math.min(100, Math.max(1, Number(topK.value) || 5)))
const mysqlPendingCount = computed(() => Number(snapshot.value?.status?.pending ?? 0))

function chooseFile(event) {
  file.value = event.target.files?.[0] ?? null
  preview.value = null
  ingestResult.value = null
  error.value = ''
}

async function run(action, operation) {
  if (busyAction.value) return
  busyAction.value = action
  error.value = ''
  try {
    await operation()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '操作失败'
  } finally {
    busyAction.value = ''
  }
}

function previewFile() {
  if (!file.value) return
  run('preview', async () => { preview.value = await previewKnowledgeMarkdown(file.value) })
}

function ingestFile() {
  if (!file.value) return
  run('ingest', async () => {
    ingestResult.value = await ingestKnowledgeMarkdown(file.value)
    await refreshSnapshot()
  })
}

function vectorize(faultStage = null) {
  if (faultStage && !window.confirm(`确认注入 ${faultStage} 测试故障吗？仅影响 /kb 上传来源。`)) return
  run(faultStage || 'vectorize', async () => {
    vectorResult.value = await vectorizeTestKnowledge(faultStage)
    await refreshSnapshot()
  })
}

function search() {
  if (!searchText.value.trim()) return
  topK.value = normalizedTopK.value
  run('search', async () => {
    searchResult.value = await searchKnowledge(searchText.value.trim(), normalizedTopK.value)
  })
}

function formatScore(score) {
  return Number(score).toFixed(4)
}

async function refreshSnapshot() {
  snapshot.value = await getKnowledgeSnapshot()
}

function refresh() {
  run('snapshot', refreshSnapshot)
}

onMounted(refresh)
</script>

<template>
  <section class="kb-workspace">
    <p v-if="error" class="error-message kb-global-error">{{ error }}</p>

    <article class="panel kb-panel kb-upload-panel">
      <div class="panel-heading"><div><p class="section-label">MARKDOWN SPLITTER</p><h2><span>01</span> 切片预览</h2></div></div>
      <p class="kb-copy">选择 UTF-8 Markdown 后先只读预览；只有点击“明确入库”才写入 MySQL。</p>
      <input class="kb-file" type="file" accept=".md,text/markdown" :disabled="Boolean(busyAction)" @change="chooseFile" />
      <div class="kb-actions">
        <button class="ghost-button" :disabled="!hasFile || Boolean(busyAction)" @click="previewFile">{{ busyAction === 'preview' ? '切分中…' : '只读预览' }}</button>
        <button class="primary-button" :disabled="!hasFile || Boolean(busyAction)" @click="ingestFile">{{ busyAction === 'ingest' ? '入库中…' : '明确入库' }}</button>
      </div>
      <p v-if="ingestResult" class="success-message">入库完成 // {{ JSON.stringify(ingestResult) }}</p>
      <div v-if="preview" class="kb-scroll">
        <div class="kb-summary">{{ preview.file_name }} // {{ preview.byte_count }} BYTES // {{ preview.char_count }} CHARS // {{ preview.chunk_count }} CHUNKS</div>
        <article v-for="chunk in preview.chunks" :key="chunk.ordinal" class="kb-chunk">
          <b>#{{ chunk.ordinal }} · {{ chunk.content_type }} · {{ chunk.char_count }} CHARS</b>
          <small>{{ chunk.section_path.join(' / ') }} · PREV {{ chunk.previous_ordinal ?? '-' }} · NEXT {{ chunk.next_ordinal ?? '-' }}</small>
          <p>{{ chunk.answer }}</p>
          <code>Q: {{ chunk.questions.join(' / ') }} | TABLE: {{ chunk.is_table }} | CRITICAL: {{ chunk.is_critical }}</code>
        </article>
      </div>
    </article>

    <article class="panel kb-panel">
      <div class="panel-heading"><div><p class="section-label">MYSQL → MILVUS</p><h2><span>02</span> 入库与向量状态</h2></div></div>
      <p class="kb-copy">补齐全部知识来源的 pending、failed、pending_delete 与过期租约记录。</p>
      <div class="kb-pending-status" :class="{ clear: mysqlPendingCount === 0 }">
        <span>MYSQL PENDING</span>
        <strong>{{ mysqlPendingCount }}</strong>
        <p>{{ mysqlPendingCount ? `仍有 ${mysqlPendingCount} 条 MySQL 知识尚未完成向量化。` : 'MySQL 中没有等待向量化的知识。' }}</p>
      </div>
      <div class="kb-actions"><button class="primary-button" :disabled="Boolean(busyAction)" @click="vectorize()">{{ busyAction === 'vectorize' ? '向量化中…' : '执行向量补偿' }}</button><button class="ghost-button" :disabled="Boolean(busyAction)" @click="refresh">刷新状态</button></div>
      <pre class="kb-log">{{ vectorResult ? JSON.stringify(vectorResult, null, 2) : JSON.stringify(snapshot?.status ?? {}, null, 2) }}</pre>
    </article>

    <article class="panel kb-panel">
      <div class="panel-heading"><div><p class="section-label">DENSE ONLY</p><h2><span>03</span> 语义检索测试</h2></div></div>
      <div class="kb-search-options">
        <label class="kb-top-k">TOP-K<input v-model.number="topK" type="number" min="1" max="100" step="1" /></label>
        <div class="kb-view-mode"><span>结果卡片</span><button class="kb-toggle" :class="{ active: cardResults }" role="switch" :aria-checked="cardResults" @click="cardResults = !cardResults"><i></i><b>{{ cardResults ? 'ON' : 'OFF' }}</b></button></div>
      </div>
      <input v-model="searchText" class="kb-input" placeholder="例如：邮费是多少" @keyup.enter="search" />
      <button class="primary-button wide" :disabled="Boolean(busyAction) || !searchText.trim()" @click="search">DENSE TOP-{{ normalizedTopK }} 检索 ▶</button>
      <div v-if="searchResult && cardResults" class="kb-match-list">
        <p v-if="!searchResult.matches.length" class="kb-empty-result">没有达到相似度阈值的知识。</p>
        <article v-for="(match, index) in searchResult.matches" :key="`${match.chunk_id}-${index}`" class="kb-match-card">
          <div class="kb-match-heading">
            <span class="kb-match-rank">#{{ index + 1 }}</span>
            <h3>{{ match.question }}</h3>
            <span class="kb-match-score">SCORE {{ formatScore(match.score) }}</span>
          </div>
          <p class="kb-match-answer">{{ match.answer }}</p>
          <div class="kb-match-meta"><span>CATEGORY // {{ match.category }}</span><span>CHUNK_ID // {{ match.chunk_id }}</span></div>
        </article>
      </div>
      <pre v-else class="kb-log">{{ searchResult ? JSON.stringify(searchResult, null, 2) : '等待检索…' }}</pre>
    </article>

    <article class="panel kb-panel">
      <div class="panel-heading"><div><p class="section-label">FAULT RECOVERY</p><h2><span>04</span> 中断恢复</h2></div></div>
      <p class="kb-copy">故障注入严格限制为 kb_upload 来源；运行后再次点“执行向量补偿”验证收敛。</p>
      <div class="kb-actions"><button class="danger-button" :disabled="Boolean(busyAction)" @click="vectorize('before_upsert')">MILVUS 前中断</button><button class="danger-button" :disabled="Boolean(busyAction)" @click="vectorize('after_upsert')">回填前中断</button></div>
    </article>

    <article class="panel kb-panel kb-status-panel">
      <div class="panel-heading"><div><p class="section-label">RUNTIME INSPECTOR</p><h2><span>05</span> 运行状态</h2></div><button class="ghost-button" :disabled="Boolean(busyAction)" @click="refresh">刷新</button></div>
      <div class="kb-scroll kb-snapshot"><pre>{{ snapshot ? JSON.stringify(snapshot, null, 2) : '正在读取状态…' }}</pre></div>
    </article>
  </section>
</template>
