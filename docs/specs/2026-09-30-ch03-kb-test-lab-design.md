# Chapter 03 增补：`/kb` 知识库测试台设计

## 1. 定位

新增前端路由 `/kb`，作为 Chapter 03 知识库功能的可视化测试台。它不替代客服聊天页，也不扩展为生产知识审核后台。

页面目标：

- 输入本地 Markdown 文件并查看结构感知切片结果；
- 查看文件、切片、类型、字符数、标题路径、questions/category/answer、关键条款和前后块信息；
- 明确触发 MySQL 入库、Milvus 向量补齐、语义检索、对话挖取、二级去重和中断恢复验证；
- 查看 MySQL/Milvus 同步状态和最近任务结果。

## 2. 页面结构

沿用现有像素艺术视觉，顶部标题在 `/kb` 路由显示“知识库测试台”。导航增加“知识库”。

桌面采用两列测试面板，移动端单列：

### 01 Markdown 切片预览

- 文件选择：单个 `.md`。
- 内容类型选择：`政策条款`、`商品 FAQ`、`售后手册`。
- “分析切片”按钮：只上传并解析，不写 MySQL/Milvus。
- 文件统计：文件名、UTF-8 字节数、字符数、行数、标题数、表格数、切片数、警告数。
- 切片列表：序号、字符数、内容类型、category、questions、answer/正文、section path、关键条款、前后块序号、是否表格、source key 预览。
- 列表内部滚动；切片正文可展开/收起。

### 02 入库与向量状态

- “入库到 MySQL”：明确写操作，再次使用当前文件和内容类型执行同一解析器；返回 chunk IDs 与 pending/no-op 数量。
- “补齐向量”：只处理本测试台上传来源的 pending/failed/stale-vectorizing 块。
- 状态统计：pending、vectorizing、vectorized、failed、pending_delete。
- 明细：MySQL chunk ID、vector status、vector ID、attempts、错误摘要、更新时间。
- 同内容再次入库应显示 no-op；内容变化使用稳定 source key 时更新原记录并回到 pending。

### 03 Dense 语义检索

- 输入自然语言问题、Top-K 和最低分数（默认使用后端配置）。
- 运行真实 BGE-M3 + Milvus COSINE 检索。
- 展示 rank、score、chunk ID、questions、answer、category、section path、content type、关键条款。
- 页面展示的是诊断信息；客服 `query_faq` 的外部返回结构不改变。

### 04 对话挖取与二级去重

- “执行一轮”按钮调用与 scheduler 相同 pipeline：mine → staging → deduplicate/promote → vectorize。
- 写操作前弹出确认，明确会处理当前数据库中的下一批历史对话。
- 展示 run ID、消息游标、抽取数、精确重复数、语义候选数、merged/conflict/independent/promoted 数及错误摘要。
- 暂存明细展示来源 conversation/message 范围、questions、answer、状态、重复目标和 LLM 判定原因。
- 只显示结构化结果，不显示模型密钥、完整系统 Prompt 或内部 tool payload。

### 05 中断恢复验证

- 仅针对 `source_type=kb_upload` 的测试台知识。
- 用户输入“第 N 个块后中断”，可选择 Milvus 写入前或写入后/MySQL 回填前故障点。
- “模拟中断”明确标记预期失败及剩余 pending/vectorizing 数。
- “重新补齐”再次运行同一 Worker。
- 验证结果：active 测试块是否全部 vectorized、MySQL/Milvus 主键是否一一对应、是否存在重复实体。
- 不允许通过该页面删除或破坏非测试台来源知识。

### 06 运行状态

- MySQL、Milvus、BGE-M3 readiness。
- 模型名、dense 维度、在线设备（不显示本地敏感路径）。
- 当前 collection、active knowledge 数、Milvus entity 数、同步差值。
- 最近 scheduler/mining run 状态与时间。

## 3. 上传与安全边界

