import { ApiError, type Answer } from "./client";

type StreamEvent = "status" | "delta" | "final" | "error";

function parseFrame(frame: string): { event: StreamEvent; data: unknown } | null {
  const lines = frame.split(/\r?\n/);
  const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))
    .join("\n");
  if (!event || !data) return null;
  if (!["status", "delta", "final", "error"].includes(event)) return null;
  try {
    return { event: event as StreamEvent, data: JSON.parse(data) as unknown };
  } catch {
    throw new ApiError(502, "服务返回了无效的流事件");
  }
}

function isAnswer(value: unknown): value is Answer {
  if (!value || typeof value !== "object") return false;
  const answer = value as Record<string, unknown>;
  return typeof answer.knowledge_base_id === "string"
    && typeof answer.conversation_id === "string"
    && typeof answer.answer === "string"
    && typeof answer.grounded === "boolean"
    && Array.isArray(answer.citations)
    && answer.citations.every((citation: unknown) => {
      if (!citation || typeof citation !== "object") return false;
      const item = citation as Record<string, unknown>;
      if (typeof item.number !== "number" || !item.source || typeof item.source !== "object") return false;
      const source = item.source as Record<string, unknown>;
      return typeof source.chunk_id === "string"
        && typeof source.document_name === "string"
        && typeof source.content === "string"
        && (source.section_title === null || typeof source.section_title === "string")
        && (source.page_number === null || typeof source.page_number === "number")
        && Array.isArray(source.section_path)
        && source.section_path.every((part: unknown) => typeof part === "string");
    });
}

export async function streamAnswer(
  token: string,
  knowledgeBaseId: string,
  query: string,
  onDelta: (text: string) => void,
  signal: AbortSignal,
  conversationId: string | null = null,
): Promise<Answer> {
  const response = await fetch(
    `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/ask/stream`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ query, conversation_id: conversationId }),
      signal,
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, `问答请求失败（${response.status}）`);
  }
  if (!response.body) throw new ApiError(502, "服务没有返回响应流");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let delimiter = /\r?\n\r?\n/.exec(buffer);
      while (delimiter?.index !== undefined) {
        const frame = parseFrame(buffer.slice(0, delimiter.index));
        buffer = buffer.slice(delimiter.index + delimiter[0].length);
        if (frame?.event === "delta") {
          const data = frame.data;
          if (data && typeof data === "object" && "text" in data && typeof data.text === "string") {
            onDelta(data.text);
          }
        } else if (frame?.event === "final") {
          if (!isAnswer(frame.data)) throw new ApiError(502, "服务返回了无效的最终答案");
          return frame.data;
        } else if (frame?.event === "error") {
          throw new ApiError(503, "模型生成失败，请重试");
        }
        delimiter = /\r?\n\r?\n/.exec(buffer);
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  throw new ApiError(502, "回答流提前结束，请重试");
}
