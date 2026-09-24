# Enterprise Agent Platform

面向企业知识检索与业务诊断的 AI Agent 平台。产品目标见 [产品规格](docs/PRODUCT_SPEC.md)。

目前已提供知识库和文档 API、TXT/Markdown/PDF 解析、可切换的手动与 LangChain 分片、持久化索引任务、OpenAI Embedding 和 pgvector 存储。检索、带引用问答和业务 Agent 尚未实现。

## 环境要求

- Python 3.12
- Docker Engine 和 Docker Compose v2

## 快速开始

在仓库根目录复制配置。只体验 API 时可以不填 `OPENAI_API_KEY`；要处理索引任务，需要填入可用的密钥：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Compose 会启动 PostgreSQL、一次性迁移任务和 API。配置密钥后，启动独立索引 worker：

```bash
docker compose --profile indexing up -d
```

验证 API：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

数据库连接正常时返回 `{"status":"ok"}`；数据库不可用时返回 HTTP 503。交互式 API 文档位于 `http://127.0.0.1:8000/docs`。

本地开发也可以只用 Compose 启动 PostgreSQL，然后在 `backend/` 建立 Python 3.12 虚拟环境、运行 `pip install -e '.[test]'`、`alembic upgrade head`，分别启动 `uvicorn app.main:app --reload` 与 `python -m app.worker`。worker 需要 `OPENAI_API_KEY`。

创建知识库并上传虚构的示例规则：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge-bases \
  -H 'Content-Type: application/json' \
  -d '{"name":"Policies","description":"Demo policies"}'
curl -X POST http://127.0.0.1:8000/api/v1/knowledge-bases/REPLACE_WITH_KB_ID/documents \
  -F 'file=@./examples/refund_policy.md;type=text/markdown'
```

上传响应中的 `id` 是文档 ID。查看处理任务和活动分片，或请求重建索引：

```bash
curl http://127.0.0.1:8000/api/v1/documents/REPLACE_WITH_DOCUMENT_ID/index-jobs
curl http://127.0.0.1:8000/api/v1/documents/REPLACE_WITH_DOCUMENT_ID/chunks
curl -X POST http://127.0.0.1:8000/api/v1/documents/REPLACE_WITH_DOCUMENT_ID/index-jobs
```

上传支持 PDF、Markdown 和 TXT，默认上限为 10 MiB。同一知识库内上传相同内容会返回 HTTP 409。上传事务同时写入首个索引任务；worker 可离线恢复任务。原文件在本地开发时保存在 `data/uploads/`，在 Compose 中保存在共享命名卷。

知识库和文档列表接口均支持 `limit`、`offset` 查询参数，默认返回 20 条，`limit` 最大为 100。数据库中的 `storage_uri` 保存相对于 `data/uploads/` 的文件 key，API 响应不公开服务器文件路径。

停止容器可运行 `docker compose --profile indexing down`；默认保留数据库和上传文件的命名卷。

## 配置

根目录的 `.env.example` 是本地开发模板；复制后的 `.env` 已被 Git 忽略。Compose 从 `POSTGRES_*` 变量生成容器内部的数据库地址；本地 Python 进程从 `DATABASE_URL` 读取宿主机地址。修改数据库名称、用户、密码或宿主机端口时，需要同步更新本地 `DATABASE_URL`。示例密码仅供本地开发使用。

### 文档处理实现切换

`DOCUMENT_PROCESSING_BACKEND` 可设为 `manual`（默认）或 `langchain`。两种实现通过同一个 `DocumentProcessor` 接口输出 `ParsedDocument` 和 `ChunkCandidate`。TXT/Markdown 处理器接收文本字符串，PDF 处理器接收原始文件字节。新任务会记录创建时选择的实现，已有任务不会因配置变化而改变。

- `manual` 使用项目内的 TXT/Markdown 解析器及结构感知分片器。
- `langchain` 使用 LangChain 的 Markdown 标题分割器和递归文本分割器；TXT 无标题结构，以 LangChain `Document` 交给递归分割器。
- PDF 在两种模式下均由 pypdf 提取页面文本，再使用所选模式的文本解析与分片实现。分片保留页码；扫描件没有可提取文本时会明确报错，目前不提供 OCR。

切换实现后重启 API，再通过重建接口创建新索引任务。两种实现保持相同输出类型与来源字段，分片边界可以不同。索引任务的租约、重试与版本发布规则见 [索引设计](docs/INDEXING.md)。

## 测试

在 `backend/` 目录中激活虚拟环境后运行：

```bash
pip install -e '.[test]'
pytest
```

测试覆盖健康接口、上传事务、PDF 页码、索引重建、失败重试和过期 worker 的发布保护。数据库集成测试使用临时 PostgreSQL 数据库；测试用户需要有创建数据库和 `vector` 扩展的权限。GitHub Actions 在 pgvector PostgreSQL 上执行迁移与完整测试。

## 当前数据模型

`KnowledgeBase` 包含多个 `Document`；每个 `Document` 包含索引任务和按 `index_version` 区分的 `Chunk`。`Chunk.embedding` 为 1536 维向量，使用 HNSW 余弦索引。删除知识库或文档时，数据库外键级联删除下级记录。

`Document.status` 表示最近一次处理尝试的状态。重建失败时，`status` 可以是 `FAILED`，而 `active_index_version` 仍指向可用的旧版本。新版本的分片、向量和活动版本指针在同一事务内发布。

## 许可证

见 [LICENSE](LICENSE)。
