import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { diagnoseOrder } from "../api/client";
import { DiagnosticPanel } from "./DiagnosticPanel";

vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/client")>(),
  diagnoseOrder: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function renderPanel(canViewTrace: boolean, onOpenRun = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <DiagnosticPanel token="token" knowledgeBaseId="kb" canViewTrace={canViewTrace} onOpenRun={onOpenRun} />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("诊断问题"), { target: { value: "退款为什么失败？" } });
  fireEvent.click(screen.getByRole("button", { name: /运行诊断/ }));
  return onOpenRun;
}

it("shows a missing-order outcome without inventing a trace or citation", async () => {
  vi.mocked(diagnoseOrder).mockResolvedValue({
    run_id: null, knowledge_base_id: "kb", status: "NEEDS_ORDER_ID",
    answer: "请提供订单号。", order: null, citations: [],
  });
  renderPanel(false);
  await waitFor(() => expect(screen.getByText("请提供订单号。")).toBeTruthy());
  expect(screen.getByText("需要订单号")).toBeTruthy();
  expect(screen.queryByText("来源")).toBeNull();
  expect(screen.queryByText("查看运行轨迹")).toBeNull();
});

it("shows business facts and citations and opens the persisted trace for an admin", async () => {
  vi.mocked(diagnoseOrder).mockResolvedValue({
    run_id: "run-1", knowledge_base_id: "kb", status: "ANSWERED",
    answer: "退款失败，需人工审批 [1]。",
    order: {
      order_id: "DEMO-WINDOW", payment_status: "PAID", total_amount_cents: 10000,
      refundable_amount_cents: 8000, currency: "CNY", created_at: "2026-01-01T00:00:00Z",
      refund_attempts: [{ attempt_number: 1, status: "FAILED", reason_code: "WINDOW_EXPIRED", amount_cents: 2000, created_at: "2026-01-01T00:00:00Z" }],
    },
    citations: [{ number: 1, source: {
      chunk_id: "chunk", document_id: "doc", document_name: "规则.md", index_version: 1,
      chunk_index: 0, content: "超期需审批。", score: 0.9, page_number: null,
      section_title: "退款", section_path: ["政策", "退款"],
    } }],
  });
  const onOpenRun = renderPanel(true);
  await waitFor(() => expect(screen.getByText("退款失败，需人工审批 [1]。")).toBeTruthy());
  expect(screen.getByText("DEMO-WINDOW")).toBeTruthy();
  expect(screen.getByText("[1] 规则.md")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看运行轨迹" }));
  expect(onOpenRun).toHaveBeenCalledExactlyOnceWith("run-1");
});

it("rejects an invalid order ID before contacting the API", () => {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <DiagnosticPanel token="token" knowledgeBaseId="kb" canViewTrace={false} onOpenRun={vi.fn()} />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("诊断问题"), { target: { value: "退款为什么失败？" } });
  fireEvent.change(screen.getByLabelText("订单号（可选）"), { target: { value: "bad/order" } });
  expect(screen.getByText("订单号只支持英文字母、数字和连字符。")).toBeTruthy();
  expect(screen.getByRole("button", { name: /运行诊断/ }).hasAttribute("disabled")).toBe(true);
  expect(diagnoseOrder).not.toHaveBeenCalled();
});
