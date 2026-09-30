# Chapter 02：Function Calling 数据查询能力设计

## 1. 目标

在现有电商客服聊天入口内接入单轮 Function Calling。用户仍只在聊天页提问；后端负责让模型选择最多一个工具、执行工具、把结果返回模型，并将最终回答按现有 OpenAI Chat Completions 风格 SSE 逐 token 输出。

本章引入 Docker MySQL、SQLAlchemy 异步分层持久化、Alembic 迁移和五个 LangChain `@tool` 工具。聊天消息、工具调用申请、工具结果及最终回答全部落库。

## 2. 范围与非目标

### 2.1 本章范围

- Docker Compose 启动 MySQL。
- SQLAlchemy 2.x 异步 ORM，驱动使用 `asyncmy`。
- Alembic 管理数据库版本，独立幂等 seed 脚本灌入测试数据。
- 建立 `faq`、`conversations`、`messages`、`tickets` 四张表。
- 实现五个业务工具：`query_order`、`query_product`、`query_logistics`、`query_faq`、`create_ticket`。
- 工具注册、参数校验、错误归一化、超时和重试。
- 工具选择、执行、最终回答生成的单轮编排。
- 前端 `demo-user` 用户选择控件和工具调用虚线提示框。

### 2.2 明确不做

- 多轮自动 Agent Loop。
- 一轮执行多个工具。
- 向量检索、同义词召回和 RAG。
- 真实订单、商品或物流 API。
- 用户认证、登录和用户表。

## 3. 技术决策

### 3.1 数据库生命周期

采用 Alembic 版本化迁移和独立 seed 脚本。SQLAlchemy ORM 模型是结构定义来源；Docker Compose 只启动 MySQL，不维护另一套手写建表 SQL。应用启动时不调用 `create_all()`。

### 3.2 异步数据库访问

使用 `create_async_engine`、`async_sessionmaker` 和 `mysql+asyncmy`。每个独立操作获取自己的 `AsyncSession`，不跨并发任务共享 Session。Engine 在 FastAPI lifespan 中创建，并在关闭时 `dispose()`。

### 3.3 工具展示协议

工具决策与执行在 `StreamingResponse` 返回前完成。若调用工具，响应头增加：

```text
X-Shop-Assistant-Tool: <tool_name>
```

CORS 暴露该响应头。SSE 正文不混入自定义事件，继续使用现有 OpenAI 风格 chunk。

### 3.4 用户身份

聊天请求增加可选 `user` 字段，默认 `demo-user`。前端在 `SYSTEM READY` 下提供用户选择控件，本章只有 `demo-user` 一个选项。暂不引入用户表或认证。

## 4. 分层结构

```text
backend/app/
├─ api/                 # HTTP/SSE 适配
├─ db/                  # Base、Engine、Session factory
├─ models/              # ORM 模型
├─ repositories/        # 持久化查询与写入
├─ services/            # 对话和业务编排
├─ tools/               # @tool、注册表、执行器
├─ config.py
├─ dependencies.py
└─ schemas.py
```

API 层不直接书写 SQL；工具不直接依赖 FastAPI Request；Repository 不调用模型；ChatService 负责流程编排。

## 5. 数据模型

### 5.1 `faq`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT | 主键，自增 |
| `question` | VARCHAR(255) | 非空，索引 |
| `answer` | TEXT | 非空 |
| `category` | VARCHAR(64) | 非空，索引 |

### 5.2 `conversations`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | VARCHAR(128) | 主键，与前端 `conversation_id` 一致 |
| `user_id` | VARCHAR(64) | 非空，索引；本章为 `demo-user` |
| `status` | ENUM | `active`、`waiting_human`、`closed`、`failed` |
| `created_at` | DATETIME | 非空，数据库默认当前时间 |

### 5.3 `messages`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT | 主键，自增 |
| `conversation_id` | VARCHAR(128) | 外键，索引，级联删除 |
| `role` | ENUM | `user`、`assistant`、`tool` |
| `content` | LONGTEXT | 非空，可用空字符串表达仅工具调用的 assistant 消息 |
| `tool_calls` | JSON | 可空，保存模型工具调用申请 |
| `tool_call_id` | VARCHAR(128) | 可空，工具结果与申请关联 ID |
| `created_at` | DATETIME | 非空，数据库默认当前时间；与 ID 共同用于稳定排序 |

### 5.4 `tickets`

| 字段 | 类型 | 约束 |
|---|---|---|
| `ticket_no` | VARCHAR(32) | 主键 |
| `conversation_id` | VARCHAR(128) | 外键，索引 |
| `issue_description` | TEXT | 非空 |
| `ticket_type` | VARCHAR(64) | 非空 |
| `status` | ENUM | `open`、`processing`、`resolved`、`closed` |
| `created_at` | DATETIME | 非空，数据库默认当前时间 |

`create_ticket` 根据稳定的 `tool_call_id` 派生工单号，使同一调用因超时重试时返回同一工单，避免重复副作用。

## 6. 测试数据

Seed 脚本使用稳定键检查或 upsert，重复运行不重复插入。FAQ 至少包含：

- 问题：`退货政策是什么`
- 分类：`售后`
- 答案：演示用退货政策正文

可以增加换货、发票等演示 FAQ，但不得加入“邮费”“运费”同义问法，以保留本章验收要求中的预期漏召回。

## 7. 工具定义

全部使用 LangChain `@tool`，参数由显式 Pydantic Schema 校验，`extra="forbid"`，字符串包含长度和非空约束。

### 7.1 `query_order`

