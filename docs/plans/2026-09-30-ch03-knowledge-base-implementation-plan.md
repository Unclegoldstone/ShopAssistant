# Chapter 03：Dense 向量知识库实施计划

## 0. 执行规则

- 严格按任务顺序执行，每个任务先写失败测试，再写最小实现。
- 每个任务完成后立即追加 `devHistory/ch03.md`，不得在收尾时补写。
- 每次使用框架/库接口前再次打开对应稳定版本官方文档；若安装版本与设计接口不一致，停止并修正规划，不猜 API。
- 不读取或修改根目录 `提示词.md`。新增 LLM 提示词只放 `backend/prompts/`。
- 不修改 `query_faq` 的工具名、`FaqKeywordArgs` 或返回 JSON 结构。
- 不实现关键词回退、混合检索、sparse、ColBERT 或 rerank。
- 涉及模型下载、Python 依赖下载和 Docker 镜像拉取时，使用用户批准的网络权限；若 BGE-M3 无法在固定技术栈下运行，停止询问，不换模型。

## Task 1：依赖、配置与运行环境预检

### 文件

- 修改：`backend/pyproject.toml`
- 修改：`backend/requirements-lock.txt`
- 修改：`.env.example`
- 修改：`.gitignore`
- 修改：`compose.yaml`
- 新增：`backend/tests/test_knowledge_config.py`
- 新增：`backend/tests/test_knowledge_dependencies.py`
- 视官方 Compose 增加：Milvus/etcd/对象存储配置与命名 volumes

### 步骤

1. 先写 Settings 测试，覆盖 BGE 模型、在线/离线设备、Milvus、Top-K、阈值、chunk、向量批次、租约、挖取周期和去重阈值；首次因字段不存在失败。
2. 再次核对官方稳定接口并锁定兼容范围：FlagEmbedding 1.4.x、PyMilvus 3.0.x、langchain-text-splitters 1.1.x、APScheduler 3.11.x；解析 PyTorch/transformers 依赖后生成 lock。
3. 配置 `.env.example` 安全默认值；模型缓存、Milvus 本地数据和临时建库产物加入 `.gitignore`。
4. 根据 Milvus 官方当前稳定 Standalone Compose，将 Milvus、etcd 和对象存储加入现有 Compose；使用命名 volume，避免把大数据目录写入 Git。
5. 运行 `docker compose config`，启动服务并等待 MySQL/Milvus 依赖 healthy。
6. 执行只读/最小 smoke：导入四个新依赖、创建 MilvusClient、确认 Python 3.12；下载并加载 BGE-M3，以短文本验证 dense 输出维度、dtype 和归一化。
7. 分别实测在线 CUDA 配置和离线 CPU 配置。若 CUDA 4 GB 无法稳定加载，暂停并向用户报告，不能自动改为其他模型；设备配置变化需用户确认。

### 完成标准

- 依赖可在项目 `.venv` 中解析，`pip check` 通过。
- BGE-M3 能输出 dense 向量且维度与配置一致。
- MySQL、Milvus Standalone 及依赖容器 healthy。
- 配置测试、Ruff、现有全量测试通过。

## Task 2：知识表模型与 Alembic 迁移

### 文件

- 新增：`backend/app/models/knowledge.py`
- 修改：`backend/app/models/__init__.py`
- 新增：`backend/alembic/versions/<revision>_add_knowledge_base_tables.py`
- 修改：`backend/tests/test_models.py`
- 修改：`backend/tests/test_migrations.py`

### 步骤

1. 先为 `knowledge_chunks`、`knowledge_staging`、`knowledge_mining_runs` 写模型结构测试，首次失败。
2. 实现枚举与 ORM：JSON questions/section path、LONGTEXT answer、状态、来源、稳定 source key、指纹、向量租约/错误、前后块自关联和时间字段。
3. 建立必要索引/唯一约束：source key、fingerprint、vector status、staging 来源范围、run/cursor。
4. 编写 Alembic upgrade/downgrade；确保自关联外键的创建和删除顺序正确。
5. 使用专用迁移测试数据库执行 upgrade → downgrade → upgrade，不在主业务库执行 downgrade。

### 完成标准

- 模型测试通过。
- 隔离迁移库可逆测试通过。
- 主 MySQL 只执行 upgrade 后三表存在，旧四表数据不受影响。

