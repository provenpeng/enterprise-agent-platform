import { useEffect, useRef, useState, type FormEvent } from "react";
import { Alert, Button, Card, Empty, Input, Space, Tag, Typography } from "antd";
import { SendOutlined, StopOutlined } from "@ant-design/icons";
import { streamAnswer } from "../api/answerStream";
import { errorMessage, type Answer } from "../api/client";
import { CitationList } from "./CitationList";

const { TextArea } = Input;

export function AnswerPanel({ token, knowledgeBaseId }: { token: string; knowledgeBaseId: string }) {
  const [question, setQuestion] = useState("");
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const current = requestId;
    return () => {
      current.current += 1;
      controller.current?.abort();
    };
  }, [knowledgeBaseId, token]);

  function stop() {
    requestId.current += 1;
    controller.current?.abort();
    controller.current = null;
    setRunning(false);
    setDraft("");
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const query = question.trim();
    if (!query || running) return;
    const id = ++requestId.current;
    const nextController = new AbortController();
    controller.current = nextController;
    setRunning(true);
    setAnswer(null);
    setDraft("");
    setError(null);
    try {
      const final = await streamAnswer(token, knowledgeBaseId, query, (part) => {
        if (requestId.current === id) setDraft((value) => value + part);
      }, nextController.signal);
      if (requestId.current === id) {
        setAnswer(final);
        setDraft("");
      }
    } catch (cause) {
      if (requestId.current === id) {
        setDraft("");
        setError(errorMessage(cause));
      }
    } finally {
      if (requestId.current === id) {
        controller.current = null;
        setRunning(false);
      }
    }
  }

  return (
    <Card className="workspace-card answer-card" title="带来源引用的问答" extra={<Tag color="blue">实时生成</Tag>}>
      <form onSubmit={(event) => void ask(event)}>
        <label htmlFor="question-input" className="field-label">向当前知识库提问</label>
        <TextArea
          id="question-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：客户申请退款需要满足哪些条件？"
          rows={3}
          maxLength={2000}
          showCount
        />
        <Space className="form-actions">
          <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={running} disabled={!question.trim()}>
            获取回答
          </Button>
          {running && <Button icon={<StopOutlined />} onClick={stop}>停止生成</Button>}
        </Space>
      </form>

      {error && <Alert type="error" showIcon message={error} className="answer-feedback" />}
      {running && (
        <div className="answer-result" aria-live="polite">
          <Tag color="processing">生成中 · 尚未核验引用</Tag>
          <Typography.Paragraph className="answer-text">{draft || "正在检索证据并生成回答…"}</Typography.Paragraph>
        </div>
      )}
      {answer && (
        <div className="answer-result" aria-live="polite">
          <Tag color={answer.grounded ? "success" : "warning"}>
            {answer.grounded ? "已校验引用" : "证据不足"}
          </Tag>
          <Typography.Paragraph className="answer-text">{answer.answer}</Typography.Paragraph>
          <CitationList citations={answer.citations} />
        </div>
      )}
      {!answer && !running && !error && <Empty className="answer-empty" description="选择知识库并提问，回答和出处会显示在这里" />}
    </Card>
  );
}
