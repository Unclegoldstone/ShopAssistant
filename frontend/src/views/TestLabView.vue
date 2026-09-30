<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  createTableRecord,
  deleteTableRecord,
  extractAfterSales,
  listTableRecords,
  runDatabaseTest,
  updateTableRecord,
} from '../api.js'

const tableConfigs = {
  faq: {
    label: 'faq',
    description: '常见问题、答案与分类',
    permissionHint: 'FAQ 业务记录可以修改；只有测试台创建的 FAQ 可以删除。',
    fields: [
      { name: 'question', label: '问题', type: 'text', required: true, max: 255 },
      { name: 'answer', label: '答案', type: 'textarea', required: true, max: 10000 },
      {
        name: 'category',
        label: '分类',
        type: 'text',
        required: true,
        max: 64,
      },
    ],
  },
  conversations: {
    label: 'conversations',
    description: '会话壳、用户与处理状态',
    fields: [
      {
        name: 'id',
        label: '会话 ID',
        type: 'text',
        required: true,
        max: 128,
        createOnly: true,
        auto: 'conversation',
      },
      { name: 'user_id', label: '用户 ID', type: 'text', required: true, max: 64, default: 'demo-user' },
      {
        name: 'status',
        label: '处理状态',
        type: 'select',
        required: true,
        options: ['active', 'waiting_human', 'closed', 'failed'],
        default: 'active',
      },
    ],
  },
  messages: {
    label: 'messages',
    description: '会话中的用户、助手与工具消息',
    hint: '请先在 conversations 中创建 test-lab- 开头的测试会话。',
    fields: [
      { name: 'conversation_id', label: '会话 ID', type: 'text', required: true, max: 128 },
      {
        name: 'role',
        label: '角色',
        type: 'select',
        required: true,
        options: ['user', 'assistant', 'tool'],
        default: 'user',
      },
      { name: 'content', label: '消息内容', type: 'textarea', required: true, max: 100000 },
      { name: 'tool_calls', label: '工具调用 JSON', type: 'json', default: '' },
      { name: 'tool_call_id', label: 'Tool Call ID', type: 'text', max: 128 },
    ],
  },
  tickets: {
    label: 'tickets',
    description: '人工工单与处理状态',
    hint: '工单只能关联 test-lab- 开头的测试会话。',
    fields: [
      {
        name: 'ticket_no',
        label: '工单号',
        type: 'text',
        required: true,
        max: 32,
        createOnly: true,
        auto: 'ticket',
      },
      { name: 'conversation_id', label: '会话 ID', type: 'text', required: true, max: 128 },
      { name: 'issue_description', label: '问题描述', type: 'textarea', required: true, max: 10000 },
      { name: 'ticket_type', label: '工单类型', type: 'text', required: true, max: 64 },
      {
        name: 'status',
        label: '处理状态',
        type: 'select',
        required: true,
        options: ['open', 'processing', 'resolved', 'closed'],
        default: 'open',
      },
    ],
  },
}

const afterSalesText = ref('订单 20260928001 的鞋子尺码小了，我想换成 42 码。')
const extractionResult = ref(null)
const extracting = ref(false)
const extractionError = ref('')
const databaseResult = ref(null)
const testingDatabase = ref(false)
const databaseError = ref('')
const selectedTable = ref('faq')
const records = ref([])
const loadingRecords = ref(false)
const savingRecord = ref(false)
const recordError = ref('')
const recordNotice = ref('')
const editingKey = ref(null)
const formValues = reactive({})
const currentConfig = computed(() => tableConfigs[selectedTable.value])

function generatedKey(kind) {
  const stamp = Date.now().toString(36)
  return kind === 'ticket' ? `TL-${stamp}` : `test-lab-${stamp}`
}

function resetRecordForm() {
  editingKey.value = null
  for (const key of Object.keys(formValues)) delete formValues[key]
  for (const field of currentConfig.value.fields) {
    if (field.auto) formValues[field.name] = generatedKey(field.auto)
    else formValues[field.name] = field.default ?? ''
  }
}

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

async function testDatabase() {
  if (testingDatabase.value) return
  testingDatabase.value = true
  databaseError.value = ''
  databaseResult.value = null
  try {
    databaseResult.value = await runDatabaseTest()
  } catch (error) {
    databaseError.value = error instanceof Error ? error.message : '数据库测试失败'
  } finally {
    testingDatabase.value = false
  }
}

