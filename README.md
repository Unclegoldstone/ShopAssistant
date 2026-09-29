# ShopAssistant：电商智能客服纯对话 MVP

Chapter 01 提供一个不含工具调用和 Agent 循环的最小可用系统：FastAPI + LangChain 后端、Vue 3 前端、阿里云百炼 OpenAI 兼容模型、SSE 流式回复、服务端多轮上下文和售后信息结构化抽取。

## 目录

```text
backend/        FastAPI、LangChain、测试与 Python 依赖
  prompts/      可独立编辑的运行时 System Prompt 文本
frontend/       Vue 3 + Vite 演示页面
scripts/        Windows PowerShell 启动脚本
docs/           design、实施计划和 curl 验收案例
devHistory/     Superpowers 全流程即时记录
提示词.md       用户的开发指令记录（程序不读取、不修改）
```

运行时提示词不硬编码在 Python 中：客服角色约束位于 `backend/prompts/customer_service_system.txt`，售后抽取约束位于 `backend/prompts/after_sales_extraction_system.txt`。修改文本后需重启后端使其生效。`backend/app/prompts.py` 仅负责加载文本并通过 `ChatPromptTemplate` 组装消息。

## 1. 环境要求

- Python 3.12（不能使用 3.13 代替验收）
- Node.js `^22.18.0 || >=24.12.0`
- npm
- 有效的阿里云百炼 API Key、同地域 OpenAI 兼容 base URL
- 支持原生 JSON Schema 的阿里云模型，例如 `.env.example` 中的示例型号

本项目的会话保存在单进程内存中。后端必须使用一个 Uvicorn worker；进程重启后会话丢失，这是本章明确接受的 MVP 边界。

## 2. 创建后端环境

在项目根目录运行：

```powershell
conda create --prefix .\backend\.venv python=3.12 pip -y
.\backend\.venv\python.exe -m pip install -e ".\backend[dev]"
```

如果使用标准 Python 3.12 而不是 Conda：

```powershell
python3.12 -m venv .\backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
```

当前已验证依赖的精确版本见 `backend/requirements-lock.txt`。

## 3. 配置 `.env`

```powershell
Copy-Item .env.example .env
```

编辑根目录 `.env`：

```dotenv
MODEL_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.8-flash
MODEL_API_KEY=<your-real-api-key>
HISTORY_MAX_TOKENS=3000
MODEL_TIMEOUT_SECONDS=60
FRONTEND_ORIGIN=http://localhost:5173
```

注意：

- API Key 与 base URL 必须属于同一阿里云地域。
- `MODEL_BASE_URL` 只填写到 `/compatible-mode/v1`，不要追加 `/chat/completions`。
- `MODEL_NAME` 必须支持阿里云原生 JSON Schema，否则售后抽取不会按既定方案工作；系统不会暗自改用工具调用或普通 JSON。
- `.env` 已被 `.gitignore` 排除，不要把真实 Key 写入 `.env.example`、前端或日志。

## 4. 安装并启动前端

```powershell
npm --prefix frontend install
```

分别打开两个终端。推荐使用不受 PowerShell Execution Policy 影响的 `.cmd` 启动器：

```powershell
.\scripts\run-backend.cmd
```

```powershell
.\scripts\run-frontend.cmd
```

也可以完全绕过启动脚本，直接运行：

```powershell
.\backend\.venv\python.exe -m uvicorn app.main:create_app --factory --app-dir .\backend --host 127.0.0.1 --port 8000
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

如果确认只想为当前一次运行绕过 PowerShell 脚本策略，可使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1
```

这不会修改机器或用户的持久化 Execution Policy。

浏览器访问 `http://localhost:5173`。前端通过 `/v1/models` 从后端读取 `.env` 中唯一配置的模型名，因此无需、也不应在前端重复配置模型或 API Key。

## 5. 接口

- `GET /health`：服务健康检查。
- `GET /v1/models`：OpenAI 风格模型列表，本 MVP 只返回 `.env` 中配置的一个模型。
- `POST /v1/chat/completions`：OpenAI Chat Completions 风格 SSE；额外要求 `conversation_id`，且本章每次只提交一个当前 user 消息。
- `POST /v1/after-sales/extract`：返回 `order_id`、`request_type`、`expected_solution` 三个固定 JSON 字段。

完整验收命令见 `docs/acceptance/ch01-curl-examples.md`。

## 6. 自动化验证

Conda 项目环境：

```powershell
.\backend\.venv\python.exe --version
.\backend\.venv\python.exe -m pytest .\backend\tests -q
.\backend\.venv\python.exe -m ruff check --no-cache .\backend\app .\backend\tests
npm --prefix frontend run build
```

标准 venv 将上述 Python 路径替换为 `.\backend\.venv\Scripts\python.exe`。

自动化测试使用 fake model，不消耗阿里云额度。真实联调只有在根目录存在有效 `.env` 时才能执行。

## 7. 常见问题

- **401 / invalid_api_key**：检查 API Key 和 base URL 是否同地域。
- **404**：检查 base URL 是否使用对应工作空间域名，且结尾为 `/compatible-mode/v1`。
- **结构化抽取失败**：确认所选模型位于阿里云官方 JSON Schema 支持列表，且未启用该型号不支持的模式。
- **第二轮没有上下文**：两轮必须复用完全相同的 `conversation_id`，且后端不能多 worker 运行。
- **curl 看不到逐步输出**：使用 `curl.exe -N` 禁用客户端缓冲。应用透传的是上游模型 chunk；供应商可能在一个 chunk 中合并多个 token，应用不会拆字伪装成 token。
- **提示“禁止运行脚本”**：这是 PowerShell Execution Policy。优先使用 `scripts/run-backend.cmd` 与 `scripts/run-frontend.cmd`，或直接运行上面的 Python/npm 命令，无需修改系统级策略。
