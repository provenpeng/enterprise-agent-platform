# Enterprise Agent Platform

面向企业知识检索与业务诊断的 AI Agent 平台。产品目标见 [产品规格](docs/PRODUCT_SPEC.md)。

目前已提供 FastAPI 应用、PostgreSQL 数据模型与 Alembic 迁移、知识库创建与查询、原始文档上传与登记，以及数据库连通性健康检查。文档解析、分片、向量化、检索、对话和 Agent 功能尚未实现。

## 环境要求

- Python 3.12
- Docker Engine 和 Docker Compose v2

## 快速开始

以下命令在仓库根目录执行。首次启动时，先复制本地配置并启动 PostgreSQL：

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

Compose 使用支持 pgvector 的 PostgreSQL 镜像，并将数据保存在命名卷中。确认 `docker compose ps` 显示数据库为 `healthy` 后，安装后端依赖并执行迁移：

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
alembic upgrade head
```

启动 API：

```bash
uvicorn app.main:app --reload
```

在另一个终端验证服务：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

数据库连接正常时返回 `{"status":"ok"}`；数据库不可用时返回 HTTP 503。交互式 API 文档位于 `http://127.0.0.1:8000/docs`。

创建知识库并上传文档：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge-bases \
  -H 'Content-Type: application/json' \
  -d '{"name":"Policies","description":"Business policies"}'
curl -X POST http://127.0.0.1:8000/api/v1/knowledge-bases/REPLACE_WITH_KB_ID/documents \
  -F 'file=@./example.txt;type=text/plain'
```

上传支持 PDF、Markdown 和 TXT，默认上限为 10 MiB（可通过 `MAX_UPLOAD_SIZE_BYTES` 调整）。原文件保存在根目录 `data/uploads/`，该目录不会提交到 Git。同一知识库内上传相同内容会返回 HTTP 409；成功登记的文档状态为 `UPLOADED`，活动索引版本为空。

知识库和文档列表接口均支持 `limit`、`offset` 查询参数，默认返回 20 条，`limit` 最大为 100。数据库中的 `storage_uri` 保存相对于 `data/uploads/` 的文件 key，API 响应不公开服务器文件路径。

停止数据库容器可在仓库根目录运行 `docker compose down`，此命令会保留数据库命名卷。

## 配置

根目录的 `.env.example` 是本地开发配置模板；复制后的 `.env` 已被 Git 忽略。Compose 从中读取 `POSTGRES_*` 变量，后端和 Alembic 从中读取 `DATABASE_URL`。如果修改数据库名称、用户、密码或宿主机端口，需要同步更新 `DATABASE_URL`。示例密码仅供本地开发使用。

## 测试

在 `backend/` 目录中激活虚拟环境后运行：

```bash
pip install -e '.[test]'
pytest
```

测试覆盖健康接口、知识库和上传链路，并使用临时 PostgreSQL 数据库验证真实文件写入及数据库失败后的清理。运行测试、在线迁移和健康检查需要运行中的 PostgreSQL；测试数据库用户需要有创建数据库的权限。

## 当前数据模型

`KnowledgeBase` 包含多个 `Document`，每个 `Document` 包含多个按 `index_version` 区分的 `Chunk`。删除知识库或文档时，数据库外键会级联删除下级记录。当前没有向量列；pgvector 镜像仅为后续选定嵌入模型和维度预留支持。

`Document.status` 表示最近一次处理尝试的状态。重建索引失败时，`status` 可以是 `FAILED`，而 `active_index_version` 仍指向可用的旧版本。后续处理流程应在新版本全部完成后，通过事务切换活动版本。

## 许可证

见 [LICENSE](LICENSE)。