## Task 3：知识领域模型、规范化与 Repository

### 文件

- 新增：`backend/app/knowledge/types.py`
- 新增：`backend/app/knowledge/text.py`
- 新增：`backend/app/repositories/knowledge.py`
- 新增：`backend/tests/test_knowledge_text.py`
- 新增：`backend/tests/test_knowledge_repository.py`

### 步骤

1. 先写 tests：questions 去空/去重/稳定排序、固定向量文本只含 category/questions/answer、Unicode/标点规范化、SHA-256 指纹稳定。
2. 实现不可变领域数据类型和纯函数。
3. 先写 Repository 集成测试：按 source key 幂等 upsert、内容变化保持主键并重置 pending、内容不变不重复写、按 Milvus ID 批量回源并恢复原顺序。
4. 实现 pending/vectorizing/vectorized/failed/pending_delete 状态更新、attempts、租约过期认领和错误脱敏字段。
5. 使用真实 MySQL 验证重复运行、事务与并发认领。

### 完成标准

- 向量文本不包含四类元数据。
- 相同 source key 重跑不增加记录；内容变化复用原主键并回到 pending。
- Repository 单元/真实 MySQL 测试通过。

## Task 4：Markdown 结构感知切分

### 文件

- 新增：`backend/app/knowledge/markdown.py`
- 新增：`backend/tests/test_markdown_knowledge_splitter.py`
- 新增：`knowledge/source/policies/shipping.md`
- 新增：`knowledge/source/policies/returns.md`
- 新增：`knowledge/source/product-faq/demo-products.md`
- 新增：`knowledge/source/manuals/after-sales.md`

### 步骤

1. 先写标题测试：H1-H6 路径、政策 questions=当前标题、category=上级路径、content type=目录类型。
2. 写失败测试：超长中文内容按完整句子切分、whole-sentence overlap、禁止半句；单个超长句保留并报告 warning。
3. 写失败测试：大型 Markdown 表格逐行分块，每块包含相同表头和分隔行，数据行不拆开。
4. 写失败测试：`> [!IMPORTANT]` 设置关键条款；不同源文件的前后指针不串联。
5. 用 LangChain `MarkdownHeaderTextSplitter` 获取结构 metadata；用 `RecursiveCharacterTextSplitter` 产生候选边界，再由项目代码执行句子边界修正和表格专用切分。
6. 生成稳定 source key：相对路径 + section path + 块序号；记录 source revision。
7. 示例 `shipping.md` 必须包含“运费/包邮”说明，但不能直接写“邮费是多少”作为唯一问题，以验证语义改写召回。

### 完成标准

- 所有切分测试通过。
- 任一普通正文 chunk 首尾均为完整句子。
- 每个表格 chunk 有 header，任一数据行只属于一个 chunk（overlap 不重复表格数据）。

## Task 5：BGE-M3 嵌入封装与 Milvus Store

### 文件

- 新增：`backend/app/knowledge/embedding.py`
- 新增：`backend/app/knowledge/vector_store.py`
- 新增：`backend/tests/test_embedding.py`
- 新增：`backend/tests/test_vector_store.py`

### 步骤

1. 定义 Embedder/VectorStore Protocol 和 Fake，先测试调用方不依赖具体 SDK。
2. 实现 `BgeM3Embedder`：懒加载、进程内单例、在线/离线配置、dense-only、维度/有限数校验、批量编码、异步 `to_thread` 和并发 semaphore。
3. 实现 `MilvusKnowledgeStore.ensure_collection()`：显式 INT64 主键、FLOAT_VECTOR、COSINE、AUTOINDEX、schema/维度不一致时拒绝启动，不能静默重建已有集合。
4. 实现 `upsert/search/delete`；Milvus 只存 chunk ID、向量和可选 embedding version。
5. Fake 测试先覆盖请求结构、顺序、错误包装与超时。
6. 真实集成测试：用临时 collection 插入两个可区分文本，验证相同主键 upsert 后实体数不增加、COSINE 搜索 Top-1 正确、delete 成功；finally 删除临时 collection。

### 完成标准

- Fake/真实 Milvus 测试通过。
- 相同 MySQL ID 重复 upsert 无重复实体。
- 在线调用不阻塞 asyncio 事件循环。

