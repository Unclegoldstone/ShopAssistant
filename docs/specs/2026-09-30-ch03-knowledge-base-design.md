# Chapter 03：Dense 向量知识库设计

## 1. 目标

将现有 `query_faq(keyword)` 的内部实现从 MySQL `LIKE` 查询升级为：

1. 使用 BGE-M3 将用户问题编码为 dense 向量；
2. 在 Milvus `knowledge` 集合中执行 COSINE Top-K 检索；
3. 根据命中的 MySQL `knowledge_chunks` 原文组织与旧版完全相同的工具返回结构。

工具名称、参数 Schema 与返回字段保持不变。本章不加入关键词召回、混合检索、稀疏向量、ColBERT、重排或 Agent Loop。

## 2. 已确认决策

- 嵌入模型：`BAAI/bge-m3`，通过 FlagEmbedding 在项目 Python 进程本地加载。
- 嵌入模式：仅启用 dense，并使用同一模型封装处理离线语料与在线查询。
- 调度方式：独立 APScheduler 进程；另提供一次性运行命令。
- `questions`：MySQL JSON 字符串数组。
- 去重：规范化指纹精确去重 + BGE-M3 候选召回 + 阿里云 LLM 结构化判定。
- 原文权威源：MySQL `knowledge_chunks`；Milvus 只保存主键和 dense 向量。
- 向量主键：使用 MySQL `knowledge_chunks.id` 作为 Milvus 主键，确保 upsert 幂等。

## 3. 总体架构

```text
Markdown / faq 表 / 历史对话
            │
            ├─ 文档解析与结构切分
            ├─ FAQ 兼容同步
            └─ 对话分批抽取 → knowledge_staging → 二级去重
                                      │
                                      ▼
                         MySQL knowledge_chunks
                         status = pending
                                      │
                         向量化补偿 Worker
                                      │
                       BGE-M3 dense → Milvus upsert
                                      │
                         回填 vector_id/status

用户问题 → BGE-M3 dense → Milvus Top-K → chunk IDs
                                      │
                                      ▼
                         MySQL 读取权威原文
                                      │
                                      ▼
                     query_faq 原有返回结构
```

组件边界：

- `BgeM3Embedder`：模型懒加载、设备选择、批量 dense 编码和维度校验。
- `MarkdownKnowledgeLoader`：读取 `knowledge/source/**/*.md`。
- `StructureAwareMarkdownSplitter`：标题、正文、表格、句子边界和重叠处理。
- `ConversationMiningService`：历史消息分批、LLM 结构化抽取和暂存。
- `KnowledgeDeduplicationService`：二级全局去重。
- `KnowledgeIngestionService`：将文档、FAQ、对话知识幂等写入 MySQL。
- `KnowledgeVectorizationService`：认领待处理块、嵌入、Milvus upsert 和状态回填。
- `MilvusKnowledgeStore`：collection 初始化、upsert、delete、search。
- `KnowledgeRetrievalService`：在线查询向量化、Top-K、阈值和 MySQL 回源。
- 独立 scheduler：使用稳定版 APScheduler 3.11.x `AsyncIOScheduler`，周期运行“对话挖取 → 去重入库 → 补向量”。

FastAPI 与独立 scheduler 是两个 Python 进程，因此不会共享同一个内存模型实例。针对本机 4 GB 显存，默认资源策略为：在线 FastAPI 使用 CUDA、小 batch；离线 scheduler 使用 CPU、小 batch，避免两个 BGE-M3 副本争抢显存。二者仍使用同一个 `BgeM3Embedder` 实现和同一个模型，不引入独立嵌入服务。在线/离线设备可分别配置；如果本机实测仍无法稳定运行，必须暂停并向用户报告，不能自行换模型。

## 4. 文档输入与结构感知切分

### 4.1 文档目录

```text
knowledge/source/
├─ policies/       # content_type=policy
├─ product-faq/    # content_type=product_faq
└─ manuals/        # content_type=after_sales_manual
```

