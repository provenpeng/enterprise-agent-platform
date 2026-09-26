import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Empty, Space, Table, Tag, Tooltip, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import { ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import {
  errorMessage, listDocuments, listIndexJobs, reindexDocument, uploadDocument,
  type Document,
} from "../api/client";

const PAGE_SIZE = 20;
const inProgress = new Set<Document["status"]>(["UPLOADED", "PARSING", "CHUNKING", "EMBEDDING"]);
const statusText: Record<Document["status"], string> = {
  UPLOADED: "排队中", PARSING: "解析中", CHUNKING: "分片中",
  EMBEDDING: "向量化中", READY: "可检索", FAILED: "索引失败",
};

function FailedJob({ token, documentId }: { token: string; documentId: string }) {
  const jobs = useQuery({
    queryKey: ["index-jobs", documentId],
    queryFn: () => listIndexJobs(token, documentId),
  });
  const reason = jobs.data?.[0]?.last_error;
  return <Tooltip title={reason || "索引失败，可重新提交"}><Tag color="error">索引失败</Tag></Tooltip>;
}

export function DocumentsPanel({ token, knowledgeBaseId, canWrite }: {
  token: string; knowledgeBaseId: string; canWrite: boolean;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const documents = useQuery({
    queryKey: ["documents", knowledgeBaseId, page],
    queryFn: () => listDocuments(token, knowledgeBaseId, page * PAGE_SIZE, PAGE_SIZE),
    refetchInterval: (query) => query.state.data?.some((document) => inProgress.has(document.status)) ? 3000 : false,
  });
  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(token, knowledgeBaseId, file),
    onSuccess: async () => {
      setFileList([]);
      setPage(0);
      await queryClient.invalidateQueries({ queryKey: ["documents", knowledgeBaseId] });
      message.success("文档已上传，索引任务正在处理");
    },
  });
  const reindex = useMutation({
    mutationFn: (documentId: string) => reindexDocument(token, documentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents", knowledgeBaseId] });
      message.success("已重新提交索引任务");
    },
  });

  const selected = fileList[0]?.originFileObj;
  const rows = documents.data || [];
  return (
    <Card
      className="workspace-card"
      title="文档与索引"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => void documents.refetch()}>刷新</Button>}
    >
      <Typography.Paragraph type="secondary">上传 TXT、Markdown 或文本型 PDF。索引完成后即可用于检索问答。</Typography.Paragraph>
      {canWrite && (
        <Space className="upload-controls" wrap>
          <Upload
            accept=".txt,.md,.pdf"
            maxCount={1}
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setFileList(next)}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Button type="primary" disabled={!selected} loading={upload.isPending} onClick={() => selected && upload.mutate(selected)}>
            上传并索引
          </Button>
        </Space>
      )}
      {upload.isError && <Alert type="error" showIcon className="panel-alert" message={errorMessage(upload.error)} />}
      {reindex.isError && <Alert type="error" showIcon className="panel-alert" message={errorMessage(reindex.error)} />}
      {documents.isError && <Alert type="error" showIcon className="panel-alert" message={errorMessage(documents.error)} />}
      <Table<Document>
        className="document-table"
        rowKey="id"
        size="small"
        loading={documents.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无文档" /> }}
        scroll={{ x: 520 }}
        columns={[
          { title: "文件", dataIndex: "filename", key: "filename", ellipsis: true },
          { title: "索引状态", key: "status", width: 125, render: (_, row) => row.status === "FAILED"
            ? <FailedJob token={token} documentId={row.id} />
            : <Tag color={row.status === "READY" ? "success" : "processing"}>{statusText[row.status]}</Tag> },
          { title: "版本", key: "version", width: 70, render: (_, row) => row.active_index_version ?? "—" },
          ...(canWrite ? [{ title: "操作", key: "actions", width: 90, render: (_: unknown, row: Document) => row.status === "FAILED"
            ? <Button type="link" size="small" loading={reindex.isPending && reindex.variables === row.id} onClick={() => reindex.mutate(row.id)}>重试</Button>
            : null }] : []),
        ]}
      />
      {(page > 0 || rows.length === PAGE_SIZE) && (
        <Space className="pagination-controls">
          <Button disabled={page === 0} onClick={() => setPage((value) => value - 1)}>上一页</Button>
          <span>第 {page + 1} 页</span>
          <Button disabled={rows.length < PAGE_SIZE} onClick={() => setPage((value) => value + 1)}>下一页</Button>
        </Space>
      )}
    </Card>
  );
}
