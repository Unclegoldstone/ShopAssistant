# Chapter 03 知识库验收手册

本章把 `query_faq` 从 SQL LIKE 升级为 BGE-M3 + Milvus 的单路 dense 语义检索。MySQL `knowledge_chunks` 是原文权威源；Milvus 只保存以 MySQL 主键为显式 ID 的向量。

## 1. 启动顺序

在项目根目录执行：

```powershell
docker compose up -d mysql etcd minio milvus
docker compose ps
.\scripts\migrate-and-seed.cmd
.\scripts\build-knowledge.cmd
```

确认四个服务均为 `healthy` 后，分别启动后端、前端和可选调度器：

```powershell
.\scripts\run-backend.cmd
.\scripts\run-frontend.cmd
.\scripts\run-knowledge-scheduler.cmd
```

后端启动会加载本地 BGE-M3 并预热；不要同时启动多个后端 worker，否则每个进程都会各自占用一份模型显存。

## 2. Markdown 建库与 `/kb` 页面

打开 `http://localhost:5173/#/kb`，选择 `knowledge/source/policies/shipping.md`。

1. 点击“只读预览”：页面应显示文件字节数、字符数、切片数，以及每片的类型、标题路径、字符数、questions、关键条款标记和前后块指针；此时不写库。
2. 点击“明确入库”：MySQL 中出现 `kb_upload:` 来源且状态为 `pending`。
3. 点击“执行向量补偿”：结果中的 `vectorized` 大于 0，状态转为 `vectorized`。
4. 在 dense 检索输入“邮费是多少”：应召回“运费规则”，即使原文没有完全相同的问法。

离线目录建库可以安全重跑：

```powershell
Set-Location backend
.\.venv\python.exe -m scripts.build_knowledge ingest
.\.venv\python.exe -m scripts.build_knowledge vectorize
```

## 3. 聊天页验收

浏览器回到“客服对话”，输入：

```text
邮费是多少？请查询知识库后回答。
```

预期：回答上方虚线框显示 `query_faq`；最终回答引用召回到的运费原文。若权威源中同时存在冲突条款，模型应明确提示以当前结算页或最新条款为准，不擅自覆盖任何一条原文。

也可直接验证 SSE 与工具响应头：

```powershell
curl.exe -N -i http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"<.env 中 MODEL_NAME>","conversation_id":"ch03-demo","user":"demo-user","stream":true,"messages":[{"role":"user","content":"邮费是多少？请查询知识库后回答。"}]}'
```

预期响应头包含 `X-Shop-Assistant-Tool: query_faq`，正文以 `data: [DONE]` 结束。

## 4. 中断与补偿验收

在 `/kb` 先上传一份尚未入库的 Markdown 并明确入库，然后点击“回填前中断”。

- 第一次结果至少有一条 `failed`；MySQL 仍保留权威原文，Milvus 使用 MySQL ID，重复 upsert 不产生重复主键。
- 再点击“执行向量补偿”；failed 块应被重新认领并转为 `vectorized`，`vector_attempts` 增加。
- “MILVUS 前中断”同样可以重跑收敛。

故障注入严格限制为 `/kb` 的 `kb_upload:` 来源，不会批量破坏正式 Markdown、FAQ 或对话知识。

## 5. FAQ 更新验收

在“功能测试 → FAQ 数据库操作”新增一条测试条款，随后修改答案。`knowledge_chunks` 中稳定的 `faq:<id>` 记录应保留主键、替换权威原文并回到 `pending`。运行一次共享流程或离线 `vectorize` 后，新问法应召回新答案；删除测试 FAQ 后，块转为 inactive/pending_delete，下一次 Worker 会幂等删除 Milvus 向量。

## 6. 对话挖取与定时任务

一次性执行完整流程：

```powershell
Set-Location backend
.\.venv\python.exe -m scripts.mine_conversations
```

流程固定为 `mine → deduplicate → vectorize`。抽取结果先进入 `knowledge_staging`，再做内容指纹精确去重和 BGE 候选 + LLM 判定的二级去重，最后才写权威知识并补向量。失败 run 不推进 completed cursor，可直接重跑。

持续任务使用：

```powershell
.\scripts\run-knowledge-scheduler.cmd
```

## 7. 自动化验收

```powershell
$env:SHOP_ASSISTANT_RUN_MYSQL_TESTS='1'
$env:RUN_MILVUS_TESTS='1'
.\backend\.venv\python.exe -m pytest .\backend\tests -q --basetemp=.\backend\.pytest-tmp-ch03
Remove-Item Env:SHOP_ASSISTANT_RUN_MYSQL_TESTS
Remove-Item Env:RUN_MILVUS_TESTS

.\backend\.venv\python.exe -m ruff check --no-cache .\backend
.\backend\.venv\python.exe -m pip check
npm --prefix frontend test
npm --prefix frontend run build
docker compose config --quiet
```

迁移可逆性必须使用专用空数据库，严禁指向开发主库：

```powershell
$env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL='mysql+asyncmy://shop_assistant:shop_assistant_dev@127.0.0.1:3306/shop_assistant_migration_test'
.\backend\.venv\python.exe -m pytest .\backend\tests\test_migrations.py -q
Remove-Item Env:SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL
```
