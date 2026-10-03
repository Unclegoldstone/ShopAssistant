const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function errorMessage(response) {
  try {
    const payload = await response.json()
    return payload.detail?.message || payload.detail || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

function parseEvent(frame) {
  const data = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')

  if (!data) return null
  if (data === '[DONE]') return { done: true }
  return { done: false, payload: JSON.parse(data) }
}

export async function streamChat({ model, conversationId, content, user, onContent, onTool }) {
  const response = await fetch(`${API_BASE_URL}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      conversation_id: conversationId,
      messages: [{ role: 'user', content }],
      stream: true,
      user,
    }),
  })

  if (!response.ok) throw new Error(await errorMessage(response))
  if (!response.body) throw new Error('浏览器未提供可读取的响应流')

  const toolName = response.headers.get('X-Shop-Assistant-Tool')
  onTool?.(toolName)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    buffer = buffer.replace(/\r\n/g, '\n')

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const event = parseEvent(frame)

      if (event?.done) return
      if (event?.payload?.error) {
        throw new Error(event.payload.error.message || '模型流式输出失败')
      }
      const text = event?.payload?.choices?.[0]?.delta?.content
      if (text) onContent(text)
      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }
}

export async function getConfiguredModel() {
  const response = await fetch(`${API_BASE_URL}/v1/models`)
  if (!response.ok) throw new Error(await errorMessage(response))
  const payload = await response.json()
  const model = payload.data?.[0]?.id
  if (!model) throw new Error('服务端未返回可用模型')
  return model
}

export async function listConversations(user) {
  const query = new URLSearchParams({ user })
  const response = await fetch(`${API_BASE_URL}/v1/conversations?${query}`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function getConversationHistory(conversationId, user) {
  const query = new URLSearchParams({ user })
  const encodedId = encodeURIComponent(conversationId)
  const response = await fetch(`${API_BASE_URL}/v1/conversations/${encodedId}/messages?${query}`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function extractAfterSales(text) {
  const response = await fetch(`${API_BASE_URL}/v1/after-sales/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function runDatabaseTest() {
  const response = await fetch(`${API_BASE_URL}/v1/tests/database`, {
    method: 'POST',
  })

  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function listFaqs() {
  const response = await fetch(`${API_BASE_URL}/v1/tests/faqs`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function createFaq(payload) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/faqs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function updateFaq(id, payload) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/faqs/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function deleteFaq(id) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/faqs/${id}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(await errorMessage(response))
}

export async function listTableRecords(tableName) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/tables/${tableName}`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function createTableRecord(tableName, values) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/tables/${tableName}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function updateTableRecord(tableName, key, values) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/tables/${tableName}/${encodeURIComponent(key)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function deleteTableRecord(tableName, key) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/tables/${tableName}/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(await errorMessage(response))
}

async function knowledgeJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/v1/tests/knowledge${path}`, options)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

function markdownForm(file) {
  const form = new FormData()
  form.append('file', file)
  return form
}

export function previewKnowledgeMarkdown(file) {
  return knowledgeJson('/preview', { method: 'POST', body: markdownForm(file) })
}

export function ingestKnowledgeMarkdown(file) {
  return knowledgeJson('/ingest', { method: 'POST', body: markdownForm(file) })
}

export function vectorizeTestKnowledge(faultStage = null) {
  return knowledgeJson('/vectorize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fault_stage: faultStage }),
  })
}

export function searchKnowledge(query, topK = 5) {
  return knowledgeJson('/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  })
}

export function getKnowledgeSnapshot() {
  return knowledgeJson('/snapshot')
}
