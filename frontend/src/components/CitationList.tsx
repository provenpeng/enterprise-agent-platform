import { Card, Space, Tag, Typography } from "antd";
import type { Answer } from "../api/client";

export function CitationList({ citations }: { citations: Answer["citations"] }) {
  if (citations.length === 0) return null;
  return (
    <section aria-label="回答来源" className="sources">
      <Typography.Title level={5}>来源</Typography.Title>
      {citations.map(({ number, source }) => (
        <Card key={`${number}-${source.chunk_id}`} size="small" className="source-card">
          <div className="source-heading">
            <strong>[{number}] {source.document_name}</strong>
            <Space wrap size={4}>
              {source.section_path.length > 0 && <Tag>{source.section_path.join(" / ")}</Tag>}
              {source.section_path.length === 0 && source.section_title && <Tag>{source.section_title}</Tag>}
              {source.page_number !== null && <Tag>第 {source.page_number} 页</Tag>}
            </Space>
          </div>
          <Typography.Paragraph className="source-content">{source.content}</Typography.Paragraph>
        </Card>
      ))}
    </section>
  );
}