文件相对路径参与生成稳定 `source_key`。首批提供可验收的 Markdown 示例，至少包含退货、运费、商品 FAQ 与售后流程。

### 4.2 标题层级

使用 LangChain `MarkdownHeaderTextSplitter` 跟踪 H1-H6，形成完整标题路径：

```text
售后政策 > 配送规则 > 运费说明
```

- 当前标题作为政策/手册块的 `questions`。
- 上级标题路径作为 `category`。
- 完整路径另存 `section_path`，不进入向量文本。
- 商品 FAQ 文档以问题标题或表格问题列作为真实 `questions`。

### 4.3 超长正文

标题段落超过配置的 chunk 大小时，先使用 `RecursiveCharacterTextSplitter` 按段落、换行和标点递归候选切分，再进行句子边界修正：

- 边界优先落在最近的 `。！？；.!?` 后；
- overlap 由完整句子组成，不按字符硬截；
- 禁止留下半截句子；
- 如果单个没有终止符的句子本身超过上限，保留整句并记录 oversize warning，而不是强行截断。

默认 chunk 大小、overlap 和最大模型长度全部放入 `.env`。

### 4.4 Markdown 表格

识别连续的 Markdown 表格块：

- 第一行表头和第二行分隔符作为固定 header；
- 数据行按完整行装入 chunk；
- 每个表格 chunk 都复制 header；
- 单行超长时整行保留并记录 warning；
- 表格行不与普通正文混切。

### 4.5 关键条款

包含 Markdown `> [!IMPORTANT]` 块的知识 chunk 标记 `is_critical=true`；其他为 false。标记只作为 MySQL 元数据，不拼入嵌入文本。

### 4.6 前后块指针

同一源文件切分完成并写入后，按文档顺序回填 `previous_chunk_id` 与 `next_chunk_id`。指针只用于未来上下文扩展，本章在线检索不自动扩展邻块。

## 5. 统一知识数据

### 5.1 向量文本

只有以下稳定模板进入 BGE-M3：

```text
分类：{category}
问题：{questions 逐项连接}
答案：{answer}
```

`section_path`、`content_type`、`is_critical`、前后块指针、来源、状态和时间均不进入向量。

### 5.2 `knowledge_chunks`

核心字段：

- `id BIGINT`：MySQL 主键，同时作为 Milvus 主键。
- `source_type`：`markdown | faq | conversation`。
- `source_key`：稳定来源键，唯一索引；用于重复执行时找到同一知识。
- `source_revision`：来源内容哈希。
- `category VARCHAR`。
- `questions JSON`：字符串数组。
- `answer LONGTEXT`。
- `section_path JSON`。
- `content_type`：`policy | product_faq | after_sales_manual | conversation_qa`。
- `is_critical BOOLEAN`。
- `previous_chunk_id / next_chunk_id`：可空自关联。
- `vector_status`：`pending | vectorizing | vectorized | failed | pending_delete`。
- `vector_id VARCHAR`：Milvus 返回/确认的主键。
- `embedding_model / embedding_version`。
- `content_fingerprint`：规范化内容指纹。
- `vector_attempts / vector_error / vectorizing_started_at`。
- `is_active / created_at / updated_at`。

同一 `source_key` 内容未变化时不重复写；内容变化时更新原行、清空旧错误并重新标记 `pending`，从而保留稳定主键。

### 5.3 `knowledge_staging`

保存 LLM 从对话中抽取、尚未正式入库的回答对：

- 来源 conversation/message 范围；
- category/questions/answer；
- 抽取模型和原始结构化结果；
- 规范化指纹；
- 状态 `extracted | exact_duplicate | candidate | merged | conflict | promoted | rejected | failed`；
- 重复目标、LLM 判定理由、错误、批次 ID 和时间。

conversation/message 范围建立唯一键，任务中断重跑不会重复暂存。

### 5.4 `knowledge_mining_runs`

记录调度批次、消息游标、状态、开始/结束时间、处理数量和脱敏错误摘要。游标只在对应暂存事务成功后推进。

## 6. 历史对话知识挖取

