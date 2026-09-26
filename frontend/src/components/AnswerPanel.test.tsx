import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AnswerPanel } from "./AnswerPanel";
import { streamAnswer } from "../api/answerStream";

vi.mock("../api/answerStream", () => ({ streamAnswer: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function submit() {
  fireEvent.change(screen.getByLabelText("向当前知识库提问"), { target: { value: "退款条件？" } });
  fireEvent.click(screen.getByRole("button", { name: /获取回答/ }));
}

it("drops provisional text if generation fails", async () => {
  vi.mocked(streamAnswer).mockImplementation(async (_token, _kb, _query, onDelta) => {
    onDelta("尚未核验的答案");
    throw new Error("模型生成失败，请重试");
  });
  render(<AnswerPanel token="token" knowledgeBaseId="kb" />);
  submit();
  await waitFor(() => expect(screen.getByText("模型生成失败，请重试")).toBeTruthy());
  expect(screen.queryByText("尚未核验的答案")).toBeNull();
  expect(screen.queryByText("已校验引用")).toBeNull();
});

it("shows source cards only after the final answer", async () => {
  vi.mocked(streamAnswer).mockResolvedValue({
    knowledge_base_id: "kb", answer: "需要审批 [1]。", grounded: true,
    citations: [{ number: 1, source: {
      chunk_id: "chunk", document_id: "doc", document_name: "退款政策.md",
      index_version: 1, chunk_index: 0, content: "退款需经理审批。", score: 0.9,
      page_number: null, section_title: "退款", section_path: ["政策", "退款"],
    } }],
  });
  render(<AnswerPanel token="token" knowledgeBaseId="kb" />);
  submit();
  await waitFor(() => expect(screen.getByText("已校验引用")).toBeTruthy());
  expect(screen.getByText("需要审批 [1]。")).toBeTruthy();
  expect(screen.getByText("[1] 退款政策.md")).toBeTruthy();
  expect(screen.getByText("退款需经理审批。")).toBeTruthy();
});

it("aborts the upstream request and removes the draft when stopped", async () => {
  let signal: AbortSignal | undefined;
  vi.mocked(streamAnswer).mockImplementation(async (_token, _kb, _query, onDelta, currentSignal) => {
    signal = currentSignal;
    onDelta("临时文本");
    return new Promise(() => undefined);
  });
  render(<AnswerPanel token="token" knowledgeBaseId="kb" />);
  submit();
  await waitFor(() => expect(screen.getByText("临时文本")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /停止生成/ }));
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("临时文本")).toBeNull();
});
