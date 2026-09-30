# Chapter 02：Function Calling 数据查询能力实施计划

## 执行原则

- 严格按已通过的设计文档实施：`docs/specs/2026-09-29-ch02-tool-calling-design.md`。
- 每个任务采用测试先行：先新增失败测试，再实现最小代码，通过后运行相关回归。
- 每完成一个任务立即更新 `devHistory/ch02.md`，不在收尾时补记。
- 不修改项目根目录 `提示词.md`。
- 不引入 Agent Loop、RAG、真实外部业务 API 或其他数据库。
- 涉及新 API 前再次核对对应官方接口；若固定技术栈出现冲突，停止并询问。

## Task 1：依赖、配置和 Docker MySQL 基础设施

### 文件

- 修改：`backend/pyproject.toml`
- 修改：`backend/requirements-lock.txt`
- 修改：`.env.example`
- 修改：`.gitignore`
- 新增：`compose.yaml`
- 新增：`backend/app/db/__init__.py`
- 新增：`backend/app/db/base.py`
- 新增：`backend/app/db/session.py`
- 修改：`backend/app/config.py`
- 新增/修改：`backend/tests/test_config.py`
- 新增：`backend/tests/test_db_session.py`

### 步骤

1. 增加配置测试：数据库 URL、MySQL Compose 参数、工具超时/重试参数必须通过 Pydantic 校验，密钥字段不得出现在 repr。
2. 增加 SQLAlchemy、asyncmy、Alembic 依赖并生成锁定版本。
3. 在 `.env.example` 增加 MySQL 与工具执行配置，不写真实密码。
4. 建立异步 Engine/Session factory；测试创建和 dispose 行为。
5. 编写 `compose.yaml`：MySQL 8.4、utf8mb4、命名 volume、healthcheck、端口和凭证环境变量。
6. 用 `docker compose config` 验证配置，再启动 MySQL 并等待 healthy。
7. 运行配置和 DB 基础设施测试。

### 完成标准

- `docker compose up -d mysql` 后容器 healthy。
- 后端可通过 `mysql+asyncmy` 建立连接。
- 现有测试不受影响。

## Task 2：ORM 模型、Alembic 首次迁移与 seed

### 文件

- 新增：`backend/app/models/__init__.py`
- 新增：`backend/app/models/faq.py`
- 新增：`backend/app/models/conversation.py`
- 新增：`backend/app/models/message.py`
- 新增：`backend/app/models/ticket.py`
- 新增：`backend/alembic.ini`
- 新增：`backend/alembic/env.py`
- 新增：`backend/alembic/script.py.mako`
- 新增：`backend/alembic/versions/*_create_chapter_02_tables.py`
- 新增：`backend/scripts/seed_demo_data.py`
- 新增：`backend/tests/test_models.py`
- 新增：`backend/tests/test_migrations.py`
- 新增：`backend/tests/test_seed.py`

### 步骤

1. 先写 ORM 约束测试：表名、主外键、枚举、JSON 字段和索引。
2. 实现四个 ORM 模型和枚举。
3. 配置 Alembic 异步迁移环境，生成并人工审查首次迁移。
4. 在空测试数据库执行 upgrade，验证四表结构；执行 downgrade/upgrade 验证可逆性。
5. 编写幂等 seed，加入退货政策及其他不影响漏召回的 FAQ。
6. 连续执行 seed 两次，验证无重复数据。

### 完成标准

- Alembic 可从空库创建四张表并回滚。
- seed 重复执行结果一致。
- FAQ 不包含“邮费”或“运费”召回词。

## Task 3：Repository 层和数据库会话历史

### 文件

- 新增：`backend/app/repositories/__init__.py`
- 新增：`backend/app/repositories/faq.py`
- 新增：`backend/app/repositories/conversations.py`
- 新增：`backend/app/repositories/messages.py`
- 新增：`backend/app/repositories/tickets.py`
- 重构：`backend/app/conversation_store.py`
- 新增：`backend/tests/test_repositories.py`
- 修改：`backend/tests/test_conversation_store.py`

### 步骤

1. 先写 Repository CRUD、FAQ LIKE、ticket 幂等创建测试。
2. 实现参数化 SQLAlchemy 查询与事务边界。
3. 将 `ConversationStore` 从内存历史改为数据库实现，同时保留进程内每会话锁。
4. 重建 HumanMessage、AIMessage 和 ToolMessage，保留 tool call ID。
5. 按完整轮次执行 token 预算裁剪，测试不会留下孤立 ToolMessage。
6. 回归现有上下文和输入超长测试。

### 完成标准

- 会话重启后历史仍可读取。
- 完整工具消息链可持久化并重建。
- 历史裁剪继续满足 token 预算。

## Task 4：五个 `@tool` 与工具基础设施

### 文件

- 新增：`backend/app/tools/__init__.py`
- 新增：`backend/app/tools/schemas.py`
- 新增：`backend/app/tools/business.py`
- 新增：`backend/app/tools/registry.py`
- 新增：`backend/app/tools/executor.py`
- 新增：`backend/tests/test_business_tools.py`
- 新增：`backend/tests/test_tool_registry.py`
- 新增：`backend/tests/test_tool_executor.py`

### 步骤

