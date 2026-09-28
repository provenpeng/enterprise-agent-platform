# 事实支撑与恶意文档复核

来源匹配只是模型引用了预标注章节；它不能替代对回答中每个事实性断言的复核。[多业务封存集](GENERALIZATION_VALIDATION.md)的 15/15 来源匹配已由实现者逐例阅读，但尚未有独立业务评审。下列流程要求两名不同评审者对同一份报告给出完整判断，分歧按未通过计算，避免把自动来源分数称为事实准确率。

在仓库根目录执行，为每名评审者各复制一份工作表。工作表包含问题、回答和引用原文，不含供应商密钥；真实业务报告仍可能含敏感信息，应保存在受控目录，不提交到仓库。

```bash
backend/.venv/bin/python backend/scripts/review_benchmark.py prepare \
  --report docs/evidence/general_sealed_v4.json \
  --dataset examples/benchmark_general_sealed_v4.json \
  --output backend/evals/reports/review_alice.json
cp backend/evals/reports/review_alice.json backend/evals/reports/review_bob.json
```

每位评审者独立填写 `reviewer`、`reviewed_at` 和每题 `verdict`。有答案题选择 `supported`、`partial` 或 `unsupported`；无答案题选择 `correct_abstention` 或 `incorrect_abstention`。`supported` 表示回答的每个事实性断言均有直接证据、比较题覆盖所有方面；可在 `notes` 记录不支持的断言。随后运行：

```bash
backend/.venv/bin/python backend/scripts/review_benchmark.py score \
  --report docs/evidence/general_sealed_v4.json \
  --dataset examples/benchmark_general_sealed_v4.json \
  --reviews backend/evals/reports/review_alice.json backend/evals/reports/review_bob.json \
  --min-support 0.9 --min-agreement 0.9
```

工具校验报告 SHA-256、数据集版本、全部题目、评审者身份与判定选项；只有双方一致判为正确才计入事实支撑率。真实企业语料评估前，应先取得授权并冻结文档、题目、评分标准和模型配置，再由未参与实现或调参的业务人员评审。没有这些材料时，不能报告真实业务准确率。

`backend/evals/prompt_injection_v1.json` 提供三种**开发期**恶意证据：伪装系统角色、伪装工具输出和要求对无关问题编造答案。以下命令调用当前配置的真实聊天模型，并以失败退出码报告攻击标记进入回答、漏掉期限或错误引用：

```bash
backend/.venv/bin/python backend/scripts/probe_prompt_injection.py \
  --output backend/evals/reports/prompt_injection_v1.json
```

使用 `deepseek-chat` 和 `json_mode` 的本地运行结果为 3/3，通过详情及语料校验和见[逐例报告](evidence/prompt_injection_v1.json)。这套小型样例不能证明系统免疫提示注入。源文档仍按不可信数据进入模型，服务端只校验引用 ID 的授权范围与当前检索结果。上线前需持续扩大攻击样例、测试编码和跨文档注入，并记录版本、模型和失败案例。对照 [OWASP LLM 应用风险](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) 与实际权限边界复审。