## Task 6：文档/FAQ 入库与向量化补偿 Worker

### 文件

- 新增：`backend/app/services/knowledge_ingestion.py`
- 新增：`backend/app/services/knowledge_vectorization.py`
- 新增：`backend/scripts/build_knowledge.py`
- 新增：`backend/tests/test_knowledge_ingestion.py`
- 新增：`backend/tests/test_knowledge_vectorization.py`

### 步骤

1. 先写测试：Markdown 与现有 FAQ 映射为统一 draft，MySQL 必须先出现 pending，尚未调用 Milvus。
2. 实现文档扫描和 FAQ 全量同步；source key 分别为 `markdown:<path>:<section>:<ordinal>`、`faq:<id>`。
3. 在同一来源批次写完后回填前后指针；重复导入内容不变时 no-op。
4. 先用 Fake Embedder/VectorStore 写状态机测试：pending → vectorizing → vectorized；错误 → failed；租约过期可认领。
5. 增加测试专用故障注入：在第 N 块的 Milvus 调用前、调用后/MySQL 回填前抛出预期异常。
6. 重跑 Worker：确认漏块补齐；Milvus 已成功但未回填的块以相同主键覆盖；attempts 和状态正确。
7. CLI 提供 `ingest`、`vectorize`、`all` 子命令，输出计数但不输出密钥/向量。
8. 用真实 MySQL + Milvus + BGE-M3 跑小规模集成测试。

### 完成标准

- 中断恢复测试通过。
- active chunks 最终全部 vectorized，Milvus 主键无重复。
- `build_knowledge.py all` 可安全重复运行。

## Task 7：历史对话抽取、暂存与游标恢复

### 文件

- 新增：`backend/prompts/conversation_knowledge_extraction_system.txt`
- 新增：`backend/app/services/conversation_mining.py`
- 扩展：`backend/app/repositories/knowledge.py`
- 新增：`backend/tests/test_conversation_mining.py`

### 步骤

1. 定义严格 Pydantic 结构化输出：零到多个 category/questions/answer、is_critical、should_store、理由；questions 必须是非空字符串数组。
2. 先写可见轮次测试：排除 failed 会话、空 assistant、assistant tool call 与 tool payload，只保留 user + 最终 assistant。
3. 写 token 预算与批次测试：完整问答轮不被拆开，游标在暂存事务成功后推进。
4. 使用现有阿里云 ChatOpenAI 和 `with_structured_output`；Prompt 只保存在 `backend/prompts/`。
5. staging source key 使用 conversation ID + 消息 ID 范围；同批重跑 upsert 同一暂存记录。
6. 模拟模型失败、结构校验失败和进程中断，确认游标不会越过未暂存数据。
7. 用 Fake 模型完成默认测试；真实模型只做受控 smoke，避免测试套件依赖外网。

### 完成标准

- 暂存、游标、重试全部幂等。
- 内部 tool JSON 不会被提炼成客服知识。
- 结构化抽取测试通过。

## Task 8：二级全局去重与正式入库

### 文件

- 新增：`backend/prompts/knowledge_deduplication_system.txt`
- 新增：`backend/app/services/knowledge_deduplication.py`
- 新增：`backend/tests/test_knowledge_deduplication.py`

### 步骤

1. 先写精确指纹测试：完全重复、空白/标点差异、questions 顺序差异被识别；答案不同不能在第一级合并。
2. 写语义候选测试：Fake Embedder 返回固定向量，只将超过配置阈值的 pair 交给 LLM。
3. 定义严格 LLM 判定 Schema：`merge | conflict | independent` + reason。
4. 写 merge 测试：合并 questions 并去重；保留既有正式知识主键，内容变化后标 pending。
5. 写 conflict/independent 测试：两条均保留，暂存记录保存判定和原因。
6. 实现 staging 与已有 `knowledge_chunks` 的分批候选；不得把全库一次放入 LLM。
7. 用 Fake 完成确定性测试；用少量真实中文改写问法做 smoke。

### 完成标准

- 只有 LLM 明确 `merge` 才合并。
- 冲突政策不被相似度自动覆盖。
- staging 状态可追踪且重跑不重复入库。

## Task 9：独立 APScheduler 与一次性挖取命令

### 文件

