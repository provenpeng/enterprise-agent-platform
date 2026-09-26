# 模型请求运行保护

`search`、`ask`、`diagnose` 在通过 JWT 和知识库租户授权后，进入同一个 API 进程内的模型请求容量门。授权事务在等待前释放，避免容量耗尽时占住数据库连接。默认最多同时处理 8 个请求，最多等待 0.1 秒；到期返回 `503 {"detail":"Model capacity is busy"}` 和 `Retry-After: 1`。健康检查、授权失败和不调用模型的管理接口不占用名额。请求结束、失败或取消时均释放名额。

可通过 `.env` 中的 `MODEL_MAX_INFLIGHT_REQUESTS` 和 `MODEL_ADMISSION_WAIT_SECONDS` 调整，修改后重启 API。该容量门保护每个 API **进程**，不跨进程或副本协调，也不限制独立的索引 worker。模型自身还有查询 Embedding、规划和生成超时；容量门不替代供应商额度管理。多副本部署应在入口层配置全局及按租户的限流，并根据模型实例吞吐量设置各 API 进程的容量。

客户端收到容量 503 时应按 `Retry-After` 延迟重试，并对总重试次数设置上限。请求 ID 见[请求级可观测性](OBSERVABILITY.md)，可用于定位容量拒绝和上游故障。
