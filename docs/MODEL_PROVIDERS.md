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
EMBEDDING_REVISION=default
CHAT_API_KEY=ollama
CHAT_API_BASE_URL=http://127.0.0.1:11434/v1
ANSWER_MODEL=qwen2.5:1.5b-instruct
CHAT_DISABLE_THINKING=false
CHAT_STRUCTURED_OUTPUT_METHOD=json_schema
```

如果 API 与 worker 在 Docker Compose 容器内运行，把两个 `127.0.0.1` 改为 `host.docker.internal`；容器中的 `127.0.0.1` 不指向宿主机。执行本地真实模型测试需在 `backend/` 安装 `.[test]` 依赖、启动 PostgreSQL，然后从仓库根目录运行：

```bash
EAP_LIVE_MODELS=1 backend/.venv/bin/pytest -q backend/tests/test_live_model_pipeline.py
```

该测试在临时数据库中创建租户知识库、上传示例规则，使用真实 Embedding 完成索引，并经过检索、结构化问答和诊断；聊天模型可以是 Ollama 或下述兼容服务，普通测试套件会跳过它。`nomic-embed-text` 原生输出 768 维，服务将尾部补零至现有的 1536 维 pgvector 列。补零保持同一向量空间内的余弦距离；检索按索引时记录的向量空间标识过滤。

## AIHubMix 免费聊天模型

把保存在本地的 AIHubMix 密钥填入 `CHAT_API_KEY`，配置：

```dotenv
CHAT_API_BASE_URL=https://aihubmix.com/v1
ANSWER_MODEL=glm-4.7-flash-free
CHAT_DISABLE_THINKING=true
```

`CHAT_DISABLE_THINKING` 只应对支持 `thinking: {type: disabled}` 的兼容模型开启。实测该免费模型在默认推理模式下可能把 512 个输出 token 全部用于推理，导致 JSON Schema 回答为空；关闭推理后普通回答可返回。模型列表中的 `-free` 不保证当时有可用通道，也不保证严格 JSON Schema 遵从。AIHubMix 对未充值账户可能限制免费调用次数；本项目不会自动改用付费模型。

## DeepSeek 聊天模型

保持上述 Ollama Embedding 配置，将聊天配置改为：

```dotenv
CHAT_API_KEY=<your-deepseek-api-key>
CHAT_API_BASE_URL=https://api.deepseek.com
ANSWER_MODEL=deepseek-chat
CHAT_STRUCTURED_OUTPUT_METHOD=json_mode
CHAT_DISABLE_THINKING=false
```

实测 DeepSeek 当前拒绝严格 `json_schema` 响应格式并返回 HTTP 400，但接受 JSON object 模式。`json_mode` 会在提示中提供目标 Pydantic schema，模型输出仍经过解析和服务端引用 ID 校验。它是付费接口；上述真实链路测试只有在显式设置 `EAP_LIVE_MODELS=1` 时运行，不进入 CI。

Embedding 独立配置。若继续用本地 Ollama Embedding，保留上述 `EMBEDDING_*` 配置；若使用另一种 Embedding 模型，应配置其实际原生维度。当前存储列上限为 1536 维，不支持更高维度的模型。

向量空间标识由 Embedding 接口 URL、模型名、原生维度和 `EMBEDDING_REVISION` 计算；它不包含密钥。服务无法探测同一 URL 和模型名背后的权重是否发生变化，因此供应商更换权重或本地模型文件后，运维人员必须显式修改 `EMBEDDING_REVISION`。API 与 worker 的上述四项配置必须一致；待处理任务与 worker 的空间不一致时会失败，需用当前配置重新入队。

切换任一空间参数后重启 API 和 worker，并为需要检索的文档创建重建任务。旧活动版本在重新索引前不会参与新空间的检索；索引失败时，旧版本仍保留，恢复旧配置后可再次检索。聊天模型切换不要求重建索引。

升级到包含向量空间标识的版本后，历史任务缺少供应商地址和原生维度，无法可靠补写标识；其旧分片在重建前不会参与检索。按租户预览并显式创建重建任务：

```bash
docker compose run --rm api python scripts/reindex_embedding_space.py --tenant-id "$TENANT_ID"
docker compose run --rm api python scripts/reindex_embedding_space.py --tenant-id "$TENANT_ID" --apply
```

命令按文档 ID 分批扫描活动索引，默认仅预览；`--apply` 对每个不匹配的文档调用有租户校验的重建服务，已有待执行或运行任务会标为 `SKIPPED_ACTIVE_JOB`。确认 worker 运行并等待新任务成功后，检索会恢复命中。建议在切换期间监控失败任务；重建需要原始上传文件仍可读取。大租户可通过 `--batch-size` 调整每次扫描数量。
