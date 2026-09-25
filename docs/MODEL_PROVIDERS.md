# 模型接口与本地验证

聊天和 Embedding 分别配置，均通过 OpenAI 兼容接口接入。默认使用 `OPENAI_API_KEY`、`gpt-4o-mini` 和 `text-embedding-3-small`；没有配置单独的 `CHAT_API_KEY` 或 `EMBEDDING_API_KEY` 时，两者回退到 `OPENAI_API_KEY`。密钥只放在被 Git 忽略的根目录 `.env`，不要提交真实凭据。

## 本地 Ollama

安装 Ollama 后拉取所需模型：

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:1.5b-instruct
```

在根目录 `.env` 中配置本机运行的后端：

```dotenv
EMBEDDING_API_KEY=ollama
EMBEDDING_API_BASE_URL=http://127.0.0.1:11434/v1
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_NATIVE_DIMENSIONS=768
CHAT_API_KEY=ollama
CHAT_API_BASE_URL=http://127.0.0.1:11434/v1
ANSWER_MODEL=qwen2.5:1.5b-instruct
CHAT_DISABLE_THINKING=false
```

如果 API 与 worker 在 Docker Compose 容器内运行，把两个 `127.0.0.1` 改为 `host.docker.internal`；容器中的 `127.0.0.1` 不指向宿主机。执行本地真实模型测试需在 `backend/` 安装 `.[test]` 依赖、启动 PostgreSQL，然后从仓库根目录运行：

```bash
EAP_LIVE_OLLAMA=1 backend/.venv/bin/pytest -q backend/tests/test_live_ollama.py
```

该测试在临时数据库中创建租户知识库、上传示例规则，使用真实 Embedding 完成索引，并经过检索、结构化问答和诊断；默认测试套件会跳过它。`nomic-embed-text` 原生输出 768 维，服务将尾部补零至现有的 1536 维 pgvector 列。补零保持同一模型内的余弦距离；检索按保存的 Embedding 模型过滤，避免跨模型比较。

## AIHubMix 免费聊天模型

把保存在本地的 AIHubMix 密钥填入 `CHAT_API_KEY`，配置：

```dotenv
CHAT_API_BASE_URL=https://aihubmix.com/v1
ANSWER_MODEL=glm-4.7-flash-free
CHAT_DISABLE_THINKING=true
```

`CHAT_DISABLE_THINKING` 只应对支持 `thinking: {type: disabled}` 的兼容模型开启。实测该免费模型在默认推理模式下可能把 512 个输出 token 全部用于推理，导致 JSON Schema 回答为空；关闭推理后普通回答可返回。模型列表中的 `-free` 不保证当时有可用通道，也不保证严格 JSON Schema 遵从。AIHubMix 对未充值账户可能限制免费调用次数；本项目不会自动改用付费模型。

Embedding 独立配置。若继续用本地 Ollama Embedding，保留上述 `EMBEDDING_*` 配置；若使用另一种 Embedding 模型，应配置其实际原生维度。当前存储列上限为 1536 维，不支持更高维度的模型。

切换 Embedding 模型后重启 API 和 worker，并为需要检索的文档创建重建任务。旧活动版本在重新索引前不会参与新模型的检索，以避免不同向量空间混算；索引失败时，旧版本仍保留，恢复原模型配置后可再次检索。聊天模型切换不要求重建索引。