1. 先写五个工具的名称、描述和 JSON Schema 测试。
2. 写随机订单、商品和物流工具；测试中注入/固定随机源以保持确定性。
3. 写 `query_faq`：验证“退货政策”命中、“邮费”不命中。
4. 写幂等 `create_ticket`：验证相同 tool call ID 不重复建单。
5. 写 ToolRegistry：注册、重复名称、未知工具测试。
6. 写 ToolExecutor：参数错误、不重试错误、超时、一次重试、错误脱敏及 ToolMessage 关联测试。

### 完成标准

- 五个工具均由 LangChain `@tool` 定义。
- 参数错误在执行前被拦截。
- 返回模型的结果统一为 JSON ToolMessage。

## Task 5：单轮 Function Calling 编排与持久化

### 文件

- 修改：`backend/prompts/customer_service_system.txt`
- 修改：`backend/app/services/chat.py`
- 修改：`backend/app/model_factory.py`
- 修改：`backend/app/dependencies.py`
- 修改：`backend/app/main.py`
- 修改：`backend/app/schemas.py`
- 修改：`backend/app/api/chat.py`
- 修改：`backend/tests/fakes.py`
- 修改：`backend/tests/test_chat_service.py`
- 修改：`backend/tests/test_chat_api.py`
- 新增：`backend/tests/test_tool_chat_flow.py`

### 步骤

1. 扩展 Fake 模型，支持预设 tool calls 和最终流式 chunks。
2. 先写无工具、一个工具、非法工具、多个工具、工具失败和模型失败测试。
3. 在模型工厂或 ChatService 中建立 bound-tools 决策模型；使用 `tool_choice="auto"` 和禁用并行工具。
4. 实现 `prepare_turn`：持久化用户消息、加载历史、调用一次决策模型、执行最多一个工具、持久化工具链。
5. 实现最终 plain-model `astream`，沿用现有 OpenAI SSE chunk。
6. 在正常、失败和客户端中断路径保存最终或部分 assistant 内容及会话状态。
7. API 请求增加默认 `user="demo-user"`。
8. 工具调用时设置 `X-Shop-Assistant-Tool`；数据库连接失败在流开始前映射为 HTTP 503。
9. CORS 增加 `expose_headers=["X-Shop-Assistant-Tool"]`。

### 完成标准

- 一轮最多执行一个工具，不发生 Agent Loop。
- 工具结果会被最终模型使用。
- SSE 格式和现有无工具聊天保持兼容。
- 完整消息链落入 MySQL。

## Task 6：前端用户选择与工具调用提示

### 文件

- 修改：`frontend/src/api.js`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/views/ChatView.vue`
- 修改：`frontend/src/style.css`
- 视需要新增：`frontend/src/components/UserSwitcher.vue`

### 步骤

1. 在 `streamChat` 请求中发送当前用户，并读取 `X-Shop-Assistant-Tool`。
2. 在品牌区 `SYSTEM READY` 下方增加用户控件，当前只有 `demo-user`。
3. assistant 消息增加 `toolName`，在回复正文上方渲染像素风虚线框。
4. 新会话继续保留当前用户，但生成新 conversation ID。
5. 验证桌面和 390×844 移动端布局，无横向溢出。

### 完成标准

- 用户只需在聊天页提问即可触发工具。
- 使用工具时，虚线框先于回答文本显示。
- 不使用工具时不显示空框。

## Task 7：脚本、文档和三条验收链路

### 文件

- 修改：`scripts/run-backend.cmd`
- 修改：`scripts/run-backend.ps1`
- 视需要新增：`scripts/start-mysql.cmd`
- 视需要新增：`scripts/migrate-and-seed.cmd`
- 修改：`README.md`
- 新增：`docs/acceptance/ch02-function-calling-examples.md`

### 步骤

1. 提供 MySQL 启动、迁移、seed、后端、前端的完整命令。
2. 运行 Ruff 和全部 pytest。
3. 运行前端 production build。
4. 用真实 MySQL 验证四表和 seed。
5. 使用 Fake 模型完成稳定自动验收。
6. 使用当前阿里云模型完成三条浏览器验收：物流、退货政策、邮费漏召回。
7. 查询数据库证明工具申请、工具结果和最终回答已经落库。
8. 将命令、输出摘要和可复现案例写入验收文档。

### 完成标准

- 三条用户验收案例符合预期。
- 自动测试全部通过。
- 功能演示命令可从干净环境复现。

## Task 8：Code Review 与 Finish

### 检查项

1. 对照 spec 逐条核查功能范围和非目标。
2. 检查事务、并发、重试幂等、错误脱敏和密钥管理。
3. 检查 SQL 查询参数化及 ORM 关系。
4. 检查 Function Calling 消息序列和 tool call ID 配对。
5. 检查 SSE 兼容性、响应头 CORS 和前端错误状态。
6. 检查迁移 upgrade/downgrade、seed 幂等和 Docker 数据持久化。
7. 修复 P0/P1/P2 问题并重跑相关测试。
8. 在 `devHistory/ch02.md` 分别记录 code review 结论和 finish；整理最终交付命令、测试结果和用户测试案例。

## 全量验证命令（计划）

```powershell
docker compose up -d mysql
cd backend
alembic upgrade head
python -m scripts.seed_demo_data
pytest
ruff check .
cd ..\frontend
npm run build
```

实际执行时使用当前环境中已确认的 Docker CLI 绝对路径，或在 PATH 刷新后使用 `docker`。
