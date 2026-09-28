# 身份与订单系统接入边界

## 令牌验签

默认本地演示继续使用挂载的 `config/auth-public.pem` 验证 RS256 JWT。配置 `AUTH_JWKS_URL=https://<身份服务>/.../jwks` 后，API 改为按 Token 的 `kid` 从该固定 HTTPS 地址获取 RS256 公钥，不读取本地公钥。仍严格验证 `iss`、`aud`、`iat`、`exp`、`sub`、`tenant_id` 和 `role`。不接受其他算法、缺少 `kid`、重复 key ID、非签名 RSA 密钥或任意重定向。成功获取的密钥缓存五分钟；新 `kid` 会触发刷新，未知 `kid` 在五秒内不重复向身份服务请求。身份服务不可用时返回 503，找不到签名密钥或令牌无效时返回 401。

生产接入需由管理员将 `AUTH_ISSUER`、`AUTH_AUDIENCE` 和 `AUTH_JWKS_URL` 对齐真实身份服务，并确保它签发包含租户和角色声明的**访问令牌**。前端 OIDC Code + PKCE 仍需要实际身份服务进行浏览器回调、登出和密钥轮换联调；目前没有该测试租户，不能声称已完成线上身份验收。本地演示 JWT 不应在开启正式 JWKS 模式后继续使用。

## 只读订单接口

未配置 `ORDER_API_BASE_URL` 时，诊断沿用数据库中的虚构订单。配置 `ORDER_API_BASE_URL` 与 `ORDER_API_TOKEN` 后，订单读取统一使用只读 HTTP 适配器。服务端只允许既定的 `GET /orders/{order_id}`；URL、Bearer 服务令牌和 `X-Tenant-ID` 从部署配置及已验签的用户身份决定，模型不能选择端点或租户。订单未找到返回 404；超时、非成功状态、格式错误或返回其他订单号均视为 503，客户端看不到上游异常细节。`ORDER_API_TIMEOUT_SECONDS` 默认三秒。

仓库提供独立的 `orders-sandbox` Compose 服务，用相同 PostgreSQL 中的虚构订单验证 HTTP 网络边界、服务令牌和租户查询。它仅在 `integration` profile 启动，不开放宿主机端口。为本地演示在被 Git 忽略的 `.env` 中设置随机的 `ORDER_API_TOKEN`，以及 `ORDER_API_BASE_URL=http://orders-sandbox:8001`，然后运行：

```bash
docker compose --profile indexing --profile integration up -d --build api indexer orders-sandbox
docker compose --profile integration ps
```

先按 README 建立租户并运行 `seed_demo_orders.py`。通过主 API 或前端触发 `DEMO-WINDOW` 诊断，读取路径将穿过 HTTP 适配器和订单沙箱。测试还覆盖错误服务令牌、跨租户未命中、上游超时与错误响应。生产系统接入时只需实现同一只读响应契约，但必须另行处理服务间认证、供应商权限、字段映射、审计和真实数据授权；本沙箱不能替代这些验收。
