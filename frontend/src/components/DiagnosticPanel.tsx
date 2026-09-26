import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Input, Space, Tag, Typography } from "antd";
import { ApartmentOutlined } from "@ant-design/icons";
import { diagnoseOrder, errorMessage, type Diagnosis } from "../api/client";
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
  const invalidOrderId = !!orderId.trim() && !/^[A-Za-z0-9-]+$/.test(orderId.trim());
  const diagnosis = useMutation({
    mutationFn: () => diagnoseOrder(token, knowledgeBaseId, question.trim(), orderId.trim() || null),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim() && !invalidOrderId && !diagnosis.isPending) diagnosis.mutate();
  }
  const result = diagnosis.data;
  const runId = result?.run_id;
  return (
    <Card className="workspace-card" title="订单诊断 Agent" extra={<Tag color="purple">LangGraph</Tag>}>
      <Typography.Paragraph type="secondary">Agent 会读取当前租户的演示订单，检索当前知识库的规则，再给出可核对的结论。</Typography.Paragraph>
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
    </Card>
  );
}
