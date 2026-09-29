# Chapter 01 纯对话 MVP 实施计划

日期：2026-09-28  
状态：已完成（2026-09-28；真实阿里云 smoke test 待用户提供 `.env`）  
依据：`docs/specs/2026-09-28-ch01-pure-chat-design.md`

## 执行原则

- 严格执行 Python 3.12 + FastAPI + LangChain + Vue 3，不替换技术栈。
- 后端按 TDD 循环实施：先写会失败的测试，确认失败原因正确，再写最小实现，随后重构并运行相关测试。
- 每完成一个任务，立即把测试结果、关键取舍和用户纠正记录到 `devHistory/ch01.md`，不在最后补写。
- 具体库/API 已先核对官方文档；实现中若遇到未覆盖的 API，再查对应官方文档后继续。
- 不调用真实模型完成自动化测试；只有发现有效 `.env` 时才执行真实阿里云 smoke test。
- 当前目录不是 Git 仓库。本计划不擅自初始化 Git 或伪造逐任务 commit；以计划文档、即时开发日志和测试输出留痕。如用户另行要求 Git，再单独执行。

## 已确认环境

- 项目解释器：`backend/.venv/python.exe`（独立 Conda 前缀，Python 3.12.13）。
- 初次使用现有 3.12.14 解释器创建标准 venv 时，pytest 的 cache provider 在该磁盘退出阶段卡住；已改用本机 Python 3.12 环境离线克隆成独立项目环境，不污染现有 Conda 环境，并在 pytest 中禁用文件缓存。
- Node.js v24.20.0、npm 11.19.0；满足当前 Vue/Vite 工具链要求。

## Task 1：建立项目骨架、Python 3.12 环境与配置契约

新增 `.gitignore`、`.env.example`、`backend/pyproject.toml`、`backend/app/__init__.py`、`backend/app/config.py`、`backend/tests/test_config.py`、`backend/tests/conftest.py`。

实施步骤：

1. 用指定 Python 3.12 创建 `backend/.venv`。
2. 在 `pyproject.toml` 声明 FastAPI、Uvicorn、LangChain、langchain-openai、pydantic-settings，以及 pytest、pytest-asyncio、httpx、ruff。
3. 安装依赖并记录解析后的精确版本，生成冻结文件供复现。
4. 先写配置测试：缺少模型配置时失败；`.env` 正确加载；token 预算和 timeout 必须为正数；SecretStr 不泄露到 repr。运行确认 RED。
5. 实现 `Settings(BaseSettings)`，通过 `SettingsConfigDict` 加载根目录 `.env`。
6. 运行测试确认 GREEN，再执行 Ruff。

验证命令：

```powershell
backend\.venv\python.exe -m pytest backend\tests\test_config.py -q
backend\.venv\python.exe -m ruff check --no-cache backend
```

## Task 2：定义 API schema、PromptTemplate 与模型工厂

新增 `backend/app/schemas.py`、`backend/app/prompts.py`、`backend/app/model_factory.py`、`backend/prompts/*.txt` 和对应三组测试。运行时 Prompt 文本在 `backend/prompts/*.txt` 中独立管理，`backend/app/prompts.py` 只负责加载并组装 `ChatPromptTemplate`；`提示词.md` 是用户的开发指令记录，不属于程序 Prompt 管理范围。

实施步骤：

1. 先写 schema 测试：对话只能有一个非空 user 消息；`stream` 只能为 true；conversation ID 有边界；模型名必填；结构化结果三个字段始终存在并可为 null。
2. 先写 Prompt 测试：`ChatPromptTemplate` 固定包含 SystemMessage、`MessagesPlaceholder("history")` 和当前 human 模板，System Prompt 覆盖已批准约束。
3. 先写模型工厂测试：mock 断言 `ChatOpenAI` 收到 model/base_url/api_key/timeout，且 API Key 不进入日志或 repr。
4. 运行确认 RED，再实现 schema、两个独立 PromptTemplate 与单一模型工厂。
5. 验证运行时 Prompt 文本从 `backend/prompts/*.txt` 加载并由 `ChatPromptTemplate` 组装，不读取或修改 `提示词.md`。
6. 运行任务测试确认 GREEN，再执行 Ruff。

## Task 3：实现内存会话、并发控制和 token 预算裁剪

新增 `backend/app/conversation_store.py` 与 `backend/tests/test_conversation_store.py`。

实施步骤：

1. 先写测试：同会话连续、不同会话隔离、成功提交完整 Human/AI 对、清空会话、最近完整轮次被保留、过长当前消息失败、同会话请求锁串行化。
2. 直接验证 LangChain `trim_messages` 结果，避免自制 token 算法。运行确认 RED。
3. 实现内存字典和每会话异步锁；使用 `trim_messages(strategy="last", token_counter="approximate", start_on="human", allow_partial=False)`。
4. 对历史预算和当前输入预算分开检查，避免当前输入被静默裁掉。
5. 运行任务测试确认 GREEN，再执行全量后端测试。

## Task 4：实现聊天服务与 OpenAI SSE 编码

