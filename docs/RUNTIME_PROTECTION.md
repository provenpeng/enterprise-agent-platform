# 模型请求运行保护

`search`、`ask`、`diagnose` 在 JWT 和知识库租户授权通过后才申请模型容量名额。授权事务在等待前释放。默认同时最多 8 个请求，最多等待 0.1 秒；到期返回 `503 {"detail":"Model capacity is busy"}` 和 `Retry-After: 1`。健康检查、授权失败和不调用模型的管理接口不占名额。请求结束、失败或取消时释放名额。

Compose 默认使用 `MODEL_ADMISSION_BACKEND=postgres`：每个名额对应同一数据库中的一个 PostgreSQL 会话级 advisory lock。不同 API 进程或副本只要连接到同一数据库，就竞争同一组名额。获得名额的请求在模型调用期间持有一条专用数据库连接；连接使用自动提交与 `NullPool`，结束时显式解锁并关闭物理连接，进程退出后 PostgreSQL 也会释放会话锁。没有新增数据表或迁移。跨独立连接的竞争和异常释放由数据库集成测试覆盖。

`MODEL_ADMISSION_BACKEND=local` 可用于单进程开发，使用进程内信号量。`MODEL_MAX_INFLIGHT_REQUESTS` 与 `MODEL_ADMISSION_WAIT_SECONDS` 对两种模式生效，修改后重启 API。多副本必须使用相同数据库和相同名额配置；如果数据库连接失效，当前锁会随连接关闭而释放，正在执行的外部模型调用未必立即停止。容量门不包括独立的索引 worker，也不提供按租户公平性、供应商配额或令牌速率控制。部署到共享模型网关时，应另行按租户及供应商额度设置限流，并用目标模型和真实并发压测确定名额。

客户端收到容量 503 时应按 `Retry-After` 延迟重试，并对总重试次数设置上限。请求 ID 见[请求级可观测性](OBSERVABILITY.md)，可用于定位容量拒绝和上游故障。
