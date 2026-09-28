import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Input, List, Space, Tag, Typography } from "antd";
import { ApartmentOutlined } from "@ant-design/icons";
import { diagnoseOrder, errorMessage, getMyDiagnosis, listMyDiagnoses, type Diagnosis } from "../api/client";
import { CitationList } from "./CitationList";

const outcome: Record<Diagnosis["status"], { label: string; color: string }> = {
  ANSWERED: { label: "诊断完成", color: "success" },
  BUSINESS_FACTS_ONLY: { label: "仅有业务事实", color: "warning" },
  NEEDS_ORDER_ID: { label: "需要订单号", color: "processing" },
  ORDER_NOT_FOUND: { label: "未找到订单", color: "warning" },
};
const paymentStatus = { PAID: "已支付", UNPAID: "未支付", REFUNDED: "已退款" };
const refundStatus = { PENDING: "处理中", FAILED: "失败", SUCCEEDED: "成功" };

function OrderDetails({ order }: { order: NonNullable<Diagnosis["order"]> }) {
  return (
    <section className="diagnostic-order" aria-label="订单快照">
      <Typography.Title level={5}>订单快照</Typography.Title>
      <Descriptions size="small" bordered column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="订单号">{order.order_id}</Descriptions.Item>
        <Descriptions.Item label="支付状态">{paymentStatus[order.payment_status]}</Descriptions.Item>
        <Descriptions.Item label="订单金额">{order.currency} {(order.total_amount_cents / 100).toFixed(2)}</Descriptions.Item>
        <Descriptions.Item label="可退金额">{order.currency} {(order.refundable_amount_cents / 100).toFixed(2)}</Descriptions.Item>
      </Descriptions>
      {order.refund_attempts.length > 0 && (
        <div className="refund-attempts">
          <Typography.Text strong>退款尝试</Typography.Text>
          {order.refund_attempts.map((attempt) => (
            <div key={attempt.attempt_number} className="refund-attempt">
              <span>第 {attempt.attempt_number} 次 · {refundStatus[attempt.status]}</span>
              <span>{attempt.reason_code || "无原因代码"}</span>
              <span>{order.currency} {(attempt.amount_cents / 100).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function DiagnosticPanel({ token, knowledgeBaseId, canViewTrace, onOpenRun }: {
  token: string; knowledgeBaseId: string; canViewTrace: boolean; onOpenRun: (runId: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [orderId, setOrderId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [historyPage, setHistoryPage] = useState(0);
  const queryClient = useQueryClient();
  const history = useQuery({
    queryKey: ["my-diagnoses", knowledgeBaseId, historyPage],
    queryFn: () => listMyDiagnoses(token, knowledgeBaseId, historyPage * 10, 10),
  });
  const selected = useQuery({
    queryKey: ["my-diagnosis", knowledgeBaseId, selectedRunId],
    queryFn: () => getMyDiagnosis(token, knowledgeBaseId, selectedRunId!),
    enabled: !!selectedRunId,
  });
  const invalidOrderId = !!orderId.trim() && !/^[A-Za-z0-9-]+$/.test(orderId.trim());
  const diagnosis = useMutation({
    mutationFn: () => diagnoseOrder(token, knowledgeBaseId, question.trim(), orderId.trim() || null),
    onSuccess: async (created) => {
      setSelectedRunId(created.run_id || null);
      setHistoryPage(0);
      await queryClient.invalidateQueries({ queryKey: ["my-diagnoses", knowledgeBaseId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim() && !invalidOrderId && !diagnosis.isPending) {
      setSelectedRunId(null);
      diagnosis.mutate();
    }
  }
  const result = selectedRunId
    ? selected.data?.response || (diagnosis.data?.run_id === selectedRunId ? diagnosis.data : undefined)
    : diagnosis.data;
  const runId = result?.run_id;
  return (
    <Card className="workspace-card" title="订单诊断 Agent" extra={<Tag color="purple">LangGraph</Tag>}>
      <Typography.Paragraph type="secondary">Agent 会读取当前租户的订单，检索当前知识库的规则，再给出可核对的结论。</Typography.Paragraph>
      <form onSubmit={submit} className="diagnostic-form">
        <label htmlFor="diagnostic-question" className="field-label">诊断问题</label>
        <Input.TextArea
          id="diagnostic-question"
          rows={3}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={2000}
          showCount
          placeholder="例如：DEMO-WINDOW 为什么退款失败？"
        />
        <label htmlFor="diagnostic-order-id" className="field-label">订单号（可选）</label>
        <Input
          id="diagnostic-order-id"
          value={orderId}
          onChange={(event) => setOrderId(event.target.value)}
          maxLength={64}
          status={invalidOrderId ? "error" : undefined}
          aria-invalid={invalidOrderId}
          placeholder="例如：DEMO-WINDOW"
        />
        {invalidOrderId && <Typography.Text type="danger">订单号只支持英文字母、数字和连字符。</Typography.Text>}
        <Button type="primary" htmlType="submit" icon={<ApartmentOutlined />} disabled={!question.trim() || invalidOrderId} loading={diagnosis.isPending}>
          运行诊断
        </Button>
      </form>
      {diagnosis.isError && <Alert className="panel-alert" type="error" showIcon message={errorMessage(diagnosis.error)} />}
      {diagnosis.isPending && <Alert className="panel-alert" type="info" showIcon message="Agent 正在执行，诊断结果将在完成后显示。" />}
      {selectedRunId && selected.isPending && <Typography.Text type="secondary">正在恢复诊断结果…</Typography.Text>}
      {selectedRunId && selected.isError && <Alert className="panel-alert" type="error" showIcon message={errorMessage(selected.error)} />}
      {result && !diagnosis.isPending && (
        <section className="answer-result" aria-live="polite">
          <Space wrap>
            <Tag color={outcome[result.status].color}>{outcome[result.status].label}</Tag>
            {canViewTrace && runId && <Button size="small" onClick={() => onOpenRun(runId)}>查看运行轨迹</Button>}
          </Space>
          <Typography.Paragraph className="answer-text">{result.answer}</Typography.Paragraph>
          {result.order && <OrderDetails order={result.order} />}
          <CitationList citations={result.citations} />
        </section>
      )}
      {!result && !diagnosis.isPending && !diagnosis.isError && <Empty className="answer-empty" description="输入订单问题，查看业务事实、规则引用与诊断结论" />}
      <section className="diagnostic-history" aria-label="诊断历史">
        <Typography.Title level={5}>我的诊断历史</Typography.Title>
        {history.isError && <Alert type="error" showIcon message={errorMessage(history.error)} />}
        <List
          size="small"
          loading={history.isPending}
          dataSource={history.data || []}
          locale={{ emptyText: "暂无诊断历史" }}
          renderItem={(item) => <List.Item actions={[<Button key="open" type="link" size="small" onClick={() => setSelectedRunId(item.id)}>恢复结果</Button>]}>
            <List.Item.Meta title={item.question} description={`${new Date(item.started_at).toLocaleString("zh-CN")} · ${item.outcome || "已完成"}`} />
          </List.Item>}
        />
        {(historyPage > 0 || (history.data?.length || 0) === 10) && <Space>
          <Button size="small" disabled={historyPage === 0} onClick={() => setHistoryPage((value) => value - 1)}>上一页</Button>
          <span>第 {historyPage + 1} 页</span>
          <Button size="small" disabled={(history.data?.length || 0) < 10} onClick={() => setHistoryPage((value) => value + 1)}>下一页</Button>
        </Space>}
      </section>
    </Card>
  );
}
