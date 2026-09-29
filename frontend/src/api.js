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

export async function streamChat({ model, conversationId, content, onContent }) {
  const response = await fetch(`${API_BASE_URL}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      conversation_id: conversationId,
      messages: [{ role: 'user', content }],
      stream: true,
    }),
  })

  if (!response.ok) throw new Error(await errorMessage(response))
  if (!response.body) throw new Error('浏览器未提供可读取的响应流')

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

export async function extractAfterSales(text) {
  const response = await fetch(`${API_BASE_URL}/v1/after-sales/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}
