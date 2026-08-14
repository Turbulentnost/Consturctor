/** Роутинг и страницы web-конструктора. */

const state = {
  user: null,
  registerMode: false,
  regulation: null,
  roleMatch: null,
  matchIndex: 0,
  agentsTab: "published",
  kpiAgentData: [],
  kpiAgentOrder: [],
  kpiActiveAgentId: "",
  kpiAgentColors: {},
};

const KPI_TAB_COLORS = ["#c5c5c5", "#8fa88a", "#c4a484", "#9eb5c4", "#b8a4c8"];
const KPI_AGENT_DEFAULT_COLORS = {
  "test-agent-zhalybin-maxim-v1": "#c5c5c5",
  "test-agent-demo-inbound-v1": "#8fa88a",
  "test-agent-demo-mto-v1": "#c4a484",
  "test-agent-demo-analytics-v1": "#9eb5c4",
};
const KPI_FOLDER_PALETTE = [
  "#c5c5c5",
  "#8fa88a",
  "#c4a484",
  "#9eb5c4",
  "#b8a4c8",
  "#e8b4b8",
  "#a8c5e8",
  "#d4c4a8",
  "#98c9a8",
  "#c9a8d4",
  "#f0d090",
  "#90c0d0",
  "#d0a090",
  "#b0b0b0",
  "#88a898",
];
const KPI_TAB_ORDER_KEY = "constructor_kpi_agent_tab_order";
const KPI_TAB_COLORS_KEY = "constructor_kpi_agent_tab_colors";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3200);
}