- 参数：`order_id`
- 行为：随机生成订单状态、金额和商品摘要。
- 不访问数据库，不调用外部 API。

### 7.2 `query_product`

- 参数：`keyword`
- 行为：随机生成商品名称、库存、价格和上下架状态。
- 不访问数据库，不调用外部 API。

### 7.3 `query_logistics`

- 参数：`order_id`
- 行为：随机生成承运商、运单号、物流状态、当前位置和预计送达时间。
- 不访问数据库，不调用外部 API。

### 7.4 `query_faq`

- 参数：`keyword`
- 行为：对 `faq.question` 执行参数化 `LIKE '%keyword%'`，限制返回数量。
- 不做分词、同义词、模糊编辑距离、向量检索或模型改写。
- 没有结果时返回明确的结构化 `not_found`，最终模型不得凭常识补写政策。

### 7.5 `create_ticket`

- 模型参数：`issue_description`、`ticket_type`。
- 运行上下文注入：`conversation_id`、`tool_call_id`，二者不暴露给模型填写。
- 行为：写入 `tickets`，同时把会话状态更新为 `waiting_human`。

## 8. 工具基础设施

### 8.1 ToolRegistry

- 注册工具名称到 LangChain BaseTool。
- 拒绝重复名称。
- 仅允许执行已注册工具。
- 为模型提供工具列表。

### 8.2 ToolExecutor

- 通过 BaseTool `ainvoke` 触发 Pydantic Schema 校验。
- 单次超时默认 5 秒。
- 最大执行次数默认 2 次。
- 参数错误、未知工具、业务 `not_found` 不重试。
- 超时及可重试系统错误重试一次。
- 输出统一为 JSON 字符串，并转换为带原 `tool_call_id` 的 `ToolMessage`。
- 对外错误不包含堆栈、数据库地址、密钥或底层异常正文。

统一结果示例：

```json
{"ok": true, "data": {}}
```

```json
{"ok": false, "error": {"code": "not_found", "message": "未查询到相关信息"}}
```

## 9. 单轮编排

1. 校验请求、用户和 conversation ID。
2. 在进程内按 conversation ID 串行化同一会话请求。
3. upsert 会话壳并写入 user 消息。
4. 从数据库加载完整消息对象并按完整对话轮次裁剪，避免产生孤立 ToolMessage；继续满足 token 预算。
5. 用 `model.bind_tools(tools, tool_choice="auto", parallel_tool_calls=False)` 进行一次非流式工具决策。
6. 无工具调用时跳过执行；有调用时只接受一个工具。
7. 保存 assistant 工具申请；通过 ToolExecutor 执行；保存 tool 结果。
8. 将原始上下文、工具申请和 ToolMessage 交给不绑定工具的模型。
9. 使用 `astream` 生成最终回答并按现有 OpenAI SSE 格式输出。
10. 流正常完成后写入最终 assistant 消息；异常时保存可用的部分内容并将会话标记为 `failed`。

本章不存在再次让模型选择工具的循环。

## 10. API 与前端

`POST /v1/chat/completions` 保持现有 URL 和 OpenAI 风格主体，新增：

```json
{"user": "demo-user"}
```

该字段可省略，后端默认 `demo-user`。

工具使用时响应头示例：

```text
X-Shop-Assistant-Tool: query_logistics
```

前端 `streamChat` 在读取流之前读取该响应头，并通过 `onToolCall(name)` 通知 ChatView。当前 assistant 消息记录 `toolName`，在文本气泡上方渲染虚线像素框。没有工具时不显示。

## 11. Prompt 约束

System Prompt 文件继续位于 `backend/prompts/`，不硬编码到 Python，也不读取或修改项目根目录的 `提示词.md`。新增约束包括：

- 订单、商品、物流、FAQ 和工单场景优先依据工具结果。
- 工具返回未找到或失败时如实告知，不编造数据。
- 一轮最多选择一个最匹配的工具。
- 用户明确需要人工处理时才创建工单。

## 12. 错误与事务

- 会话和 user 消息先提交，确保请求有审计记录。
- 工具申请与结果成对持久化。
- 工单创建在独立事务中保持幂等。
- 工具失败作为结构化 ToolMessage 交给模型，由模型生成用户可理解的降级回答。
- 模型决策失败或最终流失败通过现有 SSE 错误格式返回，并避免泄露内部错误。
- 数据库不可用时在流开始前返回明确 HTTP 503；流开始后的失败使用 SSE 错误事件。

## 13. 验收

1. `订单 1001 的物流到哪了`：选择 `query_logistics`，页面显示工具框，最终回答引用模拟物流结果；数据库包含 user、assistant tool call、tool result、assistant final 四类记录。
2. `退货政策是什么`：选择 `query_faq`，使用 MySQL FAQ 回答。
3. `邮费是多少`：`query_faq` 的 LIKE 查询无结果，最终回答明确未找到；该结果记录为下一阶段关键词召回升级项。
4. 无需工具的普通问候：不显示工具框，最终回答仍逐 token 输出并落库。

## 14. 官方依据

- FastAPI lifespan 与 yield 依赖：<https://fastapi.tiangolo.com/advanced/events/>、<https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/>
- SQLAlchemy asyncio 与 MySQL asyncmy：<https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html>、<https://docs.sqlalchemy.org/en/20/dialects/mysql.html>
- LangChain tools 与 ToolMessage：<https://reference.langchain.com/python/langchain-core/tools>、<https://reference.langchain.com/python/langchain-core/messages/tool>
- 阿里云 Function Calling：<https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling>
- MySQL 官方 Docker 镜像：<https://hub.docker.com/_/mysql>