- 使用 FastAPI `UploadFile` 和 `multipart/form-data`；增加官方要求的 `python-multipart` 依赖。
- 只接收一个 `.md`；最大大小由 `.env` 配置，默认 2 MiB。
- 内容必须是有效 UTF-8；拒绝空文件、错误扩展名和超限文件。
- 仅使用清理后的 basename 做显示，不将用户文件名拼接为服务器路径。
- 上传内容不写入 `knowledge/source`，预览只在内存/临时 spooled file 中处理。
- 入库来源键为 `kb-upload:{content_type}:{file-content-hash}:{section}:{ordinal}`，相同文件重复操作幂等。
- API 异常脱敏，不返回本地路径、数据库连接串、Milvus token 或模型缓存路径。

## 4. 后端测试接口

前缀统一为 `/v1/tests/knowledge`：

- `POST /preview`：multipart file + content_type；纯预览。
- `POST /ingest`：multipart file + content_type；写 MySQL pending。
- `POST /vectorize`：处理测试台来源 pending；JSON 参数包含 batch size 和可选故障注入。
- `POST /search`：自然语言 dense 检索，返回诊断型命中详情。
- `POST /mine-once`：运行一次受控对话挖取 pipeline。
- `GET /status`：组件 readiness、状态计数和一致性摘要。
- `GET /chunks`：分页/限制后的测试台 chunk 状态。
- `GET /staging`：分页/限制后的暂存与去重结果。
- `GET /runs`：最近挖取/调度运行记录。

所有请求/响应使用严格 Pydantic 模型。上传接口不能同时声明 JSON Body；内容类型通过 Form 字段传递。

## 5. 前端状态与交互

- 新增 `KbView.vue` 和 API 封装；不把文件内容放入 localStorage。
- 文件或 content type 变化时清除旧预览与旧入库结果，防止误把旧切片当作当前文件。
- 长操作分别显示“解析中 / 入库中 / 向量化中 / 检索中 / 挖取中”，按钮互斥，避免重复提交。
- HTTP 错误使用现有统一错误解析。
- 页面刷新后可从 status/chunks/staging/runs 恢复后端状态，但不会恢复浏览器选中的本地文件。
- 故障注入和对话挖取使用确认提示；普通预览、status 和 search 不需确认。

## 6. 测试

### 后端

- `.md`/UTF-8/大小校验和文件名净化。
- preview 不打开数据库事务、不调用 Milvus。
- preview 统计与核心 splitter 输出一致。
- ingest 相同文件幂等，返回 pending/no-op。
- vectorize 只能处理 kb_upload，不能误处理 markdown/faq/conversation 来源。
- 故障注入前后两种窗口与重跑一致性。
- search 返回 score + MySQL 权威原文。
- mine-once 使用同一 pipeline，不复制逻辑。
- status/readiness 错误脱敏。

### 前端

- `/kb` 路由和导航。
- 无文件时禁用预览/入库；文件变化清状态。
- 切片统计、类型、字符数、表格、关键条款和前后块正确显示。
- 长操作状态和互斥。
- 桌面两列、移动端单列且无横向溢出。

### 浏览器验收

1. 上传包含标题、长段落、IMPORTANT 和大表格的 Markdown，逐项核对切片信息。
2. 入库并补向量，状态由 pending 变 vectorized。
3. 输入“邮费是多少”，页面显示命中的运费说明和 COSINE score。
4. 执行对话挖取，查看 staging 与二级去重结果。
5. 在 Milvus 写入后故意中断，页面看到未完成状态；重新补齐后一致性检查通过。

## 7. 不做

- 在线 Markdown 编辑器、文件管理器、目录遍历。
- 任意服务器路径读取。
- 任意 SQL/Milvus 操作控制台。
- 批量删除生产知识。
- 知识审核、发布、回滚和权限系统。

## 8. 官方接口依据

- FastAPI `UploadFile` / `File` / `Form` 与 `python-multipart`。
- Vue 3 Composition API 和现有 vue-router 路由方式。
- Chapter 03 主设计中已确认的 LangChain splitter、BGE-M3、Milvus 和 SQLAlchemy 接口。
