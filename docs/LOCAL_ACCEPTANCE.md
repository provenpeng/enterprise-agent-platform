# 本地完整功能验收

这份流程使用六份虚构的长业务文档、四笔虚构订单和本机模型，覆盖工作台主要交互。命令在仓库根目录执行。需要 Docker Compose、后端虚拟环境、Node.js 和可用的 Embedding/Chat 模型；具体模型配置见[模型接入说明](MODEL_PROVIDERS.md)。本地演示 JWT 由仓库外的私钥签发，有效期一小时。

## 启动服务

首次运行先按 [README](../README.md#快速开始)创建 `.env` 和 `config/auth-private.pem`、`config/auth-public.pem`。在 `.env` 配置 `EMBEDDING_API_BASE_URL`、模型及密钥，以及 `CHAT_API_BASE_URL`、模型及密钥。macOS 上 Docker 容器连接宿主机 Ollama 时应先核实容器可达的地址。若要验证独立订单 HTTP 适配器，再加入以下两项；`ORDER_API_TOKEN` 应使用本机随机值，不能提交到 Git：

```dotenv
ORDER_API_BASE_URL=http://orders-sandbox:8001
ORDER_API_TOKEN=<本机随机长令牌>
```

```bash
docker compose --profile indexing --profile integration up -d --build \
  postgres migrate api indexer orders-sandbox
curl -fsS http://127.0.0.1:8000/api/v1/health
```

健康检查应返回 `{"status":"ok"}`。若不使用独立订单沙箱，可不配置上述两项，并移除启动命令中的 `--profile integration` 和 `orders-sandbox`；此时 API 使用同库的租户隔离演示订单读取器。

## 创建租户和六文档知识库

```bash
TENANT_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
TOKEN=$(python3 backend/scripts/dev_token.py \
  --subject local-reviewer --tenant-id "$TENANT_ID")
curl -fsS -X POST http://127.0.0.1:8000/api/v1/tenants \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"本地功能验收"}'
docker compose run --rm migrate python scripts/seed_demo_orders.py \
  --tenant-id "$TENANT_ID"
EAP_EVAL_TOKEN="$TOKEN" backend/.venv/bin/python \
  backend/scripts/evaluate_benchmark.py \
  --dataset examples/benchmark_general_sealed_v4.json prepare --timeout 600
```

最后一条命令输出 `knowledge_base_id=<UUID>`，并在返回前核对六份文档均已发布、来源章节可见。保存该 ID 供 API 检查。六份文档分别覆盖退款、退货、费用报销、采购、访问权限及安全事件。文档和订单都是虚构的，不能当作真实企业政策或生产订单使用。

## 在工作台逐项操作

```bash
cd frontend
npm ci
cp .env.example .env.local
```

把 `frontend/.env.local` 中的 `VITE_DEV_TOKEN_AUTH` 改成 `true`，再执行 `npm run dev`，打开输出的本地地址（通常是 `http://127.0.0.1:5173/`）。粘贴上面的 `TOKEN`。进入名称含 `synthetic-enterprise-general-sealed-v4` 的知识库：

1. **文档与索引**：确认六份文档都显示“可检索”。打开任一文档的“分片”预览，核对章节路径和正文；可对独立测试文件试用“重建索引”和“移除”。
2. **检索调试**：输入“员工出差结束后多久需要提交报销单？”，检查原文片段、文件名、分数和章节；调整返回片段数及最低分数观察结果变化。
3. **引用问答**：输入“纸质发票遗失后，员工需要补充哪些材料和审批？”，等待流式回答结束，检查 `expense_policy.md` 的引用。再问文档没有规定的事项，检查证据不足时的拒答；进入会话历史恢复已保存的正式回答。
4. **订单诊断**：输入“DEMO-WINDOW 为什么退款失败？”，订单号填 `DEMO-WINDOW`。结果应给出订单事实、`REFUND_WINDOW_EXPIRED` 原因代码、规则引用和“查看运行轨迹”入口。还可试 `DEMO-AMOUNT`、`DEMO-GATEWAY`、`DEMO-SUCCESS`，或不存在的订单号。
5. **运行轨迹**：查看各 LangGraph 步骤耗时、状态和模型 token 用量；刷新页面后重新粘贴 JWT，并从历史中恢复问答或诊断。

演示 JWT 刷新页面即从前端内存清除，过期后可使用同一 `TENANT_ID` 再运行 `dev_token.py` 签发新 token。前端开发登录入口仅在 Vite 开发模式可用。

## 自动回归与范围

`backend/scripts/smoke_compose_models.py` 可检查真实模型、索引 worker、检索、问答及诊断。六文档封存题集的自动验收命令和指标见[多业务验证记录](GENERALIZATION_VALIDATION.md)；它还需要另一个已开通租户的 JWT，才能测试有效身份之间的隔离。前端检查用 `npm run typecheck && npm run lint && npm run test && npm run build`，浏览器 E2E 用 `npm run test:e2e`。E2E 使用模拟 API，完整后端联调应按上面的人工步骤另行验证。

本地流程只验证虚构数据和本机适配器。真实文档质量、实际 OIDC 密钥轮换及订单沙箱契约，需要相应系统的授权测试资源和独立业务人员复核，不能由这套演示数据证明。
