import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getAgentRun, listAgentRuns, type AgentRunDetail, type AgentRunSummary } from "../api/client";
import { AgentRunsPanel } from "./AgentRunsPanel";

vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/client")>(),
  getAgentRun: vi.fn(),
  listAgentRuns: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const summary: AgentRunSummary = {
  id: "run-1", knowledge_base_id: "kb", question: "退款为什么失败？", model_name: "deepseek-chat",
  status: "SUCCEEDED", outcome: "ANSWERED", answer: "需要审批", error_code: null,
  input_tokens: 10, output_tokens: 20, total_tokens: 30, duration_ms: 400,
  started_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:00:01Z",
};
const detail: AgentRunDetail = {
  ...summary,
  steps: [{ sequence: 1, name: "plan", input_data: { question_present: true },
    output_data: { route: "lookup_order" }, error_code: null, input_tokens: 10,
    output_tokens: 5, total_tokens: 15, duration_ms: 120, created_at: "2026-01-01T00:00:00Z" }],
};

it("opens an admin run and renders the recorded steps", async () => {
  vi.mocked(listAgentRuns).mockResolvedValue([summary]);
  vi.mocked(getAgentRun).mockResolvedValue(detail);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSelectRun = vi.fn();
  const { rerender } = render(
    <QueryClientProvider client={queryClient}>
      <AgentRunsPanel token="token" selectedRunId={null} onSelectRun={onSelectRun} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("退款为什么失败？")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "查看" }));
  expect(onSelectRun).toHaveBeenCalledExactlyOnceWith("run-1");
  rerender(
    <QueryClientProvider client={queryClient}>
      <AgentRunsPanel token="token" selectedRunId="run-1" onSelectRun={onSelectRun} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText(/规划路由/)).toBeTruthy());
  expect(screen.getByText("deepseek-chat")).toBeTruthy();
  expect(screen.getByText("输出摘要")).toBeTruthy();
  expect(getAgentRun).toHaveBeenCalledExactlyOnceWith("token", "run-1");
});
