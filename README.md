# ShopAssistant：电商智能客服

当前版本包含三个阶段：

- Chapter 01：SSE 流式纯对话、多轮上下文、售后信息结构化抽取。
- Chapter 02：模型通过 Function Calling 自主选择订单、商品、物流、FAQ 或人工工单工具；聊天消息和工具链持久化到 MySQL。
- Chapter 03：`query_faq` 保持原工具契约，内部升级为本地 BGE-M3 dense 向量检索；MySQL 保存权威原文，Milvus 保存向量，并提供 Markdown 建库、历史对话挖取、二级去重、失败补偿和 `/kb` 验证页。

技术栈固定为 Python 3.12、FastAPI、LangChain、SQLAlchemy 2.x、MySQL 8.4（Docker）、Milvus Standalone、BGE-M3 和 Vue 3。工具链每轮最多执行一次，不包含 Agent Loop；知识检索仅使用 dense 向量，不含关键词混合检索和重排。

## 目录

```text
backend/        FastAPI、LangChain、SQLAlchemy、Alembic、测试
  prompts/      可独立编辑的运行时 System Prompt
  scripts/      FAQ seed、知识建库、对话挖取和定时调度入口
frontend/       Vue 3 + Vite 像素风页面
scripts/        Windows 启动、迁移脚本
knowledge/      Markdown 知识原文
docs/           设计、实施计划、验收案例
devHistory/     Superpowers 流程即时记录
提示词.md       用户开发指令记录，程序不读取、不修改
```

## 1. 环境要求

- Python 3.12
- Node.js `^22.18.0 || >=24.12.0` 与 npm
- Docker Desktop，Linux Engine 已启动（MySQL、etcd、MinIO、Milvus）
- NVIDIA CUDA 环境（在线 BGE 默认使用 `cuda`；离线建库可在 `.env` 改为 `cpu`）
- 有效的阿里云百炼 API Key、同地域 OpenAI 兼容 base URL
- 支持 Function Calling 和原生 JSON Schema 的阿里云模型

## 2. 安装依赖

Conda 环境：

```powershell
conda create --prefix .\backend\.venv python=3.12 pip -y
.\backend\.venv\python.exe -m pip install -e ".\backend[dev]"
npm --prefix frontend install
```

标准 Python venv：

```powershell
python3.12 -m venv .\backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
npm --prefix frontend install
```

已验证依赖精确版本见 `backend/requirements-lock.txt`。

## 3. 配置

```powershell
Copy-Item .env.example .env
```

编辑根目录 `.env`。除阿里云配置外，需要以下数据库、BGE-M3、Milvus 和知识库配置：

```dotenv
MODEL_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.8-flash
MODEL_API_KEY=<your-real-api-key>

DATABASE_URL=mysql+asyncmy://shop_assistant:shop_assistant_dev@127.0.0.1:3306/shop_assistant
MYSQL_DATABASE=shop_assistant
MYSQL_USER=shop_assistant
MYSQL_PASSWORD=shop_assistant_dev
MYSQL_ROOT_PASSWORD=shop_assistant_root_dev
MYSQL_PORT=3306

HISTORY_MAX_TOKENS=3000
MODEL_TIMEOUT_SECONDS=60
TOOL_TIMEOUT_SECONDS=5
TOOL_MAX_ATTEMPTS=2
FRONTEND_ORIGIN=http://localhost:5173

BGE_MODEL_NAME_OR_PATH=D:\Projects\ShopAssistant\.model-cache\huggingface\models--BAAI--bge-m3\snapshots\<snapshot-id>
BGE_ONLINE_DEVICE=cuda
BGE_OFFLINE_DEVICE=cpu
BGE_USE_FP16=true
BGE_BATCH_SIZE=2
BGE_MAX_LENGTH=1024

MILVUS_URI=http://127.0.0.1:19530
MILVUS_TOKEN=root:Milvus
MILVUS_DATABASE=default
MILVUS_COLLECTION=knowledge

KNOWLEDGE_TOP_K=5
KNOWLEDGE_MIN_SCORE=0.5
KNOWLEDGE_CHUNK_SIZE=1000
KNOWLEDGE_CHUNK_OVERLAP=120
KNOWLEDGE_VECTOR_BATCH_SIZE=4
KNOWLEDGE_VECTOR_LEASE_SECONDS=300
KNOWLEDGE_VECTOR_MAX_ATTEMPTS=3
KNOWLEDGE_MINING_INTERVAL_MINUTES=60
KNOWLEDGE_MINING_BATCH_SIZE=5
KNOWLEDGE_MINING_TOKEN_BUDGET=6000
KNOWLEDGE_DEDUP_CANDIDATE_SCORE=0.9
```

`.env` 已被 Git 排除。不要把真实 API Key 或生产数据库密码写入源码、前端、`.env.example` 或日志。示例 MySQL 密码仅用于本机演示。

运行时提示词位于 `backend/prompts/`；修改后需要重启后端。项目根目录 `提示词.md` 只保存开发指令，程序不会读取或修改它。

## 4. 首次启动

在项目根目录依次执行：

```powershell
docker compose up -d mysql etcd minio milvus
docker compose ps
.\scripts\migrate-and-seed.cmd
.\scripts\build-knowledge.cmd
```

