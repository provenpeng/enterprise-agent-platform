import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Empty, Input, InputNumber, Space, Tag, Typography } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { errorMessage, searchKnowledgeBase } from "../api/client";

export function SearchPanel({ token, knowledgeBaseId }: { token: string; knowledgeBaseId: string }) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [minScore, setMinScore] = useState(0.5);
  const search = useMutation({
    mutationFn: () => searchKnowledgeBase(token, knowledgeBaseId, query.trim(), topK, minScore),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim() && !search.isPending) search.mutate();
  }

  return (
    <Card className="workspace-card" title="检索调试">
      <Typography.Paragraph type="secondary">直接查看授权知识库中的检索片段、章节和向量相似度；问答会另行选择证据并生成结论。</Typography.Paragraph>
      <form onSubmit={submit} className="search-form">
        <label htmlFor="search-query" className="field-label">检索问题</label>
        <Input id="search-query" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={2000} placeholder="例如：供应商更换收款账户如何核验？" />
        <Space wrap>
          <label htmlFor="search-top-k">返回片段数</label>
          <InputNumber id="search-top-k" min={1} max={20} value={topK} onChange={(value) => setTopK(value ?? 5)} />
          <label htmlFor="search-min-score">最低向量分数</label>
          <InputNumber id="search-min-score" min={0} max={1} step={0.05} value={minScore} onChange={(value) => setMinScore(value ?? 0.5)} />
          <Button type="primary" htmlType="submit" icon={<SearchOutlined />} disabled={!query.trim()} loading={search.isPending}>检索</Button>
        </Space>
      </form>
      {search.isError && <Alert className="panel-alert" type="error" showIcon message={errorMessage(search.error)} />}
      {search.isSuccess && search.data.length === 0 && <Empty description="当前阈值下没有命中片段" />}
      {search.data?.map((hit, index) => (
        <Card size="small" key={hit.chunk_id} className="source-card">
          <Space wrap>
            <strong>{index + 1}. {hit.document_name}</strong>
            <Tag>向量分数 {hit.score.toFixed(3)}</Tag>
            <Tag>索引版本 {hit.index_version}</Tag>
            {hit.page_number && <Tag>第 {hit.page_number} 页</Tag>}
          </Space>
          {hit.section_path.length > 0 && <Typography.Text type="secondary">{hit.section_path.join(" / ")}</Typography.Text>}
          <Typography.Paragraph className="source-content">{hit.content}</Typography.Paragraph>
        </Card>
      ))}
    </Card>
  );
}