新增 `backend/app/services/chat.py`、`backend/app/sse.py`、`backend/tests/fakes.py` 及对应测试。

实施步骤：

1. 建立 fake streaming chat model，可记录收到的消息并按指定 chunk/异常输出。
2. 先写测试：首事件包含 assistant role；每个上游文本 chunk 立即成为 content chunk；末尾有 stop chunk 与 `[DONE]`；中文 JSON 不转义；第二轮包含首轮上下文；失败流不写历史；成功流完整落历史。运行确认 RED。
3. 实现 SSE 编码器和 `ChatService.stream`：模板格式化 → 上游 `astream` → 累积完整答复 → 成功后提交历史。
4. 流开始后的异常转换为脱敏 error SSE 后结束；日志不记录密钥。
5. 运行任务测试确认 GREEN，再执行 Ruff。

## Task 5：实现 FastAPI 应用与流式对话接口

新增 `backend/app/dependencies.py`、`backend/app/api/chat.py`、`backend/app/main.py` 与接口测试。

实施步骤：

1. 先写接口测试：`GET /health`；正确的 `text/event-stream` 与禁缓存/禁代理缓冲头；SSE 终止符；模型不匹配、空消息、非法 role、`stream=false` 返回 4xx；可用依赖覆盖注入 fake service。运行确认 RED。
2. 使用 FastAPI lifespan 构造设置、模型、store 和 service，避免 import 时读取真实密钥。
3. 实现 `POST /v1/chat/completions` 与 `StreamingResponse`；CORS 只允许 `.env` 指定的前端 origin。
4. 运行接口测试和全量后端测试确认 GREEN。

## Task 6：实现 `with_structured_output` 售后抽取

新增 `backend/app/services/extraction.py`、`backend/app/api/extraction.py` 与两组测试。

实施步骤：

1. 先写服务测试：必须以 `AfterSalesInfo`、`method="json_schema"` 和 `strict=True` 调用模型的 `with_structured_output`；输入经独立 PromptTemplate 发送；返回 Pydantic 对象。
2. 先写接口测试：固定返回三个字段；缺失信息为 null；空文本返回 4xx；上游错误脱敏。运行确认 RED。
3. 实现 `ExtractionService` 和 `POST /v1/after-sales/extract`。
4. 不设置可能截断 JSON 的 `max_tokens`，不提供工具调用或普通 JSON 降级路径。
5. 运行任务测试、全量测试和 Ruff 确认 GREEN。

## Task 7：建立 Vue 3 最小演示前端

生成 `frontend/package.json`、lockfile、Vite 配置、HTML、`src/main.js`、`src/App.vue`、`src/api.js` 和样式。

实施步骤：

1. 按 Vue 官方推荐的 Vue 3 + Vite 最小模板创建项目，不添加 Router、Pinia 或 UI 框架。
2. 将 SSE 解码独立到 `api.js`：处理跨 chunk UTF-8、跨 chunk 行边界、多个 data 事件、`[DONE]` 与 error event。
3. 实现聊天区：生成/持久化 conversation ID、流式追加、请求期间禁用重复提交、清空时生成新 ID。
4. 实现结构化抽取区，格式化显示 JSON/null。
5. 通过 Vite proxy 访问后端，绝不把模型 Key 放入前端。
6. 执行 `npm --prefix frontend install` 和 `npm --prefix frontend run build`，修复后重跑直至通过。

## Task 8：文档、启动脚本与 curl 验收案例

新增 `README.md`、`scripts/run-backend.ps1`、`scripts/run-frontend.ps1`、`docs/acceptance/ch01-curl-examples.md`。

实施步骤：

1. README 写清 Python 3.12、安装、`.env`、单 worker 限制、前后端启动、接口与故障排查。
2. 启动脚本使用项目 `.venv`，后端固定单 worker。
3. 提供三组可复制命令：首轮 SSE、复用 ID 第二轮、售后结构化抽取；Windows 使用 `curl.exe -N`。
4. 记录 API Key/base URL 同地域以及模型必须支持 JSON Schema。
5. 检查 README 命令与实际路径一致。

## Task 9：全量验证、真实 smoke test 与 code review

1. 确认解释器为 Python 3.12；运行全量 pytest 与 Ruff。
2. 运行前端 production build。
3. 用 fake/测试环境执行本地 API smoke test，保存实际状态码、SSE 片段和 JSON 结果摘要。
4. 若根目录存在有效 `.env`，启动真实后端并执行三项 curl；否则明确记录“未执行真实模型联调”及缺失条件。
5. 执行 code review：逐项核对 spec、协议、并发/失败语义、密钥风险、测试盲点与超范围功能；先修复问题再复验。
6. 每个结论即时写入 `devHistory/ch01.md`；无高优先级问题后记录 finish。

最终命令：

```powershell
backend\.venv\python.exe --version
backend\.venv\python.exe -m pytest backend\tests -q
backend\.venv\python.exe -m ruff check --no-cache backend
npm --prefix frontend run build
```

## 计划评审门槛

只有用户明确批准本计划后才开始 Task 1。任何评审纠正会先同步到本计划和 `devHistory/ch01.md`，再请求复审。
