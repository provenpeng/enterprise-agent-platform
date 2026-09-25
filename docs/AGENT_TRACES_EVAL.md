# Agent 运行轨迹与固定评测

诊断接口返回 `run_id`。服务先提交一条 `RUNNING` 记录，再按 LangGraph 节点逐步持久化 `plan`、`lookup_order`、可选的 `retrieve_policy` 和 `compose`。每一步保存受限输入、输出、耗时、错误类型和模型报告的 token 用量；结束时将运行标记为 `SUCCEEDED` 或 `FAILED`。进程意外退出可能留下 `RUNNING` 记录，便于定位中断，不会伪装为成功。

只有租户 `admin` 可以调用 `GET /api/v1/agent-runs` 和 `GET /api/v1/agent-runs/{run_id}`。跨租户 ID 统一返回 404；`viewer` 返回 403。运行记录包含原问题和最终回答；步骤只保存订单编号、原因代码及检索命中的 ID、版本和分数，不重复存储订单快照或知识库正文。部署方应配置访问审计，并定期运行保留清理：

```bash
docker compose run --rm migrate python scripts/prune_agent_runs.py --days 30
```

命令删除超过指定天数的运行及其步骤，包括已中断的 `RUNNING` 记录。数据库不保存 API 密钥或供应商原始异常。`total_tokens` 只汇总聊天模型在结构化响应中报告的 token；供应商未报告时为 `null`，目前不包含 Embedding token。

固定数据集位于 `backend/evals/demo_cases.json`，涵盖三个退款失败原因和一个成功对照。配置好 `OPENAI_API_KEY`，为同一租户载入模拟订单并将 [`examples/refund_policy.md`](../examples/refund_policy.md) 上传、索引后，在仓库根目录运行：

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

CI 在无外部密钥下验证固定数据集、评分逻辑、真实数据库工作流和轨迹契约。**CI 分数不是线上语义质量分数**；真实模型和 Embedding 的表现应运行上述脚本并记录模型版本、数据集版本与结果。上述字符串匹配指标只能检查原因代码及来源片段，不能证明回答每句话的事实支持性。
