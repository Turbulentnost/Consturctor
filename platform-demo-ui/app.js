const SERVICES = [
  { id: "gateway", name: "Gateway", port: 7812 },
  { id: "runtime", name: "Agent Runtime", port: 7825 },
  { id: "kpi", name: "platform-kpi", port: 7820 },
  { id: "imap", name: "tool-imap HTTP", port: 7821 },
  { id: "onec", name: "tool-onec HTTP", port: 7822 },
  { id: "shell", name: "tool-shell sandbox", port: 7823 },
  { id: "shellNative", name: "tool-shell native", port: 7828 },
  { id: "browser", name: "tool-browser", port: 7824 },
  { id: "com", name: "tool-com", port: 7826 },
  { id: "fs", name: "tool-fs", port: 7827 },
];

const FIGJAM_URL = "https://www.figma.com/board/d3SqK8NI5SejQtfy8yzpxF";
const SEVERE_BELOW_THRESHOLD_PP = 15;

const ACCESS_LEVELS = [
  {
    level: 1,
    title: "Наблюдатель",
    summary: "Генерация текста, инструменты чтения и human-in-the-loop.",
    ok: ["Генерация текста", "Инструменты чтения"],
    hitl: ["Все остальные операции — только после подтверждения человека"],
    forbidden: [],
  },
  {
    level: 2,
    title: "Ограниченная запись",
    summary: "Уровень 1 + разрешённые инструменты записи без подтверждения.",
    ok: ["Всё из уровня 1", "Разрешённые write-tools без HITL"],
    hitl: [],
    forbidden: ["Запись, изменение и удаление данных в 1С"],
  },
  {
    level: 3,
    title: "Контролируемая автономия",
    summary: "Запись/редактирование/удаление и рассылка; код и PowerShell — с HITL.",
    ok: ["Всё из уровня 2", "Write / edit / delete", "Массовая рассылка"],
    hitl: ["Написание и запуск кода", "Команды PowerShell"],
    forbidden: [],
  },
  {
    level: 4,
    title: "Полный доступ",
    summary: "Все инструменты без HITL, кроме прав сотрудника и системных политик.",
    ok: ["Все реализованные инструменты без подтверждения"],
    hitl: ["Права конкретного сотрудника", "Системные политики"],
    forbidden: [],
  },
];

const accessSim = {
  agentId: "demo-agent",
  level: 1,
  changeKind: 0,
  week: 1,
  accuracy: 72,
  promoteOffered: false,
};

let token = null;
let lastRunId = null;

function $(id) {
  return document.getElementById(id);
}