async function loadRecords() {
  loadingRecords.value = true
  recordError.value = ''
  try {
    records.value = await listTableRecords(selectedTable.value)
  } catch (error) {
    recordError.value = error instanceof Error ? error.message : '数据查询失败'
  } finally {
    loadingRecords.value = false
  }
}

function editRecord(record) {
  if (!record.can_update) return
  editingKey.value = record.key
  for (const field of currentConfig.value.fields) {
    const value = record.values[field.name]
    formValues[field.name] = field.type === 'json' && value != null
      ? JSON.stringify(value, null, 2)
      : (value ?? '')
  }
  recordNotice.value = `正在编辑 ${selectedTable.value} // ${record.key}`
  recordError.value = ''
}

function requestValues() {
  const values = {}
  for (const field of currentConfig.value.fields) {
    if (editingKey.value !== null && field.createOnly) continue
    const rawValue = formValues[field.name]
    if (field.type === 'json') {
      values[field.name] = String(rawValue || '').trim() ? JSON.parse(rawValue) : null
    } else if (!field.required && String(rawValue || '').trim() === '') {
      values[field.name] = null
    } else {
      values[field.name] = String(rawValue).trim()
    }
  }
  return values
}

async function saveRecord() {
  if (savingRecord.value) return
  savingRecord.value = true
  recordError.value = ''
  recordNotice.value = ''
  try {
    const values = requestValues()
    if (editingKey.value === null) {
      await createTableRecord(selectedTable.value, values)
      recordNotice.value = `${selectedTable.value} 新增成功`
    } else {
      const key = editingKey.value
      await updateTableRecord(selectedTable.value, key, values)
      recordNotice.value = `${selectedTable.value} // ${key} 更新成功`
    }
    resetRecordForm()
    await loadRecords()
  } catch (error) {
    recordError.value = error instanceof Error ? error.message : '记录保存失败'
  } finally {
    savingRecord.value = false
  }
}

async function removeRecord(record) {
  if (!record.can_delete) return
  const cascadeWarning = selectedTable.value === 'conversations'
    ? '\n该测试会话关联的测试消息和测试工单也会被清理。'
    : ''
  if (!window.confirm(`确认删除 ${selectedTable.value} // ${record.key} 吗？${cascadeWarning}`)) return
  recordError.value = ''
  recordNotice.value = ''
  try {
    await deleteTableRecord(selectedTable.value, record.key)
    if (editingKey.value === record.key) resetRecordForm()
    recordNotice.value = `${selectedTable.value} // ${record.key} 已删除`
    await loadRecords()
  } catch (error) {
    recordError.value = error instanceof Error ? error.message : '记录删除失败'
  }
}

function fieldLabel(name) {
  return currentConfig.value.fields.find((field) => field.name === name)?.label ?? name
}

