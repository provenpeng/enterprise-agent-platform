# Enterprise Agent Platform

一个可运行、可审计的企业知识检索与订单诊断 Agent 示例。项目展示从文档上传、异步索引、租户隔离检索到带来源引用的回答，以及由 LangGraph 编排的受限业务工作流。业务数据和规则均为虚构示例。

## 能力一览

| 能力 | 实现与边界 |
| --- | --- |
| 文档处理 | TXT、Markdown、文本型 PDF；手动实现与 LangChain 实现可按索引任务切换，输出相同的解析和分片契约 |
| 持久化索引 | PostgreSQL 任务租约、失败重试、版本原子发布；pgvector 存储 1536 维向量，支持 OpenAI 兼容 Embedding 接口 |
| 租户隔离 | RS256 JWT 中的 `tenant_id` 决定访问范围；知识库、检索、订单和运行轨迹均按租户查询 |
| 检索与问答 | 仅检索已发布版本及当前 Embedding 向量空间；同步和 SSE 流式问答共用服务端引用校验，证据不足时拒答；按用户保存正式回答与引用历史 |
| 订单诊断 | LangGraph 固定路由、只读订单工具、步骤轨迹、token 用量与固定合成数据评测 |
| 请求可观测性 | 响应关联 ID、脱敏结构化访问日志；诊断运行另有持久化步骤轨迹 |
| 运行保护 | 模型请求并发容量门、快速可重试的 503、模型阶段超时 |
| Web 工作台 | React、TypeScript、Vite、Ant Design；租户初始化、文档上传/重建/移除与分片预览、检索调试、流式问答与历史、订单诊断和管理员运行轨迹 |

`manual` 与 `langchain` 文档处理器通过同一接口接入；LangChain 同时用于 Embedding、结构化模型调用，LangGraph 用于工作流。框架被放在适配层，任务、权限和索引版本规则保留在业务层。

```mermaid
flowchart LR
    Web["React 工作台"] --> Client["API 客户端"]
    Client["API 客户端"] --> API["FastAPI / JWT"]
    API --> PG[("PostgreSQL + pgvector")]
    API --> Model["Embedding / Chat 模型"]
    API --> Graph["LangGraph 诊断"]
    Graph --> PG
    Graph --> Model
    API --> Uploads[("共享上传卷")]
    Worker["索引 worker"] --> PG
    Worker --> Uploads
    Worker --> Model
```

## 快速开始

需要 Python 3.12、Docker Engine、Docker Compose v2 和 OpenSSL。以下命令在仓库根目录执行；索引、检索、问答和诊断需要可用模型。默认配置使用 OpenAI API 密钥；也可按 [模型接入说明](docs/MODEL_PROVIDERS.md) 分别接入 Ollama 或其他兼容网关。复制配置后，在本机编辑 `.env`；`.env` 和私钥已被 Git 忽略。

```bash
cp .env.example .env
mkdir -p config
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out config/auth-private.pem
openssl pkey -in config/auth-private.pem -pubout -out config/auth-public.pem
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/api/v1/health
```

健康检查应返回 `{"status":"ok"}`。交互式 API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。Compose 启动 PostgreSQL、一次性迁移任务和 API；索引 worker 单独启动：

```bash
docker compose --profile indexing up -d indexer
```

建立演示租户、上传规则、等待索引并提问。以下变量由响应自动提取，无需手动替换 ID。演示 Token 有效期一小时，私钥只在本机使用；部署时应由身份服务签发 JWT。

```bash
TENANT_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
TOKEN=$(python3 backend/scripts/dev_token.py --subject demo-user --tenant-id "$TENANT_ID")
curl -fsS -X POST http://127.0.0.1:8000/api/v1/tenants \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Demo tenant"}'

KB_ID=$(curl -fsS -X POST http://127.0.0.1:8000/api/v1/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Refund policies"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
DOC_ID=$(curl -fsS -X POST "http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@./examples/refund_policy.md;type=text/markdown' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/documents/$DOC_ID/index-jobs"
```

完整演示语料还包括 [`returns_policy.md`](examples/returns_policy.md)、[`expense_policy.md`](examples/expense_policy.md)、[`procurement_policy.md`](examples/procurement_policy.md)、[`access_control.md`](examples/access_control.md) 和 [`incident_response.md`](examples/incident_response.md)。把六份文档上传到同一知识库，可验证跨业务问答与相似条款辨析；版本化题集及验收结果见[多业务验证记录](docs/GENERALIZATION_VALIDATION.md)。

索引任务显示 `SUCCEEDED` 后运行：

```bash
curl -fsS -X POST "http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/ask" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"退款需要谁批准？"}'
curl -N -X POST "http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/ask/stream" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"退款需要谁批准？"}'
docker compose run --rm migrate python scripts/seed_demo_orders.py --tenant-id "$TENANT_ID"
curl -fsS -X POST "http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/diagnose" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"DEMO-WINDOW 为什么退款失败？","order_id":"DEMO-WINDOW"}'
```

诊断结果的 `run_id` 可供租户管理员查询 `/api/v1/agent-runs/{run_id}`。使用 `docker compose --profile indexing down` 停止服务；命名卷中的数据库和上传文件默认保留。

### Web 工作台

需要 Node.js 22。API 与索引 worker 启动后，在另一个终端运行：

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

打开 Vite 输出的本机地址。开发服务器将 `/api` 代理至 `http://127.0.0.1:8000`。如需使用本机演示 JWT，把 `frontend/.env.local` 中的 `VITE_DEV_TOKEN_AUTH` 改为 `true`，刷新页面，然后粘贴上面 `backend/scripts/dev_token.py` 签发的 token。这个入口只在 Vite 开发模式出现；token 仅保存在当前页面内存，刷新或退出即清除。演示 token 一小时后过期，届时需重新签发。前端会引导管理员创建未开通的租户，也可以直接使用上面的 API 步骤。