然后分别打开两个终端：

```powershell
.\scripts\run-backend.cmd
```

```powershell
.\scripts\run-frontend.cmd
```

浏览器访问 `http://localhost:5173`。前端提供 `demo-user` 与 `user1` 两个演示用户；聊天页左侧会话栏只显示当前 user ID 的记录，选择后可加载历史并继续对话。

知识库测试台位于 `http://localhost:5173/#/kb`：选择 Markdown 只做预览；点击“明确入库”才写 MySQL；随后可验证向量补偿、dense 检索、对话挖取/去重、故障注入恢复和运行状态。若要持续挖取历史对话，另开终端执行：

```powershell
.\scripts\run-knowledge-scheduler.cmd
```

`.cmd` 脚本不受 PowerShell Execution Policy 限制。如果需要运行 PowerShell 版本，可以只为单次命令绕过限制：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1
```

## 5. 手动命令

如果不使用脚本：

```powershell
docker compose up -d mysql
docker compose up -d etcd minio milvus
Set-Location backend
.\.venv\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\python.exe -m scripts.seed_demo_data
.\.venv\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

另一个终端：

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

如果 `docker` 不在 Codex 或新终端的 PATH 中，本机 Docker CLI 默认位置可能是：

```text
C:\Users\<用户名>\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe
```

## 6. 接口和工具

- `GET /health`：服务健康检查。
- `GET /v1/models`：返回 `.env` 配置的模型。
- `POST /v1/chat/completions`：OpenAI Chat Completions 风格 SSE；额外使用 `conversation_id` 和默认 `user="demo-user"`。
- `GET /v1/conversations?user=...`：按 user ID 获取最近会话摘要。
- `GET /v1/conversations/{conversation_id}/messages?user=...`：校验会话归属后返回 UI 可见历史；跨用户访问返回 404。
- `POST /v1/after-sales/extract`：固定 JSON 字段抽取。
- `/v1/tests/knowledge/*`：`/kb` 页面使用的预览、入库、向量补偿、检索、共享 pipeline 与状态接口。

内置工具：

- `query_order`：随机演示订单数据。
- `query_product`：随机演示商品数据。
- `query_logistics`：随机演示物流数据。
- `query_faq`：BGE-M3 将问题向量化，Milvus dense Top-K 检索，再按 ID 回 MySQL 读取权威原文；工具入参/出参保持不变，无 SQL LIKE fallback。
- `create_ticket`：幂等创建人工工单并更新会话状态。

使用工具时，响应头 `X-Shop-Assistant-Tool` 给出本轮工具名；SSE 正文仍是 OpenAI chunk 协议。前端会在回答上方显示虚线工具框。

## 7. 自动化验证

```powershell
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-manual
.\backend\.venv\python.exe -m ruff check --no-cache .\backend
npm --prefix frontend test
npm --prefix frontend run build
```

需要 Docker MySQL 的集成测试默认跳过。显式运行：

```powershell
$env:SHOP_ASSISTANT_RUN_MYSQL_TESTS='1'
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-mysql
Remove-Item Env:SHOP_ASSISTANT_RUN_MYSQL_TESTS
```

迁移的 downgrade/upgrade 测试有独立保护开关，必须明确提供隔离数据库，不能指向包含开发数据的 `shop_assistant` 主库：

```powershell
$env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL='mysql+asyncmy://shop_assistant:shop_assistant_dev@127.0.0.1:3306/shop_assistant_migration_test'
.\backend\.venv\python.exe -m pytest .\backend\tests\test_migrations.py -q --basetemp=.\backend\.pytest-tmp-migrations
Remove-Item Env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL
```

完整 Chapter 02 演示命令和案例见 `docs/acceptance/ch02-function-calling-examples.md`；Chapter 03 见 `docs/acceptance/ch03-knowledge-base-examples.md`。

## 8. 常见问题

- **Docker 命令不存在**：确认 Docker Desktop 已启动，并重新打开终端或使用 Docker CLI 绝对路径。
- **MySQL 容器为 exited**：运行 `docker compose up -d mysql`，再用 `docker compose ps` 等待 `healthy`。
- **PowerShell 禁止运行脚本**：优先使用 `.cmd`；无需修改系统级 Execution Policy。
- **401 / invalid_api_key**：检查 API Key 与 base URL 是否属于同一阿里云地域。
- **模型未调用工具**：确认模型支持 Function Calling，并检查 System Prompt 与输入是否明确。
- **BGE 启动时尝试联网**：确认 `BGE_MODEL_NAME_OR_PATH` 指向本地完整 snapshot，而不是只写 Hugging Face 模型名。
- **BGE CUDA 内存不足**：减小 `BGE_BATCH_SIZE`；离线建库可将 `BGE_OFFLINE_DEVICE=cpu`，在线配置仍按需求使用 CUDA。
- **Milvus 不健康**：运行 `docker compose ps`，确认 etcd、MinIO、Milvus 均为 healthy，再启动后端。
- **历史对话挖取超时**：保持 `KNOWLEDGE_MINING_BATCH_SIZE=5`，失败 run 不推进游标，下次调度会安全重试。
- **curl 看不到流式输出**：使用 `curl.exe -N` 禁用客户端缓冲。供应商可能合并多个 token，应用不会拆字伪装。
