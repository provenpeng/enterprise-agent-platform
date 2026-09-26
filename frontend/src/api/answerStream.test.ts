import { afterEach, describe, expect, it, vi } from "vitest";
import { streamAnswer } from "./answerStream";

const final = {
  knowledge_base_id: "00000000-0000-0000-0000-000000000001",
  answer: "退款需要审批 [1]。",
  grounded: true,
  citations: [{ number: 1, source: {
    chunk_id: "chunk-1", document_id: "doc-1", document_name: "政策.md",
    index_version: 1, chunk_index: 0, content: "退款需经理审批。", score: 0.9,
    page_number: null, section_title: "退款", section_path: ["政策", "退款"],
  } }],
};

function responseFrom(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("streamAnswer", () => {
  it("reads split SSE frames and returns only the verified final answer", async () => {
    const fetchMock = vi.fn().mockResolvedValue(responseFrom([
      'event: status\ndata: {"phase":"generating"}\n\nevent: del',
      'ta\ndata: {"text":"临时片段","provisional":true}\n\n',
      `event: final\ndata: ${JSON.stringify(final)}\n\n`,
    ]));
    vi.stubGlobal("fetch", fetchMock);
    const onDelta = vi.fn();
    await expect(streamAnswer("token", "kb-id", "退款？", onDelta, new AbortController().signal)).resolves.toEqual(final);
    expect(onDelta).toHaveBeenCalledExactlyOnceWith("临时片段");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer token");
  });

  it("rejects an error after provisional text instead of treating it as an answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseFrom([
      'event: delta\ndata: {"text":"未核验"}\n\n',
      'event: error\ndata: {"code":"ANSWER_GENERATION_FAILED"}\n\n',
    ])));
    const onDelta = vi.fn();
    await expect(streamAnswer("token", "kb-id", "问题", onDelta, new AbortController().signal))
      .rejects.toThrow("模型生成失败");
    expect(onDelta).toHaveBeenCalledExactlyOnceWith("未核验");
  });

  it("rejects a stream that ends without a final frame", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseFrom(['event: delta\ndata: {"text":"一半"}\n\n'])));
    await expect(streamAnswer("token", "kb-id", "问题", vi.fn(), new AbortController().signal))
      .rejects.toThrow("回答流提前结束");
  });

  it("rejects a malformed final citation before rendering it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseFrom([
      'event: final\ndata: {"knowledge_base_id":"kb","answer":"text","grounded":true,"citations":[{"number":1,"source":{}}]}\n\n',
    ])));
    await expect(streamAnswer("token", "kb-id", "问题", vi.fn(), new AbortController().signal))
      .rejects.toThrow("无效的最终答案");
  });

  it("forwards cancellation to fetch", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn((_url: string, options: RequestInit) => {
      expect(options.signal).toBe(controller.signal);
      controller.abort();
      return Promise.reject(new DOMException("aborted", "AbortError"));
    }));
    await expect(streamAnswer("token", "kb-id", "问题", vi.fn(), controller.signal))
      .rejects.toMatchObject({ name: "AbortError" });
  });
});
