# Chapter 02 Function Calling 验收

## 1. 启动顺序

在项目根目录执行：

```powershell
.\scripts\start-mysql.cmd
.\scripts\migrate-and-seed.cmd
```

分别打开两个终端：

```powershell
.\scripts\run-backend.cmd
```

```powershell
.\scripts\run-frontend.cmd
```

浏览器访问 `http://localhost:5173`，确认右上角 `SYSTEM READY` 下方可选择 `demo-user` 或 `user1`。

## 2. curl 流式对话

先读取模型名：

```powershell
curl.exe http://127.0.0.1:8000/v1/models
```

物流工具示例：

```powershell
curl.exe -N -i http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"qwen3.8-flash","conversation_id":"curl-ch02-logistics","user":"demo-user","messages":[{"role":"user","content":"订单 1001 的物流到哪了"}],"stream":true}'
```

预期结果：

- HTTP 响应头包含 `X-Shop-Assistant-Tool: query_logistics`。
- SSE 先返回 assistant role chunk，随后逐步返回文本 chunk，最后为 `data: [DONE]`。
- 回答引用工具生成的承运商、物流状态、当前位置或预计送达时间，不把演示数据描述为真实接口结果。

FAQ 示例：

```powershell
curl.exe -N -i http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"qwen3.8-flash","conversation_id":"curl-ch02-faq","user":"demo-user","messages":[{"role":"user","content":"退货政策是什么"}],"stream":true}'
```

预期响应头为 `X-Shop-Assistant-Tool: query_faq`，回答包含 seed 中的“签收后 7 天内”等信息。

预期漏召回示例：

```powershell
curl.exe -N -i http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"qwen3.8-flash","conversation_id":"curl-ch02-shipping-gap","user":"demo-user","messages":[{"role":"user","content":"邮费是多少"}],"stream":true}'
```

预期仍选择 `query_faq`，但 SQL `LIKE '%邮费%'` 查不到数据；回答应明确当前无法查询或核实，不能编造政策。这是本章保留的预期结果。

## 3. 浏览器验收案例

依次在聊天页输入：

1. `订单 1001 的物流到哪了`
2. `退货政策是什么`
3. `邮费是多少`

使用工具时，回答正文上方应先出现像素风虚线框；三次分别显示 `query_logistics`、`query_faq`、`query_faq`。第三次回答应明确未查到邮费规则。

点击“新会话”后 conversation ID 会变化，当前用户仍为 `demo-user`。

### 会话选择与历史加载

1. 使用 `demo-user` 完成两轮不同会话，确认左侧 B 按最近活动排序显示会话预览。
2. 点击任一历史会话，右侧 A 应恢复 user/assistant 气泡；带工具的历史还应恢复“调用了 xxx 工具”虚线框。
3. 在选中的旧会话继续提问，刷新后新消息仍属于同一个 conversation ID。
4. 切换为 `user1`，B 不应出现 `demo-user` 的会话；为 `user1` 创建会话后，切回 `demo-user` 也不应看到它。
5. 用错误用户直接读取详情应返回 404：

```powershell
curl.exe -i "http://127.0.0.1:8000/v1/conversations/替换为-user1-会话ID/messages?user=demo-user"
```

本阶段不包含登录认证；`demo-user` / `user1` 用于验证基于 user ID 的演示级归属隔离。

## 4. 数据库核对

将示例 conversation ID 替换为页面显示的实际值：

```powershell
docker compose exec mysql mysql -ushop_assistant -pshop_assistant_dev shop_assistant -e "SELECT id,role,tool_call_id,tool_calls,content FROM messages WHERE conversation_id='web-替换为实际ID' ORDER BY id;"
```

一次成功使用工具的轮次应有四条记录：

1. `user`：用户问题。
2. `assistant`：`content` 可为空，`tool_calls` 保存模型申请。
3. `tool`：保存统一 JSON 结果及相同 `tool_call_id`。
4. `assistant`：最终流式回答。

会话壳核对：

```powershell
docker compose exec mysql mysql -ushop_assistant -pshop_assistant_dev shop_assistant -e "SELECT id,user_id,status,created_at FROM conversations ORDER BY created_at DESC LIMIT 10;"
```

## 5. 自动测试

```powershell
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-acceptance
.\backend\.venv\python.exe -m ruff check --no-cache .\backend
npm --prefix frontend run build
```

真实 MySQL 集成测试：

```powershell
$env:SHOP_ASSISTANT_RUN_MYSQL_TESTS='1'
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-acceptance-mysql
Remove-Item Env:SHOP_ASSISTANT_RUN_MYSQL_TESTS
```

迁移可逆性测试必须显式指向隔离库：

```powershell
$env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL='mysql+asyncmy://shop_assistant:shop_assistant_dev@127.0.0.1:3306/shop_assistant_migration_test'
.\backend\.venv\python.exe -m pytest .\backend\tests\test_migrations.py -q --basetemp=.\backend\.pytest-tmp-acceptance-migrations
Remove-Item Env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL
```

## 6. 2026-09-29 自测结果

- Docker：`shopassistant-mysql-1` 为 `healthy`，映射 `3306:3306`。
- 启动脚本：`start-mysql.cmd` 实测成功；`migrate-and-seed.cmd` 实测输出 `inserted=0, total_demo=3`，证明可重复运行。
- 浏览器物流：模型选择 `query_logistics`，虚线框正确显示，最终回答引用模拟物流结果。
- 浏览器 FAQ：模型选择 `query_faq`，命中“退货政策是什么”。
- 浏览器漏召回：模型选择 `query_faq`，工具返回 `not_found`，最终回答明确无法核实邮费规则。
- 消息落库：同一三轮会话生成 12 条记录，每轮均为 user、assistant tool call、tool result、assistant final，三个 tool call ID 均正确配对。
- 响应式：桌面 1440px 与移动端 390×844 均无横向溢出。
- Alembic：隔离库 downgrade → upgrade 通过；迁移测试必须提供独立 URL，防止误回滚主库。
- 自动化：启用真实 MySQL 后端测试 `69 passed, 1 skipped`；唯一跳过项为必须另给隔离库 URL 的迁移破坏性测试，该测试已单独运行 `1 passed`；Ruff 与 Vue production build 均通过。

## 7. 2026-09-30 会话选择自测结果

- 桌面布局：1280px 视口中 B/A 的 top、bottom 与高度完全一致；移动端 390×844 自动单列且无横向溢出。
- 用户隔离：`user1` 新会话只出现在 `user1` 列表，`demo-user` 列表不包含该 ID；用 `demo-user` 读取该详情返回 404。
- 历史恢复：选择 `demo-user` 的既有三轮工具会话后，完整恢复用户问题、最终回答以及 `query_logistics` / `query_faq` 虚线工具提示，内部 tool payload 未显示。
- 真实模型说明：本次临时后端访问上游时出现 `OpenAIConnectionError`，`user1` 首轮按既有错误处理落为 failed；会话创建、列表刷新和隔离仍完成验证，临时会话随后已清理。历史加载使用数据库中此前成功的真实模型会话完成验收。
- 自动化：默认后端回归 `79 passed, 11 skipped`；启用真实 MySQL 后 `89 passed, 1 skipped`；唯一跳过项为独立迁移库测试。Ruff 与 Vue production build 均通过。
