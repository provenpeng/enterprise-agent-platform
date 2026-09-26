# 带来源引用的知识库问答

`POST /api/v1/knowledge-bases/{id}/ask` 使用与检索接口相同的租户授权和活动索引版本范围。请求包括 `query`、可选的 `top_k`（默认及最大值均为 10）和 `min_score`（默认 0.5）。`admin` 与 `viewer` 均可调用。实测默认取 5 个片段会漏掉相关政策章节，因此问答默认扩展到 10 个候选；调用方可显式调低 `top_k` 控制上下文长度与模型成本。

`POST /api/v1/knowledge-bases/{id}/ask/stream` 接受相同请求和权限，返回 `text/event-stream`。原有同步接口继续可用。浏览器应使用带 Bearer Token 的 `fetch` 读取响应流；原生 `EventSource` 只能发 GET，不能直接调用这个 POST 接口。

```json
{"query":"退款需要谁批准？","top_k":10,"min_score":0.5}
```

服务先检索并重排候选分片，为本次请求的候选分配短编号 `E1`、`E2` 等，再通过 LangChain `ChatOpenAI` 的结构化输出让模型引用这些编号。提示要求模型选择支持全部结论的最小充分来源集合；比较问题要覆盖每个独立方面，通用规则问题优先引用直接规则章节。服务端把有效编号映射回本次授权检索得到的 chunk UUID；只要有一个未知编号，就拒绝整条草稿。按模型给出的引用顺序去重并编号；最终回答中的 `来源：[1]` 等标记由服务端追加，响应的 `citations` 中提供对应的文档、页码、章节、分片正文和余弦分数。模型不能自己指定文档路径或引用元数据。

流式接口先完成授权、Embedding 和检索，再发响应头；这些步骤的失败仍返回常规 HTTP 状态。生成阶段使用同一证据编号、提示和服务端引用校验，通过 LangChain 的 JSON 部分解析器提取逐步增长的回答文本。事件顺序如下：

```text
event: status
data: {"phase":"generating"}

event: delta
data: {"text":"退款申请","provisional":true}

event: final
data: {"knowledge_base_id":"...","answer":"...","grounded":true,"citations":[...]}
```

`delta` 是**临时草稿**，尚未通过完整 JSON 和引用校验。客户端只有收到一次 `final` 后才能把 `final.answer` 与 `final.citations` 作为正式结果，并应以它们替换草稿；`final` 也可能是拒答。模型在响应头发出后失败或超时，服务发送 `error` 事件（`code: ANSWER_GENERATION_FAILED`），不再发送 `final`，客户端应丢弃草稿。连接在 `final` 或 `error` 前断开也视为失败；用户主动取消时关闭读取并中止请求。服务端会关闭上游模型流并释放并发槽。流式响应设置 `Cache-Control: no-cache, no-transform` 和 `X-Accel-Buffering: no`，部署网关仍需允许 SSE 透传，不得缓冲事件。不同模型的 token 边界不同，不保证每个 `delta` 对应一个字或词。
检索没有证据时，首个 `status.phase` 为 `no_evidence`，随后直接发送拒答 `final`，不会调用聊天模型。响应头之后的生成故障仍保持 HTTP 200，但访问日志的 `failure_type` 记录为 `AnswerGenerationFailed`，便于按请求 ID 定位。

没有检索证据时不调用生成模型。模型未给出回答、未引用证据或引用了结果集之外的 chunk 时，统一返回 `grounded: false`、空引用和“根据当前知识库资料，无法确定答案。”。同步接口的模型超时或故障返回 503；流式接口在响应头发出后通过 `error` 事件报告生成故障，均不暴露供应商异常。`ANSWER_MODEL` 默认 `gpt-4o-mini`，`ANSWER_GENERATION_TIMEOUT_SECONDS` 默认 30 秒；API 进程需要 `CHAT_API_KEY` 或回退使用 `OPENAI_API_KEY`。

来源内容在提示中作为不可信数据提供，系统提示要求模型忽略其中的指令。服务端验证引用 ID 的归属与版本，**不能自动证明回答中的每个事实都被引用内容支持**。聊天模型可使用独立的 `CHAT_API_KEY` 和 `CHAT_API_BASE_URL`，配置见 [模型接入](MODEL_PROVIDERS.md)。上线前应建立人工标注的问答评测集，监控拒答率、引用准确率和事实支持率；高风险场景仍需人工核验。数据库集成测试使用假 Embedding 与假生成器，不访问外部模型。

2026-09-26 的本机端到端检查使用同一已索引知识库提问退款与退货期限：`deepseek-chat` 的 `json_mode` 和本地 `qwen2.5:7b-instruct` 的 `json_schema` 均返回多个 `delta`、一个 `grounded: true` 的 `final`，最终引用分别覆盖退款申请时限与商品退货时限章节。该检查证明两种模型配置的流式协议可运行，不代表其他问题的事实正确率或引用质量达标。