function pct(v) {
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function rateVariant(value, { good = 0.8, warn = 0.6, invert = false } = {}) {
  const v = Number(value) || 0;
  const ok = invert ? v <= good : v >= good;
  const mid = invert ? v <= warn : v >= warn;
  if (ok) return "good";
  if (mid) return "warn";
  return "bad";
}

function formatDuration(sec) {
  const value = Number(sec) || 0;
  if (value <= 0) return "—";
  if (value < 60) return `${Math.round(value)} сек`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return seconds ? `${minutes} мин ${seconds} сек` : `${minutes} мин`;
}

function renderKpiTile({ icon, label, value, hint, variant, badge }) {
  const badgeHtml = badge
    ? `<span class="kpi-tile-badge kpi-tile-badge--${variant}">${escapeHtml(badge)}</span>`
    : "";
  return `<div class="kpi-tile kpi-tile--${variant}">
    <div class="kpi-tile-icon">${icon}</div>
    <div class="kpi-tile-value">${escapeHtml(String(value))}</div>
    <div class="kpi-tile-label">${escapeHtml(label)}</div>
    ${hint ? `<div class="kpi-tile-hint">${escapeHtml(hint)}</div>` : ""}
    ${badgeHtml}
  </div>`;
}

function buildSummaryTiles(summary) {
  const tasksHint =
    summary.tasks_total > 0
      ? `${summary.tasks_correct || 0} из ${summary.tasks_total} задач`
      : "нет задач в истории";
  return [
    renderKpiTile({
      icon: "👤",
      label: "HITL",
      value: pct(summary.hitl_rate),
      hint: "участие оператора",
      variant: rateVariant(summary.hitl_rate, { good: 0.15, warn: 0.3, invert: true }),
    }),
    renderKpiTile({
      icon: "◎",
      label: "Успех задач",
      value: pct(summary.task_success_rate || 0),
      hint: tasksHint,
      variant: rateVariant(summary.task_success_rate || 0),
    }),
    renderKpiTile({
      icon: "✔",
      label: "Выполненные задачи",
      value: summary.completed_tasks_total ?? 0,
      hint: "завершённые процессы",
      variant: (summary.completed_tasks_total ?? 0) > 0 ? "good" : "muted",
    }),
    renderKpiTile({
      icon: "⏱",
      label: "Среднее время",
      value: formatDuration(summary.avg_execution_duration_sec),
      hint: "средняя длительность процесса",
      variant: "info",
    }),
  ].join("");
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderExecutionHistory(items) {
  if (!items || !items.length) {
    return "<p class='muted'>История выполнения пуста</p>";
  }
  const rows = items
    .map(
      (item) => `<tr>
        <td>#${item.process_seq}</td>
        <td>${escapeHtml(formatDateTime(item.started_at))}</td>
        <td>${item.is_completed ? escapeHtml(formatDuration(item.duration_sec || 0)) : "—"}</td>
        <td><span class="history-status history-status--${item.is_completed ? "done" : item.is_started ? "run" : "new"}">${
          item.is_completed ? "Завершён" : item.is_started ? "В работе" : "Создан"
        }</span></td>
      </tr>`
    )
    .join("");
  return `<div class="kpi-history-wrap">
    <div class="kpi-history-title">История выполнения (${items.length})</div>
    <table class="kpi-history-table">
      <thead><tr><th>№</th><th>Начало</th><th>Длительность</th><th>Статус</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderAgentPanelContent(c, summary, historyItems) {
  return `
    <div class="meta">${escapeHtml(agentDisplayTitle(c))} · ${escapeHtml(c.department || "без отдела")}</div>
    <div class="kpi-grid kpi-grid--agent">${buildSummaryTiles(summary || {})}</div>
    ${renderExecutionHistory(historyItems || [])}
  `;
}

function renderFolderSettingsContent(card, folderColorValue) {
  return `<div class="kpi-folder-settings-panel" data-agent-id="${escapeHtml(card.agent_id)}">
    ${renderFolderNameEditor(card)}
    ${renderFolderColorPicker(card.agent_id, folderColorValue)}
  </div>`;
}

function renderFolderSettingsToolbar(card, folderColorValue) {
  return `<div class="kpi-folder-toolbar">
    <button
      type="button"
      class="kpi-folder-settings-btn"
      aria-label="Настройки папки"
      aria-expanded="false"
      aria-controls="kpi-folder-settings-popover"
      title="Настройки папки"
    >
      <svg class="kpi-folder-settings-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.49.49 0 0 0 .12-.63l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96a7.02 7.02 0 0 0-1.63-.94l-.36-2.54A.484.484 0 0 0 14 2h-4a.484.484 0 0 0-.49.42l-.36 2.54c-.59.24-1.13.57-1.63.94l-2.39-.96a.488.488 0 0 0-.59.22L2.74 8.87a.48.48 0 0 0 .12.63l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.49.49 0 0 0-.12.63l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.37 1.04.7 1.63.94l.36 2.54c.05.24.24.42.49.42h4c.25 0 .44-.18.49-.42l.36-2.54c.59-.24 1.13-.57 1.63-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.49.49 0 0 0-.12-.63l-2.03-1.58ZM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2Z"/>
      </svg>
    </button>
    <div id="kpi-folder-settings-popover" class="kpi-folder-settings-popover hidden">
      ${renderFolderSettingsContent(card, folderColorValue)}
    </div>
  </div>`;
}

function agentDisplayTitle(card) {
  return (card.title || card.agent_id || "Агент").trim();
}

function parseAgentTabTitle(card) {
  const full = agentDisplayTitle(card);
  const colon = full.indexOf(":");
  if (colon >= 0) {
    const prefix = full.slice(0, colon).trim();
    const name = full.slice(colon + 1).trim();
    return { prefix, name: name || full };
  }
  return { prefix: "", name: full };
}

function renderFolderTabLabelHtml(card) {
  const { prefix, name } = parseAgentTabTitle(card);
  if (prefix) {
    return `<span class="kpi-folder-tab-num">${escapeHtml(prefix)}</span><span class="kpi-folder-tab-name">${escapeHtml(name)}</span>`;
  }
  return `<span class="kpi-folder-tab-name kpi-folder-tab-name--solo">${escapeHtml(name)}</span>`;
}

function renderFolderNameEditor(card) {
  const title = agentDisplayTitle(card);
  return `<div class="kpi-folder-settings-section kpi-folder-name-bar" data-agent-id="${escapeHtml(card.agent_id)}">
    <label class="kpi-folder-name-label" for="kpi-name-${escapeHtml(card.agent_id)}">Имя агента</label>
    <div class="kpi-folder-name-row">
      <input
        id="kpi-name-${escapeHtml(card.agent_id)}"
        type="text"
        class="kpi-folder-name-input"
        data-agent-id="${escapeHtml(card.agent_id)}"
        value="${escapeHtml(title)}"
        maxlength="80"
        placeholder="Название на вкладке"
        autocomplete="off"
      />
      <button type="button" class="btn ghost kpi-folder-name-save" data-agent-id="${escapeHtml(card.agent_id)}">Сохранить</button>
    </div>
  </div>`;
}

function applyAgentTitlesToStack(stackEl) {
  if (!stackEl) return;

  const byId = new Map(state.kpiAgentData.map((item) => [item.card.agent_id, item]));
  stackEl.querySelectorAll(".kpi-folder-tab-slot").forEach((tab) => {
    const item = byId.get(tab.dataset.agentId);
    if (!item) return;
    const label = tab.querySelector(".kpi-folder-tab-label");
    if (label) label.innerHTML = renderFolderTabLabelHtml(item.card);
  });
}

async function saveAgentTitle(agentId, rawTitle, stackEl) {
  const title = String(rawTitle || "").trim();
  if (!title) {
    toast("Имя не может быть пустым");
    return false;
  }

  const item = state.kpiAgentData.find((entry) => entry.card.agent_id === agentId);
  const previous = item ? agentDisplayTitle(item.card) : "";
  if (title === previous) return true;

  try {
    const updated = await Api.updateKpiAgentTitle(agentId, title);
    if (item) item.card.title = updated.title || title;
    applyAgentTitlesToStack(stackEl);
    toast("Имя агента сохранено");
    return true;
  } catch (err) {
    toast(err.message || "Не удалось сохранить имя");
    return false;
  }
}

function bindFolderNameEditor(stackEl) {
  if (!stackEl) return;

  stackEl.querySelectorAll(".kpi-folder-name-input").forEach((input) => {
    const agentId = input.dataset.agentId;
    const saveBtn = stackEl.querySelector(`.kpi-folder-name-save[data-agent-id="${agentId}"]`);
    let saving = false;

    const commit = async () => {
      if (saving) return;
      saving = true;
      input.disabled = true;
      if (saveBtn) saveBtn.disabled = true;

      const ok = await saveAgentTitle(agentId, input.value, stackEl);
      if (!ok) {
        const item = state.kpiAgentData.find((entry) => entry.card.agent_id === agentId);
        input.value = item ? agentDisplayTitle(item.card) : agentId;
      } else {
        const item = state.kpiAgentData.find((entry) => entry.card.agent_id === agentId);
        if (item) input.value = agentDisplayTitle(item.card);
      }

      input.disabled = false;
      if (saveBtn) saveBtn.disabled = false;
      saving = false;
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      }
    });

    if (saveBtn) {
      saveBtn.addEventListener("mousedown", (e) => e.preventDefault());
      saveBtn.addEventListener("click", (e) => {
        e.preventDefault();
        commit();
      });
    }
  });
}

function defaultFolderColor(index) {
  return KPI_TAB_COLORS[index % KPI_TAB_COLORS.length];
}

function defaultColorForAgent(agentId, index) {
  return KPI_AGENT_DEFAULT_COLORS[agentId] || defaultFolderColor(index);
}

function ensureAgentFolderColors(order) {
  let changed = false;
  order.forEach((agentId, index) => {
    if (!normalizeHexColor(state.kpiAgentColors[agentId])) {
      state.kpiAgentColors[agentId] = defaultColorForAgent(agentId, index);
      changed = true;
    }
  });
  if (changed) saveKpiAgentColors(state.kpiAgentColors);
}

function loadKpiAgentColors() {
  try {
    const raw = localStorage.getItem(KPI_TAB_COLORS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveKpiAgentColors(colors) {
  localStorage.setItem(KPI_TAB_COLORS_KEY, JSON.stringify(colors));
}

function normalizeHexColor(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(trimmed)) return trimmed.toLowerCase();
  if (/^#[0-9a-fA-F]{3}$/.test(trimmed)) {
    const [, r, g, b] = trimmed.match(/^#(.)(.)(.)$/) || [];
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return "";
}

function folderColorForAgent(agentId, index = 0) {
  const saved = normalizeHexColor(state.kpiAgentColors[agentId]);
  if (saved) return saved;
  return defaultColorForAgent(agentId, index);
}

function hexToRgb(hex) {
  const normalized = normalizeHexColor(hex);
  if (!normalized) return { r: 197, g: 197, b: 197 };
  return {
    r: parseInt(normalized.slice(1, 3), 16),
    g: parseInt(normalized.slice(3, 5), 16),
    b: parseInt(normalized.slice(5, 7), 16),
  };
}

function colorLuminance({ r, g, b }) {
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

function isDarkFolderColor(hex) {
  return colorLuminance(hexToRgb(hex)) < 0.52;
}

function folderForegroundColor(hex) {
  return isDarkFolderColor(hex) ? "#f4f6f5" : "#101817";
}

function folderMutedForegroundColor(hex) {
  if (isDarkFolderColor(hex)) {
    return "rgba(244, 246, 245, 0.88)";
  }
  const { r, g, b } = hexToRgb(hex);
  const mix = (channel) => Math.max(0, Math.min(255, Math.round(channel * 0.28)));
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
}

function inactiveTabRgb(hex) {
  const { r, g, b } = hexToRgb(hex);
  return {
    r: Math.round(r * 0.88 + 255 * 0.12),
    g: Math.round(g * 0.88 + 255 * 0.12),
    b: Math.round(b * 0.88 + 255 * 0.12),
  };
}

function folderTabTextColor(hex, isActive) {
  const rgb = isActive ? hexToRgb(hex) : inactiveTabRgb(hex);
  return colorLuminance(rgb) < 0.52 ? "#f4f6f5" : "#101817";
}

function applyFolderTheme(stackEl, activeColor) {
  const dark = isDarkFolderColor(activeColor);
  stackEl.style.setProperty("--folder-fg", folderForegroundColor(activeColor));
  stackEl.style.setProperty("--folder-fg-muted", folderMutedForegroundColor(activeColor));
  stackEl.style.setProperty(
    "--folder-control-bg",
    dark
      ? "color-mix(in srgb, var(--folder-color) 38%, #ffffff)"
      : "color-mix(in srgb, var(--folder-color) 58%, #ffffff)"
  );
  stackEl.style.setProperty(
    "--folder-border",
    dark ? "rgba(244, 246, 245, 0.18)" : "rgba(16, 24, 23, 0.14)"
  );
  stackEl.dataset.folderTone = dark ? "dark" : "light";
}

function renderFolderColorPicker(agentId, currentColor) {
  const normalized = normalizeHexColor(currentColor) || defaultFolderColor(0);
  const swatches = KPI_FOLDER_PALETTE.map(
    (color) => `<button
      type="button"
      class="kpi-color-swatch${color.toLowerCase() === normalized ? " is-selected" : ""}"
      data-agent-id="${escapeHtml(agentId)}"
      data-color="${color}"
      style="--swatch:${color}"
      aria-label="Цвет ${color}"
      title="${color}"
    ></button>`
  ).join("");

  return `<div class="kpi-folder-settings-section kpi-folder-color-bar" data-agent-id="${escapeHtml(agentId)}">
    <span class="kpi-folder-color-label">Цвет папки</span>
    <div class="kpi-folder-palette" role="listbox" aria-label="Палитра цветов">${swatches}</div>
    <label class="kpi-folder-color-custom" title="Свой цвет">
      <input
        type="color"
        class="kpi-folder-color-input"
        value="${normalized}"
        data-agent-id="${escapeHtml(agentId)}"
        aria-label="Выбрать свой цвет"
      />
      <span aria-hidden="true">+</span>
    </label>
  </div>`;
}

function applyFolderColorsToStack(stackEl) {
  if (!stackEl) return;

  const byId = new Map(state.kpiAgentData.map((item) => [item.card.agent_id, item]));
  const order = state.kpiAgentOrder.filter((id) => byId.has(id));
  const activeIndex = order.indexOf(state.kpiActiveAgentId);

  stackEl.querySelectorAll(".kpi-folder-tab-slot").forEach((tab, index) => {
    const agentId = tab.dataset.agentId;
    if (!agentId) return;
    const color = folderColorForAgent(agentId, index);
    const isActive = tab.classList.contains("is-active");
    tab.style.setProperty("--folder-color", color);
    tab.style.setProperty("--folder-tab-fg", folderTabTextColor(color, isActive));
  });

  if (activeIndex >= 0) {
    const activeColor = folderColorForAgent(state.kpiActiveAgentId, activeIndex);
    stackEl.style.setProperty("--folder-color", activeColor);
    applyFolderTheme(stackEl, activeColor);
  }
}

function updateFolderColorPickerUi(stackEl, agentId, color) {
  const panel = stackEl.querySelector(`.kpi-folder-settings-panel[data-agent-id="${agentId}"]`);
  if (!panel) return;

  panel.querySelectorAll(".kpi-color-swatch").forEach((swatch) => {
    swatch.classList.toggle("is-selected", swatch.dataset.color?.toLowerCase() === color);
  });

  const input = panel.querySelector(".kpi-folder-color-input");
  if (input) input.value = color;
}

function closeFolderSettings(stackEl) {
  const popover = stackEl?.querySelector(".kpi-folder-settings-popover");
  const btn = stackEl?.querySelector(".kpi-folder-settings-btn");
  popover?.classList.add("hidden");
  btn?.setAttribute("aria-expanded", "false");
}

function updateFolderSettingsPanel(stackEl, card, folderColorValue) {
  const popover = stackEl.querySelector(".kpi-folder-settings-popover");
  if (!popover) return;
  popover.innerHTML = renderFolderSettingsContent(card, folderColorValue);
  closeFolderSettings(stackEl);
  bindFolderSettingsControls(stackEl);
}

function bindFolderSettingsControls(stackEl) {
  bindFolderColorPicker(stackEl);
  bindFolderNameEditor(stackEl);
}

function bindFolderSettings(stackEl) {
  if (!stackEl) return;

  const btn = stackEl.querySelector(".kpi-folder-settings-btn");
  const popover = stackEl.querySelector(".kpi-folder-settings-popover");

  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = "1";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      popover.classList.toggle("hidden");
      btn.setAttribute("aria-expanded", String(!popover.classList.contains("hidden")));
    });
  }

  if (popover && !popover.dataset.bound) {
    popover.dataset.bound = "1";
    popover.addEventListener("click", (e) => e.stopPropagation());
  }

  if (!document.body.dataset.kpiFolderSettingsBound) {
    document.body.dataset.kpiFolderSettingsBound = "1";
    document.addEventListener("click", () => {
      const currentStack = $("#kpi-folder-stack");
      if (currentStack) closeFolderSettings(currentStack);
    });
  }

  bindFolderSettingsControls(stackEl);
}

function setAgentFolderColor(agentId, color, stackEl = $("#kpi-folder-stack")) {
  const normalized = normalizeHexColor(color);
  if (!normalized || !agentId) return;

  state.kpiAgentColors[agentId] = normalized;
  saveKpiAgentColors(state.kpiAgentColors);
  applyFolderColorsToStack(stackEl);
  updateFolderColorPickerUi(stackEl, agentId, normalized);
}

function bindFolderColorPicker(stackEl) {
  if (!stackEl) return;

  stackEl.querySelectorAll(".kpi-color-swatch").forEach((swatch) => {
    swatch.addEventListener("click", (e) => {
      e.stopPropagation();
      setAgentFolderColor(swatch.dataset.agentId, swatch.dataset.color, stackEl);
    });
  });

  stackEl.querySelectorAll(".kpi-folder-color-input").forEach((input) => {
    input.addEventListener("input", () => {
      setAgentFolderColor(input.dataset.agentId, input.value, stackEl);
    });
  });
}

function bindFolderDragDrop(root) {
  root.querySelectorAll("[data-agent-id][draggable='true']").forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/agent-id", el.dataset.agentId);
      e.dataTransfer.effectAllowed = "move";
      el.classList.add("is-dragging");
    });
    el.addEventListener("dragend", () => el.classList.remove("is-dragging"));
    el.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      el.classList.add("is-drop-target");
    });
    el.addEventListener("dragleave", () => el.classList.remove("is-drop-target"));
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      el.classList.remove("is-drop-target");
      const draggedId = e.dataTransfer.getData("text/agent-id");
      const targetId = el.dataset.agentId;
      if (!draggedId || draggedId === targetId) return;
      reorderKpiAgents(draggedId, targetId);
    });
  });
}

function reorderKpiAgents(draggedId, targetId) {
  const next = [...state.kpiAgentOrder];
  const from = next.indexOf(draggedId);
  const to = next.indexOf(targetId);
  if (from < 0 || to < 0) return;
  next.splice(from, 1);
  next.splice(to, 0, draggedId);
  state.kpiAgentOrder = next;
  saveKpiAgentOrder(next);
  renderKpiFolderStack();
}

function setFolderTabPosition(stackEl, activeIndex, total) {
  if (total <= 1) {
    stackEl.dataset.tabPosition = "only";
  } else if (activeIndex === 0) {
    stackEl.dataset.tabPosition = "first";
  } else if (activeIndex === total - 1) {
    stackEl.dataset.tabPosition = "last";
  } else {
    stackEl.dataset.tabPosition = "middle";
  }
}

function applyFolderTabStacking(stackEl, activeIndex) {
  const tabs = stackEl.querySelectorAll(".kpi-folder-tab-slot");
  const total = tabs.length;
  tabs.forEach((tab, index) => {
    tab.style.zIndex = index === activeIndex ? String(total + 10) : String(total - index);
  });
}

function animateKpiFolderSwitch(stackEl, activeIndex, activeColor, active) {
  const prevIndex = Number(stackEl.dataset.activeIndex ?? activeIndex);
  const direction = activeIndex === prevIndex ? 1 : activeIndex > prevIndex ? 1 : -1;
  const bodyEl = stackEl.querySelector(".kpi-folder-body");

  stackEl.dataset.activeIndex = String(activeIndex);
  setFolderTabPosition(stackEl, activeIndex, stackEl.querySelectorAll(".kpi-folder-tab-slot").length);
  stackEl.style.setProperty("--folder-color", activeColor);
  stackEl.style.setProperty("--slide-dir", String(direction));

  stackEl.querySelectorAll(".kpi-folder-tab-slot").forEach((tab, index) => {
    const isActive = index === activeIndex;
    tab.classList.toggle("is-active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
    tab.title = isActive ? "Перетащите для смены порядка" : "Открыть · перетащите для смены порядка";
  });

  applyFolderTabStacking(stackEl, activeIndex);
  applyFolderColorsToStack(stackEl);

  if (!bodyEl || !active) return;

  bodyEl.classList.remove("is-entering");
  bodyEl.classList.add("is-leaving");

  window.setTimeout(() => {
    bodyEl.classList.remove("is-leaving");
    bodyEl.innerHTML = renderAgentPanelContent(active.card, active.agentSummary, active.historyItems);
    bodyEl.classList.add("is-entering");
    updateFolderSettingsPanel(stackEl, active.card, folderColorForAgent(active.card.agent_id, activeIndex));
    window.setTimeout(() => bodyEl.classList.remove("is-entering"), 320);
  }, 220);
}

function renderKpiFolderStack({ animate = false } = {}) {
  const stackEl = $("#kpi-folder-stack");
  if (!stackEl) return;

  const byId = new Map(state.kpiAgentData.map((item) => [item.card.agent_id, item]));
  const order = state.kpiAgentOrder.filter((id) => byId.has(id));
  if (!order.length) return;

  if (!order.includes(state.kpiActiveAgentId)) {
    state.kpiActiveAgentId = order[0];
  }

  const activeIndex = order.indexOf(state.kpiActiveAgentId);
  const activeColor = folderColorForAgent(state.kpiActiveAgentId, activeIndex);
  const active = byId.get(state.kpiActiveAgentId);

  if (animate && stackEl.querySelector(".kpi-folder-tabs")) {
    stackEl.style.setProperty("--tab-count", String(order.length));
    animateKpiFolderSwitch(stackEl, activeIndex, activeColor, active);
    return;
  }

  stackEl.style.setProperty("--tab-count", String(order.length));
  stackEl.style.setProperty("--folder-color", activeColor);
  stackEl.dataset.activeIndex = String(activeIndex);
  setFolderTabPosition(stackEl, activeIndex, order.length);
  applyFolderTheme(stackEl, activeColor);

  const tabsHtml = order
    .map((agentId, index) => {
      const item = byId.get(agentId);
      const isActive = index === activeIndex;
      const color = folderColorForAgent(agentId, index);
      const tabFg = folderTabTextColor(color, isActive);
      const tabTitle = agentDisplayTitle(item.card);
      return `<button
        type="button"
        class="kpi-folder-tab-slot${isActive ? " is-active" : ""}"
        role="tab"
        aria-selected="${isActive}"
        draggable="true"
        data-agent-id="${escapeHtml(agentId)}"
        data-tab-index="${index}"
        style="--folder-color:${color};--folder-tab-fg:${tabFg};"
        title="${escapeHtml(tabTitle)}"
      ><span class="kpi-folder-tab-label">${renderFolderTabLabelHtml(item.card)}</span></button>`;
    })
    .join("");

  stackEl.innerHTML = `
    <div class="kpi-folder-tabs" role="tablist">${tabsHtml}</div>
    <div class="kpi-folder-panel" role="tabpanel">
      ${renderFolderSettingsToolbar(active.card, activeColor)}
      <div class="kpi-folder-body">
        ${renderAgentPanelContent(active.card, active.agentSummary, active.historyItems)}
      </div>
    </div>
  `;

  stackEl.querySelectorAll(".kpi-folder-tab-slot").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.classList.contains("is-active") || stackEl.classList.contains("is-switching")) return;
      stackEl.classList.add("is-switching");
      state.kpiActiveAgentId = tab.dataset.agentId;
      renderKpiFolderStack({ animate: true });
      window.setTimeout(() => stackEl.classList.remove("is-switching"), 540);
    });
  });

  bindFolderDragDrop(stackEl);
  bindFolderSettings(stackEl);
  applyFolderTabStacking(stackEl, activeIndex);
}

function loadKpiAgentOrder(agentIds) {
  try {
    const raw = localStorage.getItem(KPI_TAB_ORDER_KEY);
    if (!raw) return [...agentIds];
    const saved = JSON.parse(raw);
    if (!Array.isArray(saved)) return [...agentIds];
    const known = new Set(agentIds);
    const order = saved.filter((id) => known.has(id));
    for (const id of agentIds) {
      if (!order.includes(id)) order.push(id);
    }
    return order;
  } catch {
    return [...agentIds];
  }
}

function saveKpiAgentOrder(order) {
  localStorage.setItem(KPI_TAB_ORDER_KEY, JSON.stringify(order));
}

function renderKpiAgentsSection(agentData) {
  const wrap = $("#kpi-agents-wrap");
  const empty = $("#kpi-agents-empty");
  if (!agentData.length) {
    wrap.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  wrap.classList.remove("hidden");
  state.kpiAgentData = agentData;
  state.kpiAgentColors = loadKpiAgentColors();
  state.kpiAgentOrder = loadKpiAgentOrder(agentData.map((item) => item.card.agent_id));
  ensureAgentFolderColors(state.kpiAgentOrder);
  if (!state.kpiActiveAgentId || !state.kpiAgentOrder.includes(state.kpiActiveAgentId)) {
    state.kpiActiveAgentId = state.kpiAgentOrder[0];
  }
  renderKpiFolderStack();
}

function showLogin() {
  $("#screen-login").classList.remove("hidden");
  $("#screen-app").classList.add("hidden");
}

function showApp() {
  $("#screen-login").classList.add("hidden");
  $("#screen-app").classList.remove("hidden");
}

function setUserChip(user) {
  $("#user-chip").textContent = `${user.fio}${user.department ? " · " + user.department : ""}`;
}

function gotoPage(name) {
  $$(".page").forEach((p) => p.classList.add("hidden"));
  $$(".nav-item[data-page]").forEach((b) => b.classList.remove("active"));
  const page = $(`#page-${name}`);
  if (page) page.classList.remove("hidden");
  const nav = $(`.nav-item[data-page="${name}"]`);
  if (nav) nav.classList.add("active");
  const titles = {
    create: ["Создать агента", "Загрузите регламент для анализа"],
    review: ["Обзор регламента", ""],
    "role-match": ["Функции роли", "Подтвердите или отклоните совпадения"],
    agents: ["Мои агенты", "Черновики и опубликованные workflow"],
    kpi: ["KPI", "Метрики эффективности агентов"],
    settings: ["Настройки", "Профиль и отдел"],
  };
  const [t, s] = titles[name] || ["", ""];
  $("#page-title").textContent = t;
  $("#page-subtitle").textContent = s;
  if (name === "agents") loadAgents();
  if (name === "kpi") loadKpi();
  if (name === "settings") loadSettings();
}

async function tryRestoreSession() {
  if (!Api.token) return false;
  try {
    state.user = await Api.me();
    setUserChip(state.user);
    showApp();
    gotoPage("create");
    return true;
  } catch {
    Api.setToken("");
    return false;
  }
}

async function testServer() {
  $("#server-status").textContent = "Проверка…";
  try {
    const h = await Api.health();
    const body = h.body || h;
    $("#server-status").textContent = `Сервер ${body.status || "ok"}. ERP: ${
      body.erp_reachable ? "да" : "нет"
    }. Регистрация: ${body.registration_enabled ? "открыта" : "закрыта"}.`;
  } catch (e) {
    $("#server-status").textContent = `Нет связи: ${e.message}`;
  }
}

async function submitLogin() {
  $("#login-error").textContent = "";
  const fio = $("#login-fio").value.trim();
  const password = $("#login-password").value;
  if (!fio || !password) {
    $("#login-error").textContent = "Введите ФИО и пароль";
    return;
  }
  try {
    const data = state.registerMode
      ? await Api.register(fio, password, $("#login-department").value.trim())
      : await Api.login(fio, password);
    Api.setToken(data.access_token);
    state.user = data.user;
    setUserChip(state.user);
    showApp();
    gotoPage("create");
    toast(state.registerMode ? "Регистрация успешна" : "Вход выполнен");
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
}

function toggleRegister() {
  state.registerMode = !state.registerMode;
  $("#register-fields").classList.toggle("hidden", !state.registerMode);
  $("#login-subtitle").textContent = state.registerMode
    ? "Регистрация локального аккаунта"
    : "Вход через учётную запись 1С";
  $("#btn-login").textContent = state.registerMode ? "Зарегистрироваться" : "Войти";
  $("#btn-toggle-register").textContent = state.registerMode
    ? "Уже есть аккаунт? Войти"
    : "Нет аккаунта? Зарегистрироваться";
}

async function handleUpload(file) {
  if (!file) return;
  $("#upload-status").textContent = "Загрузка и разбор…";
  try {
    state.regulation = await Api.uploadRegulation(file);
    renderReview();
    gotoPage("review");
    $("#upload-status").textContent = "";
  } catch (e) {
    $("#upload-status").textContent = e.message;
  }
}

function renderReview() {
  const r = state.regulation;
  if (!r) return;
  $("#review-filename").textContent = r.fileName || r.file_name || "Регламент";
  $("#review-meta").textContent = `Страниц: ${r.pageCount || r.page_count || "?"}, секций: ${
    r.sectionCount || r.section_count || "?"
  }, таблиц: ${r.tableCount || r.table_count || "?"}`;
  const sections = r.sections || [];
  $("#review-sections").innerHTML = sections
    .slice(0, 20)
    .map((s) => `<span class="tag">${escapeHtml(s)}</span>`)
    .join("");
  const frags = r.fragments || [];
  $("#review-fragments").innerHTML = frags
    .slice(0, 30)
    .map(
      (f) =>
        `<div class="fragment"><div class="kind">${escapeHtml(
          f.section || f.kind || ""
        )}</div>${escapeHtml((f.text || "").slice(0, 400))}</div>`
    )
    .join("");
}

async function startRoleMatch() {
  const r = state.regulation;
  if (!r) return;
  const regId = r.regulationId || r.regulation_id;
  $("#role-match-card").innerHTML = "<p class='muted'>Поиск функций…</p>";
  gotoPage("role-match");
  try {
    state.roleMatch = await Api.createRoleMatches(regId, {
      position: state.user?.position || "Специалист",
      department: state.user?.department || "",
    });
    state.matchIndex = 0;
    renderRoleMatch();
  } catch (e) {
    $("#role-match-card").innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

function renderRoleMatch() {
  const rm = state.roleMatch;
  if (!rm) return;
  const matches = rm.matches || [];
  const pending = matches.filter((m) => m.status === "pending");
  if (!pending.length) {
    $("#role-match-card").innerHTML =
      "<h3>Все функции обработаны</h3><p class='muted'>Можно создать черновик агента.</p>";
    $("#btn-finish-role-match").classList.remove("hidden");
    return;
  }
  $("#btn-finish-role-match").classList.add("hidden");
  const m = pending[0];
  const fn = m.function || {};
  $("#role-match-card").innerHTML = `
    <p class="muted">Осталось: ${pending.length} из ${matches.length}</p>
    <h3>${escapeHtml(fn.action || "Функция")} ${escapeHtml(fn.object || "")}</h3>
    <p>${escapeHtml(fn.explanation || m.explanation || "")}</p>
    <p class="muted">Цитата: ${escapeHtml((m.evidence && m.evidence.quote) || "")}</p>
    <div class="match-actions">
      <button class="btn primary" id="btn-approve-match">Подтвердить</button>
      <button class="btn ghost" id="btn-reject-match">Отклонить</button>
    </div>`;
  $("#btn-approve-match").onclick = () => decideMatch(m.matchId || m.match_id, "accepted");
  $("#btn-reject-match").onclick = () => decideMatch(m.matchId || m.match_id, "rejected");
}

async function decideMatch(matchId, status) {
  const regId = state.regulation.regulationId || state.regulation.regulation_id;
  const runId = state.roleMatch.runId || state.roleMatch.run_id;
  try {
    state.roleMatch = await Api.decideRoleMatch(regId, runId, matchId, status);
    renderRoleMatch();
  } catch (e) {
    toast(e.message);
  }
}

async function finishRoleMatch() {
  const regId = state.regulation.regulationId || state.regulation.regulation_id;
  const runId = state.roleMatch.runId || state.roleMatch.run_id;
  try {
    await Api.createDraft(regId, runId);
    toast("Черновик агента создан");
    gotoPage("agents");
  } catch (e) {
    toast(e.message);
  }
}

async function loadAgents() {
  $("#agents-published").innerHTML = "<p class='muted'>Загрузка…</p>";
  $("#agents-drafts").innerHTML = "";
  try {
    const [drafts, workflows] = await Promise.all([Api.listDrafts(), Api.listWorkflows()]);
    const published = (workflows || []).filter((w) => w.phase === "done");
    $("#agents-published").innerHTML = published.length
      ? published.map(renderWorkflowCard).join("")
      : "<p class='muted'>Нет опубликованных агентов</p>";
    const items = (drafts.items || drafts) || [];
    $("#agents-drafts").innerHTML = items.length
      ? items.map(renderDraftCard).join("")
      : "<p class='muted'>Нет черновиков</p>";
  } catch (e) {
    $("#agents-published").innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

function renderWorkflowCard(w) {
  return `<div class="card agent-card">
    <h3>${escapeHtml(w.title || w.workflowId || w.workflow_id)}</h3>
    <div class="meta">${escapeHtml(w.phase || "")} · ${escapeHtml(w.updatedAt || w.updated_at || "")}</div>
  </div>`;
}

function renderDraftCard(d) {
  const id = d.draftId || d.draft_id;
  return `<div class="card agent-card">
    <h3>${escapeHtml(d.title || id)}</h3>
    <div class="meta">${escapeHtml(d.status || "")} · ${d.progress || 0}%</div>
    <button class="btn ghost" data-delete-draft="${escapeHtml(id)}">Удалить</button>
  </div>`;
}

async function loadKpi() {
  $("#kpi-summary").innerHTML = "<p class='muted'>Загрузка…</p>";
  $("#kpi-agents-wrap").classList.add("hidden");
  $("#kpi-agents-empty").classList.add("hidden");
  try {
    const [summary, cardsResp] = await Promise.all([
      Api.kpiSummary(),
      Api.kpiAgentCards(),
    ]);
    $("#kpi-summary").innerHTML = buildSummaryTiles(summary);
    const cards = cardsResp.items || [];
    if (!cards.length) {
      $("#kpi-agents-empty").classList.remove("hidden");
      state.kpiAgentData = [];
      return;
    }
    const agentData = await Promise.all(
      cards.map(async (card) => {
        const [agentSummary, history] = await Promise.all([
          Api.kpiSummary(card.agent_id),
          Api.kpiExecutionHistory(card.agent_id, 50),
        ]);
        return { card, agentSummary, historyItems: history.items || [] };
      })
    );
    renderKpiAgentsSection(agentData);
  } catch (e) {
    $("#kpi-summary").innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

async function loadSettings() {
  try {
    state.user = await Api.me();
    $("#settings-fio").textContent = state.user.fio || "";
    $("#settings-position").textContent = state.user.position || "—";
    $("#settings-department").textContent = state.user.department || "—";
    const deps = await Api.listDepartments();
    const sel = $("#settings-dept-select");
    sel.innerHTML = (deps.items || [])
      .map((d) => `<option value="${escapeHtml(d)}" ${d === state.user.department ? "selected" : ""}>${escapeHtml(d)}</option>`)
      .join("");
  } catch (e) {
    $("#settings-status").textContent = e.message;
  }
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setupDropzone() {
  const dz = $("#dropzone");
  const input = $("#file-input");
  dz.addEventListener("dragover", (e) => {
    e.preventDefault();
    dz.classList.add("dragover");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    handleUpload(file);
  });
  $("#btn-pick-file").onclick = () => input.click();
  input.onchange = () => handleUpload(input.files[0]);
}

function bindEvents() {
  $("#btn-login").onclick = submitLogin;
  $("#btn-test-server").onclick = testServer;
  $("#btn-toggle-register").onclick = toggleRegister;
  $("#btn-logout").onclick = () => {
    Api.setToken("");
    state.user = null;
    showLogin();
  };
  $$(".nav-item[data-page]").forEach((btn) => {
    btn.onclick = () => gotoPage(btn.dataset.page);
  });
  $$("[data-goto]").forEach((btn) => {
    btn.onclick = () => gotoPage(btn.dataset.goto);
  });
  $("#btn-start-role-match").onclick = startRoleMatch;
  $("#btn-finish-role-match").onclick = finishRoleMatch;
  $$(".tab").forEach((tab) => {
    tab.onclick = () => {
      $$(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.agentsTab = tab.dataset.tab;
      $("#agents-published").classList.toggle("hidden", state.agentsTab !== "published");
      $("#agents-drafts").classList.toggle("hidden", state.agentsTab !== "drafts");
    };
  });
  document.body.addEventListener("click", async (e) => {
    const id = e.target.dataset?.deleteDraft;
    if (id && confirm("Удалить черновик?")) {
      try {
        await Api.deleteDraft(id);
        loadAgents();
      } catch (err) {
        toast(err.message);
      }
    }
  });
  $("#btn-save-dept").onclick = async () => {
    try {
      state.user = await Api.updateDepartment($("#settings-dept-select").value);
      setUserChip(state.user);
      $("#settings-department").textContent = state.user.department;
      $("#settings-status").textContent = "Отдел сохранён";
    } catch (e) {
      $("#settings-status").textContent = e.message;
    }
  };
  setupDropzone();
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  if (!(await tryRestoreSession())) showLogin();
});
