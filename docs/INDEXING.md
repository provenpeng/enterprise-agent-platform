# 文档索引设计

## 任务与事务边界

上传接口将 `Document` 与第一个 `IndexJob` 写入同一数据库事务。原文件写入失败或数据库提交失败时，上传服务清理临时文件。独立 worker 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取到期任务；因此 API 重启不会丢失已提交的任务。

任务记录创建时的解析后端与版本、Embedding 模型、tokenizer、分片限制、批量大小和目标索引版本。修改 `DOCUMENT_PROCESSING_BACKEND` 后，需重启 API 并调用 `POST /api/v1/documents/{id}/index-jobs` 创建新任务。已有任务继续使用其记录的处理参数。一个文档同一时间只允许一个待执行或运行中的任务。

## 执行与恢复

worker 领取任务时增加 `attempts`，设置租约，并将文档状态更新为 `PARSING`。随后校验原文件 SHA-256，解析和分片，再按批调用 LangChain `OpenAIEmbeddings`。处理阶段显示为 `PARSING`、`CHUNKING`、`EMBEDDING`。任务在批次之间续租；单次 Embedding 调用有独立超时，必须至少比租约短 30 秒。进程崩溃后，其他 worker 可领取租约过期的任务。

每次领取都有递增的尝试次数。旧 worker 在续租、失败记录和发布结果前核对任务状态与尝试次数；被重新领取的旧尝试不能覆盖新结果。暂时性错误延迟重试，默认最多尝试 3 次；无效文件、校验失败和配置错误直接标记失败。API 只返回经过筛选的错误描述，详细异常留在 worker 日志。

完整的分片和向量在单个数据库事务中写入，同时切换 `Document.active_index_version`。失败时活动版本不变。成功后保留新版本和上一个已发布版本的分片，用于回滚并控制存储增长。读取活动分片的 API 仅返回当前活动版本。

## 模型与边界

默认使用 `text-embedding-3-small` 的 1536 维输出和 pgvector 存储。当前检索先物化租户内已发布分片，再进行精确余弦排序；全局 HNSW 索引无法服务这条查询，因此不再维护。分片表的唯一索引已有 `(document_id, index_version, chunk_index)` 前缀，可满足按文档与版本读取，也不再重复维护同前缀的普通索引。OpenAI 兼容 Embedding 接口也可接入本地 Ollama；原生维度低于 1536 时补零，详情见 [模型接入](MODEL_PROVIDERS.md)。分片目标为 400 token、硬上限为 600 token，每个文档最多 1000 个分片，每批最多 32 个分片。worker 使用 `EMBEDDING_API_KEY`，未设置时回退到 `OPENAI_API_KEY`。普通测试注入确定性的假 Embedding，不访问外部服务。

PDF 只处理可提取的文本，不提供 OCR。索引完成文档到向量的写入；知识库检索见 [检索设计](RETRIEVAL.md)，引用与问答见 [问答设计](CITED_QA.md)。
