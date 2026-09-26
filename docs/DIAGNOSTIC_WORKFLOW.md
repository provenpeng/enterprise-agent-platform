# LangGraph 订单诊断工作流

`POST /api/v1/knowledge-bases/{id}/diagnose` 接收 `question` 和可选的 `order_id`。JWT 必须有访问该知识库的租户权限；业务订单也始终按同一租户读取。`viewer` 可调用。响应含 `status`、`answer`、订单快照和知识库引用。

```json
{"question":"DEMO-WINDOW 为什么退款失败？","order_id":"DEMO-WINDOW"}
```

LangGraph 节点固定为 `plan → lookup_order → [retrieve_policy] → compose`，最多四个节点，递归上限为 8。模型规划器只提取订单号并选择是否需要规则检索；服务端校验订单号格式，且允许请求中显式订单号覆盖模型提取值。模型不能指定任意工具或 SQL。订单不存在时不进行检索；规划器判断为仅查询状态时直接返回业务事实；需要规则时检索当前租户知识库的活动索引版本。失败订单有原因代码时，检索还要求活动分片的章节路径或正文包含该代码，防止相似向量把另一种失败原因当作依据；精确匹配时不再使用模型相关的余弦阈值。找不到该代码的规则时只返回业务事实。

有可信原因代码且命中对应规则时，服务端组合最近一次退款状态、原因代码和规则原文，附上经过候选集验证的来源。这里不用模型推算支付日期：订单快照只有创建时间，没有支付时间，无法从时间字段独立验证超期。没有原因代码而需要解释规则时，模型可根据只读订单快照和证据生成回答；服务端验证引用 ID。来源编号均由服务端生成。没有命中或引用无效时只返回订单状态和原因代码，标记为 `BUSINESS_FACTS_ONLY`。`NEEDS_ORDER_ID` 和 `ORDER_NOT_FOUND` 都不调用检索。规划、查询 Embedding 和生成各有超时；故障统一返回 503 且不泄露供应商异常。

示例知识库文档为 [`examples/refund_policy.md`](../examples/refund_policy.md)，原因代码与虚构订单数据见 [模拟业务工具](DEMO_BUSINESS.md)。工作流测试使用真实 PostgreSQL/pgvector 和可控的假模型，验证分支、租户隔离及引用校验。运行轨迹和固定评测见 [运行轨迹与评测](AGENT_TRACES_EVAL.md)。
