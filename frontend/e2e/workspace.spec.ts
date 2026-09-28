import { expect, test } from "@playwright/test";

const kb = "00000000-0000-4000-8000-000000000001";
const doc = "00000000-0000-4000-8000-000000000002";
const run = "00000000-0000-4000-8000-000000000003";
const conversation = "00000000-0000-4000-8000-000000000004";
const now = "2026-09-01T10:00:00Z";
const source = {
  chunk_id: "00000000-0000-4000-8000-000000000005", document_id: doc,
  document_name: "expense_policy.md", index_version: 1, chunk_index: 0,
  content: "员工应在出差结束后 30 个自然日内提交报销单。", score: 0.91,
  page_number: null, section_title: "报销提交期限",
  section_path: ["员工差旅与费用报销管理办法", "报销提交期限"],
};
const citation = { number: 1, source };
const answer = {
  knowledge_base_id: kb, conversation_id: conversation,
  answer: "出差结束后 30 个自然日内提交。\n\n来源：[1]",
  grounded: true, citations: [citation],
};
const diagnosis = {
  run_id: run, knowledge_base_id: kb, status: "BUSINESS_FACTS_ONLY",
  answer: "订单 DEMO-SUCCESS 最近一次退款状态为 SUCCEEDED。", citations: [],
  order: {
    order_id: "DEMO-SUCCESS", payment_status: "REFUNDED", currency: "CNY",
    total_amount_cents: 10000, refundable_amount_cents: 0, created_at: now,
    refund_attempts: [{ attempt_number: 1, status: "SUCCEEDED", amount_cents: 10000, reason_code: null, created_at: now }],
  },
};

test("login, upload, index, cited QA, diagnosis and restore after reload", async ({ page }) => {
  let uploaded = false;
  let answered = false;
  let diagnosed = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
    expect(request.headers().authorization).toBe("Bearer browser-test-token");
    if (method === "GET" && path === "/api/v1/me") return json({ subject: "browser-user", tenant_id: kb, role: "admin" });
    if (method === "GET" && path === "/api/v1/tenants/current") return json({ id: kb, name: "演示租户", created_at: now });
    if (method === "GET" && path === "/api/v1/knowledge-bases") return json([{ id: kb, tenant_id: kb, name: "综合业务知识库", description: "多业务政策", created_at: now }]);
    if (path === `/api/v1/knowledge-bases/${kb}/documents` && method === "GET") return json(uploaded ? [{ id: doc, knowledge_base_id: kb, filename: "expense_policy.md", file_type: "text/markdown", status: "READY", active_index_version: 1, checksum: "fixture", created_at: now }] : []);
    if (path === `/api/v1/knowledge-bases/${kb}/documents` && method === "POST") { uploaded = true; return json({ id: doc, filename: "expense_policy.md" }, 201); }
    if (path === `/api/v1/agent-runs/mine` && method === "GET") return json(diagnosed ? [{ id: run, question: "DEMO-SUCCESS 的退款状态？", outcome: "BUSINESS_FACTS_ONLY", started_at: now }] : []);
    if (path === `/api/v1/agent-runs/mine/${run}` && method === "GET") return json({ id: run, question: "DEMO-SUCCESS 的退款状态？", outcome: "BUSINESS_FACTS_ONLY", started_at: now, response: diagnosis });
    if (path === "/api/v1/agent-runs" && method === "GET") return json([]);
    if (path === `/api/v1/knowledge-bases/${kb}/conversations` && method === "GET") return json(answered ? [{ id: conversation, title: "出差报销的提交期限？", created_at: now, updated_at: now }] : []);
    if (path === `/api/v1/knowledge-bases/${kb}/conversations/${conversation}` && method === "GET") return json({ id: conversation, title: "出差报销的提交期限？", turns: [{ id: "turn-1", question: "出差报销的提交期限？", answer: answer.answer, grounded: true, citations: [citation], created_at: now }], has_older: false });
    if (path === `/api/v1/knowledge-bases/${kb}/ask/stream` && method === "POST") {
      expect(request.postDataJSON().query).toBe("出差报销的提交期限？");
      answered = true;
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: `event: delta\ndata: ${JSON.stringify({ text: "出差结束后 30 个自然日内提交。" })}\n\nevent: final\ndata: ${JSON.stringify(answer)}\n\n` });
    }
    if (path === `/api/v1/knowledge-bases/${kb}/diagnose` && method === "POST") {
      expect(request.postDataJSON().order_id).toBe("DEMO-SUCCESS");
      diagnosed = true;
      return json(diagnosis);
    }
    throw new Error(`Unexpected API call: ${method} ${path}`);
  });

  await page.goto("/");
  await page.getByLabel("演示访问令牌").fill("browser-test-token");
  await page.getByRole("button", { name: "连接工作台" }).click();
  await page.getByRole("list", { name: "知识库列表" }).getByRole("listitem").first().click();
  await page.locator("input[type=file]").setInputFiles({ name: "expense_policy.md", mimeType: "text/markdown", buffer: Buffer.from("# 员工差旅与费用报销管理办法\n\n员工应在出差结束后 30 个自然日内提交报销单。") });
  await page.getByRole("button", { name: "上传并索引" }).click();
  await expect(page.getByText("可检索")).toBeVisible();
  await page.getByLabel("向当前知识库提问").fill("出差报销的提交期限？");
  await page.getByRole("button", { name: "获取回答" }).click();
  await expect(page.getByText("出差结束后 30 个自然日内提交。", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("[1] expense_policy.md")).toBeVisible();
  await page.getByRole("tab", { name: "订单诊断" }).click();
  await page.getByLabel("诊断问题").fill("DEMO-SUCCESS 的退款状态？");
  await page.getByLabel("订单号（可选）").fill("DEMO-SUCCESS");
  await page.getByRole("button", { name: "运行诊断" }).click();
  await expect(page.getByText("订单 DEMO-SUCCESS 最近一次退款状态为 SUCCEEDED。")).toBeVisible();
  await page.reload();
  await page.getByLabel("演示访问令牌").fill("browser-test-token");
  await page.getByRole("button", { name: "连接工作台" }).click();
  await page.getByRole("list", { name: "知识库列表" }).getByRole("listitem").first().click();
  await page.getByRole("tab", { name: "订单诊断" }).click();
  await page.getByRole("button", { name: "恢复结果" }).click();
  await expect(page.getByText("订单 DEMO-SUCCESS 最近一次退款状态为 SUCCEEDED。")).toBeVisible();
});
