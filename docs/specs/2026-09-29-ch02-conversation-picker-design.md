# Chapter 02 会话选择与历史加载设计

## 1. 目标

在“客服对话”页增加会话选择模块 B。桌面端 B 位于现有聊天模块 A 左侧，A/B 水平排列、顶边与底边对齐；选择当前用户的某个会话后，A 加载该会话的可见历史消息，并可在该会话中继续对话。

## 2. 范围

- 当前用户来自现有 `currentUser`；前端提供 `demo-user` 与 `user1` 两个演示用户，用于验证数据隔离。
- B 只展示属于当前用户的会话，按最近消息时间倒序，最多返回 50 条。
- 选择会话后加载 user/assistant 可见消息；内部 tool 消息和仅包含工具申请的 assistant 消息不作为普通气泡显示。
- 若历史轮次使用过工具，将工具名附到对应最终 assistant 回复上，复用现有虚线工具提示框。
- “新会话”继续生成新 conversation ID；尚未发送消息的新会话不写数据库，因此不会出现在 B 中。
- 本次不做会话删除、重命名、搜索、分页、WebSocket 或 Agent Loop。

## 3. 方案比较

### 方案 A：新增面向聊天页的只读会话接口（采用）

新增专用会话列表和历史消息接口，由后端按 `user_id` 强制过滤并转换为前端展示模型。优点是边界清晰、不会暴露内部工具结果，也不依赖测试台接口；后续增加真实用户时可以继续沿用。

### 方案 B：复用 `/v1/tests/tables` 通用数据库接口

不采用。该接口面向功能测试，会暴露内部消息流水，前端还要自行拼装工具链，并且用户归属隔离不够自然。

### 方案 C：只依赖浏览器 localStorage

不采用。无法跨浏览器或刷新后可靠恢复数据库中的真实历史，也无法覆盖已经落库的会话。

## 4. 后端接口

### 4.1 会话列表

`GET /v1/conversations?user=demo-user`

返回：

```json
[
  {
    "id": "web-...",
    "status": "active",
    "created_at": "2026-09-29T10:00:00",
    "last_message_at": "2026-09-29T10:05:00",
    "preview": "订单 1001 的物流到哪了",
    "message_count": 4
  }
]
```

- `user` 使用既有 `UserId` 规则校验。
- SQLAlchemy 查询强制 `Conversation.user_id == user`。
- 排序优先使用最后一条消息时间，没有消息时退回会话创建时间。
- `preview` 取最近一条非空的用户可见消息并截断，供 B 展示。

### 4.2 会话历史

`GET /v1/conversations/{conversation_id}/messages?user=demo-user`

返回：

```json
{
  "conversation_id": "web-...",
  "messages": [
    {"role": "user", "content": "订单 1001 的物流到哪了", "tool_name": null},
    {"role": "assistant", "content": "您的订单正在运输中。", "tool_name": "query_logistics"}
  ]
}
```

- 必须同时匹配 `conversation_id` 和 `user_id`；不属于该用户时返回 404，避免泄露其他用户会话是否存在。
- 只输出前端需要的字段，内部工具执行结果不返回。
- 遍历消息流水时，assistant 工具申请记录工具名，跳过 tool 结果，将工具名挂到紧随其后的最终 assistant 文本消息。

## 5. 分层结构

- `ConversationRepository`：增加按用户列会话、按用户取单个会话的方法。
- `MessageRepository`：继续按创建时间和 ID 稳定排序读取消息；增加会话摘要所需的受控查询。
- `ConversationHistoryService`：负责用户归属检查、摘要生成、内部消息到 UI 消息的转换。
- `conversation_history` API router：只负责参数校验、错误映射和响应模型。
- 依赖通过现有 FastAPI app state/session factory 注入，不创建第二套数据库连接。

## 6. 前端交互

- `api.js` 增加 `listConversations(user)` 和 `getConversationHistory(id, user)`。
- ChatView 初始化时读取模型并加载当前用户会话列表。
- B 中每项显示：消息预览、最近时间、状态；当前会话使用像素风高亮。
- 点击会话：更新 `conversationId` 和 localStorage，加载历史并替换 A 的消息列表。
- 发送完成：刷新 B，让最新会话移动到顶部并更新预览。
- 新会话：生成新 ID、显示初始问候；第一轮成功落库后刷新 B。
- 用户切换：立即清空旧用户消息，生成/恢复该用户自己的 conversation ID，再加载该用户会话；异步请求使用序号防止旧响应覆盖新用户界面。
- 发送过程中禁用会话切换和新会话按钮，避免流式内容写入错误会话。

## 7. 布局

- 桌面端 `.chat-workspace` 使用两列：B 固定约 280px，A 占剩余宽度。
- B/A 都拉伸到同一网格行高度，保证上下边界对齐。
- B 内部列表滚动，不因会话数量增加撑高 A/B 外框。
- 小于 900px 时改为单列，B 位于 A 上方，避免聊天区域被过度压缩。

## 8. 错误与空状态

- 无历史会话：B 显示“暂无历史会话”。
- 会话列表失败：B 显示局部错误，A 仍可创建新会话。
- 历史加载失败：保留当前 A 内容或回到初始问候，并显示明确错误，不伪造历史。
- 历史为空：显示初始问候。
- 所有数据库底层异常统一映射为不泄露连接信息的 503。

## 9. 测试与验收

- Repository/service：只返回指定用户会话；排序、摘要、消息计数正确。
- 使用 `demo-user` 与 `user1` 分别创建会话，验证列表和历史互不混入；用一方 user ID 读取另一方 conversation ID 必须返回 404。
- 历史转换：普通对话、带工具对话、空 assistant 工具申请、tool 消息均正确处理。
- API：合法用户、跨用户 404、参数校验、数据库失败不泄密。
- 前端构建与浏览器：B 在 A 左侧且上下边界对齐；切换会话能加载历史；选择后继续提问仍写入同一会话；新会话第一轮后出现在列表顶部。
- 回归：SSE、工具提示、多轮上下文、结构化抽取和数据库测试页保持正常。

## 10. 数据库影响

不新增表、不改字段，不需要 Alembic 迁移。复用现有 `conversations` 与 `messages` 数据。

## 11. 本阶段身份边界

- 本阶段明确不加入登录、JWT 或服务端 Session。
- 后端不允许仅凭 conversation ID 读取历史，所有列表和详情查询都必须携带并校验 `user_id`。
- 这属于演示环境的归属隔离：能够验证 `demo-user` 与 `user1` 的数据不会在正常 UI 和 API 归属检查中互相混入。
- 因 `user_id` 仍由客户端提供，本阶段不宣称能够阻止恶意调用者手工冒充其他 user ID；真正身份认证留给后续用户系统章节。
