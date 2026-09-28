# 请求级可观测性

API 为每个 HTTP 请求生成新的 32 位十六进制请求 ID，通过 `X-Request-ID` 响应头返回。客户端可把该 ID 与错误报告一同提供给维护者。服务不信任客户端传入的同名请求头，避免伪造或日志注入。

每个请求结束时写入一条 JSON 格式的日志消息，字段为 `event`、`request_id`、`method`、`route`、`status`、`duration_ms` 和 `failure_type`。`route` 使用路由模板，例如 `/api/v1/knowledge-bases/{knowledge_base_id}/ask`；未匹配路由统一记为 `unmatched`。日志不包含原始 URL、查询参数、请求正文、Authorization 头、回答正文或订单快照。未处理异常返回 500 和请求 ID，日志只记录异常类型，不记录异常消息。

Compose 关闭 Uvicorn 自带的原始 URL 访问日志，避免同一请求产生两种格式并泄漏路径值。自行启动 Uvicorn 时也应传入 `--no-access-log`，并将 `uvicorn.error` 的 JSON 消息送往日志系统。日志接收端应按 `request_id` 检索，并对日志实施保留期与访问控制。

诊断接口同时返回业务运行 `run_id`；前者用于追踪一次 HTTP 请求，后者用于查看 LangGraph 步骤，两者职责不同。租户管理员可调用 `GET /api/v1/agent-runs/metrics?hours=24`，从共享数据库中的持久化运行与步骤记录汇总当前租户的运行数、成功和失败、结果类别、p50/p95 耗时、已报告模型 token，以及各步骤 p95。时间窗可设为 1–720 小时。返回值不含原问题和回答；未报告 token 的成功运行单独计数，不能把空值当零用量。工作台“运行轨迹”页也显示这组指标。

这组指标仅覆盖订单诊断 Agent，不包括普通检索、引用问答或索引 worker。当前没有跨进程分布式 tracing、HTTP 指标聚合或持久化的请求 ID 到运行 ID 映射；如需生产级告警和全链路观测，应将结构化日志、指标与模型网关遥测接入运维平台。外部模型调用已有独立超时；请求并发保护见[运行保护](RUNTIME_PROTECTION.md)。
