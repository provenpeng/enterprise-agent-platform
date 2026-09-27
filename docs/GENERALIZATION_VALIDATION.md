# 多业务长文档与独立验收记录

## 语料与冻结顺序

`examples/` 中的六份虚构企业文档覆盖客户退款、实物退换、员工差旅报销、供应商采购、身份访问控制和安全事件处置，共 8,617 个字符（UTF-8 文件合计 24,419 字节）。每份包含版本、适用范围、职责、流程、时限、例外和留档条款。旧版三份短文档仍保留在 `backend/evals/corpus/`，其历史评测清单和 SHA-256 未被改写。

开发集 `benchmark_general_dev_v1.json` 先用于调试。随后 `benchmark_general_holdout_v1.json`、`benchmark_general_final_v2.json` 和 `benchmark_general_acceptance_v3.json` 在各自首次运行前提交冻结；它们的失败分别推动了引用必要性、无答案拒答和跨文档候选覆盖的改进，因此都只算开发证据。最终 `benchmark_general_sealed_v4.json` 及质量门槛在首次运行前提交冻结（提交 `d728783`），四组题目的 ID 与问题文本互不重复，六份文档及校验和一致。

## 独立验收

2026-09-27 使用本机 API、PostgreSQL、索引 worker 和本机 Ollama Embedding 服务运行；问答模型为配置的 `deepseek-chat`，Embedding 为 `nomic-embed-text`（768 维），文档处理后端为 `manual`。正式的[逐例脱敏报告](evidence/general_sealed_v4.json)保留了模型配置、语料及门槛校验和、逐题回答和引用原文。题集 [JSON](../examples/benchmark_general_sealed_v4.json) 与[门槛 JSON](../examples/general_sealed_quality_gate_v4.json)可直接复跑。

| 指标 | 结果 | 门槛 |
| --- | ---: | ---: |
| 检索 Recall@1 | 16/17 = 0.941 | 0.70 |
| 检索 Recall@5 | 17/17 = 1.000 | 0.90 |
| 检索 MRR@5 | 0.971 | 0.75 |
| 无答案检索零命中 | 3/3 | 3/3 |
| 问答精确引用来源 | 15/15 | ≥ 0.90 |
| 问答拒答 | 3/3 | 3/3 |
| 订单、原因代码、规则路由、状态、诊断引用 | 各 4/4 | 各 4/4 |
| 跨租户隔离 | 3/3 | 3/3 |

质量门槛通过。运行器的引用指标要求命中所有预标注章节且不引用其他章节；它本身不能证明回答语义正确。为补足这一点，我逐条阅读了报告中的最终回答与所引原文，并按“每个事实性断言均由所引章节直接支持；比较题覆盖双方；无答案题没有引用”复核：

| 用例 | 引用章节 | 人工事实支撑 |
| --- | --- | --- |
| seal_q01 | refund_exclusion | 通过 |
| seal_q02 | refund_window | 通过 |
| seal_q03 | refund_gateway_error | 通过 |
| seal_q04 | return_window | 通过 |
| seal_q05 | return_inspection | 通过 |
| seal_q06 | expense_invoice | 通过 |
| seal_q07 | expense_approval | 通过 |
| seal_q08 | procurement_payment | 通过 |
| seal_q09 | procurement_exception | 通过 |
| seal_q10 | access_mfa | 通过 |
| seal_q11 | access_vendor | 通过 |
| seal_q12 | incident_level | 通过 |
| seal_q13 | incident_notice | 通过 |
| seal_q14 | refund_approval + expense_payment | 通过 |
| seal_q15 | return_window + refund_window | 通过 |
| seal_q16–18 | 无引用，标准拒答 | 通过 |

这次人工复核为 15/15 有答案问题和 3/3 无答案问题。复核者为本次实现的 Codex，并非独立第三方；报告中的完整回答和证据便于其他人复审。结果只说明这套合成业务资料、该模型配置和这一次运行通过预设门槛，不代表任意真实企业文档或其他模型也达到同样准确率。

## 复跑与浏览器验证

在 API、索引 worker、模型服务就绪后，设置 `EAP_EVAL_TOKEN` 为目标租户管理员 JWT、`EAP_EVAL_OUTSIDER_TOKEN` 为另一租户 JWT，并让运行器与服务使用同一套 `EMBEDDING_*` 配置。先准备新知识库，播种该租户的演示订单，再运行验收：

```bash
backend/.venv/bin/python backend/scripts/evaluate_benchmark.py \
  --dataset examples/benchmark_general_sealed_v4.json prepare
backend/.venv/bin/python backend/scripts/seed_demo_orders.py --tenant-id "$TENANT_ID"
backend/.venv/bin/python backend/scripts/evaluate_benchmark.py \
  --dataset examples/benchmark_general_sealed_v4.json run \
  --knowledge-base-id "$KB_ID" \
  --output backend/evals/reports/general_sealed_v4.json \
  --quality-profile examples/general_sealed_quality_gate_v4.json
backend/.venv/bin/python backend/scripts/export_public_benchmark.py \
  --report backend/evals/reports/general_sealed_v4.json \
  --dataset examples/benchmark_general_sealed_v4.json \
  --output docs/evidence/general_sealed_v4.json
```

`frontend/e2e/workspace.spec.ts` 在真实 Chromium 中覆盖演示登录、上传、索引状态、流式引用问答、订单诊断及刷新后恢复结果。浏览器测试拦截 API 以获得确定性结果；后端数据库、索引、授权和模型链路由独立的集成测试与上述真实模型验收覆盖。CI 会运行浏览器测试，但不会自动调用付费聊天模型。
