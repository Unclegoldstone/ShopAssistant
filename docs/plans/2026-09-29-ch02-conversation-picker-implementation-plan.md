# Chapter 02：会话选择与历史加载实施计划

## 执行原则

- 严格按已通过设计实施：`docs/specs/2026-09-29-ch02-conversation-picker-design.md`。
- 每个任务测试先行：先新增失败测试，再写最小实现，再运行相关回归。
- 每完成一个任务立即追加 `devHistory/ch02.md`，不在 Finish 时集中补写。
- 不读取或修改项目根目录 `提示词.md`。
- 不新增数据库表或字段，不复用测试台通用 CRUD 作为聊天页数据源。
- 不增加会话删除、重命名、搜索、分页、WebSocket、Agent Loop 或 RAG。
- 不增加登录、JWT 或服务端 Session；使用 `demo-user` 与 `user1` 验证本阶段基于 user ID 的归属隔离。
- 遇到固定技术栈冲突或无法保证用户隔离时停止并询问，不自行改方案。

## Task 1：历史响应模型与消息转换规则

### 文件

- 修改：`backend/app/schemas.py`
- 新增：`backend/app/services/conversation_history.py`
- 新增：`backend/tests/test_conversation_history_service.py`

### 步骤

1. 先写失败测试，定义 `ConversationSummary`、`ConversationHistoryMessage`、`ConversationHistory` 的输出字段与严格校验。
2. 写普通 user/assistant 历史转换测试。
3. 写带工具链的转换测试：跳过空 assistant 工具申请与 tool 结果，把第一个工具名挂到最终 assistant 文本消息。
4. 写异常/部分消息测试：空文本不生成气泡；工具后没有最终回答时不伪造内容；多个历史轮次之间不串工具名。
5. 实现最小纯函数转换逻辑，保持内部消息不向前端泄露。
6. 运行定向测试与 Ruff。

### 完成标准

- UI 历史只包含 `user`、`assistant` 两种可见角色。
- 工具名与对应最终回答正确关联。
- 响应模型不包含工具结果、原始 tool call 参数或数据库内部字段。

## Task 2：Repository、历史服务与用户隔离

### 文件

- 修改：`backend/app/repositories/conversations.py`
- 修改：`backend/app/repositories/messages.py`
- 修改：`backend/app/services/conversation_history.py`
- 修改：`backend/tests/test_repositories.py`
- 修改：`backend/tests/test_conversation_history_service.py`

### 步骤

1. 先写真实 MySQL 集成测试：两个用户各自创建会话与消息，列表互不混入。
2. 为 `ConversationRepository` 增加按 `user_id` 查询、按最近消息时间倒序和最多 50 条限制。
3. 使用 SQLAlchemy 2.0 `select()`、聚合/关联子查询计算最近消息时间、预览与消息数，避免加载所有用户消息后在 Python 全量过滤。
4. 增加按 `conversation_id + user_id` 读取会话的方法；不匹配时视为不存在。
5. 历史服务先校验归属，再按既有稳定顺序读取消息并执行 Task 1 的 UI 转换。
6. 测试同时间消息按 ID 稳定排序、无消息会话、跨用户读取和 50 条边界。
7. 测试数据全部使用唯一 ID，并在 finally 中清理。

### 完成标准

- 会话列表只属于请求用户并按最近活动排序。
- 跨用户读取不会泄露会话是否存在。
- 不修改表结构，不产生 Alembic 迁移。

## Task 3：FastAPI 会话列表与历史接口

### 文件

- 新增：`backend/app/api/conversation_history.py`
- 修改：`backend/app/api/__init__.py`
- 修改：`backend/app/dependencies.py`
- 修改：`backend/app/main.py`
- 新增：`backend/tests/test_conversation_history_api.py`

### 步骤

1. 先用 Fake history service 写 API 失败测试。
2. 实现 `GET /v1/conversations?user=...`，使用既有 `UserId` 类型验证用户参数并返回 `list[ConversationSummary]`。
3. 实现 `GET /v1/conversations/{conversation_id}/messages?user=...`，复用 `ConversationId` / `UserId` 校验。
4. 将“不存在或不属于用户”统一映射为不泄露细节的 404。
5. 将数据库异常映射为脱敏 503，日志只记录异常类型。
6. 在 app lifespan 中用现有 `database_runtime.session_factory` 构造服务并注入，不建立额外 Engine。
7. 验证 OpenAPI 响应模型、422 参数校验、404、503 与 CORS GET。