- 新增：`backend/scripts/run_knowledge_scheduler.py`
- 新增：`backend/scripts/mine_conversations.py`
- 新增：`scripts/run-knowledge-scheduler.cmd`
- 新增：`scripts/build-knowledge.cmd`
- 新增：`backend/tests/test_knowledge_scheduler.py`

### 步骤

1. 再次核对 APScheduler 3.11.3 官方 `AsyncIOScheduler`、trigger、`max_instances`、`coalesce`、shutdown 接口。
2. 先用 Fake service 测试调度配置：唯一 job ID、`max_instances=1`、`coalesce=true`、配置化 interval/cron。
3. 独立进程启动时创建数据库、LLM、离线 BGE 与 Milvus runtime，退出时完整关闭。
4. 每轮顺序：mine → deduplicate/promote → vectorize；单阶段失败记录 run 并留待下轮恢复。
5. `mine_conversations.py --once` 调用完全相同的 pipeline。
6. Windows `.cmd` 使用项目解释器，避免 PowerShell execution policy 问题。

### 完成标准

- 调度测试通过。
- 一次性命令与 scheduler 使用同一 pipeline。
- 后端重启不会启动/复制 scheduler。

## Task 10：`query_faq` 切换为 dense 检索

### 文件

- 修改：`backend/app/tools/business.py`
- 修改：`backend/app/main.py`
- 修改：`backend/app/dependencies.py`（如需要）
- 新增：`backend/app/services/knowledge_retrieval.py`
- 修改：`backend/tests/test_business_tools.py`
- 修改：`backend/tests/test_tool_chat_flow.py`
- 新增：`backend/tests/test_knowledge_retrieval.py`

### 步骤

1. 先锁定现有 `FaqKeywordArgs` 与返回 JSON 契约测试，防止接口漂移。
2. 用 Fake Embedder/VectorStore/Repository 测试 Top-K 顺序、阈值、inactive/non-vectorized 过滤、MySQL 批量回源和 no-result。
3. `build_business_tools` 注入 `KnowledgeRetrievalService`；`query_faq` 内部不再调用 `FaqRepository.search_by_question`。
4. 匹配结果将 questions 数组用稳定可读分隔符合并为旧 `question: str`。
5. Milvus/BGE 错误进入现有 ToolExecutor 错误路径；禁止 SQL LIKE fallback。
6. FastAPI lifespan 初始化/预热在线 BGE 与 Milvus collection 校验；关闭时释放引用/连接。
7. 检查工具超时：预热后真实查询应小于当前超时；如不满足，依据实测调整 `.env` 默认 timeout 并记录，不绕过 ToolExecutor。

### 完成标准

- 原工具契约测试通过。
- 旧“退货政策”仍命中；“邮费是多少”语义命中运费文档。
- 工具聊天最终回答基于返回知识，仍为 SSE 流式输出。

## Task 11：FAQ CRUD 与知识同步

### 文件

- 修改：`backend/app/services/faq_crud.py`
- 修改：`backend/app/services/table_crud.py`
- 修改：相关 Repository/依赖
- 修改：`backend/tests/test_faq_crud_service.py`
- 修改：`backend/tests/test_table_crud_service.py`
- 修改：`frontend/src/views/TestLabView.vue`（仅在需要展示同步状态时）

### 步骤

1. 先写两个入口的回归测试：FAQ create/update 在同一 MySQL 事务 upsert `faq:<id>` knowledge chunk 并标 pending；delete 标 inactive/pending_delete。
2. 抽取共享 FAQ→Knowledge 同步函数，禁止两个入口各写一套规则。
3. 保持业务 FAQ 可更新、不可删除；测试 FAQ 可删除的旧权限不变。
4. pending_delete Worker 先删除 Milvus 实体再完成 MySQL 状态；中断可重跑。
5. 若前端展示状态，只增加只读提示，不扩展为知识审核后台。

### 完成标准

- 原 FAQ CRUD 测试全部通过。
- 更新 FAQ 后可观察到 pending，补向量后检索得到新答案。
- 删除测试 FAQ 后 Milvus 不再返回对应知识。

## Task 12：`/kb` 知识库测试台

### 文件

