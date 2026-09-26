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

## 本地 Ollama 实测记录（2026-09-26）

在相同的 `synthetic-policy-v1` 语料（数据集 SHA-256：`a4de6c3e944ebf7357602e1a70ec9972f5066b546180f1df09f405216ef99c1e`）、同一知识库和 `manual` 处理后端上运行。Embedding 为本地 `nomic-embed-text`（768 维），聊天模型为本地 `qwen2.5:1.5b-instruct`；API、worker 和评测运行器均指向同一个 Ollama 实例。先运行原始实现，再仅修改诊断中原因代码的证据约束后复测。`--min-score 0` 用于采集基线，**不代表达到了质量上线门槛**。原始逐例 JSON 报告保存在本地被 Git 忽略的 `backend/evals/reports/`。

| 指标 | 原始实现 | 原因代码约束后 |
| --- | ---: | ---: |
| 检索 Recall@5 | 0.90 | 0.90 |
| 检索无答案无命中率 | 1.00 | 1.00 |
| 问答引用来源准确率 | 0.00 | 0.00 |
| 问答拒答准确率 | 0.00 | 0.00 |
| 诊断规则来源准确率 | 0.00 | 0.75 |
| 诊断状态准确率 | 0.75 | 0.75 |
| 跨租户隔离准确率 | 1.00 | 1.00 |

诊断原先把向量相似但原因代码不符的规则交给模型，出现错误解释；现在只允许章节路径或正文包含订单真实原因代码的活动分片作为规则证据。4 个诊断中仍有 1 个状态查询被小模型误判为需要规则检索。问答的 6 个正例常出现多余或错误引用，2 个无答案问题均未正确拒答；部分正例的目标章节也没有进入 Top 5。引用 ID 的租户与候选集校验只能证明来源可访问，不能证明内容真正支持回答。后续应在同一数据集上评估更强的本地模型、检索候选和证据选择策略，达到预设门槛后再考虑上线质量声明。

### 7B 模型与问答候选数对照

保持同一知识库、索引和原因代码约束，仅把聊天模型换为本地 `qwen2.5:7b-instruct`。先用旧版问答默认 `top_k=5` 运行，再改为 `top_k=10` 复测；两次都使用相同的 8 条问答和 4 条诊断案例。

| 指标 | 7B / Top 5 | 7B / Top 10 |
| --- | ---: | ---: |
| 问答引用来源准确率（6 个正例） | 0.33 | 0.83 |
| 问答拒答准确率（2 个无答案例） | 1.00 | 1.00 |
| 诊断规则来源准确率 | 0.50 | 0.50 |
| 跨租户隔离准确率 | 1.00 | 1.00 |

扩大候选后，两条原本未进入 Top 5 的目标章节进入问答上下文，另一个此前拒答的正例也得到正确引用；第 6 个正例仍被模型拒答。两个无答案例继续正确拒答。该 7B 模型对诊断的 4 个案例仅有 2 个正确来源，说明问答质量提升不等于整个 Agent 达标；这一小规模合成评测也不能替代真实业务验证。运行时输出保存在本地被 Git 忽略的报告目录。

### 诊断生成归因与修复

在相同索引上逐步检查 7B 的 4 条诊断：规划、订单查询和原因代码检索均正确；两个失败发生在 `compose`，模型没有产出可验证的引用。随后用已配置的付费 `deepseek-chat` 对照：它的 4 条诊断和那条多来源问答都有正确章节引用，但 `DEMO-WINDOW` 的回答把订单创建时间当成支付时间，声称退款尝试与创建时间相同却超过 30 天。可见来源 ID 准确率不能充当事实一致性检查。

诊断对可信原因代码的路径现在由服务端组合最近一次业务状态、原因代码和匹配规则的原文及引用，不由生成模型推算时间或改写事实。模拟超期案例的退款尝试时间也修正为订单创建后 32 天；订单快照仍没有支付时间，因此回答不会独立计算支付后的间隔。没有原因代码的开放式规则问题仍走受限模型生成和引用校验。

同一 `synthetic-policy-v1` 知识库修复后的完整基准：本地 7B 的诊断状态和规则来源均由 **2/4 提升到 4/4**，问答来源仍为 **5/6**、拒答 **2/2**；付费 `deepseek-chat` 的诊断状态及来源 **4/4**、问答来源 **6/6**、拒答 **2/2**。两者检索 Recall@5 均为 **0.90**。逐例报告留在被 Git 忽略的 `backend/evals/reports/`。这些结果仍只覆盖已知合成案例；后续要用未参与调参的案例检验泛化，并为事实一致性设置独立人工检查。

### 多来源问答的引用编号

7B 在 `qa_compare_deadlines` 已找到两个正确章节，原始草稿也给出正确事实，但把第一个 36 字符 chunk UUID 的一个字符抄错；服务端因此拒绝整个回答。改为请求内短证据编号并由服务端映射回 UUID 后，相同知识库和模型的完整基准中问答来源从 **5/6 提升到 6/6**，无答案拒答保持 **2/2**，诊断来源保持 **4/4**。付费 `deepseek-chat` 对照仍为问答 **6/6**、拒答 **2/2**、诊断 **4/4**。未知编号仍让整条草稿拒答，不会猜测最相近的 UUID。此结果尚需用未参与调参的案例验证。
