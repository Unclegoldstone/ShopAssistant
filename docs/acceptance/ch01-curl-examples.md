# Chapter 01 curl 验收案例

前置条件：已在项目根目录配置 `.env`，并通过 `scripts/run-backend.cmd` 启动后端。以下命令在 PowerShell 7 中执行。

先从后端读取唯一配置的模型名称：

```powershell
$model = (Invoke-RestMethod http://127.0.0.1:8000/v1/models).data[0].id
$conversationId = 'curl-demo-001'
```

## 1. 第一轮 SSE 流式对话

```powershell
$body = @{
  model = $model
  conversation_id = $conversationId
  messages = @(@{ role = 'user'; content = '我买的蓝牙耳机左耳没有声音。' })
  stream = $true
} | ConvertTo-Json -Depth 5 -Compress

curl.exe -N -X POST http://127.0.0.1:8000/v1/chat/completions `
  -H 'Content-Type: application/json' `
  --data-binary $body
```

预期：终端持续出现多行 `data: {..."chat.completion.chunk"...}`，最后一行为 `data: [DONE]`。

## 2. 复用同一会话进行第二轮

```powershell
$body = @{
  model = $model
  conversation_id = $conversationId
  messages = @(@{ role = 'user'; content = '我刚才说的是哪一边没有声音？' })
  stream = $true
} | ConvertTo-Json -Depth 5 -Compress

curl.exe -N -X POST http://127.0.0.1:8000/v1/chat/completions `
  -H 'Content-Type: application/json' `
  --data-binary $body
```

预期：回复能指出上一轮描述的是“左耳”，证明服务端按 `conversation_id` 延续上下文。

## 3. 售后描述结构化抽取

```powershell
$body = @{
  text = '订单 20260928001 的鞋子尺码小了，我想换成 42 码。'
} | ConvertTo-Json -Compress

curl.exe -X POST http://127.0.0.1:8000/v1/after-sales/extract `
  -H 'Content-Type: application/json' `
  --data-binary $body
```

预期形状：

```json
{
  "order_id": "20260928001",
  "request_type": "换货",
  "expected_solution": "更换为 42 码"
}
```

模型措辞可能略有差异，但三个字段必须始终存在；原文缺少的信息必须为 `null`。
