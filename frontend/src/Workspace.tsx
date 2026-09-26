import { useState, type FormEvent } from "react";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Empty, Input, Layout, Space, Spin, Tabs, Tag, Typography } from "antd";
import { BookOutlined, LogoutOutlined, PlusOutlined } from "@ant-design/icons";
import {
  ApiError, createKnowledgeBase, createTenant, errorMessage, getCurrentTenant, getIdentity,
  listKnowledgeBases,
} from "./api/client";
import { useAuth } from "./auth/authContext";
import { AnswerPanel } from "./components/AnswerPanel";
import { DocumentsPanel } from "./components/DocumentsPanel";
import { DiagnosticPanel } from "./components/DiagnosticPanel";
import { AgentRunsPanel } from "./components/AgentRunsPanel";

const PAGE_SIZE = 20;

function TenantSetup({ token }: { token: string }) {
  const { message } = App.useApp();
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => createTenant(token, name.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tenant"] });
      message.success("租户已创建");
    },
  });
  return (
    <Card className="setup-card" title="创建演示租户">
      <Typography.Paragraph type="secondary">当前身份还没有对应的租户。创建后即可添加知识库和文档。</Typography.Paragraph>
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
        <Space.Compact className="full-width">
          <Input aria-label="租户名称" placeholder="例如：产品知识团队" maxLength={255} value={name} onChange={(event) => setName(event.target.value)} />
          <Button type="primary" htmlType="submit" loading={create.isPending} disabled={!name.trim()}>创建租户</Button>
        </Space.Compact>
      </form>
      {create.isError && <Alert className="panel-alert" type="error" showIcon message={errorMessage(create.error)} />}
    </Card>
  );
}

function KnowledgeBases({ token, canWrite, selectedId, onSelect }: {
  token: string; canWrite: boolean; selectedId: string | null; onSelect: (id: string) => void;
}) {
  const { message } = App.useApp();
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const bases = useQuery({
    queryKey: ["knowledge-bases", page],
    queryFn: () => listKnowledgeBases(token, page * PAGE_SIZE, PAGE_SIZE),
  });
  const create = useMutation({
    mutationFn: () => createKnowledgeBase(token, name.trim(), description.trim()),
    onSuccess: async (created) => {
      setName("");
      setDescription("");
      setCreating(false);
      setPage(0);
      onSelect(created.id);
      await queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
      message.success("知识库已创建");
    },
  });
  const rows = bases.data || [];
  return (
    <Card className="workspace-card kb-card" title="知识库" extra={canWrite && <Button size="small" icon={<PlusOutlined />} onClick={() => setCreating((value) => !value)}>新建</Button>}>
      {creating && (
        <form className="create-form" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
          <Input aria-label="知识库名称" placeholder="知识库名称" maxLength={255} value={name} onChange={(event) => setName(event.target.value)} />
          <Input.TextArea aria-label="知识库描述" placeholder="用途描述（可选）" maxLength={2000} rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
          <Button type="primary" htmlType="submit" loading={create.isPending} disabled={!name.trim()}>创建</Button>
          {create.isError && <Alert type="error" showIcon message={errorMessage(create.error)} />}
        </form>
      )}
      {bases.isPending && <div className="centered"><Spin /></div>}
      {bases.isError && <Alert type="error" showIcon message={errorMessage(bases.error)} action={<Button size="small" onClick={() => void bases.refetch()}>重试</Button>} />}
      {!bases.isPending && !bases.isError && rows.length === 0 && <Empty description="暂无知识库" />}
      <div className="kb-list" role="list" aria-label="知识库列表">
        {rows.map((base) => (
          <button
            key={base.id}
            type="button"
            role="listitem"
            className={`kb-item${selectedId === base.id ? " selected" : ""}`}
            aria-current={selectedId === base.id ? "true" : undefined}
            onClick={() => onSelect(base.id)}
          >
            <span className="kb-icon"><BookOutlined /></span>
            <span className="kb-copy"><strong>{base.name}</strong><small>{base.description || "暂无描述"}</small></span>
          </button>
        ))}
      </div>
      {(page > 0 || rows.length === PAGE_SIZE) && (
        <Space className="pagination-controls">
          <Button size="small" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>上一页</Button>
          <span>第 {page + 1} 页</span>
          <Button size="small" disabled={rows.length < PAGE_SIZE} onClick={() => setPage((value) => value + 1)}>下一页</Button>
        </Space>
      )}
    </Card>
  );
}