function log(msg) {
  const el = $("log");
  el.textContent += `${new Date().toLocaleTimeString()}  ${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

function resolveProxyUrl(path) {
  return path;
}

function apiUrl(path) {
  return resolveProxyUrl(`/api/gateway${path}`);
}

function setStep(step, state) {
  document.querySelectorAll("#pipeline li").forEach((li) => {
    if (li.dataset.step !== step) return;
    li.classList.remove("active", "done", "fail");
    if (state) li.classList.add(state);
  });
}

async function fetchHealth(port) {
  const r = await fetch(resolveProxyUrl(`/health/${port}`));
  return r.json();
}

async function renderServices() {
  const box = $("services");
  if (!box) return;
  box.innerHTML = "";
  for (const svc of SERVICES) {
    const div = document.createElement("div");
    div.className = "svc";
    div.innerHTML = `<div class="name">${svc.name}</div><div class="status">...</div>`;
    box.appendChild(div);
    try {
      const data = await fetchHealth(svc.port);
      div.classList.add(data.reachable ? "ok" : "down");
      div.querySelector(".status").textContent = data.reachable
        ? `OK — ${JSON.stringify(data.body?.status || data.body?.service || "ok")}`
        : `DOWN — ${data.error || "unreachable"}`;
    } catch (e) {
      div.classList.add("down");
      div.querySelector(".status").textContent = `DOWN — ${e.message}`;
    }
  }
}

function formatApiError(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((x) => x.msg || JSON.stringify(x)).join("; ");
  }
  if (data.error) return data.error;
  return fallback;
}

async function loadErpStatus() {
  const banner = $("erpBanner");
  try {
    const r = await fetch(resolveProxyUrl("/api/gateway-health"));
    const data = await r.json();
    if (data.erp_reachable) {
      banner.className = "erp-banner ok";
      banner.textContent = `ERP SQL OK (${data.erp_server}) — вход через 1С v8users`;
    } else {
      banner.className = "erp-banner warn";
      banner.textContent =
        `ERP SQL недоступен (${data.erp_server}). ` +
        `При AUTH_STUB=true в backend\\.env можно войти для теста платформы (пароль 1С не проверяется).`;
    }
  } catch (e) {
    banner.className = "erp-banner warn";
    banner.textContent = `Gateway недоступен: ${e.message}. Запустите backend на :7812.`;
  }
}

async function login() {
  setStep("login", "active");
  const fio = $("fio").value.trim();
  const password = $("password").value;
  if (!fio || !password) {
    log("Укажите ФИО и пароль");
    setStep("login", "fail");
    return;
  }
  $("btnLogin").disabled = true;
  log("Вход: запрос к gateway...");
  try {
    const r = await fetch(resolveProxyUrl("/api/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fio, password }),
    });
    let data = {};
    try {
      data = await r.json();
    } catch {
      data = {};
    }
    if (!r.ok) throw new Error(formatApiError(data, r.statusText));
    if (!data.access_token) throw new Error("Ответ login без access_token");
    token = String(data.access_token).trim();
    const stub = (data.user?.department || "").includes("AUTH_STUB");
    log(
      `Вход OK: ${data.user?.fio}, отдел: ${data.user?.department || "—"}` +
        (stub ? " [тестовый режим, ERP SQL недоступен]" : "")
    );
    setStep("login", "done");
    loadSandboxTests();
  } catch (e) {
    let msg = e.message || String(e);
    if (msg === "Failed to fetch") {
      msg = "нет связи с сервером UI (:8790). Откройте http://127.0.0.1:8790/ и проверьте, что Docker запущен.";
    }
    log(`Вход FAILED: ${msg}`);
    setStep("login", "fail");
  } finally {
    $("btnLogin").disabled = false;
  }
}

async function startRun() {
  if (!token) {
    log("Сначала выполните вход");
    return;
  }
  setStep("run", "active");
  setStep("queue", "active");
  try {
    const r = await fetch(apiUrl("/api/v1/runs"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        agent_id: "demo-agent",
        tools: ["imap.list_unread"],
        config: {},
      }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    lastRunId = data.run_id;
    log(`Run создан: ${data.run_id}, status=${data.status}`);
    setStep("run", "done");
    await pollRun();
  } catch (e) {
    log(`Run FAILED: ${e.message}`);
    setStep("run", "fail");
    setStep("queue", "fail");
  }
}

async function invokeToolViaRuntime() {
  if (!token) {
    log("Сначала выполните вход");
    return;
  }
  setStep("tool", "active");
  try {
    const r = await fetch(apiUrl("/api/v1/tools/imap.list_unread/invoke"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ payload: { source: "demo-ui" } }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    log(`Tool via Runtime OK: ok=${data.ok}, summary=${data.data?.summary || JSON.stringify(data.data)}`);
    setStep("tool", "done");
  } catch (e) {
    log(`Tool invoke FAILED: ${e.message}`);
    log("Проверьте: celery worker -Q imap и broker RabbitMQ :5673");
    setStep("tool", "fail");
  }
}

async function pollRun(attempts = 15) {
  if (!lastRunId || !token) return;
  for (let i = 0; i < attempts; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    const r = await fetch(apiUrl(`/api/v1/runs/${lastRunId}`), {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await r.json();
    log(`Run poll: status=${data.status}, tool_events=${data.tool_events_count}`);
    if (data.status === "done") {
      setStep("queue", "done");
      setStep("worker", "done");
      setStep("audit", "done");
      setStep("done", "done");
      return;
    }
    if (data.status === "error") {
      setStep("queue", "fail");
      setStep("worker", "fail");
      setStep("done", "fail");
      log(`Run error: ${data.error || "unknown"}`);
      log("Частая причина: не запущен celery worker -Q imap");
      return;
    }
  }
  log("Run poll timeout — проверьте workers в logs\\");
}

async function kpiSummary() {
  if (!token) {
    log("Сначала выполните вход");
    return;
  }
  setStep("kpi", "active");
  try {
    const r = await fetch(apiUrl("/api/v1/kpi/summary"), {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    log(
      `KPI: runs=${data.total_runs}, success=${(data.success_rate * 100).toFixed(1)}%, ` +
        `tool_fail=${(data.tool_failure_rate * 100).toFixed(1)}%`
    );
    if (typeof data.success_rate === "number" && data.total_runs > 0) {
      const prev = accessSim.accuracy;
      const next = Math.round(data.success_rate * 100);
      const delta = next - prev;
      accessSim.accuracy = next;
      applyAccessLevelNotices(prev, next, delta);
      renderAccessPanel();
      log(`KPI → симуляция: точность недели ${accessSim.accuracy}%, уровень ${accessSim.level}`);
    }
    setStep("kpi", "done");
  } catch (e) {
    log(`KPI FAILED: ${e.message}`);
    setStep("kpi", "fail");
  }
}

async function loadMockScenarios() {
  const box = $("mockScenarios");
  if (!box) return;
  if (!token) {
    box.innerHTML =
      "<p class='hint'>Войдите (кнопка 1), чтобы загрузить сценарии моков агента.</p>";
    return;
  }
  box.innerHTML = "<p class='hint'>Загрузка сценариев...</p>";
  try {
    const headers = { Authorization: `Bearer ${token}` };
    const r = await fetch(apiUrl("/api/v1/agent/mocks"), { headers });
    const data = await r.json();
    if (!r.ok) throw new Error(formatApiError(data, r.statusText));
    box.innerHTML = "";
    for (const item of data.items || []) {
      const card = document.createElement("div");
      card.className = "mock-card";
      card.innerHTML = `
        <div class="mock-title">${item.title}</div>
        <div class="mock-desc">${item.description}</div>
        <div class="mock-tools">${(item.tools || []).join(" → ")}</div>
        <div class="mock-actions">
          <button data-simulate="${item.id}">Simulate</button>
          <button data-run="${item.id}" class="secondary">Run (Celery)</button>
        </div>`;
      box.appendChild(card);
    }
    box.querySelectorAll("[data-simulate]").forEach((btn) => {
      btn.addEventListener("click", () => simulateMock(btn.getAttribute("data-simulate")));
    });
    box.querySelectorAll("[data-run]").forEach((btn) => {
      btn.addEventListener("click", () => runMock(btn.getAttribute("data-run")));
    });
  } catch (e) {
    box.innerHTML = `<p class="hint">Не удалось загрузить моки: ${e.message}. Сначала войдите или запустите gateway.</p>`;
  }
}

async function simulateMock(scenarioId) {
  if (!token) {
    log("Сначала выполните вход");
    return;
  }
  log(`Mock simulate: ${scenarioId}...`);
  try {
    const r = await fetch(apiUrl(`/api/v1/agent/mocks/${scenarioId}/simulate`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ agent_id: `mock-${scenarioId}` }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(formatApiError(data, r.statusText));
    log(`=== ${data.title} (${data.scenario_id}) status=${data.status} ===`);
    for (const step of data.steps || []) {
      if (step.phase === "plan") log(`  PLAN: ${step.message}`);
      if (step.phase === "tool") {
        log(`  TOOL ${step.ok ? "OK" : "FAIL"} ${step.tool_name}: ${step.summary || step.error || ""}`);
      }
      if (step.phase === "error") log(`  ERROR ${step.tool_name}: ${step.message}`);
    }
  } catch (e) {
    log(`Mock simulate FAILED: ${e.message}`);
  }
}

async function runMock(scenarioId) {
  if (!token) {
    log("Сначала выполните вход");
    return;
  }
  log(`Mock run (async): ${scenarioId}...`);
  try {
    const r = await fetch(apiUrl(`/api/v1/agent/mocks/${scenarioId}/run`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ agent_id: `mock-${scenarioId}` }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(formatApiError(data, r.statusText));
    lastRunId = data.run_id;
    log(`Mock run создан: ${data.run_id}, status=${data.status}`);
    await pollRun();
  } catch (e) {
    log(`Mock run FAILED: ${e.message}`);
  }
}

function sandboxRequireLogin() {
  if (token) return true;
  log("Sandbox: сначала выполните вход (кнопка 1)");
  return false;
}

function setSandboxFormState(tool, state, message) {
  const form = document.querySelector(`.sandbox-tool-form[data-tool="${tool}"]`);
  const status = $(`sb${tool.charAt(0).toUpperCase()}${tool.slice(1)}Status`);
  if (form) {
    form.classList.remove("running", "done", "fail");
    if (state) form.classList.add(state);
  }
  if (status) {
    status.textContent = message || "";
    status.className =
      "sandbox-status" +
      (state === "done" ? " ok" : state === "fail" ? " err" : state === "running" ? " run" : "");
  }
}

function writeSandboxOut(outId, text) {
  const el = $(outId);
  if (el) el.textContent = text;
}

function formatToolResult(result) {
  if (!result) return "—";
  if (!result.ok) return `Ошибка: ${result.error || "не удалось выполнить запрос"}`;
  const data = result.data || {};
  if (Array.isArray(data.value) && data.value.length) {
    const lines = [data.summary || `записей: ${data.value.length}`];
    for (const row of data.value) {
      if (!row || typeof row !== "object") continue;
      lines.push(
        `- ${row.Number || "—"} | ${row.Date || "—"} | ${row.Description || row.Subject || ""}`.trimEnd()
      );
    }
    if (data.source) lines.push(`источник: ${data.source}`);
    return lines.join("\n");
  }
  if (Array.isArray(data.uids) && data.uids.length && !data.value && !data.entries) {
    const lines = [data.summary || `найдено uid: ${data.uids.length}`];
    if (data.user) lines.push(`user: ${data.user}`);
    if (data.query) lines.push(`query: ${data.query}`);
    lines.push(`uids: ${data.uids.join(", ")}`);
    if (Array.isArray(data.messages) && data.messages.length) {
      lines.push("");
      for (const row of data.messages) {
        lines.push(`- uid=${row.uid} | ${row.subject || "—"} | ${row.from || ""}`.trimEnd());
      }
    }
    return lines.join("\n");
  }
  if (Array.isArray(data.entries) && data.entries.length) {
    const lines = [data.summary || `записей: ${data.entries.length}`];
    if (data.path) lines.push(`path: ${data.path}`);
    for (const row of data.entries) {
      lines.push(`- ${row.is_dir ? "[dir]" : "[file]"} ${row.path} (${row.size ?? 0} B)`);
    }
    return lines.join("\n");
  }
  if (Array.isArray(data.apps) && data.apps.length) {
    const lines = [data.summary || `apps: ${data.apps.length}`];
    if (data.platform) lines.push(`platform: ${data.platform}`);
    if (typeof data.com_available === "boolean") {
      lines.push(`com_available: ${data.com_available}`);
    }
    for (const row of data.apps) {
      lines.push(`- ${row.id}: ${row.progid}`);
    }
    return lines.join("\n");
  }
  if (typeof data.result !== "undefined") {
    return JSON.stringify(data.result, null, 2);
  }
  if (Array.isArray(data.results) && data.results.length) {
    const lines = [data.summary || `найдено: ${data.results.length}`];
    if (data.query) lines.push(`запрос: ${data.query}`);
    for (const [idx, row] of data.results.entries()) {
      if (!row || typeof row !== "object") continue;
      lines.push(`${idx + 1}. ${row.title || "—"}`);
      if (row.url) lines.push(`   ${row.url}`);
      if (row.snippet) lines.push(`   ${row.snippet}`);
    }
    if (typeof data.text === "string" && data.text.length) {
      lines.push("", "=== текст первого результата ===", data.text.trimEnd());
    }
    return lines.join("\n");
  }
  if (typeof data.text === "string" && data.text.length) {
    const header = [
      data.title ? `Заголовок: ${data.title}` : "",
      data.url ? `URL: ${data.url}` : "",
      data.query ? `запрос: ${data.query}` : "",
      data.source ? `источник: ${data.source}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    const body = data.text.trimEnd();
    return header ? `${header}\n\n${body}` : body;
  }
  if (typeof data.stdout === "string" && data.stdout.length) {
    let out = data.stdout;
    if (data.stderr) out += `\n[stderr]\n${data.stderr}`;
    if (data.exit_code != null) out += `\n[exit_code=${data.exit_code}]`;
    if (data.cwd) out += `\n[cwd=${data.cwd}]`;
    return out.trimEnd();
  }
  if (data.summary) return String(data.summary);
  return JSON.stringify(data, null, 2);
}