1. scheduler 按配置周期触发，通过 APScheduler 3.11.x 的 `max_instances=1` 与 `coalesce=true` 禁止同一任务重叠堆积。
2. 从上次成功游标继续，按消息 ID/会话分批读取。
3. 排除 `failed` 会话、空 assistant、tool payload 与纯工具申请；仅保留用户问题及最终 assistant 文本。
4. 按 token 预算将可见轮次分批喂给现有阿里云模型。
5. 使用 `with_structured_output` 输出零到多个 `category/questions/answer`，并附带是否关键、是否值得沉淀等判定。
6. 先写 `knowledge_staging`，同一来源范围幂等。
7. 对本轮 staging 与全部现有知识执行二级去重。
8. 可合并项合并 questions；冲突项保留并记录；通过项写入 `knowledge_chunks`，状态为 `pending`。

调度器与一次性 CLI 调用相同 service，避免两套逻辑。

## 7. 二级去重

### 7.1 精确层

对 Unicode、空白、标点和 questions 顺序进行规范化，计算 `category + questions + answer` 的 SHA-256。命中相同指纹时直接标记重复。

### 7.2 语义层

1. BGE-M3 为暂存项生成临时 dense 向量。
2. 在本轮 staging 与已有知识中找相似候选。
3. 达到配置候选阈值的 pair 分批提交阿里云 LLM。
4. LLM 结构化返回 `merge | conflict | independent` 和原因。
5. `merge`：合并、规范化并去重 questions；`conflict/independent`：分别保留。

向量相似度只负责缩小候选范围，不能单独决定删除，避免误合并不同版本政策。

## 8. MySQL → Milvus 双写与恢复

### 8.1 正常流程

1. 在 MySQL 事务中 upsert `knowledge_chunks`，设置 `vector_status=pending` 并提交。
2. Worker 小批量认领 `pending`、可重试 `failed` 或租约过期的 `vectorizing` 记录。
3. 提交短事务，将记录置为 `vectorizing`、记录开始时间和 attempts。
4. 在事务外调用 BGE-M3，避免持有数据库锁。
5. 使用 `knowledge_chunks.id` 对 Milvus 执行 `upsert`。
6. Milvus 成功后回写相同 `vector_id`，状态改为 `vectorized`。

### 8.2 中断恢复

- MySQL 成功、Milvus 未写：记录仍为 pending/过期 vectorizing，下次捡起。
- Milvus 成功、MySQL 未回填：下次用相同主键再次 upsert，只覆盖同一实体，不产生重复向量。
- 内容更新：稳定主键不变，新向量 upsert 覆盖旧向量。
- 多 Worker：通过 MySQL 认领状态与租约避免同时处理同一批；Milvus 主键仍提供最终幂等保护。
- 删除：先将 MySQL 标记 `pending_delete/is_active=false`，Milvus 删除成功后再完成状态，不先丢失权威记录。

验收中通过故障注入参数在指定数量后主动中断，随后重跑并核对所有 active chunk 均为 `vectorized`、Milvus 主键集合无重复。

## 9. Milvus 集合

集合名从 `.env` 读取，默认 `knowledge`。最小 Schema：

- `chunk_id INT64`：primary key，`auto_id=false`。
- `embedding FLOAT_VECTOR`：维度从 BGE-M3 实际输出校验，预期 1024。
- 可选 `embedding_version VARCHAR`：用于诊断，不参与相似度。

使用 COSINE 与 AUTOINDEX。Milvus 不复制原文和业务元数据；搜索只返回 chunk IDs 与 score，再回 MySQL 读取 active、vectorized 权威记录。

Docker Compose 增加官方 Milvus Standalone 所需的 Milvus、etcd 和对象存储服务及命名 volume、healthcheck；MySQL 保持现有服务与数据卷。

## 10. 在线检索与 `query_faq` 兼容

1. `keyword` 原样作为语义查询文本。
2. BGE-M3 在工作线程中执行，避免阻塞 FastAPI 事件循环，并由 semaphore 限制并发。
3. Milvus COSINE Top-K，Top-K、最低分数和超时由 `.env` 控制。
4. 按 Milvus 顺序批量查询 MySQL `knowledge_chunks`，过滤 inactive/non-vectorized。
5. 无结果时继续抛出既有 `ToolNotFoundError`。
6. 有结果时映射为现有结构：

