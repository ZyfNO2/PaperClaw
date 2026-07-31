(() => {
  "use strict";

  const ACTIVE_STATUSES = new Set(["starting", "running", "stopping"]);
  const MAX_TIMELINE_ROWS = 300;
  const ACTIVE_POLL_MS = 250;
  const IDLE_POLL_MS = 1500;
  const HIDDEN_POLL_MS = 4000;
  const MAX_BACKOFF_MS = 8000;
  const MAX_MISSION_ROWS = 300;
  const THEME_STORAGE_KEY = "paperclaw.theme.v1";
  const THEMES = new Map([
    ["dark", "Dark"],
    ["light", "Light"]
  ]);
  const bootstrap = window.PaperClawBackend ? window.PaperClawBackend.bootstrap : {token: "", theme: ""};
  const debugEnabled = new URLSearchParams(window.location.search).get("debug") === "1";
  const bridgeClientId = createClientId();
  const ui = {};
  const trace = [];
  let domReady = false;
  let bridgeReady = false;
  let pollTimer = null;
  let pollInFlight = false;
  let initializePromise = null;
  let initialized = false;
  let initializeAttempts = 0;
  let pollFailures = 0;
  let requestGeneration = 0;
  let eventGeneration = null;
  let lastAppliedSequence = 0;
  let lastSuccessfulPoll = null;
  let backendConnected = false;
  let lastPublicErrorCode = null;
  let cancelSubmitting = false;
  let backendActive = false;
  const renderedEvents = new Set();
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
      "close-toast", "brand-version", "frontend-diagnostics"
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
    document.addEventListener("visibilitychange", () => {
      schedulePoll(0);
      updateDiagnostics();
    });
    window.addEventListener("beforeunload", stopPolling, {once:true});
    ui.closeSettings.addEventListener("click", closeSettings);
    ui.closeToast.addEventListener("click", hideToast);
    bindFilterGroup(ui.missionFilters, "data-log-filter", applyMissionFilter);
    bindFilterGroup(ui.timelineFilters, "data-tl-filter", applyTimelineFilter);
    bindNavigation();
    bindToolChips();
    ui.themeSelect.value = currentTheme;
    if (backendMode() === "browser") {
      bridgeReady = true;
      ui.openBrowser.disabled = true;
      ui.openBrowser.textContent = "◎ BROWSER MODE";
      ui.openBrowser.title = "当前已在系统浏览器中运行";
    }
    updateTaskInput();
    ui.frontendDiagnostics.hidden = !debugEnabled;
    maybeInitialize();
  }

  function toCamel(value) {
    return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  }

  function backendApi() {
    return window.PaperClawBackend ? window.PaperClawBackend.api : null;
  }

  function backendMode() {
    return window.PaperClawBackend ? window.PaperClawBackend.mode() : "desktop";
  }

  function markBridgeReady() {
    bridgeReady = true;
    maybeInitialize();
  }

  async function maybeInitialize() {
    if (!domReady) return;
    if (!bridgeReady && backendApi()) bridgeReady = true;
    if (!bridgeReady) return;
    if (initialized) return;
    if (initializePromise) return initializePromise;
    initializeAttempts += 1;
    ui.envBadge.textContent = "INIT";
    initializePromise = (async () => {
      const generation = requestGeneration;
      const defaultsLoaded = await loadDefaults(generation);
      const stateLoaded = await refreshState(generation);
      if (!defaultsLoaded || !stateLoaded) {
        if (initializeAttempts < 3) {
          window.setTimeout(maybeInitialize, 250 * initializeAttempts);
        }
        return;
      }
      initialized = true;
      backendConnected = true;
      clearError();
      schedulePoll(0);
    })().finally(() => { initializePromise = null; });
    return initializePromise;
  }

  async function loadDefaults(generation = requestGeneration) {
    const api = backendApi();
    if (!api || typeof api.get_defaults !== "function") {
      showError("gui_dependency_missing", "PaperClaw bridge does not expose environment defaults.");
      return false;
    }
    try {
      const response = await api.get_defaults();
      if (generation !== requestGeneration) return false;
      if (!response || !response.ok) {
        renderBackendError(response);
        return false;
      }
      workspace = stringValue(response.workspace, "");
      renderWorkspace(workspace);
      setText(ui.configProvider, stringValue(response.provider, "openai-compatible"));
      setText(ui.configBaseUrl, stringValue(response.base_url, "not configured"));
      setText(ui.configModel, stringValue(response.model, "not configured"));
      setText(ui.configCredential, response.configured ? "Configured (hidden)" : `Missing: ${(response.missing || []).join(", ")}`);
      setText(ui.modelLabel, stringValue(response.model, "ENV"));
      setText(ui.brandVersion, `v${stringValue(response.package_version, "unknown")} · workbench`);
      setText(ui.providerSummary, response.configured
        ? `LLM · ENV · ${stringValue(response.provider, "openai-compatible")} / ${stringValue(response.model, "model")}`
        : `LLM · ENV INCOMPLETE · ${(response.missing || []).join(", ")}`);
      ui.envBadge.textContent = response.configured ? "ENV✓" : "ENV!";
      ui.envBadge.dataset.configured = response.configured ? "true" : "false";
      if (!THEMES.has(bootstrap.theme) && response.theme && THEMES.has(response.theme)) {
        applyTheme(response.theme, false);
      }
      document.dispatchEvent(new CustomEvent("paperclaw:defaults", {detail: response}));
      return true;
    } catch (_error) {
      showError("runtime_error", "Environment defaults could not be loaded.");
      return false;
    }
  }

  async function refreshState(generation = requestGeneration) {
    const api = backendApi();
    if (!api) return false;
    try {
      const response = await api.get_state();
      if (generation !== requestGeneration) return false;
      if (response && response.ok && response.state) {
        renderSnapshot(response.state);
        return true;
      }
      renderBackendError(response);
      return false;
    } catch (_error) {
      showError("runtime_error", "Desktop state could not be loaded.");
      return false;
    }
  }

  async function pollBackend() {
    if (pollInFlight) return;
    const api = backendApi();
    if (!api) return;
    const generation = requestGeneration;
    pollInFlight = true;
    try {
      const response = await api.poll_events(200, bridgeClientId);
      if (generation !== requestGeneration) return;
      if (!response || !response.ok) {
        renderBackendError(response);
        pollFailures += 1;
        backendConnected = false;
        return;
      }
      if (eventGeneration !== null && response.generation !== eventGeneration) {
        renderedEvents.clear();
        lastAppliedSequence = 0;
      }
      eventGeneration = response.generation;
      for (const item of response.items || []) {
        if (item.kind === "event" && item.event) appendTimelineRow(item.event, eventGeneration);
        else if (item.kind === "snapshot" && item.snapshot) renderSnapshot(item.snapshot);
      }
      setText(ui.eventMeta, `${numberValue(response.dropped_count)} dropped`);
      pollFailures = 0;
      backendConnected = true;
      lastSuccessfulPoll = new Date().toISOString();
      if (["connection_error", "timeout", "invalid_response"].includes(lastPublicErrorCode)) clearError();
      updateDiagnostics();
      if (!ACTIVE_STATUSES.has(currentStatus)) await refreshState(generation);
    } catch (_error) {
      showError("runtime_error", "Desktop event polling failed.");
      pollFailures += 1;
      backendConnected = false;
    } finally {
      pollInFlight = false;
      schedulePoll(nextPollDelay());
      updateDiagnostics();
    }
  }

  function nextPollDelay() {
    const base = document.hidden
      ? HIDDEN_POLL_MS
      : ACTIVE_STATUSES.has(currentStatus) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    return Math.min(MAX_BACKOFF_MS, base * Math.max(1, 2 ** pollFailures));
  }

  function schedulePoll(delay) {
    if (!initialized && delay !== 0) return;
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(() => {
      pollTimer = null;
      pollBackend();
    }, delay);
  }

  function stopPolling() {
    requestGeneration += 1;
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = null;
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
    const previousStatus = currentStatus;
    const generation = ++requestGeneration;
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
        updateControls(previousStatus);
        return;
      }
      const response = await api.start_run(payload);
      if (!response || !response.ok) {
        renderBackendError(response);
        await refreshState(generation);
        return;
      }
      ui.task.value = "";
      updateTaskInput();
      appendMissionMessage("system", "SYSTEM", "Run accepted. Model configuration will be resolved from environment variables in Python.");
      updateControls(response.status || "starting");
      schedulePoll(0);
    } catch (_error) {
      showError("runtime_error", "Run could not be started.");
      await refreshState(generation);
    } finally {
      frontendSubmitting = false;
      updateControls(currentStatus);
    }
  }

  async function cancelRun() {
    if (cancelSubmitting) return;
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "PaperClaw bridge is not available.");
      return;
    }
    const generation = ++requestGeneration;
    cancelSubmitting = true;
    updateControls("stopping");
    try {
      const response = await api.cancel_run();
      if (!response || !response.ok) {
        renderBackendError(response);
        await refreshState(generation);
        return;
      }
      appendMissionMessage("system", "SYSTEM", "Cancellation requested.");
      updateControls(response.status || "stopping");
      schedulePoll(0);
    } catch (_error) {
      showError("runtime_error", "Cancel request could not be sent.");
      await refreshState(generation);
    } finally {
      cancelSubmitting = false;
      updateControls(currentStatus);
    }
  }

  async function selectWorkspace() {
    if (backendActive || ACTIVE_STATUSES.has(currentStatus)) return;
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

  function renderWorkspace(value) {
    const normalized = stringValue(value, "not selected");
    const segments = normalized.split(/[\\/]/).filter(Boolean);
    setText(ui.workspaceName, segments.length ? segments[segments.length - 1] : normalized);
    setText(ui.workspacePath, normalized);
  }

  function renderSnapshot(snapshot) {
    const incomingRunId = snapshot.run_id || null;
    const incomingSequence = numberValue(snapshot.last_sequence);
    if (incomingRunId && currentRunId === incomingRunId && incomingSequence < lastAppliedSequence) return;
    if (incomingRunId && incomingRunId !== currentRunId) {
      lastFinalResult = "";
      lastAppliedSequence = 0;
      renderedEvents.clear();
    }
    const previousStatus = currentStatus;
    currentStatus = stringValue(snapshot.status, "idle").toLowerCase();
    currentRunId = snapshot.run_id || currentRunId;
    backendActive = Boolean(snapshot.active) || ACTIVE_STATUSES.has(currentStatus);
    lastAppliedSequence = Math.max(lastAppliedSequence, incomingSequence);
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
    }
    updateControls(currentStatus);
    updateDiagnostics();
  }

  function appendTimelineRow(row, generation) {
    const eventType = stringValue(row.event_type, "unknown.event");
    const eventKey = `${generation}:${numberValue(row.sequence)}:${eventType}`;
    if (renderedEvents.has(eventKey)) return;
    renderedEvents.add(eventKey);
    while (renderedEvents.size > MAX_TIMELINE_ROWS * 2) {
      renderedEvents.delete(renderedEvents.values().next().value);
    }
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
    while (ui.missionLog.children.length > MAX_MISSION_ROWS) ui.missionLog.firstElementChild.remove();
    ui.missionLog.scrollTop = ui.missionLog.scrollHeight;
    applyMissionFilter();
    applyMissionSearch();
  }

  function updateControls(status) {
    currentStatus = stringValue(status, currentStatus).toLowerCase();
    const active = backendActive || ACTIVE_STATUSES.has(currentStatus) || frontendSubmitting;
    ui.runButton.disabled = active;
    ui.sendButton.disabled = active;
    ui.cancelButton.disabled = !active || currentStatus === "stopping" || cancelSubmitting;
    ui.selectWorkspace.disabled = active;
    ui.workspaceCard.disabled = active;
    ui.newRunButton.disabled = active;
    ui.task.disabled = active;
    ui.verificationEnabled.disabled = active;
    ui.maxSteps.disabled = active;
    ui.maxModelCalls.disabled = active;
    ui.maxToolCalls.disabled = active;
    for (const id of [
      "provider-connect", "provider-model", "provider-reset",
      "use-manual-model", "disconnect-provider"
    ]) {
      const control = byId(id);
      if (control) control.disabled = active;
    }
  }

  function updateDiagnostics() {
    if (!debugEnabled || !ui.frontendDiagnostics) return;
    const transport = window.PaperClawBackend ? window.PaperClawBackend.diagnostics() : {};
    ui.frontendDiagnostics.textContent = JSON.stringify({
      mode: backendMode(),
      run_id: currentRunId,
      connected: backendConnected,
      last_successful_poll: lastSuccessfulPoll,
      last_sequence: lastAppliedSequence,
      event_generation: eventGeneration,
      dropped: numberValue((ui.eventMeta.textContent || "").split(" ")[0]),
      last_public_error_code: lastPublicErrorCode || transport.lastErrorCode || null,
      active_requests: numberValue(transport.activeRequests),
      polling_interval_ms: nextPollDelay(),
      document_hidden: document.hidden
    }, null, 2);
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
    lastPublicErrorCode = stringValue(code, "runtime_error");
    ui.publicError.hidden = false;
    ui.publicError.textContent = `${stringValue(code, "runtime_error")}: ${stringValue(message, "Desktop operation failed.")}`;
  }

  function clearError() {
    lastPublicErrorCode = null;
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