- 新增：`backend/app/api/knowledge_test.py`
- 新增：`backend/app/services/knowledge_test.py`
- 修改：`backend/app/schemas.py` 或新增知识测试 Schema 模块
- 修改：`backend/app/dependencies.py`
- 修改：`backend/app/main.py`
- 新增：`backend/tests/test_knowledge_test_api.py`
- 新增：`backend/tests/test_knowledge_test_service.py`
- 新增：`frontend/src/views/KbView.vue`
- 修改：`frontend/src/router.js`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/api.js`
- 修改：`frontend/src/style.css`

### 步骤

1. 核对 FastAPI 当前稳定版 `UploadFile`、`File`、`Form` 官方接口，增加并锁定 `python-multipart`。
2. 先写上传 API 失败测试：非 `.md`、空文件、非 UTF-8、超限、危险文件名；确认错误脱敏。
3. 写 preview 测试：只调用 splitter，不打开写事务、不调用 Embedder/Milvus；响应包含文件/切片字符数、类型、标题路径、表格、关键条款、questions/category/answer 和前后块序号。
4. 写 ingest 测试：相同上传重复执行 no-op，内容落 MySQL pending；来源固定为 `kb_upload`。
5. 写 vectorize/fault-injection 测试：接口只处理 kb_upload；分别在 Milvus 前、Milvus 后回填前中断，重跑后一致性通过。
6. 写 search/mine-once/status/chunks/staging/runs 测试；复用正式 service，不复制检索、挖取和去重逻辑。
7. 实现 `/v1/tests/knowledge/*` 严格请求响应模型、依赖和 router。
8. 新增 `/kb` 路由和导航；上传使用 FormData，不把文件内容放 localStorage。
9. 实现 01 切片预览、02 入库/向量状态、03 dense 检索、04 对话挖取/二级去重、05 中断恢复、06 运行状态六区；长列表面板内滚动。
10. 文件或类型变化立即清除旧结果；长操作互斥；对话挖取与故障注入执行前确认。
11. Vue test/build 后用真实浏览器验证桌面两列、移动端单列、无横向溢出和五条页面验收流程。

### 完成标准

- `/kb` 能完整观察并验证本章主要功能，不需要进入数据库命令行。
- 选择文件只预览，必须点击明确按钮才写入。
- 页面无法读取任意服务器路径或对非测试台知识做故障注入/批量破坏。
- 后端/API/前端构建与真实浏览器验收通过。

## Task 13：全链路验收、文档、Code Review 与 Finish

### 文件

- 修改：`README.md`
- 新增：`docs/acceptance/ch03-knowledge-base-examples.md`
- 修改：`devHistory/ch03.md`（按阶段即时写入）

### 步骤

1. 更新启动顺序：MySQL/Milvus → migration → 模型准备 → 建库 → backend/frontend → scheduler，并加入 `/kb` 测试台说明。
2. 写出 curl、浏览器、一次性挖取、故障注入与状态核对命令。
3. 真实验收 A：在 `/kb` 上传并预览运费文档，入库/补向量后问“邮费是多少”，确认 `/kb` 命中详情以及聊天页 `query_faq` 工具框和正确运费回答。
4. 真实验收 B：通过 `/kb` 在第 N 块模拟中断；核对 MySQL 存在未完成块；页面点击重跑后所有 active 测试块 vectorized，Milvus ID 无重复。
5. 真实验收 C：修改业务 FAQ → pending → 补向量 → 新答案可召回。
6. 真实验收 D：scheduler 一次性挖取一组专用测试会话，staging、去重、promote、vectorize 状态完整；清理测试数据。
7. 运行完整后端默认测试、真实 MySQL+Milvus 集成测试、隔离迁移测试、Ruff、pip check、Compose config、Vue test/build。
8. Code Review 重点：工具契约、原文权威、无 SQL fallback、元数据未进入向量、双写窗口、租约/幂等、跨进程模型资源、敏感信息、临时测试清理。
9. 立即记录 Code Review 结论；修复所有 P0/P1/P2 后再次全量验证。
10. 立即记录 Finish；关闭仅为验收创建的临时进程/浏览器，保留用户要求运行的基础容器，并报告状态。

### 完成标准

- 两条用户验收标准均由真实 BGE-M3 + Milvus 通过。
- 所有运行命令、自测结果和用户测试案例齐全。
- `devHistory/ch03.md` 包含 brainstorm、用户决策、主设计与 `/kb` 增补设计通过、计划与增补计划通过、每个任务、Code Review、Finish 和所有纠正记录。