function Console({ token, name, signOut }: { token: string; name: string; signOut: () => Promise<void> }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("answers");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const identity = useQuery({ queryKey: ["identity"], queryFn: () => getIdentity(token), retry: false });
  const tenant = useQuery({ queryKey: ["tenant"], queryFn: () => getCurrentTenant(token), enabled: identity.isSuccess, retry: false });
  const canWrite = identity.data?.role === "admin";
  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <div className="header-brand"><span className="header-logo">EA</span><span>Enterprise Agent <span className="header-muted">/ Console</span></span></div>
        <Space size="middle" className="header-user">
          {tenant.data && <Tag className="tenant-tag">{tenant.data.name}</Tag>}
          <span className="user-name">{name}</span>
          <Button ghost size="small" icon={<LogoutOutlined />} onClick={() => void signOut()}>退出</Button>
        </Space>
      </Layout.Header>
      <Layout.Content className="app-content">
        <div className="page-intro">
          <Typography.Text className="eyebrow">KNOWLEDGE WORKSPACE</Typography.Text>
          <Typography.Title level={2}>知识工作台</Typography.Title>
          <Typography.Paragraph type="secondary">从文档索引到有据可查的回答，在一个工作区完成。</Typography.Paragraph>
        </div>
        {identity.isPending && <div className="centered"><Spin tip="正在验证身份" /></div>}
        {identity.isError && <Alert type="error" showIcon message="身份验证失败" description={errorMessage(identity.error)} action={<Button onClick={() => void signOut()}>重新登录</Button>} />}
        {identity.isSuccess && tenant.isPending && <div className="centered"><Spin tip="正在加载租户" /></div>}
        {identity.isSuccess && tenant.isError && (
          tenant.error instanceof ApiError && tenant.error.status === 404 && canWrite
            ? <TenantSetup token={token} />
            : <Alert type="error" showIcon message="无法进入租户" description={tenant.error instanceof ApiError && tenant.error.status === 404 ? "请联系租户管理员先创建租户。" : errorMessage(tenant.error)} />
        )}
        {identity.isSuccess && tenant.isSuccess && (
          <div className="workspace-grid">
            <aside><KnowledgeBases token={token} canWrite={canWrite} selectedId={selectedId} onSelect={setSelectedId} /></aside>
            <main className="workspace-main">
              {selectedId ? (
                <>
                  <DocumentsPanel key={`docs-${selectedId}`} token={token} knowledgeBaseId={selectedId} canWrite={canWrite} />
                  <Card className="workspace-card workspace-tabs">
                    <Tabs
                      activeKey={activeTab}
                      onChange={setActiveTab}
                      destroyOnHidden
                      items={[
                        { key: "answers", label: "引用问答", children: <AnswerPanel key={`answer-${selectedId}`} token={token} knowledgeBaseId={selectedId} /> },
                        { key: "diagnostic", label: "订单诊断", children: <DiagnosticPanel key={`diagnostic-${selectedId}`} token={token} knowledgeBaseId={selectedId} canViewTrace={canWrite} onOpenRun={(runId) => { setSelectedRunId(runId); setActiveTab("runs"); }} /> },
                        ...(canWrite ? [{ key: "runs", label: "运行轨迹", children: <AgentRunsPanel token={token} selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} /> }] : []),
                      ]}
                    />
                  </Card>
                </>
              ) : <Card className="workspace-card workspace-placeholder"><Empty description="选择或创建知识库，开始管理文档和提问" /></Card>}
            </main>
          </div>
        )}
      </Layout.Content>
    </Layout>
  );
}

export function Workspace() {
  const { state, signOut } = useAuth();
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 5000, retry: 1 } } }));
  if (state.status !== "signed_in") return null;
  return <QueryClientProvider client={queryClient}><Console token={state.token} name={state.name} signOut={signOut} /></QueryClientProvider>;
}
