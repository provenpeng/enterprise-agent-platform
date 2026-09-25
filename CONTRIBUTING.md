# 贡献指南

感谢关注。这个仓库以可复现的工程实践为目标；提交变更时，请让问题、设计取舍和验证证据都能从 PR 中看清。

## 报告问题

请描述预期行为、实际行为、复现步骤及运行环境。涉及外部模型时，请注明模型名称、配置和输入的脱敏示例；不要提交 API 密钥、JWT、私钥或真实业务资料。

## 开发流程

1. 从最新的 `main` 创建针对单一主题的分支。行为修复、文档改进和依赖更新尽量分别提交；提交信息用简短的祈使句说明实际变更。
2. 在 `backend/` 安装 Python 3.12 环境：`pip install -e '.[test]'`。从根目录复制 `.env.example` 为 `.env`，按 README 启动 pgvector PostgreSQL。
3. 对行为变化补能证明边界的测试，包括租户权限、失败路径和事务/索引并发；不需要为纯格式改动添加镜像实现的测试。
4. 提交前运行：

   ```bash
   ruff check app tests scripts alembic
   ruff format --check app tests scripts alembic
   alembic upgrade head
   alembic check
   pytest -q
   ```

5. PR 说明应包含问题、实现选择、测试结果、数据迁移或兼容性影响。等待 CI 通过后使用 merge commit 合并，保留主题分支上的提交脉络。

## 设计约定

- 业务权限与租户条件应在数据库查询里显式体现；模型输出、文档内容和客户端输入均视为不可信。
- 外部模型调用不要持有数据库连接；长任务通过有租约的索引 worker 运行，发布版本要保持原子性。
- 文档处理实现通过 `DocumentProcessor` 契约切换。增加框架适配器时保持服务层与具体框架解耦。
- 新迁移只追加，不修改已经发布的迁移语义；同时更新 SQLAlchemy 模型和相关文档。
- README 中只描述已经实现且能够复现的功能；真实模型表现和安全保证应写清测量方法与限制。

项目采用 [MIT 许可证](LICENSE)。
