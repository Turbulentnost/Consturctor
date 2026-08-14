/** HTTP-клиент: все запросы через прокси web-ui → backend. */

const Api = {
  token: localStorage.getItem("constructor_token") || "",
  gatewayPath: "/api/gateway",

  setToken(token) {
    this.token = token || "";
    if (token) localStorage.setItem("constructor_token", token);
    else localStorage.removeItem("constructor_token");
  },

  async request(method, path, { json, formData, params } = {}) {
    let url = `${this.gatewayPath}${path}`;
    if (params) {
      const qs = new URLSearchParams(params);
      url += `?${qs}`;
    }
    const headers = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const opts = { method, headers };
    if (formData) {
      opts.body = formData;
    } else if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(json);
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!resp.ok) {
      const msg = (data && (data.detail || data.message)) || `HTTP ${resp.status}`;
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = resp.status;
      throw err;
    }
    return data;
  },

  health() {
    return fetch("/api/health").then((r) => r.json());
  },

  login(fio, password) {
    return this.request("POST", "/api/v1/auth/login", { json: { fio, password } });
  },

  register(fio, password, department = "") {
    return this.request("POST", "/api/v1/auth/register", {
      json: { fio, password, department },
    });
  },

  me() {
    return this.request("GET", "/api/v1/auth/me");
  },

  listDepartments() {
    return this.request("GET", "/api/v1/auth/departments");
  },

  updateDepartment(department) {
    return this.request("PATCH", "/api/v1/auth/me/department", { json: { department } });
  },

  uploadRegulation(file) {
    const fd = new FormData();
    fd.append("file", file);
    return this.request("POST", "/api/v1/regulations/upload", { formData: fd });
  },

  createRoleMatches(regulationId, body) {
    return this.request("POST", `/api/v1/regulations/${regulationId}/role-matches`, {
      json: body,
    });
  },

  decideRoleMatch(regulationId, runId, matchId, status) {
    return this.request(
      "PATCH",
      `/api/v1/regulations/${regulationId}/role-matches/${runId}/${matchId}`,
      { json: { status } }
    );
  },

  createDraft(regulationId, runId) {
    return this.request(
      "POST",
      `/api/v1/regulations/${regulationId}/role-matches/${runId}/draft`
    );
  },

  listDrafts() {
    return this.request("GET", "/api/v1/agents/drafts");
  },

  listWorkflows() {
    return this.request("GET", "/api/v1/workflows");
  },

  deleteDraft(draftId) {
    return this.request("DELETE", `/api/v1/agents/drafts/${draftId}`);
  },

  kpiSummary(agentId = "", hours = 168) {
    const params = { hours: String(hours) };
    if (agentId) params.agent_id = agentId;
    return this.request("GET", "/api/v1/kpi/summary", { params });
  },

  kpiExecutionHistory(agentId = "", limit = 50) {
    const params = { limit: String(limit) };
    if (agentId) params.agent_id = agentId;
    return this.request("GET", "/api/v1/kpi/execution-history", { params });
  },

  kpiAgentCards() {
    return this.request("GET", "/api/v1/kpi/agent-cards");
  },

  kpiAgentOverview(agentId, hours = 168, limit = 50) {
    const params = { hours: String(hours), limit: String(limit) };
    return this.request(
      "GET",
      `/api/v1/kpi/agent-overview/${encodeURIComponent(agentId)}`,
      { params }
    );
  },

  updateKpiAgentTitle(agentId, title) {
    return this.request("PATCH", `/api/v1/kpi/agent-cards/${encodeURIComponent(agentId)}/title`, {
      json: { title },
    });
  },
};

window.Api = Api;