```json
{
  "keyword": "邮费是多少",
  "matches": [
    {
      "question": "邮费怎么计算 / 什么情况下包邮",
      "answer": "……",
      "category": "配送规则"
    }
  ]
}
```

工具名、参数和顶层/明细字段均不变化。

## 11. FAQ 编辑兼容

现有功能测试页仍可管理 `faq`：

- `faq` 不再作为在线查询源。
- FAQ 新增/修改时，在同一 MySQL 事务中 upsert `source_key=faq:{id}` 的知识块并标记 pending。
- FAQ 删除时将对应知识块标记 inactive/pending_delete，等待 Milvus 清理。
- 初次建库命令会将现有 FAQ 全量幂等同步到知识表。

因此此前的业务条款修改能力保留，但更新内容只有在补向量任务成功后才进入在线检索；测试页/命令输出应展示同步状态。

## 12. 配置

`.env` 至少增加：

- BGE-M3 模型名/本地路径、在线/离线 device、FP16、batch size、max length；
- Milvus URI/token/database/collection；
- Top-K、最低 COSINE score、请求超时；
- chunk size、overlap；
- 向量批大小、租约、重试上限；
- 对话挖取周期、批大小、token 预算；
- 语义去重候选阈值。

密钥和 token 不写入仓库；`.env.example` 只给安全默认值/占位符。

## 13. 错误与可观测性

- 模型、Milvus、MySQL 错误只记录类型、chunk/run ID 和阶段，不打印密钥或完整连接串。
- 建库 CLI 输出文档数、chunk 数、staging 数、去重数、pending/vectorized/failed 数。
- scheduler 每轮记录 run 状态与游标。
- 在线 Milvus 不可用时，`query_faq` 走既有工具错误处理，不回退到 SQL LIKE，避免违反 dense 单路范围。

## 14. 测试与验收

### 自动化

- 标题路径、政策 questions/category 映射。
- 递归长文切分、完整句子 overlap、无半句。
- 大表格按行切分且每块含 header。
- questions JSON 与向量文本严格只包含三个业务字段。
- 对话可见轮次、分批结构化抽取、暂存幂等和游标恢复。
- 指纹去重、语义候选、LLM merge/conflict/independent。
- MySQL 先写 pending、Milvus 成功后 vectorized。
- 在 Milvus upsert 前后故障注入并重跑，无漏块/重复主键。
- `query_faq` 入参/出参兼容测试。
- FAQ CRUD 同步 pending/pending_delete。

### 真实集成验收

1. Docker 中 MySQL 与 Milvus Standalone 全部 healthy。
2. 导入包含“运费说明”的 Markdown 与现有 FAQ。
3. 运行建库，MySQL active 块全部 vectorized。
4. 浏览器询问“邮费是多少”，`query_faq` 命中“运费/包邮”知识并正确回答。
5. 使用故障注入中断建库，再次运行后所有漏向量块补齐，Milvus 无重复主键。
6. 更新一条业务 FAQ，状态变 pending；补向量后再次检索得到新内容。

## 15. 本章不做

- BM25/关键词召回、hybrid search、sparse、ColBERT、reranker。
- 自动扩展前后块、生成式 RAG 链或多工具循环。
- 用户登录与权限系统。
- 知识审核后台、复杂版本发布/回滚 UI。

## 16. 官方接口依据

- LangChain `MarkdownHeaderTextSplitter`、`RecursiveCharacterTextSplitter`。
- FlagEmbedding 官方 BGE-M3 dense 编码接口。
- Milvus `MilvusClient` 自定义集合、COSINE、`search`、`upsert` 和 Docker Compose Standalone。
- SQLAlchemy 2.0 asyncio transaction/session。
- APScheduler 3.11.x `AsyncIOScheduler`、Interval/Cron trigger 与 `max_instances`。
