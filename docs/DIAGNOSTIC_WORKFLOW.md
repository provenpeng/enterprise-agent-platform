# LangGraph 订单诊断工作流

`POST /api/v1/knowledge-bases/{id}/diagnose` 接收 `question` 和可选的 `order_id`。JWT 必须有访问该知识库的租户权限；业务订单也始终按同一租户读取。`viewer` 可调用。响应含 `status`、`answer`、订单快照和知识库引用。

```json
{"question":"DEMO-WINDOW 为什么退款失败？","order_id":"DEMO-WINDOW"}
```

LangGraph 节点固定为 `plan → lookup_order → [retrieve_policy] → compose`，最多四个节点，递归上限为 8。模型规划器只提取订单号并选择是否需要规则检索；服务端校验订单号格式，且允许请求中显式订单号覆盖模型提取值。模型不能指定任意工具或 SQL。订单不存在时不进行检索；仅查询状态时直接返回业务事实；需要规则时检索当前租户知识库的活动索引版本。

有知识库命中时，模型根据只读订单快照和证据生成解释并返回引用的 chunk ID。服务端验证所有 ID 都属于本次检索结果，来源编号由服务端生成。没有命中或引用无效时只返回订单状态和原因代码，标记为 `BUSINESS_FACTS_ONLY`，不编造规则解释。`NEEDS_ORDER_ID` 和 `ORDER_NOT_FOUND` 都不调用检索。规划、查询 Embedding 和生成各有超时；故障统一返回 503 且不泄露供应商异常。

示例知识库文档为 [`examples/refund_policy.md`](../examples/refund_policy.md)，原因代码与虚构订单数据见 [模拟业务工具](DEMO_BUSINESS.md)。工作流测试使用真实 PostgreSQL/pgvector 和可控的假模型，验证分支、租户隔离及引用校验。模型生成的文字仍需标注评测集检验事实支持率；后续独立 PR 将加入运行轨迹和评测门禁。
