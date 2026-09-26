# Agent 运行轨迹与固定评测

诊断接口返回 `run_id`。服务先提交一条 `RUNNING` 记录，再按 LangGraph 节点逐步持久化 `plan`、`lookup_order`、可选的 `retrieve_policy` 和 `compose`。每一步保存受限输入、输出、耗时、错误类型和模型报告的 token 用量；结束时将运行标记为 `SUCCEEDED` 或 `FAILED`。进程意外退出可能留下 `RUNNING` 记录，便于定位中断，不会伪装为成功。

只有租户 `admin` 可以调用 `GET /api/v1/agent-runs` 和 `GET /api/v1/agent-runs/{run_id}`。跨租户 ID 统一返回 404；`viewer` 返回 403。运行记录包含原问题和最终回答；步骤只保存订单编号、原因代码及检索命中的 ID、版本和分数，不重复存储订单快照或知识库正文。部署方应配置访问审计，并定期运行保留清理：

```bash
docker compose run --rm migrate python scripts/prune_agent_runs.py --days 30
```

命令删除超过指定天数的运行及其步骤，包括已中断的 `RUNNING` 记录。数据库不保存 API 密钥或供应商原始异常。`total_tokens` 只汇总聊天模型在结构化响应中报告的 token；供应商未报告时为 `null`，目前不包含 Embedding token。

## 轻量演示检查

原有的轻量数据集位于 `backend/evals/demo_cases.json`，涵盖三个退款失败原因和一个成功对照。配置好模型，为同一租户载入模拟订单并将 [`examples/refund_policy.md`](../examples/refund_policy.md) 上传、索引后，在仓库根目录运行：

```bash
export EAP_EVAL_TOKEN="$TOKEN"
backend/.venv/bin/python backend/scripts/evaluate_demo.py \
  --knowledge-base-id REPLACE_WITH_KB_ID --min-score 0.75
```

脚本通过真实 API 执行查询和诊断，打印每个案例与汇总指标；任一指标低于门槛时退出码为 1。指标定义：

- `retrieval_recall_at_5`：Top 5 命中的正文或章节来源中是否包含标注的原因代码。
- `order_lookup_accuracy`：读取的订单号是否与案例一致。
- `reason_code_accuracy`：工具返回的最新退款原因是否与标注一致。
- `policy_route_accuracy`：是否按预期执行规则检索节点。
- `citation_accuracy`：需要规则的案例是否引用正文或章节来源包含目标原因代码的分片；状态查询是否没有引用。

这套检查适合快速验证演示链路；字符串匹配只能检查原因代码及来源片段。

## 可复现 RAG 与 Agent 基准

正式基准在 [`backend/evals/benchmark_v1.json`](../backend/evals/benchmark_v1.json)。它固定三份合成文档及 SHA-256、14 个章节来源标签、12 个检索问题、8 个带引用问答、4 个订单诊断和 3 个跨租户访问场景。检索覆盖直接提问、改写、相似业务混淆及无答案问题。评分前会检查知识库**恰好**包含这三份文件、校验和与活动索引匹配、索引向量空间等于运行器配置、每个标注章节确实存在。解析器或模型切换后仍用相同章节标签比较结果。

先启动 API 和索引 worker，确保运行器与服务使用相同的 `EMBEDDING_*` 配置。以下命令在仓库根目录执行，`TOKEN`、`TENANT_ID` 的生成方法见 README；准备语料会调用当前配置的 Embedding 服务，运行基准还会调用当前聊天模型。可按[模型接入说明](MODEL_PROVIDERS.md)选用本地 Ollama，脚本不会自动切换到付费模型：

```bash
export EAP_EVAL_TOKEN="$TOKEN"
backend/.venv/bin/python backend/scripts/evaluate_benchmark.py prepare
# 将输出的 knowledge_base_id 保存为 KB_ID，待索引完成后：
backend/.venv/bin/python backend/scripts/seed_demo_orders.py --tenant-id "$TENANT_ID"
OTHER_TENANT_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
export EAP_EVAL_OUTSIDER_TOKEN=$(python3 backend/scripts/dev_token.py \
  --subject eval-outsider --tenant-id "$OTHER_TENANT_ID")
backend/.venv/bin/python backend/scripts/evaluate_benchmark.py run \
  --knowledge-base-id "$KB_ID" --output backend/evals/reports/baseline.json \
  --min-score 0
```

首次运行用 `--min-score 0` 采集模型质量基线；跨租户隔离始终要求全部通过。以后切换模型、解析器或检索参数时，使用相同数据集运行并比较；报告文件默认被 Git 忽略，若要公开评测结果，应先检查其内容：

```bash
backend/.venv/bin/python backend/scripts/evaluate_benchmark.py run \
  --knowledge-base-id "$KB_ID" --output backend/evals/reports/candidate.json \
  --baseline backend/evals/reports/baseline.json \
  --max-regression 0.05 --min-score 0.75
```

脚本先写完整 JSON 报告，再根据门槛返回非零退出码。只有数据集 SHA-256 一致才允许比较。报告包含每例排名、分片 ID、错误、耗时，以及检索 Recall@1/5、MRR@5、无答案无命中率、问答引用来源准确率和拒答率、诊断步骤与来源准确率、跨租户隔离准确率。引用评分要求命中全部标注章节且不引用其他章节；它不能证明回答的每个语义结论被证据支持。耗时分位数、配置期望值、索引实际空间与处理后端、诊断轨迹报告的模型名和 token 用量也会保存；当前 API 不提供问答与 Embedding 的 token 用量。

CI 用假模型和 HTTP 模拟结果验证基准评分、语料契约及失败报告，并运行现有真实数据库权限与工作流测试；**CI 的确定性分数不是线上语义质量分数**。真实质量基准需显式运行，不进入 CI，也不会自动使用付费模型。
