# 本地检索容量基准

[`benchmark_retrieval_capacity.py`](../backend/scripts/benchmark_retrieval_capacity.py) 在一次性 PostgreSQL 数据库里生成 1536 维向量，并调用应用实际使用的 `search_knowledge_base`。它逐步增至 1,000、5,000 和 20,000 个当前版本切片；每档先预热三次，再测 20 次顺序查询与 20 次最高并发为 4 的查询。每次使用独立数据库会话、租户与知识库过滤、Top 5 和最低相似度 0.5。报告采用最近秩法计算 p50/p95。测试完成后删除临时数据库，不写入业务库。

2026-09-28 在本地 Docker Desktop PostgreSQL 16.15 上运行的[原始结果](evidence/retrieval_capacity.json)：

| 当前切片数 | 顺序 p50 / p95 | 并发 4 p50 / p95 |
| ---: | ---: | ---: |
| 1,000 | 16.72 / 26.00 ms | 34.80 / 99.74 ms |
| 5,000 | 48.61 / 58.47 ms | 74.15 / 89.64 ms |
| 20,000 | 233.45 / 243.17 ms | 320.78 / 324.82 ms |

复跑命令：

```bash
backend/.venv/bin/python backend/scripts/benchmark_retrieval_capacity.py \
  --sizes 1000 5000 20000 --trials 20 --concurrency 4 \
  --output docs/evidence/retrieval_capacity.json
```

该基准只测检索函数调用（含数据库会话和内存中的固定 Embedding），不测 HTTP、真实 Embedding/Chat 模型、索引吞吐或端到端用户延迟。合成切片内容相同，不能代表真实文档的相关性和重排质量；20 次样本也不足以声明生产环境 SLO。当前查询先按租户、知识库、活动版本和向量空间筛选，再对授权候选精确计算余弦距离。它避免向量近邻索引在租户过滤后丢失结果，但成本随知识库切片数增长。20,000 切片档顺序 p95 已达约 243 ms；更大语料或更高并发须在目标部署环境重新压测，并设计按租户及版本分区或召回率经过验证的索引策略，再定服务容量上限。