function displayValue(value) {
  if (value == null) return 'null'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function recordAccessLabel(record) {
  if (record.can_delete) return 'TEST / EDITABLE'
  if (record.can_update) return 'BUSINESS / UPDATE ONLY'
  return 'BUSINESS / READ ONLY'
}

watch(selectedTable, () => {
  recordNotice.value = ''
  recordError.value = ''
  resetRecordForm()
  loadRecords()
})

resetRecordForm()
onMounted(loadRecords)
</script>

<template>
  <section class="workspace test-workspace">
    <div class="test-column test-column-a">
      <article class="panel extract-panel">
        <div class="panel-heading">
          <div>
            <p class="section-label">STRUCTURED OUTPUT</p>
            <h2><span>01</span> 售后信息抽取</h2>
          </div>
        </div>

        <label for="after-sales">售后描述</label>
        <textarea id="after-sales" v-model="afterSalesText" rows="7"></textarea>
        <button class="primary-button wide" type="button" :disabled="extracting || !afterSalesText.trim()" @click="runExtraction">
          {{ extracting ? '抽取中…' : '生成结构化 JSON ▶' }}
        </button>
        <p v-if="extractionError" class="error-message">{{ extractionError }}</p>
        <div class="result-card">
          <span><i></i> JSON_RESULT.LOG</span>
          <pre>{{ extractionResult ? JSON.stringify(extractionResult, null, 2) : '等待抽取结果…' }}</pre>
        </div>
      </article>

      <article class="panel database-panel">
        <div class="panel-heading">
          <div>
            <p class="section-label">DATABASE SELF TEST</p>
            <h2><span>02</span> 数据库测试</h2>
          </div>
        </div>
        <p class="database-description">依次验证数据库连接、新增、查询、更新和删除。测试使用临时 FAQ 记录，完成后不会保留数据。</p>
        <button class="primary-button wide database-test-button" type="button" :disabled="testingDatabase" @click="testDatabase">
          {{ testingDatabase ? '测试中…' : '运行数据库 CRUD 测试 ▶' }}
        </button>
        <p v-if="databaseError" class="error-message">{{ databaseError }}</p>
        <div class="database-result" :class="{ passed: databaseResult?.ok }">
          <div class="database-result-heading">
            <span><i></i> DATABASE_TEST.LOG</span>
            <strong v-if="databaseResult">{{ databaseResult.ok ? 'PASS' : 'FAIL' }}</strong>
          </div>
          <p v-if="!databaseResult" class="database-waiting">等待运行数据库测试…</p>
          <template v-else>
            <p class="database-name">DATABASE // {{ databaseResult.database }}</p>
            <ol class="database-steps">
              <li v-for="step in databaseResult.steps" :key="step.operation">
                <span class="operation-tag">{{ step.operation.toUpperCase() }}</span>
                <span>{{ step.detail }}</span>
                <b>{{ step.ok ? 'OK' : 'ERR' }}</b>
              </li>
            </ol>
          </template>
        </div>
      </article>
    </div>

    <article class="panel crud-panel">
      <div class="panel-heading crud-heading">
        <div>
          <p class="section-label">DATABASE TABLE CONSOLE</p>
          <h2><span>03</span> 数据库操作</h2>
        </div>
        <div class="crud-toolbar">
          <select v-model="selectedTable" aria-label="选择数据库表">
            <option v-for="(config, name) in tableConfigs" :key="name" :value="name">{{ config.label }}</option>
          </select>
          <button class="ghost-button" type="button" :disabled="loadingRecords" @click="loadRecords">
            {{ loadingRecords ? '查询中…' : '刷新查询' }}
          </button>
        </div>
      </div>

      <p class="database-description">{{ currentConfig.description }}。{{ currentConfig.permissionHint ?? '业务记录只读，只有测试台创建的记录可以修改和删除。' }}</p>
      <p v-if="currentConfig.hint" class="crud-hint">{{ currentConfig.hint }}</p>

      <form class="crud-form" @submit.prevent="saveRecord">
        <label v-for="field in currentConfig.fields" :key="field.name">
          <span>{{ field.label }}</span>
          <select v-if="field.type === 'select'" v-model="formValues[field.name]" :disabled="editingKey !== null && field.createOnly" :required="field.required">
            <option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
          </select>
          <textarea v-else-if="field.type === 'textarea' || field.type === 'json'" v-model="formValues[field.name]" :required="field.required" :maxlength="field.max" rows="3"></textarea>
          <input v-else v-model="formValues[field.name]" :required="field.required" :maxlength="field.max" :disabled="editingKey !== null && field.createOnly" />
        </label>
        <div class="crud-form-actions">
          <button class="primary-button" type="submit" :disabled="savingRecord">
            {{ savingRecord ? '保存中…' : editingKey === null ? '新增测试记录' : '保存修改' }}
          </button>
          <button v-if="editingKey !== null" class="ghost-button" type="button" @click="resetRecordForm">取消编辑</button>
        </div>
      </form>

      <p v-if="recordNotice" class="success-message">{{ recordNotice }}</p>
      <p v-if="recordError" class="error-message">{{ recordError }}</p>

      <div class="crud-list-heading">
        <span>QUERY_RESULT // {{ selectedTable }}</span>
        <b>{{ records.length }} RECORDS</b>
      </div>
      <div class="crud-list">
        <p v-if="loadingRecords" class="crud-empty">正在查询 {{ selectedTable }}…</p>
        <p v-else-if="records.length === 0" class="crud-empty">该表暂无记录</p>
        <article v-for="record in records" v-else :key="record.key" class="crud-item" :class="{ readonly: !record.can_update }">
          <div class="crud-item-meta">
            <span>{{ record.key }}</span>
            <b>{{ recordAccessLabel(record) }}</b>
          </div>
          <dl class="record-fields">
            <div v-for="(value, name) in record.values" :key="name">
              <dt>{{ fieldLabel(name) }}</dt>
              <dd>{{ displayValue(value) }}</dd>
            </div>
          </dl>
          <div class="crud-item-actions">
            <button class="ghost-button" type="button" :disabled="!record.can_update" @click="editRecord(record)">修改</button>
            <button class="danger-button" type="button" :disabled="!record.can_delete" @click="removeRecord(record)">删除</button>
          </div>
        </article>
      </div>
    </article>
  </section>
</template>
