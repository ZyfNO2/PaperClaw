(() => {
  "use strict";

  const ACTIVE_STATUSES = new Set(["starting", "running", "stopping"]);
  const MAX_TIMELINE_ROWS = 300;
  const POLL_INTERVAL_MS = 250;
  const THEME_STORAGE_KEY = "paperclaw.theme.v1";
  const THEMES = new Map([
    ["dark", "Dark"],
    ["light", "Light"]
  ]);
  const bootstrap = readBrowserBootstrap();
  const bridgeClientId = createClientId();
  const httpApi = bootstrap.token ? createHttpApi(bootstrap.token) : null;
  const ui = {};
  const trace = [];
  let domReady = false;
  let bridgeReady = false;
  let pollTimer = null;
  let pollInFlight = false;
  let frontendSubmitting = false;
  let workspace = "";
  let currentStatus = "idle";
  let currentRunId = null;
  let lastFinalResult = "";
  let toastTimer = null;
  let currentTheme = resolveInitialTheme(bootstrap.theme);
  document.documentElement.dataset.theme = currentTheme;

  function byId(id) {
    return document.getElementById(id);
  }

  function bindDom() {
    if (domReady) return;
    domReady = true;
    for (const id of [
      "app", "sidebar-toggle", "workspace-card", "workspace-name", "workspace-path",
      "sidebar-nav", "trace-count", "env-badge", "new-run-button", "run-subtitle",
      "global-search", "run-status", "run-button", "cancel-button", "export-button",
      "select-workspace", "provider-summary", "mission-filters", "mission-log", "public-error",
      "task", "send-button", "clear-task", "task-count", "summary-status", "model-calls",
      "tool-calls", "last-sequence", "event-meta", "model-label", "verification-status",
      "verification-summary", "progress-label", "progress-bar", "timeline-filters", "timeline",
      "settings-panel", "close-settings", "config-provider", "config-base-url", "config-model",
      "config-credential", "max-steps", "max-model-calls", "max-tool-calls",
      "verification-enabled", "theme-select", "open-browser", "toast", "toast-message",
      "close-toast"
    ]) ui[toCamel(id)] = byId(id);

    ui.sidebarToggle.addEventListener("click", toggleSidebar);
    ui.workspaceCard.addEventListener("click", selectWorkspace);
    ui.selectWorkspace.addEventListener("click", selectWorkspace);
    ui.runButton.addEventListener("click", startRun);
    ui.sendButton.addEventListener("click", startRun);
    ui.cancelButton.addEventListener("click", cancelRun);
    ui.exportButton.addEventListener("click", exportTrace);
    ui.newRunButton.addEventListener("click", resetForNewRun);
    ui.themeSelect.addEventListener("change", () => applyTheme(ui.themeSelect.value, true));
    ui.openBrowser.addEventListener("click", openInBrowser);
    ui.clearTask.addEventListener("click", clearTask);
    ui.task.addEventListener("input", updateTaskInput);
    ui.task.addEventListener("keydown", onTaskKeydown);
    ui.globalSearch.addEventListener("input", applyMissionSearch);
    ui.globalSearch.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        ui.globalSearch.value = "";
        applyMissionSearch();
        ui.globalSearch.blur();
      }
    });
    document.addEventListener("keydown", onGlobalKeydown);
    ui.closeSettings.addEventListener("click", closeSettings);
    ui.closeToast.addEventListener("click", hideToast);
    bindFilterGroup(ui.missionFilters, "data-log-filter", applyMissionFilter);
    bindFilterGroup(ui.timelineFilters, "data-tl-filter", applyTimelineFilter);
    bindNavigation();
    bindToolChips();
    ui.themeSelect.value = currentTheme;
    if (httpApi) {
      bridgeReady = true;
      ui.openBrowser.disabled = true;
      ui.openBrowser.textContent = "◎ BROWSER MODE";
      ui.openBrowser.title = "当前已在系统浏览器中运行";
    }
    updateTaskInput();
    maybeInitialize();
  }

  function toCamel(value) {
    return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  }

  function backendApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return httpApi;
  }

  function backendMode() {
    return httpApi && !(window.pywebview && window.pywebview.api) ? "browser" : "desktop";
  }

  function markBridgeReady() {
    bridgeReady = true;
    maybeInitialize();
  }

  async function maybeInitialize() {
    if (!domReady) return;
    if (!bridgeReady && backendApi()) bridgeReady = true;
    if (!bridgeReady) return;
    await loadDefaults();
    await refreshState();
    if (pollTimer === null) pollTimer = window.setInterval(pollBackend, POLL_INTERVAL_MS);
  }

  async function loadDefaults() {
    const api = backendApi();
    if (!api || typeof api.get_defaults !== "function") {
      showError("gui_dependency_missing", "PaperClaw bridge does not expose environment defaults.");
      return;
    }
    try {
      const response = await api.get_defaults();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      workspace = stringValue(response.workspace, "");
      renderWorkspace(workspace);
      setText(ui.configProvider, stringValue(response.provider, "openai-compatible"));
      setText(ui.configBaseUrl, stringValue(response.base_url, "not configured"));
      setText(ui.configModel, stringValue(response.model, "not configured"));
      setText(ui.configCredential, response.configured ? "Configured (hidden)" : `Missing: ${(response.missing || []).join(", ")}`);
      setText(ui.modelLabel, stringValue(response.model, "ENV"));
      setText(ui.providerSummary, response.configured
        ? `LLM · ENV · ${stringValue(response.provider, "openai-compatible")} / ${stringValue(response.model, "model")}`
        : `LLM · ENV INCOMPLETE · ${(response.missing || []).join(", ")}`);
      ui.envBadge.textContent = response.configured ? "ENV✓" : "ENV!";
      ui.envBadge.dataset.configured = response.configured ? "true" : "false";
      if (!THEMES.has(bootstrap.theme) && response.theme && THEMES.has(response.theme)) {
        applyTheme(response.theme, false);
      }
    } catch (_error) {
      showError("runtime_error", "Environment defaults could not be loaded.");
    }
  }

  async function refreshState() {
    const api = backendApi();
    if (!api) return;
    try {
      const response = await api.get_state();
      if (response && response.ok && response.state) renderSnapshot(response.state);
      else renderBackendError(response);
    } catch (_error) {
      showError("runtime_error", "Desktop state could not be loaded.");
    }
  }

  async function pollBackend() {
    if (pollInFlight) return;
    const api = backendApi();
    if (!api) return;
    pollInFlight = true;
    try {
      const response = await api.poll_events(200, bridgeClientId);
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      for (const item of response.items || []) {
        if (item.kind === "event" && item.event) appendTimelineRow(item.event);
        else if (item.kind === "snapshot" && item.snapshot) renderSnapshot(item.snapshot);
      }
      setText(ui.eventMeta, `${numberValue(response.dropped_count)} dropped`);
    } catch (_error) {
      showError("runtime_error", "Desktop event polling failed.");
    } finally {
      pollInFlight = false;
    }
  }

  async function startRun() {
    if (frontendSubmitting || ACTIVE_STATUSES.has(currentStatus)) {
      showError("run_already_active", "A run is already active in this window.");
      return;
    }
    const task = ui.task.value.trim();
    if (!task) {
      showError("validation_error", "请输入任务后再执行。");
      ui.task.focus();
      return;
    }
    if (!workspace) {
      showError("workspace_not_found", "请先选择工作区。");
      return;
    }
    clearError();
    frontendSubmitting = true;
    updateControls("starting");
    appendMissionMessage("user", "YOU", task);
    const payload = {
      task,
      workspace,
      enable_verification_gate: ui.verificationEnabled.checked,
      max_steps: boundedInteger(ui.maxSteps.value, 12, 200),
      max_model_calls: boundedInteger(ui.maxModelCalls.value, 10, 100),
      max_tool_calls: boundedInteger(ui.maxToolCalls.value, 20, 1000)
    };
    try {
      const api = backendApi();
      if (!api) {
        showError("gui_dependency_missing", "PaperClaw bridge is not available.");
        updateControls("idle");
        return;
      }
      const response = await api.start_run(payload);
      if (!response || !response.ok) {
        renderBackendError(response);
        updateControls("idle");
        return;
      }
      ui.task.value = "";
      updateTaskInput();
      appendMissionMessage("system", "SYSTEM", "Run accepted. Model configuration will be resolved from environment variables in Python.");
      updateControls(response.status || "starting");
    } catch (_error) {
      showError("runtime_error", "Run could not be started.");
      updateControls("idle");
    } finally {
      frontendSubmitting = false;
      updateControls(currentStatus);
    }
  }

  async function cancelRun() {
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "PaperClaw bridge is not available.");
      return;
    }
    ui.cancelButton.disabled = true;
    try {
      const response = await api.cancel_run();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      appendMissionMessage("system", "SYSTEM", "Cancellation requested.");
      updateControls(response.status || "stopping");
    } catch (_error) {
      showError("runtime_error", "Cancel request could not be sent.");
    }
  }

  async function selectWorkspace() {
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "PaperClaw bridge is not available.");
      return;
    }
    try {
      const response = await api.select_workspace();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      if (response.workspace) {
        workspace = response.workspace;
        renderWorkspace(workspace);
        showToast("Workspace updated.");
      }
    } catch (_error) {
      showError("runtime_error", "Workspace picker could not be opened.");
    }
  }

  async function openInBrowser() {
    if (backendMode() === "browser") {
      showToast("当前已在系统浏览器中运行。");
      return;
    }
    const api = backendApi();
    if (!api || typeof api.open_in_browser !== "function") {
      showError("gui_dependency_missing", "Desktop bridge does not expose browser mode.");
      return;
    }
    ui.openBrowser.disabled = true;
    try {
      const response = await api.open_in_browser(currentTheme);
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      showToast("Browser mode opened on a protected localhost URL.");
    } catch (_error) {
      showError("runtime_error", "Browser mode could not be opened.");
    } finally {
      ui.openBrowser.disabled = false;
    }
  }

  function applyTheme(theme, persist) {
    const normalized = THEMES.has(theme) ? theme : "dark";
    currentTheme = normalized;
    document.documentElement.dataset.theme = normalized;
    if (ui.themeSelect) ui.themeSelect.value = normalized;
    if (persist) {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, normalized);
      } catch (_error) {
        // The Python preference store remains authoritative when storage is restricted.
      }
      const api = backendApi();
      if (api && typeof api.set_theme === "function") {
        Promise.resolve(api.set_theme(normalized)).catch(() => undefined);
      }
      showToast(`Theme: ${THEMES.get(normalized)}`);
    }
  }

  function resolveInitialTheme(fragmentTheme) {
    if (THEMES.has(fragmentTheme)) return fragmentTheme;
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (THEMES.has(stored)) return stored;
    } catch (_error) {
      // Continue with the built-in default when storage is unavailable.
    }
    return "dark";
  }

  function readBrowserBootstrap() {
    const result = {token: "", theme: ""};
    if (!window.location.hash) return result;
    try {
      const values = new URLSearchParams(window.location.hash.slice(1));
      result.token = values.get("token") || "";
      result.theme = values.get("theme") || "";
      if (result.token || result.theme) {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      }
    } catch (_error) {
      return {token: "", theme: ""};
    }
    return result;
  }

  function createClientId() {
    try {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return `ui-${window.crypto.randomUUID()}`;
      }
    } catch (_error) {
      // Fall back to a per-document identifier below.
    }
    return `ui-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function createHttpApi(token) {
    async function invoke(method, args) {
      const response = await window.fetch(`/api/${method}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-PaperClaw-Token": token
        },
        body: JSON.stringify({args})
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
      if (!payload) throw new Error("PaperClaw browser bridge returned invalid JSON.");
      return payload;
    }
    return {
      get_defaults: () => invoke("get_defaults", []),
      get_state: () => invoke("get_state", []),
      start_run: (request) => invoke("start_run", [request]),
      cancel_run: () => invoke("cancel_run", []),
      poll_events: (limit, clientId) => invoke("poll_events", [limit, clientId]),
      select_workspace: () => invoke("select_workspace", []),
      set_theme: (theme) => invoke("set_theme", [theme])
    };
  }

  function renderWorkspace(value) {
    const normalized = stringValue(value, "not selected");
    const segments = normalized.split(/[\\/]/).filter(Boolean);
    setText(ui.workspaceName, segments.length ? segments[segments.length - 1] : normalized);
    setText(ui.workspacePath, normalized);
  }

  function renderSnapshot(snapshot) {
    const previousStatus = currentStatus;
    currentStatus = stringValue(snapshot.status, "idle").toLowerCase();
    currentRunId = snapshot.run_id || currentRunId;
    setStatus(ui.runStatus, currentStatus);
    setStatus(ui.summaryStatus, currentStatus);
    setText(ui.runSubtitle, `Agent runtime monitor · run=${stringValue(currentRunId, "not-started")}`);
    setText(ui.modelCalls, numberValue(snapshot.model_calls));
    setText(ui.toolCalls, numberValue(snapshot.tool_calls));
    setText(ui.lastSequence, numberValue(snapshot.last_sequence));
    setText(ui.traceCount, numberValue(snapshot.last_sequence));
    setText(ui.verificationStatus, stringValue(snapshot.verification_status, "—").toUpperCase());
    setText(ui.verificationSummary, stringValue(snapshot.verification_summary, "not run"));
    updateProgress(currentStatus, snapshot.terminal);
    if (snapshot.final_result && snapshot.final_result !== lastFinalResult) {
      lastFinalResult = snapshot.final_result;
      appendMissionMessage("agent", "PAPERCLAW", snapshot.final_result);
    }
    if (snapshot.error_code || snapshot.error_message) {
      const code = stringValue(snapshot.error_code, "runtime_error");
      const message = stringValue(snapshot.error_message, "PaperClaw runtime failed.");
      showError(code, message);
      if (previousStatus !== "failed" || currentStatus === "failed") appendMissionMessage("error", "ERROR", `${code}: ${message}`);
    } else if (!ACTIVE_STATUSES.has(currentStatus)) {
      clearError();
    }
    updateControls(currentStatus);
  }

  function appendTimelineRow(row) {
    const eventType = stringValue(row.event_type, "unknown.event");
    const category = eventCategory(eventType);
    const item = document.createElement("div");
    item.className = "event-row";
    item.dataset.type = category;
    item.dataset.eventType = eventType;

    const sequence = document.createElement("span");
    sequence.className = "event-num";
    sequence.textContent = String(numberValue(row.sequence)).padStart(2, "0");

    const main = document.createElement("div");
    main.className = "event-main";
    const title = document.createElement("div");
    title.className = "event-title";
    title.textContent = eventType;
    const meta = document.createElement("div");
    meta.className = "event-meta";
    meta.textContent = stringValue(row.label, eventType);
    main.append(title, meta);

    const right = document.createElement("div");
    right.className = "event-right";
    const time = document.createElement("span");
    time.className = "event-time";
    time.textContent = new Date().toLocaleTimeString([], {hour12:false});
    const dot = document.createElement("span");
    dot.className = `event-dot${eventType.endsWith("failed") ? " failed" : eventType.endsWith("started") ? " running" : ""}`;
    right.append(time, dot);

    item.append(sequence, main, right);
    ui.timeline.append(item);
    while (ui.timeline.children.length > MAX_TIMELINE_ROWS) ui.timeline.firstElementChild.remove();
    ui.timeline.scrollTop = ui.timeline.scrollHeight;
    trace.push({sequence:numberValue(row.sequence), event_type:eventType, label:stringValue(row.label, eventType), category, at:new Date().toISOString()});
    if (trace.length > MAX_TIMELINE_ROWS) trace.shift();
    applyTimelineFilter();
  }

  function appendMissionMessage(type, heading, body) {
    const article = document.createElement("article");
    article.className = `msg msg-${type}`;
    article.dataset.logType = type;
    const head = document.createElement("div");
    head.className = "msg-head";
    const marker = document.createElement("span");
    marker.className = `msg-marker${type === "user" ? " user" : type === "system" ? " sys" : type === "error" ? " error" : ""}`;
    const label = document.createElement("span");
    label.textContent = heading;
    const meta = document.createElement("span");
    meta.className = "msg-meta push-right";
    meta.textContent = new Date().toLocaleTimeString([], {hour12:false});
    head.append(marker, label, meta);
    const messageBody = document.createElement("div");
    messageBody.className = "msg-body";
    messageBody.textContent = stringValue(body, "");
    article.append(head, messageBody);
    ui.missionLog.append(article);
    ui.missionLog.scrollTop = ui.missionLog.scrollHeight;
    applyMissionFilter();
    applyMissionSearch();
  }

  function updateControls(status) {
    currentStatus = stringValue(status, currentStatus).toLowerCase();
    const active = ACTIVE_STATUSES.has(currentStatus) || frontendSubmitting;
    ui.runButton.disabled = active;
    ui.sendButton.disabled = active;
    ui.cancelButton.disabled = !active || currentStatus === "stopping";
    ui.selectWorkspace.disabled = active;
    ui.workspaceCard.disabled = active;
  }

  function updateProgress(status, terminal) {
    const map = {idle:0, starting:12, running:56, stopping:80, completed:100, failed:100, cancelled:100};
    const progress = terminal ? 100 : (map[status] || 0);
    ui.progressBar.style.width = `${progress}%`;
    setText(ui.progressLabel, `${progress}%`);
  }

  function setStatus(element, status) {
    const normalized = stringValue(status, "idle").toLowerCase();
    element.dataset.status = normalized;
    element.textContent = normalized.toUpperCase();
  }

  function bindNavigation() {
    for (const button of ui.sidebarNav.querySelectorAll("[data-nav]")) {
      button.addEventListener("click", () => {
        const target = button.dataset.nav;
        if (window.PaperClawShell && typeof window.PaperClawShell.showPage === "function") {
          window.PaperClawShell.showPage(target);
          return;
        }
        for (const candidate of ui.sidebarNav.querySelectorAll("[data-nav]")) candidate.classList.remove("active");
        button.classList.add("active");
      });
    }
  }

  function bindToolChips() {
    for (const button of document.querySelectorAll("[data-insert]")) {
      button.addEventListener("click", () => {
        const insert = button.dataset.insert || "";
        const start = ui.task.selectionStart;
        const end = ui.task.selectionEnd;
        ui.task.setRangeText(insert, start, end, "end");
        updateTaskInput();
        ui.task.focus();
      });
    }
  }

  function bindFilterGroup(container, attribute, callback) {
    for (const chip of container.querySelectorAll(`[${attribute}]`)) {
      chip.addEventListener("click", () => {
        for (const candidate of container.querySelectorAll(`[${attribute}]`)) candidate.classList.remove("active");
        chip.classList.add("active");
        callback();
      });
    }
  }

  function applyMissionFilter() {
    const active = ui.missionFilters.querySelector(".chip.active");
    const filter = active ? active.dataset.logFilter : "all";
    for (const row of ui.missionLog.querySelectorAll("[data-log-type]")) {
      row.hidden = filter !== "all" && row.dataset.logType !== filter;
    }
  }

  function applyTimelineFilter() {
    const active = ui.timelineFilters.querySelector(".chip.active");
    const filter = active ? active.dataset.tlFilter : "all";
    for (const row of ui.timeline.querySelectorAll(".event-row")) row.hidden = filter !== "all" && row.dataset.type !== filter;
  }

  function applyMissionSearch() {
    const query = ui.globalSearch.value.trim().toLowerCase();
    for (const row of ui.missionLog.querySelectorAll("[data-log-type]")) {
      row.style.display = !query || row.textContent.toLowerCase().includes(query) ? "" : "none";
    }
  }

  function eventCategory(eventType) {
    if (eventType.startsWith("model.")) return "model";
    if (eventType.startsWith("tool.") || eventType === "permission.denied") return "tool";
    if (eventType.startsWith("verification.")) return "verify";
    return "system";
  }

  function toggleSidebar() {
    const collapsed = ui.app.classList.toggle("sidebar-collapsed");
    ui.sidebarToggle.textContent = collapsed ? "→" : "←";
    ui.sidebarToggle.setAttribute("aria-label", collapsed ? "展开侧边栏" : "折叠侧边栏");
  }

  function openSettings() {
    if (window.PaperClawShell && typeof window.PaperClawShell.showPage === "function") {
      window.PaperClawShell.showPage("settings");
      return;
    }
    ui.settingsPanel.hidden = false;
    ui.closeSettings.focus();
  }

  function closeSettings() {
    if (window.PaperClawShell && typeof window.PaperClawShell.backFromSettings === "function") {
      window.PaperClawShell.backFromSettings();
      return;
    }
    ui.settingsPanel.hidden = true;
  }

  function resetForNewRun() {
    if (ACTIVE_STATUSES.has(currentStatus)) {
      showToast("Stop the active run before starting a new one.");
      return;
    }
    ui.timeline.replaceChildren();
    trace.length = 0;
    currentRunId = null;
    lastFinalResult = "";
    setText(ui.runSubtitle, "Agent runtime monitor · run=not-started");
    setText(ui.traceCount, 0);
    setText(ui.lastSequence, 0);
    setText(ui.modelCalls, 0);
    setText(ui.toolCalls, 0);
    setText(ui.verificationStatus, "—");
    setText(ui.verificationSummary, "not run");
    updateProgress("idle", false);
    clearError();
    appendMissionMessage("system", "SYSTEM", "New run workspace prepared. Environment-backed model configuration is unchanged.");
    ui.task.focus();
  }

  function exportTrace() {
    const payload = JSON.stringify({run_id:currentRunId, workspace, exported_at:new Date().toISOString(), events:trace}, null, 2);
    const blob = new Blob([payload], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${currentRunId || "paperclaw-trace"}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast("Trace export prepared.");
  }

  function clearTask() {
    ui.task.value = "";
    updateTaskInput();
    ui.task.focus();
  }

  function updateTaskInput() {
    setText(ui.taskCount, `${ui.task.value.length} / 100000`);
    ui.task.style.height = "auto";
    ui.task.style.height = `${Math.min(ui.task.scrollHeight, 180)}px`;
  }

  function onTaskKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      startRun();
    }
    if (event.key === "Escape") clearError();
  }

  function onGlobalKeydown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      ui.globalSearch.focus();
    }
    if (event.key === "Escape" && !ui.settingsPanel.hidden) closeSettings();
  }

  function renderBackendError(response) {
    showError(response && response.error_code ? response.error_code : "runtime_error", response && response.error_message ? response.error_message : "Desktop operation failed.");
  }

  function showError(code, message) {
    ui.publicError.hidden = false;
    ui.publicError.textContent = `${stringValue(code, "runtime_error")}: ${stringValue(message, "Desktop operation failed.")}`;
  }

  function clearError() {
    ui.publicError.hidden = true;
    ui.publicError.textContent = "";
  }

  function showToast(message) {
    setText(ui.toastMessage, message);
    ui.toast.hidden = false;
    if (toastTimer !== null) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(hideToast, 3200);
  }

  function hideToast() {
    if (toastTimer !== null) window.clearTimeout(toastTimer);
    toastTimer = null;
    ui.toast.hidden = true;
  }

  function setText(element, value) {
    element.textContent = String(value);
  }

  function stringValue(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return String(value);
  }

  function numberValue(value) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.floor(number) : 0;
  }

  function boundedInteger(value, fallback, maximum) {
    const number = Number(value);
    return Number.isInteger(number) && number >= 1 && number <= maximum ? number : fallback;
  }

  // Let the workbench shell (mock pages, inspector, modal) reuse the same
  // toast pipeline as the live console instead of duplicating it.
  window.PaperClawToast = showToast;

  document.addEventListener("DOMContentLoaded", bindDom, {once:true});
  window.addEventListener("pywebviewready", markBridgeReady, {once:true});
})();
