# 模拟订单业务工具

本模块只保存虚构的订单与退款尝试，不连接真实支付或订单系统。每条订单以 `(tenant_id, order_id)` 标识；退款尝试使用复合外键绑定同一租户的订单。`OrderLookupTool` 从已验证 JWT 中注入的租户范围读取快照，找不到订单时返回 `None`。API `GET /api/v1/business/orders/{order_id}` 将其映射为 404；`admin` 和 `viewer` 都可读，没有业务数据写入 API。

管理员先按 README 创建租户，再显式执行种子命令：

```bash
docker compose run --rm migrate python scripts/seed_demo_orders.py --tenant-id "$TENANT_ID"
```

本地虚拟环境也可在 `backend/` 运行 `python scripts/seed_demo_orders.py --tenant-id UUID`。

脚本只向指定的已有租户插入缺失的虚构数据，可重复执行。固定案例：

| 订单 ID | 退款结果 | 原因代码 | 用途 |
| --- | --- | --- | --- |
| `DEMO-WINDOW` | 失败 | `REFUND_WINDOW_EXPIRED` | 规则期限判断 |
| `DEMO-AMOUNT` | 失败 | `AMOUNT_EXCEEDS_REFUNDABLE` | 可退金额判断 |
| `DEMO-GATEWAY` | 失败 | `GATEWAY_TIMEOUT` | 外部服务暂时故障 |
| `DEMO-SUCCESS` | 成功 | 无 | 成功对照案例 |

金额以整数分保存，币种为 `CNY`；不包含姓名、地址、银行卡或其他个人信息。原因代码是业务数据，不是模型自由生成的诊断结论。后续 Agent 应通过只读工具获取快照，再结合知识库中的虚构规则解释处理建议。
