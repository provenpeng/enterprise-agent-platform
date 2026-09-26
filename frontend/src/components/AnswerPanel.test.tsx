import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnswerPanel } from "./AnswerPanel";
import { streamAnswer } from "../api/answerStream";
import { deleteConversation, getConversation, listConversations } from "../api/client";

vi.mock("../api/answerStream", () => ({ streamAnswer: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/client")>(),
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

const citation = { number: 1, source: {
  chunk_id: "chunk", document_id: "doc", document_name: "退款政策.md",
  index_version: 1, chunk_index: 0, content: "退款需经理审批。", score: 0.9,
  page_number: null, section_title: "退款", section_path: ["政策", "退款"],
} };
const final = {
  knowledge_base_id: "kb", conversation_id: "conversation", answer: "需要审批 [1]。", grounded: true,
  citations: [citation],
};
const saved = {
  id: "conversation", knowledge_base_id: "kb", title: "退款条件？",
  created_at: "2026-09-26T10:00:00Z", updated_at: "2026-09-26T10:00:00Z",
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AnswerPanel token="token" knowledgeBaseId="kb" /></QueryClientProvider>);
}

function submit() {
  fireEvent.change(screen.getByLabelText("向当前知识库提问"), { target: { value: "退款条件？" } });
  fireEvent.click(screen.getByRole("button", { name: /获取回答/ }));
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("drops provisional text if generation fails without opening a history entry", async () => {
  vi.mocked(listConversations).mockResolvedValue([]);
  vi.mocked(streamAnswer).mockImplementation(async (_token, _kb, _query, onDelta) => {
    onDelta("尚未核验的答案");
    throw new Error("模型生成失败，请重试");
  });
  renderPanel();
  submit();
  await waitFor(() => expect(screen.getByText("模型生成失败，请重试")).toBeTruthy());
  expect(screen.queryByText("尚未核验的答案")).toBeNull();
  expect(getConversation).not.toHaveBeenCalled();
});

it("loads the saved verified answer and sources after the final frame", async () => {
  vi.mocked(listConversations).mockResolvedValue([saved]);
  vi.mocked(getConversation).mockResolvedValue({
    ...saved, has_older: false, turns: [{
      id: "turn", question: "退款条件？", answer: final.answer, grounded: true,
      citations: [citation], created_at: saved.created_at,
    }],
  });
  vi.mocked(streamAnswer).mockResolvedValue(final);
  renderPanel();
  submit();
  await waitFor(() => expect(screen.getByText("需要审批 [1]。")).toBeTruthy());
  expect(screen.getByText("[1] 退款政策.md")).toBeTruthy();
  expect(screen.getByText("退款需经理审批。")).toBeTruthy();
  expect(streamAnswer).toHaveBeenCalledWith("token", "kb", "退款条件？", expect.any(Function), expect.any(AbortSignal), null);
});

it("opens a previous conversation and appends using its ID", async () => {
  vi.mocked(listConversations).mockResolvedValue([saved]);
  vi.mocked(getConversation).mockResolvedValue({ ...saved, has_older: false, turns: [] });
  vi.mocked(streamAnswer).mockResolvedValue(final);
  renderPanel();
  await waitFor(() => expect(screen.getByText("退款条件？")).toBeTruthy());
  fireEvent.click(screen.getByText("退款条件？").closest("button")!);
  await waitFor(() => expect(getConversation).toHaveBeenCalled());
  submit();
  await waitFor(() => expect(streamAnswer).toHaveBeenCalledWith("token", "kb", "退款条件？", expect.any(Function), expect.any(AbortSignal), "conversation"));
});

it("deletes a selected conversation after confirmation", async () => {
  vi.mocked(listConversations).mockResolvedValue([saved]);
  vi.mocked(getConversation).mockResolvedValue({ ...saved, has_older: false, turns: [] });
  vi.mocked(deleteConversation).mockResolvedValue();
  renderPanel();
  await waitFor(() => expect(screen.getByText("退款条件？")).toBeTruthy());
  fireEvent.click(screen.getByText("退款条件？").closest("button")!);
  fireEvent.click(screen.getByRole("button", { name: "删除对话：退款条件？" }));
  fireEvent.click(await screen.findByRole("button", { name: /^删\s*除$/ }));
  await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("token", "kb", "conversation"));
});

it("aborts the upstream request and removes the draft when stopped", async () => {
  vi.mocked(listConversations).mockResolvedValue([]);
  let signal: AbortSignal | undefined;
  vi.mocked(streamAnswer).mockImplementation(async (_token, _kb, _query, onDelta, currentSignal) => {
    signal = currentSignal;
    onDelta("临时文本");
    return new Promise(() => undefined);
  });
  renderPanel();
  submit();
  await waitFor(() => expect(screen.getByText("临时文本")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /停止生成/ }));
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("临时文本")).toBeNull();
});
