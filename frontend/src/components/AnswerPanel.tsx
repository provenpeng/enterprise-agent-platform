import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Empty, Input, Popconfirm, Space, Spin, Tag, Typography } from "antd";
import { DeleteOutlined, PlusOutlined, SendOutlined, StopOutlined } from "@ant-design/icons";
import { streamAnswer } from "../api/answerStream";
import { deleteConversation, errorMessage, getConversation, listConversations } from "../api/client";
import { CitationList } from "./CitationList";

const { TextArea } = Input;
const PAGE_SIZE = 20;

export function AnswerPanel({ token, knowledgeBaseId }: { token: string; knowledgeBaseId: string }) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [draft, setDraft] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [historyPage, setHistoryPage] = useState(0);
  const [turnPage, setTurnPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef(0);

  const history = useQuery({
    queryKey: ["conversations", knowledgeBaseId, historyPage],
    queryFn: () => listConversations(token, knowledgeBaseId, historyPage * PAGE_SIZE, PAGE_SIZE),
  });
  const detail = useQuery({
    queryKey: ["conversation", knowledgeBaseId, selectedId, turnPage],
    queryFn: () => getConversation(token, knowledgeBaseId, selectedId!, turnPage * PAGE_SIZE, PAGE_SIZE),
    enabled: selectedId !== null,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteConversation(token, knowledgeBaseId, id),
    onSuccess: async (_value, id) => {
      if (selectedId === id) setSelectedId(null);
      setHistoryPage(0);
      await queryClient.invalidateQueries({ queryKey: ["conversations", knowledgeBaseId] });
      queryClient.removeQueries({ queryKey: ["conversation", knowledgeBaseId, id] });
    },
  });

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

  function selectConversation(id: string | null) {
    if (running) return;
    setSelectedId(id);
    setTurnPage(0);
    setQuestion("");
    setError(null);
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const query = question.trim();
    if (!query || running) return;
    const id = ++requestId.current;
    const nextController = new AbortController();
    controller.current = nextController;
    setRunning(true);
    setDraft("");
    setError(null);
    try {
      const final = await streamAnswer(token, knowledgeBaseId, query, (part) => {
        if (requestId.current === id) setDraft((value) => value + part);
      }, nextController.signal, selectedId);
      if (requestId.current === id && final.conversation_id) {
        controller.current = null;
        setRunning(false);
        setSelectedId(final.conversation_id);
        setTurnPage(0);
        setHistoryPage(0);
        setQuestion("");
        setDraft("");
        void queryClient.invalidateQueries({ queryKey: ["conversations", knowledgeBaseId] });
        void queryClient.invalidateQueries({ queryKey: ["conversation", knowledgeBaseId, final.conversation_id] });
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
      <div className="conversation-layout">
        <aside className="conversation-sidebar" aria-label="对话历史">
          <Button icon={<PlusOutlined />} block onClick={() => selectConversation(null)} disabled={running}>新对话</Button>
          {history.isPending && <div className="centered"><Spin /></div>}
          {history.isError && <Alert type="error" showIcon message={errorMessage(history.error)} action={<Button size="small" onClick={() => void history.refetch()}>重试</Button>} />}
          {history.data?.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />}
          <div className="conversation-list">
            {history.data?.map((conversation) => (
              <div className="conversation-list-row" key={conversation.id}>
                <button
                  type="button"
                  className={`conversation-item${selectedId === conversation.id ? " selected" : ""}`}
                  onClick={() => selectConversation(conversation.id)}
                  disabled={running}
                  aria-current={selectedId === conversation.id ? "true" : undefined}
                >
                  <strong>{conversation.title}</strong>
                  <small>{new Date(conversation.updated_at).toLocaleString()}</small>
                </button>
                <Popconfirm
                  title="删除这段对话？"
                  description="问题、回答和引用记录会一并删除。"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => remove.mutate(conversation.id)}
                >
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} aria-label={`删除对话：${conversation.title}`} disabled={running || remove.isPending} />
                </Popconfirm>
              </div>
            ))}
          </div>
          {(historyPage > 0 || history.data?.length === PAGE_SIZE) && (
            <Space className="pagination-controls">
              <Button size="small" disabled={historyPage === 0} onClick={() => setHistoryPage((page) => page - 1)}>上一页</Button>
              <Button size="small" disabled={(history.data?.length ?? 0) < PAGE_SIZE} onClick={() => setHistoryPage((page) => page + 1)}>下一页</Button>
            </Space>
          )}
          {remove.isError && <Alert className="panel-alert" type="error" showIcon message={errorMessage(remove.error)} />}
        </aside>

        <section className="conversation-main" aria-label="对话内容">
          {selectedId && detail.isPending && <div className="centered"><Spin /></div>}
          {selectedId && detail.isError && <Alert type="error" showIcon message={errorMessage(detail.error)} action={<Button size="small" onClick={() => void detail.refetch()}>重试</Button>} />}
          {selectedId && detail.data && (
            <>
              <div className="conversation-turns">
                {detail.data.turns.map((turn) => (
                  <article key={turn.id} className="conversation-turn">
                    <Typography.Text type="secondary">提问</Typography.Text>
                    <Typography.Paragraph className="answer-text">{turn.question}</Typography.Paragraph>
                    <Tag color={turn.grounded ? "success" : "warning"}>{turn.grounded ? "已校验引用" : "证据不足"}</Tag>
                    <Typography.Paragraph className="answer-text">{turn.answer}</Typography.Paragraph>
                    <CitationList citations={turn.citations} />
                  </article>
                ))}
              </div>
              {(turnPage > 0 || detail.data.has_older) && (
                <Space className="pagination-controls">
                  <Button size="small" disabled={!detail.data.has_older} onClick={() => setTurnPage((page) => page + 1)}>更早记录</Button>
                  <Button size="small" disabled={turnPage === 0} onClick={() => setTurnPage((page) => page - 1)}>较新记录</Button>
                </Space>
              )}
            </>
          )}
          {!selectedId && !running && <Empty className="answer-empty" description="新建对话或打开历史记录" />}
          {error && <Alert type="error" showIcon message={error} className="answer-feedback" />}
          {running && (
            <div className="answer-result" aria-live="polite">
              <Tag color="processing">生成中 · 尚未核验引用</Tag>
              <Typography.Paragraph className="answer-text">{draft || "正在检索证据并生成回答…"}</Typography.Paragraph>
            </div>
          )}
          <form className="conversation-form" onSubmit={(event) => void ask(event)}>
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
          <Typography.Text type="secondary" className="conversation-note">每次提问独立检索当前知识库；历史内容不会作为模型上下文。</Typography.Text>
        </section>
      </div>
    </Card>
  );
}
