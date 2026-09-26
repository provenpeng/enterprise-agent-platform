import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type KnowledgeBase = components["schemas"]["KnowledgeBaseRead"];
export type Document = components["schemas"]["DocumentRead"];
export type Answer = components["schemas"]["AskResponse"];
export type SearchHit = components["schemas"]["SearchHit"];
export type Identity = components["schemas"]["IdentityRead"];
export type Tenant = components["schemas"]["TenantRead"];
export type IndexJob = components["schemas"]["IndexJobRead"];
export type Diagnosis = components["schemas"]["DiagnoseResponse"];
export type AgentRunSummary = components["schemas"]["AgentRunSummary"];
export type AgentRunDetail = components["schemas"]["AgentRunDetail"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detail(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const value = error.detail;
    if (typeof value === "string") return value;
  }
  return fallback;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

export function api(token: string) {
  return createClient<paths>({
    baseUrl: window.location.origin,
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getIdentity(token: string): Promise<Identity> {
  const { data, error, response } = await api(token).GET("/api/v1/me");
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法验证身份"));
  return data;
}

export async function getCurrentTenant(token: string): Promise<Tenant> {
  const { data, error, response } = await api(token).GET("/api/v1/tenants/current");
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法获取租户"));
  return data;
}

export async function createTenant(token: string, name: string): Promise<Tenant> {
  const { data, error, response } = await api(token).POST("/api/v1/tenants", { body: { name } });
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法创建租户"));
  return data;
}

export async function listKnowledgeBases(token: string, offset: number, limit = 20): Promise<KnowledgeBase[]> {
  const { data, error, response } = await api(token).GET("/api/v1/knowledge-bases", {
    params: { query: { limit, offset } },
  });
  if (!response.ok || !data) {
    throw new ApiError(response.status, detail(error, "无法获取知识库"));
  }
  return data;
}

export async function createKnowledgeBase(
  token: string,
  name: string,
  description: string,
): Promise<KnowledgeBase> {
  const { data, error, response } = await api(token).POST("/api/v1/knowledge-bases", {
    body: { name, description: description || null },
  });
  if (!response.ok || !data) {
    throw new ApiError(response.status, detail(error, "无法创建知识库"));
  }
  return data;
}

export async function listDocuments(token: string, knowledgeBaseId: string, offset: number, limit = 20): Promise<Document[]> {
  const { data, error, response } = await api(token).GET(
    "/api/v1/knowledge-bases/{knowledge_base_id}/documents",
    {
      params: { path: { knowledge_base_id: knowledgeBaseId }, query: { limit, offset } },
    },
  );
  if (!response.ok || !data) {
    throw new ApiError(response.status, detail(error, "无法获取文档"));
  }
  return data;
}

export async function listIndexJobs(token: string, documentId: string): Promise<IndexJob[]> {
  const { data, error, response } = await api(token).GET("/api/v1/documents/{document_id}/index-jobs", {
    params: { path: { document_id: documentId } },
  });
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法获取索引任务"));
  return data;
}

export async function reindexDocument(token: string, documentId: string): Promise<IndexJob> {
  const { data, error, response } = await api(token).POST("/api/v1/documents/{document_id}/index-jobs", {
    params: { path: { document_id: documentId } },
  });
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法重新索引文档"));
  return data;
}

export async function diagnoseOrder(
  token: string,
  knowledgeBaseId: string,
  question: string,
  orderId: string | null,
): Promise<Diagnosis> {
  const { data, error, response } = await api(token).POST(
    "/api/v1/knowledge-bases/{knowledge_base_id}/diagnose",
    {
      params: { path: { knowledge_base_id: knowledgeBaseId } },
      body: { question, order_id: orderId },
    },
  );
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "订单诊断失败"));
  return data;
}

export async function listAgentRuns(token: string, offset: number, limit = 20): Promise<AgentRunSummary[]> {
  const { data, error, response } = await api(token).GET("/api/v1/agent-runs", {
    params: { query: { limit, offset } },
  });
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法获取运行记录"));
  return data;
}

export async function getAgentRun(token: string, runId: string): Promise<AgentRunDetail> {
  const { data, error, response } = await api(token).GET("/api/v1/agent-runs/{run_id}", {
    params: { path: { run_id: runId } },
  });
  if (!response.ok || !data) throw new ApiError(response.status, detail(error, "无法获取运行轨迹"));
  return data;
}

export async function uploadDocument(
  token: string,
  knowledgeBaseId: string,
  file: File,
): Promise<Document> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, detail(body, "无法上传文档"));
  }
  if (!body || typeof body !== "object" || !("id" in body) || typeof body.id !== "string") {
    throw new ApiError(502, "服务返回了无效文档信息");
  }
  return body as Document;
}
