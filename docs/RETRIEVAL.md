# 知识库检索

`POST /api/v1/knowledge-bases/{id}/search` 使用已签名 JWT 中的 `tenant_id` 授权知识库，再为查询生成 Embedding。`admin` 和 `viewer` 都可检索；不存在或其他租户的知识库统一返回 404，不会调用模型。

请求示例：

```json
{"query":"退款需要谁批准？","top_k":5,"min_score":0.5}
```

`top_k` 范围为 1–20；`min_score` 范围为 0–1。响应的 `hits` 按余弦相似度降序排列，同分时按分片 ID 稳定排序。每条命中包含分片 ID、文档 ID 与文件名、索引版本、分片序号、正文、页码、章节标题及章节路径，供后续问答接口生成和验证来源引用。分数为 `1 - cosine_distance`，截断至 0–1。没有命中时返回空数组。

## 数据与隔离边界

查询只读取所请求租户和知识库的文档，且只读取 `Document.active_index_version` 指向的分片。尚未发布或已被新版本替代的分片不会出现。重建失败时活动版本仍可检索。SQL 使用 PostgreSQL `MATERIALIZED` CTE 先筛出授权的活动分片，再做精确余弦距离排序和 Top-K，防止全局 ANN 候选集经过租户过滤后数量不足。代价是大知识库检索时需要计算其全部活动向量的距离；将来若引入分区或租户内 ANN，需要用同一套租户、版本和 Recall@K 测试验证结果。

查询 Embedding 与索引使用相同的 1536 维 `text-embedding-3-small` 配置。API 进程需要 `OPENAI_API_KEY`；未配置、超时或模型返回无效向量时返回 503。API 使用独立的 `RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS`（默认 15 秒），不影响 worker 的索引超时。服务端日志记录故障，响应不会泄露供应商异常或密钥。

`backend/tests/test_retrieval.py` 用固定向量和真实 pgvector 数据库验证排序、阈值、Top-K、活动版本、未发布分片、跨租户授权、viewer 权限和供应商故障，不消耗模型额度。线上语义质量仍需有标注的真实查询集持续衡量；当前固定向量测试验证检索契约，不代表自然语言 Recall@K。