“订单诊断”页使用合成订单数据；先按上面的 `seed_demo_orders.py` 命令为当前租户写入演示订单。诊断接口是同步响应，页面会显示执行中状态，完成后展示业务事实、知识库引用；管理员可在“运行轨迹”页查看步骤摘要、耗时和 token 用量。

“引用问答”页会在收到经过服务端核验的最终回答后保存对话，可新建、恢复和删除。每轮问题独立检索当前知识库，历史内容不会作为下一轮的模型上下文；临时流式草稿与失败请求不保存。接口及分页行为见[问答说明](docs/CITED_QA.md#对话历史)。

“检索调试”页可调整返回片段数和向量分数阈值，直接检查命中原文与章节；“文档与索引”可预览当前已发布分片。管理员可重建索引或移除文档；移除会删除原文件、任务和分片，已保存回答中的引用快照仍保留。若需替换文件内容，目前应移除旧文档再上传新版，期间不提供零停机版本切换。

如需对接企业 OIDC，在 `frontend/.env.local` 配置 `VITE_OIDC_AUTHORITY`、`VITE_OIDC_CLIENT_ID` 和可选的 `VITE_OIDC_SCOPE`。客户端使用 Authorization Code + PKCE，回调地址为 `<前端地址>/auth/callback`。身份服务还须签发后端接受的 RS256 JWT，包含 `sub`、`tenant_id`、`role`、`iss`、`aud`、`iat` 和 `exp`，并配置相同的签名公钥、issuer、audience；仅配置前端 OIDC 地址无法完成后端认证。生产环境需将 `/api` 与前端设为同源，或在可信反向代理中转发 API 请求。

## 开发与质量检查

本地安装：在 `backend/` 使用 Python 3.12 创建虚拟环境并运行 `pip install -e '.[test]'`。复制 `.env.example` 后，`DATABASE_URL` 指向宿主机 PostgreSQL；测试用户需要创建数据库和 `vector` 扩展的权限。

```bash
cd backend
ruff check app tests scripts alembic
ruff format --check app tests scripts alembic
alembic upgrade head
alembic check
pytest -q
```

CI 在 pgvector PostgreSQL 上执行迁移、迁移漂移检查、静态检查、格式检查和数据库集成测试，同时构建后端镜像，并通过 Chromium 检查工作台登录、上传、索引状态、问答、诊断及刷新后恢复。测试使用确定性的假模型和浏览器 API 模拟；[版本化 RAG 与 Agent 基准](docs/AGENT_TRACES_EVAL.md)可在显式启动模型后生成可比较的检索、引用、拒答和跨租户报告。旧三短文档留出集曾只有 5/6 精确引用；新增的独立多业务长文档验收集达到 15/15 精确引用，详情见[逐例结果和事实支撑复核](docs/GENERALIZATION_VALIDATION.md)。合成数据集不能代表真实业务质量。

前端检查使用 `cd frontend && npm run typecheck && npm run lint && npm run test && npm run build`。`backend/scripts/export_openapi.py` 导出后端契约，`npm run generate:api` 更新 TypeScript 类型；CI 检查两个生成文件与后端路由一致。

在 macOS Docker Compose 中接入宿主机 Ollama 时，按[模型接入说明](docs/MODEL_PROVIDERS.md#macos-docker-compose-与宿主机-ollama)配置可达地址，并运行 `backend/scripts/smoke_compose_models.py` 验证 Embedding、容器索引 worker、检索、问答及诊断。

希望按六份长文档逐项手动检查工作台，可使用[本地完整功能验收步骤](docs/LOCAL_ACCEPTANCE.md)。

## 设计与限制

- [代码边界与扩展点](docs/ARCHITECTURE.md) · [产品范围](docs/PRODUCT_SPEC.md) · [模型接入](docs/MODEL_PROVIDERS.md) · [租户隔离](docs/TENANCY.md) · [索引状态机](docs/INDEXING.md) · [检索](docs/RETRIEVAL.md) · [带引用问答](docs/CITED_QA.md) · [诊断工作流](docs/DIAGNOSTIC_WORKFLOW.md)
- [请求级可观测性](docs/OBSERVABILITY.md) · [运行轨迹与评测](docs/AGENT_TRACES_EVAL.md)
- [独立事实复核与恶意文档探针](docs/QUALITY_REVIEW.md)
- [可轮换身份验签与只读订单接口](docs/EXTERNAL_INTEGRATIONS.md)
- [模型请求运行保护](docs/RUNTIME_PROTECTION.md)
- [本地检索容量基准](docs/RETRIEVAL_CAPACITY.md)
- PDF 只提取文本，不含 OCR。默认上传上限为 10 MiB；上传文件保存在共享卷。生产部署还应在入口网关限制请求体大小。
- 引用校验确认来源属于本次授权检索结果，不能证明回答的每一句话在语义上成立。高风险结论仍需人工审核。
- 运行轨迹包含原问题与最终回答；应限制管理员访问并按 [保留说明](docs/AGENT_TRACES_EVAL.md) 定期清理。
- 本仓库是架构与工程实践示例。线上身份服务和真实订单系统需要各自的授权测试环境才能完成联调；目前提供可轮换 JWKS 验签与只读 HTTP 订单适配器，并用本地沙箱验证其契约。分布式限流和 OCR 尚未实现。

欢迎通过 Issue 描述可复现问题，或按 [贡献指南](CONTRIBUTING.md) 提交改进。许可证：[MIT](LICENSE)。
