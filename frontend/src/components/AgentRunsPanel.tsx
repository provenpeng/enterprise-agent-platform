import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Space, Table, Tag, Timeline, Typography } from "antd";
import { getAgentRun, listAgentRuns, errorMessage, type AgentRunSummary } from "../api/client";

const PAGE_SIZE = 20;
const stepNames: Record<string, string> = {
  plan: "规划路由",
  lookup_order: "读取订单",
  retrieve_policy: "检索规则",
  compose: "形成结论",
};
const runStatus: Record<AgentRunSummary["status"], string> = {
  RUNNING: "运行中", SUCCEEDED: "成功", FAILED: "失败",
};

function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function JsonFacts({ label, value }: { label: string; value: Record<string, unknown> }) {
  if (Object.keys(value).length === 0) return null;
  return (
    <details className="step-facts">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function AgentRunsPanel({ token, selectedRunId, onSelectRun }: {
  token: string; selectedRunId: string | null; onSelectRun: (runId: string) => void;
}) {
  const [page, setPage] = useState(0);
  const runs = useQuery({
    queryKey: ["agent-runs", page],
    queryFn: () => listAgentRuns(token, page * PAGE_SIZE, PAGE_SIZE),
    refetchInterval: (query) => query.state.data?.some((run) => run.status === "RUNNING") ? 3000 : false,
  });
  const detail = useQuery({
    queryKey: ["agent-run", selectedRunId],
    queryFn: () => getAgentRun(token, selectedRunId!),
    enabled: !!selectedRunId,
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 3000 : false,
  });
  const rows = runs.data || [];
  return (
    <div className="runs-stack">
      <Card className="workspace-card" title="运行记录" extra={<Button size="small" onClick={() => void runs.refetch()}>刷新</Button>}>
        <Typography.Paragraph type="secondary">仅租户管理员可查看。轨迹包含原始问题与结论，请按敏感运行数据管理。</Typography.Paragraph>
        {runs.isError && <Alert type="error" showIcon message={errorMessage(runs.error)} />}
        <Table<AgentRunSummary>
          rowKey="id"
          size="small"
          loading={runs.isPending}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 640 }}
          locale={{ emptyText: <Empty description="暂无运行记录" /> }}
          columns={[
            { title: "问题", dataIndex: "question", key: "question", ellipsis: true },
            { title: "状态", key: "status", width: 110, render: (_, row) => <Tag color={row.status === "SUCCEEDED" ? "success" : row.status === "FAILED" ? "error" : "processing"}>{runStatus[row.status]}</Tag> },
            { title: "耗时", key: "duration", width: 100, render: (_, row) => row.duration_ms === null ? "—" : `${row.duration_ms} ms` },
            { title: "开始时间", key: "started", width: 170, render: (_, row) => formatTime(row.started_at) },
            { title: "操作", key: "actions", width: 90, render: (_, row) => <Button type="link" size="small" onClick={() => onSelectRun(row.id)}>查看</Button> },
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
      {selectedRunId && (
        <Card className="workspace-card" title="运行轨迹">
          {detail.isPending && <Typography.Text type="secondary">正在加载轨迹…</Typography.Text>}
          {detail.isError && <Alert type="error" showIcon message={errorMessage(detail.error)} action={<Button size="small" onClick={() => void detail.refetch()}>重试</Button>} />}
          {detail.data && (
            <>
              <Descriptions size="small" column={{ xs: 1, sm: 2 }} className="run-metadata">
                <Descriptions.Item label="问题">{detail.data.question}</Descriptions.Item>
                <Descriptions.Item label="结果">{detail.data.outcome || detail.data.status}</Descriptions.Item>
                <Descriptions.Item label="知识库">{detail.data.knowledge_base_id || "—"}</Descriptions.Item>
                <Descriptions.Item label="模型">{detail.data.model_name}</Descriptions.Item>
                <Descriptions.Item label="耗时">{detail.data.duration_ms === null ? "—" : `${detail.data.duration_ms} ms`}</Descriptions.Item>
                <Descriptions.Item label="Token 用量">{detail.data.total_tokens ?? "未提供"}</Descriptions.Item>
                {detail.data.error_code && <Descriptions.Item label="错误代码">{detail.data.error_code}</Descriptions.Item>}
              </Descriptions>
              {detail.data.answer && <Typography.Paragraph className="answer-text">{detail.data.answer}</Typography.Paragraph>}
              <Timeline className="run-timeline" items={detail.data.steps.map((step) => ({
                color: step.error_code ? "red" : "green",
                children: (
                  <div>
                    <strong>{step.sequence}. {stepNames[step.name] || step.name}</strong>
                    <Space size="small" wrap className="step-meta">
                      <Tag>{step.duration_ms} ms</Tag>
                      {step.total_tokens !== null && <Tag>{step.total_tokens} tokens</Tag>}
                      {step.error_code && <Tag color="error">{step.error_code}</Tag>}
                    </Space>
                    <JsonFacts label="输入摘要" value={step.input_data} />
                    <JsonFacts label="输出摘要" value={step.output_data} />
                  </div>
                ),
              }))} />
            </>
          )}
        </Card>
      )}
    </div>
  );
}