### 完成标准

- 两个接口的 JSON 结构稳定且经过 Pydantic 响应模型过滤。
- 现有聊天、测试台接口保持兼容。

## Task 4：前端会话状态与历史加载

### 文件

- 修改：`frontend/src/api.js`
- 修改：`frontend/src/views/ChatView.vue`

### 步骤

1. 增加 `listConversations(user)` 和 `getConversationHistory(conversationId, user)`，统一复用现有错误解析。
2. ChatView 增加会话列表、列表加载、历史加载、局部错误和当前选中会话状态。
3. 将用户选项扩展为 `demo-user` 与 `user1`；初始化时并行读取模型配置和当前用户会话，保留当前 conversation ID 仅当它属于该用户，否则创建新 ID。
4. 点击 B 中会话时加载历史，成功后再切换 A；历史为空时显示初始问候。
5. 用户切换时使用每用户 localStorage key，清除旧用户 UI；为异步请求增加递增序号，忽略过期响应。
6. 发送过程中禁用新会话与会话切换；发送完成后刷新 B，并保持当前会话选中。
7. 历史消息直接复用现有气泡和工具虚线框结构。
8. 验证失败状态不会丢失当前可用消息，也不会把旧用户响应覆盖到新用户。

### 完成标准

- 选择会话后 A 显示数据库历史并可继续发送。
- 新会话首轮结束后出现在 B 顶部。
- 快速切换或用户变化不会造成历史串线。

## Task 5：B/A 像素风布局与响应式适配

### 文件

- 修改：`frontend/src/views/ChatView.vue`
- 修改：`frontend/src/style.css`

### 步骤

1. 在 A 左侧新增 B panel，标题、刷新状态、空状态和会话项沿用现有像素艺术视觉语言。
2. 桌面 `.chat-workspace` 设置约 `280px + minmax(0, 1fr)` 两列，`align-items: stretch`；B/A 高度由同一网格行拉伸对齐。
3. B 内部使用 flex column，会话列表独立滚动，避免数量增加改变外框高度。
4. 当前会话高亮；状态、时间、预览使用紧凑可读布局；长文本省略但保留可访问名称。
5. 小于 900px 改为单列，B 在 A 上方；验证 390×844 无横向溢出。
6. 运行 Vue production build。

### 完成标准

- 桌面 B 在左、A 在右，顶边和底边对齐。
- 移动端操作完整且无横向滚动。
- 空状态、加载状态、错误状态与选中状态清晰。

## Task 6：端到端验收、Code Review 与 Finish

### 文件

- 修改：`devHistory/ch02.md`
- 修改：`docs/acceptance/ch02-function-calling-examples.md`
- 视需要修改：`README.md`

### 步骤

1. 运行后端完整 pytest、真实 MySQL 集成测试、Ruff、前端 production build。
2. 启动临时 8001/5174 服务，不覆盖用户可能正在运行的 8000/5173。
3. 浏览器以 `demo-user` 创建至少两个会话，验证 B 的排序、预览、状态与选中高亮。
4. 切换到 `user1` 创建独立会话，验证两个用户的 B 列表互不混入；直接用另一用户 ID 请求 conversation ID 必须得到 404。
5. 在普通历史会话和带工具历史会话间切换，验证气泡与工具提示恢复正确。
6. 选择旧会话继续提问，核对新消息仍落在原 conversation ID。
7. 验证“新会话”初始不入列表，第一轮完成后进入顶部。
8. 验证桌面 B/A 上下边界对齐和 390×844 响应式无溢出。
9. 查询数据库证明用户隔离与消息归属，清理验收专用记录；不停止 MySQL。
10. Code Review 重点检查：跨用户访问、内部 tool 数据泄露、流式期间切换、过期请求覆盖、N+1 查询与错误脱敏。
11. 每项验收与修正即时写入 `ch02.md`，最后更新演示命令和可测试案例。

### 完成标准

- 用户可以从 B 选择当前用户的历史会话，并在 A 中查看及继续对话。
- A/B 桌面布局上下边界对齐，移动端可用。
- 无 P0、P1、P2 遗留，临时服务和验收数据已清理。