async function invokeSandboxTool(toolName, payload) {
  const r = await fetch(apiUrl(`/api/v1/tools/${toolName}/invoke`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ payload }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(formatApiError(data, r.statusText));
  return data;
}

async function refreshSandboxMode() {
  const modeEl = $("sandboxMode");
  if (!modeEl) return;
  if (!token) {
    modeEl.textContent = "войдите для проверки";
    return;
  }
  try {
    const r = await fetch(apiUrl("/api/v1/tools/sandbox"), {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await r.json();
    if (!r.ok) throw new Error(formatApiError(data, r.statusText));
    modeEl.textContent = data.use_stubs ? "USE_STUBS=true (stub)" : "real integrations";
  } catch (e) {
    modeEl.textContent = "режим неизвестен";
  }
}

function parseOnecPreset(value) {
  if (!value) return null;
  const [entity, topRaw] = value.split("|");
  return {
    entity: (entity || "").trim(),
    top: Math.max(1, Number.parseInt(topRaw, 10) || 3),
  };
}

function getOnecSandboxParams() {
  const preset = parseOnecPreset($("sbOnecPreset")?.value);
  const entity = ($("sbOnecPath")?.value || preset?.entity || "Document_ТД_ВходящаяКорреспонденция")
    .trim()
    .replace(/^\//, "");
  const topRaw = $("sbOnecTop")?.value;
  const top = topRaw
    ? Math.max(1, Number.parseInt(topRaw, 10) || 3)
    : (preset?.top || 3);
  return { entity, top };
}

function syncOnecPresetFields() {
  const preset = parseOnecPreset($("sbOnecPreset")?.value);
  if (!preset) return;
  if ($("sbOnecPath") && preset.entity) $("sbOnecPath").value = preset.entity;
  if ($("sbOnecTop") && preset.top) $("sbOnecTop").value = preset.top;
}

async function runSandboxOnec() {
  if (!sandboxRequireLogin()) return;
  const { entity, top } = getOnecSandboxParams();
  setSandboxFormState("onec", "running", "Запрос OData 1С...");
  writeSandboxOut("sbOnecOut", `GET ${entity}?$format=json&$top=${top}\n...`);
  try {
    const result = await invokeSandboxTool("onec.odata_get", {
      path: `/${entity}?$top=${top}`,
      entity,
      top,
      subsystem: "document_flow",
    });
    writeSandboxOut("sbOnecOut", formatToolResult(result));
    setSandboxFormState(
      "onec",
      result.ok ? "done" : "fail",
      result.ok ? "OK" : result.error || "Ошибка"
    );
    log(`Sandbox 1C: ${result.ok ? result.data?.summary || "ok" : result.error}`);
  } catch (e) {
    writeSandboxOut("sbOnecOut", `Ошибка: ${e.message}`);
    setSandboxFormState("onec", "fail", e.message);
    log(`Sandbox 1C FAILED: ${e.message}`);
  }
}

async function runSandboxImap() {
  if (!sandboxRequireLogin()) return;
  const user = $("sbImapUser").value.trim();
  const limit = Math.max(1, Number.parseInt($("sbImapLimit").value, 10) || 3);
  setSandboxFormState("imap", "running", "Поиск писем...");
  writeSandboxOut("sbImapOut", "Выполняется imap.search...");
  try {
    const search = await invokeSandboxTool("imap.search", { query: user, user, limit });
    if (!search.ok) throw new Error(search.error || "imap.search failed");
    const uids = (search.data?.uids || []).slice(0, limit);
    const lines = [`=== imap.search (user=${user}, limit=${limit}) ===`, formatToolResult(search), ""];
    if (!uids.length) {
      lines.push("Письма не найдены.");
      writeSandboxOut("sbImapOut", lines.join("\n"));
      setSandboxFormState("imap", "done", "OK — 0 писем");
      return;
    }
    for (let i = 0; i < uids.length; i += 1) {
      const uid = uids[i];
      lines.push(`=== imap.fetch_message uid=${uid} (${i + 1}/${uids.length}) ===`);
      const msg = await invokeSandboxTool("imap.fetch_message", { uid, user });
      lines.push(formatToolResult(msg));
      lines.push("");
    }
    writeSandboxOut("sbImapOut", lines.join("\n").trimEnd());
    setSandboxFormState("imap", "done", `OK — ${uids.length} пис.`);
    log(`Sandbox IMAP: ${uids.length} messages for ${user}`);
  } catch (e) {
    writeSandboxOut("sbImapOut", `FAILED: ${e.message}`);
    setSandboxFormState("imap", "fail", e.message);
    log(`Sandbox IMAP FAILED: ${e.message}`);
  }
}

async function runSandboxBrowser() {
  if (!sandboxRequireLogin()) return;
  const url = ($("sbBrowserUrl")?.value || "").trim();
  const query = ($("sbBrowserQuery")?.value || "").trim();
  setSandboxFormState("browser", "running", url ? "Загрузка страницы..." : "Поиск...");
  writeSandboxOut("sbBrowserOut", url ? `GET ${url}\n...` : `Поиск: ${query}\n...`);
  try {
    const payload = { selector: "body", fetch_first: true };
    if (url) payload.url = url;
    else if (query) payload.query = query;
    else throw new Error("Укажите URL или поисковый запрос");
    const text = await invokeSandboxTool("browser.extract_text", payload);
    writeSandboxOut("sbBrowserOut", formatToolResult(text));
    setSandboxFormState("browser", text.ok ? "done" : "fail", text.ok ? "OK" : text.error || "Ошибка");
    log(`Sandbox Browser: ${text.ok ? text.data?.summary || "ok" : text.error}`);
  } catch (e) {
    writeSandboxOut("sbBrowserOut", `Ошибка: ${e.message}`);
    setSandboxFormState("browser", "fail", e.message);
    log(`Sandbox Browser FAILED: ${e.message}`);
  }
}

async function runSandboxShell() {
  if (!sandboxRequireLogin()) return;
  const command = $("sbShellCmd").value.trim() || "dir";
  const runtime = ($("sbShellRuntime")?.value || "native").trim();
  const cwd = ($("sbShellCwd")?.value || "").trim();
  setSandboxFormState("shell", "running", "Выполнение команды...");
  writeSandboxOut("sbShellOut", `> ${command}\n...`);
  try {
    const payload = { command, runtime };
    if (cwd) payload.cwd = cwd;
    const result = await invokeSandboxTool("shell.run", payload);
    writeSandboxOut("sbShellOut", `$ ${command}\n${formatToolResult(result)}`);
    setSandboxFormState("shell", result.ok ? "done" : "fail", result.ok ? "OK" : result.error || "Ошибка");
    log(`Sandbox Shell (${runtime}): ${command}`);
  } catch (e) {
    writeSandboxOut("sbShellOut", `$ ${command}\nFAILED: ${e.message}`);
    setSandboxFormState("shell", "fail", e.message);
    log(`Sandbox Shell FAILED: ${e.message}`);
  }
}

async function runSandboxFs() {
  if (!sandboxRequireLogin()) return;
  const toolName = ($("sbFsOp")?.value || "fs.list").trim();
  const path = ($("sbFsPath")?.value || ".").trim();
  const path2 = ($("sbFsPath2")?.value || "").trim();
  const content = ($("sbFsContent")?.value || "").trim();
  setSandboxFormState("fs", "running", toolName);
  writeSandboxOut("sbFsOut", `${toolName} ${path}\n...`);
  try {
    let payload;
    if (toolName === "fs.move" || toolName === "fs.copy") {
      if (!path2) throw new Error("Укажите путь to");
      payload = { from: path, to: path2 };
    } else if (toolName === "fs.write") {
      payload = { path, content, mode: "overwrite" };
    } else {
      payload = { path };
      if (toolName === "fs.read") payload.max_bytes = 4096;
    }
    const result = await invokeSandboxTool(toolName, payload);
    if (toolName === "fs.read" && result.ok && result.data?.content) {
      writeSandboxOut(
        "sbFsOut",
        `${toolName} ${path}\n${result.data.content}`
      );
    } else {
      writeSandboxOut("sbFsOut", formatToolResult(result));
    }
    setSandboxFormState("fs", result.ok ? "done" : "fail", result.ok ? "OK" : result.error || "Ошибка");
    log(`Sandbox FS: ${toolName} ${path}`);
  } catch (e) {
    writeSandboxOut("sbFsOut", `FAILED: ${e.message}`);
    setSandboxFormState("fs", "fail", e.message);
  }
}

async function runSandboxComList() {
  if (!sandboxRequireLogin()) return;
  setSandboxFormState("com", "running", "com.list_apps");
  writeSandboxOut("sbComOut", "com.list_apps...\n");
  try {
    const result = await invokeSandboxTool("com.list_apps", {});
    writeSandboxOut("sbComOut", formatToolResult(result));
    setSandboxFormState("com", result.ok ? "done" : "fail", result.ok ? "OK" : result.error || "Ошибка");
    log(`Sandbox COM: list_apps`);
  } catch (e) {
    writeSandboxOut("sbComOut", `FAILED: ${e.message}`);
    setSandboxFormState("com", "fail", e.message);
  }
}

async function runSandboxCom() {
  if (!sandboxRequireLogin()) return;
  const app = ($("sbComApp")?.value || "onec").trim();
  const method = ($("sbComMethod")?.value || "Connect").trim();
  let args = [];
  try {
    args = JSON.parse($("sbComArgs")?.value || "[]");
    if (!Array.isArray(args)) throw new Error("args must be array");
  } catch (e) {
    writeSandboxOut("sbComOut", `Args JSON: ${e.message}`);
    setSandboxFormState("com", "fail", "invalid args");
    return;
  }
  setSandboxFormState("com", "running", "COM connect...");
  writeSandboxOut("sbComOut", `com.connect(${app})...\n`);
  try {
    const connect = await invokeSandboxTool("com.connect", { app });
    if (!connect.ok) throw new Error(connect.error || "connect failed");
    const sessionId = connect.data?.session_id;
    writeSandboxOut("sbComOut", `session: ${sessionId}\ncom.invoke(${method})...\n`);
    const invoke = await invokeSandboxTool("com.invoke", {
      session_id: sessionId,
      method,
      args,
    });
    await invokeSandboxTool("com.release", { session_id: sessionId }).catch(() => {});
    const lines = [
      `app: ${app}`,
      `session: ${sessionId}`,
      `method: ${method}`,
      formatToolResult(invoke),
    ];
    writeSandboxOut("sbComOut", lines.join("\n"));
    setSandboxFormState("com", invoke.ok ? "done" : "fail", invoke.ok ? "OK" : invoke.error || "Ошибка");
    log(`Sandbox COM: ${app}.${method}`);
  } catch (e) {
    writeSandboxOut("sbComOut", `FAILED: ${e.message}`);
    setSandboxFormState("com", "fail", e.message);
  }
}

function clearSandboxOutput() {
  for (const id of ["sbOnecOut", "sbImapOut", "sbBrowserOut", "sbShellOut", "sbFsOut", "sbComOut"]) {
    writeSandboxOut(id, "—");
  }
  for (const tool of ["onec", "imap", "browser", "shell", "fs", "com"]) {
    setSandboxFormState(tool, null, "");
  }
}

async function runAllSandboxTests() {
  if (!sandboxRequireLogin()) return;
  log("Sandbox: run all...");
  await runSandboxOnec();
  await runSandboxImap();
  await runSandboxBrowser();
  await runSandboxShell();
  await runSandboxFs();
  await runSandboxCom();
  log("Sandbox: все 6 форм выполнены");
}

function syncFsOpFields() {
  const op = ($("sbFsOp")?.value || "fs.list").trim();
  const path2Wrap = $("sbFsPath2Wrap");
  const contentWrap = $("sbFsContentWrap");
  const needsPath2 = op === "fs.move" || op === "fs.copy";
  const needsContent = op === "fs.write";
  if (path2Wrap) path2Wrap.classList.toggle("sandbox-field-hidden", !needsPath2);
  if (contentWrap) contentWrap.classList.toggle("sandbox-field-hidden", !needsContent);
}

function initSandboxPanel() {
  const bindings = [
    ["btnSbOnec", runSandboxOnec],
    ["btnSbImap", runSandboxImap],
    ["btnSbBrowser", runSandboxBrowser],
    ["btnSbShell", runSandboxShell],
    ["btnSbFs", runSandboxFs],
    ["btnSbComList", runSandboxComList],
    ["btnSbCom", runSandboxCom],
  ];
  for (const [id, fn] of bindings) {
    const btn = $(id);
    if (btn) btn.addEventListener("click", fn);
  }
  const fsOp = $("sbFsOp");
  if (fsOp) {
    fsOp.addEventListener("change", syncFsOpFields);
    syncFsOpFields();
  }
  const btnAll = $("btnSandboxAll");
  if (btnAll) btnAll.addEventListener("click", runAllSandboxTests);
  const btnClear = $("btnSandboxClear");
  if (btnClear) btnClear.addEventListener("click", clearSandboxOutput);
  const preset = $("sbOnecPreset");
  if (preset) preset.addEventListener("change", syncOnecPresetFields);
  syncOnecPresetFields();
  refreshSandboxMode();
}

async function loadSandboxTests() {
  await refreshSandboxMode();
}

async function loadDiagram() {
  const node = $("diagramSource");
  if (!node) return;
  try {
    const r = await fetch("diagram.mmd");
    const text = await r.text();
    node.textContent = text;
    await mermaid.run({ nodes: [node] });
  } catch (e) {
    log(`Diagram load failed: ${e.message}`);
  }
}

function renderCmdBlock() {
  const el = $("cmdBlock");
  if (!el) return;
  el.textContent = `rem === Всё в Docker (рекомендуется) ===
cd c:\\Users\\mdj\\Desktop\\конструктор\\Consturctor
scripts\\docker_up.cmd

rem Gateway: http://127.0.0.1:7812/health
rem Demo UI: http://127.0.0.1:8790/

rem === Mock agent scenarios ===
scripts\\run_agent_mocks.cmd --all

rem === Остановка ===
scripts\\docker_down.cmd

rem === FigJam v2 ===
${FIGJAM_URL}`;
}

function clampThreshold(value, fallback = 0) {
  const n = Number.parseInt(String(value), 10);
  if (Number.isNaN(n)) return fallback;
  return Math.min(100, Math.max(0, n));
}

let suppressThresholdSideEffects = false;

function getAccessThresholds() {
  const promote = clampThreshold($("promoteThreshold").value, 80);
  let demote = clampThreshold($("demoteThreshold").value, 60);
  if (demote >= promote) {
    demote = Math.max(0, promote - 1);
    const demoteEl = $("demoteThreshold");
    if (demoteEl && demoteEl.value !== String(demote)) {
      suppressThresholdSideEffects = true;
      demoteEl.value = String(demote);
      suppressThresholdSideEffects = false;
    }
  }
  return { promote, demote };
}

function renderAccessLevelCards() {
  const box = $("accessLevelCards");
  box.innerHTML = "";
  for (const spec of ACCESS_LEVELS) {
    const card = document.createElement("div");
    card.className = "access-level-card" + (spec.level === accessSim.level ? " active" : "");
    const okItems = spec.ok.map((x) => `<li class="ok-item">${x}</li>`).join("");
    const hitlItems = spec.hitl.map((x) => `<li class="hitl-item">${x}</li>`).join("");
    const noItems = spec.forbidden.map((x) => `<li class="no-item">${x}</li>`).join("");
    card.innerHTML = `
      <div class="lvl-head">Уровень ${spec.level}: ${spec.title}</div>
      <div class="hint">${spec.summary}</div>
      <ul>${okItems}${hitlItems}${noItems}</ul>`;
    box.appendChild(card);
  }
}

function setAccessNotice(text, kind) {
  const el = $("accessNotice");
  if (!text) {
    el.className = "access-notice hidden";
    el.textContent = "";
    return;
  }
  el.className = `access-notice ${kind || "warn"}`;
  el.textContent = text;
}

function positionThresholdMark(labelId, markerId, percent) {
  const clamped = Math.min(100, Math.max(0, percent));
  $(labelId).style.left = `${clamped}%`;
  $(markerId).style.left = `${clamped}%`;
}

function severeLineForDemote(demote) {
  return Math.max(0, demote - SEVERE_BELOW_THRESHOLD_PP);
}

function changeKindLabel(kind) {
  if (kind === 1) return "+1";
  if (kind === -1) return "−1";
  return "0";
}

function normalizeChangeKind(value) {
  const n = Number(value);
  if (n === 1 || n === -1) return n;
  return 0;
}

function resetAccessWeekState() {
  accessSim.changeKind = 0;
  accessSim.promoteOffered = false;
}

/**
 * Состояние: level + changeKind (−1 / 0 / +1).
 * kind=0 + KPI↑ — порог фиксируется, предложение повышения только при закрытии недели.
 * kind=−1 + KPI↑ — восстановление сразу (kind→0, level+1).
 */
function applyAccessTransition(prevAccuracy, newAccuracy, delta, { thresholdChange = false } = {}) {
  accessSim.changeKind = normalizeChangeKind(accessSim.changeKind);
  const kindBefore = accessSim.changeKind;

  const { promote, demote } = getAccessThresholds();
  const severeLine = severeLineForDemote(demote);
  const notices = [];
  const errorEvent = delta < 0;
  const improveEvent = delta > 0;

  const crossedPromoteUp = prevAccuracy < promote && newAccuracy >= promote;
  const crossedDemote = prevAccuracy > demote && newAccuracy <= demote;
  const crossedSevere = prevAccuracy > severeLine && newAccuracy <= severeLine;
  const inSevere = newAccuracy <= severeLine;
  const inDemote = newAccuracy <= demote;

  if ((errorEvent && crossedSevere) || (thresholdChange && inSevere)) {
    if (accessSim.level !== 1) {
      const from = accessSim.level;
      accessSim.level = 1;
      accessSim.changeKind = -1;
      accessSim.promoteOffered = false;
      notices.push(`Крит. порог (≤ ${severeLine}%): уровень ${from} → 1, вид −1.`);
    }
  } else if (
    ((errorEvent && crossedDemote) || (thresholdChange && inDemote)) &&
    accessSim.changeKind > -1
  ) {
    if (accessSim.level > 1) {
      accessSim.level -= 1;
    }
    accessSim.changeKind = -1;
    accessSim.promoteOffered = false;
    notices.push(
      `Порог понижения (${demote}%): уровень → ${accessSim.level}, вид −1 ` +
        `(был ${changeKindLabel(kindBefore)}).`
    );
  }

  if (crossedPromoteUp && improveEvent && !thresholdChange && accessSim.level < 4) {
    const kind = accessSim.changeKind;
    if (kind === 1) {
      notices.push(
        `KPI ${prevAccuracy}% → ${newAccuracy}%: повышение уже было (вид +1), уровень без изменений.`
      );
    } else if (kind === -1) {
      accessSim.level += 1;
      accessSim.changeKind = 0;
      notices.push(
        `Восстановление (вид был −1): ${prevAccuracy}% → ${newAccuracy}% (≥ ${promote}%) — ` +
          `уровень +1 → ${accessSim.level}, вид 0.`
      );
    } else if (kind === 0) {
      notices.push(
        `KPI ${prevAccuracy}% → ${newAccuracy}% (≥ ${promote}%): порог выполнен — ` +
          `повышение будет предложено при закрытии недели (кнопка «+1 неделя»).`
      );
    }
  }

  return notices;
}

function renderAccessPanel() {
  const { promote, demote } = getAccessThresholds();
  const spec = ACCESS_LEVELS.find((x) => x.level === accessSim.level) || ACCESS_LEVELS[0];

  $("weekNum").textContent = String(accessSim.week);
  $("weeklyAccuracy").textContent = String(accessSim.accuracy);
  $("levelNum").textContent = String(accessSim.level);
  $("levelTitle").textContent = spec.title;
  $("accessLevelBadge").dataset.level = String(accessSim.level);
  $("accessAgentLabel").textContent =
    `Агент: ${accessSim.agentId} · неделя ${accessSim.week} · уровень ${accessSim.level} · ` +
    `вид ${changeKindLabel(accessSim.changeKind)}`;

  $("accuracyBar").style.width = `${accessSim.accuracy}%`;
  $("demoteZone").style.width = `${demote}%`;
  $("promoteZone").style.width = `${100 - promote}%`;
  $("demoteScaleLabel").textContent = `↓ ${demote}%`;
  $("promoteScaleLabel").textContent = `↑ ${promote}%`;
  const severeLine = severeLineForDemote(demote);
  $("severeScaleLabel").textContent = `крит. ${severeLine}%`;
  positionThresholdMark("demoteScaleLabel", "demoteMarker", demote);
  positionThresholdMark("promoteScaleLabel", "promoteMarker", promote);
  if (severeLine > 0) {
    $("severeScaleLabel").style.display = "";
    $("severeMarker").style.display = "";
    positionThresholdMark("severeScaleLabel", "severeMarker", severeLine);
  } else {
    $("severeScaleLabel").style.display = "none";
    $("severeMarker").style.display = "none";
  }

  renderAccessLevelCards();

  const promoteBtn = $("btnPromote");
  if (promoteBtn) {
    if (accessSim.promoteOffered && accessSim.changeKind === 0 && accessSim.level < 4) {
      promoteBtn.classList.remove("hidden");
      promoteBtn.textContent = `Подтвердить повышение до уровня ${accessSim.level + 1}`;
    } else {
      promoteBtn.classList.add("hidden");
    }
  }
}

function applyAccessLevelNotices(prevAccuracy, newAccuracy, delta, options) {
  const notices = applyAccessTransition(prevAccuracy, newAccuracy, delta, options);
  if (!notices.length) {
    if (delta >= 0 && !options?.thresholdChange) setAccessNotice("", "");
    return null;
  }
  const hasErr = notices.some((msg) => msg.includes("→ 1") || msg.includes("−1"));
  const hasOk = notices.some(
    (msg) => msg.includes("Доступно повышение") || msg.includes("доступно повышение") || msg.includes("Восстановление")
  );
  setAccessNotice(notices.join(" "), hasErr ? "err" : hasOk ? "ok" : "warn");
  for (const msg of notices) log(`ACCESS: ${msg}`);
  return notices.join(" ");
}

function adjustAccessAccuracy(delta) {
  const prev = accessSim.accuracy;
  accessSim.accuracy = Math.min(100, Math.max(0, accessSim.accuracy + delta));
  applyAccessLevelNotices(prev, accessSim.accuracy, delta);
  renderAccessPanel();
  log(
    `KPI симуляция: точность ${accessSim.accuracy}% (неделя ${accessSim.week}, ` +
      `уровень ${accessSim.level}, вид ${changeKindLabel(accessSim.changeKind)})`
  );
}

function onDemoteThresholdChange() {
  if (suppressThresholdSideEffects) return;
  const prevAccuracy = accessSim.accuracy;
  applyAccessLevelNotices(prevAccuracy, prevAccuracy, 0, { thresholdChange: true });
  renderAccessPanel();
}

function closeAccessWeek() {
  const { promote } = getAccessThresholds();
  const closedWeek = accessSim.week;
  const accuracy = accessSim.accuracy;

  if (
    accuracy >= promote &&
    accessSim.changeKind === 0 &&
    accessSim.level < 4 &&
    !accessSim.promoteOffered
  ) {
    accessSim.promoteOffered = true;
    setAccessNotice(
      `Неделя ${closedWeek}: KPI ${accuracy}% ≥ ${promote}%. ` +
        `Подтвердите повышение до уровня ${accessSim.level + 1} (кнопка) или нажмите «+1 неделя» ещё раз, чтобы закрыть без повышения.`,
      "ok"
    );
    log(`ACCESS: promote offered at week ${closedWeek} end (${accuracy}% ≥ ${promote}%)`);
    renderAccessPanel();
    return;
  }

  if (accessSim.promoteOffered && accessSim.changeKind === 0) {
    setAccessNotice(
      `Неделя ${closedWeek} закрыта без подтверждения повышения. Неделя ${closedWeek + 1}: вид → 0.`,
      "warn"
    );
  } else {
    setAccessNotice(
      `Неделя ${closedWeek} закрыта. Неделя ${closedWeek + 1}: вид → 0, уровень ${accessSim.level} сохранён.`,
      "warn"
    );
  }

  accessSim.week += 1;
  resetAccessWeekState();
  accessSim.accuracy = 70;
  log(
    `ACCESS: week ${closedWeek} → ${accessSim.week}, level ${accessSim.level}, changeKind=0, accuracy=70%`
  );
  renderAccessPanel();
}

function promoteAccessLevel() {
  if (!accessSim.promoteOffered || accessSim.changeKind !== 0 || accessSim.level >= 4) return;
  accessSim.level += 1;
  accessSim.changeKind = 1;
  accessSim.promoteOffered = false;
  setAccessNotice(
    `Повышение подтверждено: уровень ${accessSim.level}, вид +1.`,
    "ok"
  );
  log(`ACCESS: promoted → level ${accessSim.level}, changeKind=+1`);
  renderAccessPanel();
}

function initAccessPanel() {
  renderAccessLevelCards();
  renderAccessPanel();

  $("promoteThreshold").addEventListener("input", renderAccessPanel);
  $("demoteThreshold").addEventListener("input", renderAccessPanel);
  $("promoteThreshold").addEventListener("change", renderAccessPanel);
  $("demoteThreshold").addEventListener("change", onDemoteThresholdChange);
  $("btnAccMinus").addEventListener("click", () => adjustAccessAccuracy(-5));
  $("btnAccPlus").addEventListener("click", () => adjustAccessAccuracy(5));
  $("btnWeekPlus").addEventListener("click", closeAccessWeek);
  $("btnPromote").addEventListener("click", promoteAccessLevel);
}

document.addEventListener("DOMContentLoaded", () => {
  try {
    mermaid.initialize({ startOnLoad: false, theme: "default" });
  } catch (e) {
    console.error("mermaid init failed", e);
  }
  loadDiagram();
  loadErpStatus();
  try {
    initAccessPanel();
  } catch (e) {
    console.error("access panel init failed", e);
    log(`Access panel init failed: ${e.message}`);
  }
  try {
    initSandboxPanel();
  } catch (e) {
    console.error("sandbox init failed", e);
    log(`Sandbox init failed: ${e.message}`);
  }
  $("btnLogin").addEventListener("click", login);
  const btnHealth = $("btnHealth");
  if (btnHealth) {
    btnHealth.addEventListener("click", () => renderServices().then(() => log("Health check завершён")));
  }
  $("btnRun")?.addEventListener("click", startRun);
  $("btnTool")?.addEventListener("click", invokeToolViaRuntime);
  $("btnKpi")?.addEventListener("click", kpiSummary);
  log("Demo UI v2. FigJam: " + FIGJAM_URL);
  log("Войдите (кнопка 1), затем используйте Sandbox инструментов.");
});
