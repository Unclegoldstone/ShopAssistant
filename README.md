# ShopAssistant：电商智能客服

当前版本包含两个阶段：

- Chapter 01：SSE 流式纯对话、多轮上下文、售后信息结构化抽取。
- Chapter 02：模型通过 Function Calling 自主选择订单、商品、物流、FAQ 或人工工单工具；聊天消息和工具链持久化到 MySQL。

技术栈固定为 Python 3.12、FastAPI、LangChain、SQLAlchemy 2.x、MySQL 8.4（Docker）和 Vue 3。工具链每轮最多执行一次，不包含 Agent Loop 或 RAG。

## 目录

```text
backend/        FastAPI、LangChain、SQLAlchemy、Alembic、测试
  prompts/      可独立编辑的运行时 System Prompt
  scripts/      FAQ 幂等 seed
frontend/       Vue 3 + Vite 像素风页面
scripts/        Windows 启动、迁移脚本
docs/           设计、实施计划、验收案例
devHistory/     Superpowers 流程即时记录
提示词.md       用户开发指令记录，程序不读取、不修改
```

## 1. 环境要求

- Python 3.12
- Node.js `^22.18.0 || >=24.12.0` 与 npm
- Docker Desktop，Linux Engine 已启动
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

编辑根目录 `.env`。除阿里云配置外，Chapter 02 需要以下数据库和工具配置：

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
```

`.env` 已被 Git 排除。不要把真实 API Key 或生产数据库密码写入源码、前端、`.env.example` 或日志。示例 MySQL 密码仅用于本机演示。

运行时提示词位于 `backend/prompts/`；修改后需要重启后端。项目根目录 `提示词.md` 只保存开发指令，程序不会读取或修改它。

## 4. 首次启动

在项目根目录依次执行：

```powershell
.\scripts\start-mysql.cmd
.\scripts\migrate-and-seed.cmd
```

然后分别打开两个终端：

```powershell
.\scripts\run-backend.cmd
```

```powershell
.\scripts\run-frontend.cmd
```

浏览器访问 `http://localhost:5173`。前端提供 `demo-user` 与 `user1` 两个演示用户；聊天页左侧会话栏只显示当前 user ID 的记录，选择后可加载历史并继续对话。

`.cmd` 脚本不受 PowerShell Execution Policy 限制。如果需要运行 PowerShell 版本，可以只为单次命令绕过限制：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1
```

## 5. 手动命令

如果不使用脚本：

```powershell
docker compose up -d mysql
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

内置工具：

- `query_order`：随机演示订单数据。
- `query_product`：随机演示商品数据。
- `query_logistics`：随机演示物流数据。
- `query_faq`：对 MySQL `faq.question` 做 SQL `LIKE` 查询。
- `create_ticket`：幂等创建人工工单并更新会话状态。

使用工具时，响应头 `X-Shop-Assistant-Tool` 给出本轮工具名；SSE 正文仍是 OpenAI chunk 协议。前端会在回答上方显示虚线工具框。

## 7. 自动化验证

```powershell
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-manual
.\backend\.venv\python.exe -m ruff check --no-cache .\backend
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

完整 Chapter 02 演示命令和案例见 `docs/acceptance/ch02-function-calling-examples.md`。

## 8. 常见问题

- **Docker 命令不存在**：确认 Docker Desktop 已启动，并重新打开终端或使用 Docker CLI 绝对路径。
- **MySQL 容器为 exited**：运行 `docker compose up -d mysql`，再用 `docker compose ps` 等待 `healthy`。
- **PowerShell 禁止运行脚本**：优先使用 `.cmd`；无需修改系统级 Execution Policy。
- **401 / invalid_api_key**：检查 API Key 与 base URL 是否属于同一阿里云地域。
- **模型未调用工具**：确认模型支持 Function Calling，并检查 System Prompt 与输入是否明确。
- **“邮费是多少”没有 FAQ 结果**：这是本章故意保留的关键词 `LIKE` 漏召回，用于下一阶段检索升级。
- **curl 看不到流式输出**：使用 `curl.exe -N` 禁用客户端缓冲。供应商可能合并多个 token，应用不会拆字伪装。
