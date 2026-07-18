(() => {
  "use strict";

  const ACTIVE_STATUSES = new Set(["starting", "running", "stopping"]);
  const MAX_TIMELINE_ROWS = 300;
  const POLL_INTERVAL_MS = 250;
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
  const THEME_STORAGE_KEY = "paperclaw.theme.v1";
  const THEMES = new Map([
    ["neo-brutalist", "Neo Brutalist"],
    ["soft-minimal", "Soft Minimal"],
    ["terminal-dark", "Terminal Dark"],
    ["clean-mono", "Clean Mono"],
    ["paper-light", "Paper Light"]
  ]);
  const bootstrap = readBrowserBootstrap();
  const bridgeClientId = createClientId();
  const httpApi = bootstrap.token ? createHttpApi(bootstrap.token) : null;
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> edf37eb
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
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
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
  let currentTheme = resolveInitialTheme(bootstrap.theme);
  document.documentElement.dataset.theme = currentTheme;
>>>>>>> edf37eb
=======
  let providerSource = "env";
>>>>>>> f189121
=======
  let currentTheme = resolveInitialTheme(bootstrap.theme);
  document.documentElement.dataset.theme = currentTheme;
>>>>>>> 18cf7be
=======
  let currentTheme = resolveInitialTheme(bootstrap.theme);
  document.documentElement.dataset.theme = currentTheme;
>>>>>>> 70e7334

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
<<<<<<< HEAD
      "settings-panel", "close-settings", "config-provider", "config-base-url", "config-model",
      "config-credential", "max-steps", "max-model-calls", "max-tool-calls",
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
      "settings-panel", "close-settings", "config-source", "config-provider", "config-base-url",
      "config-model", "config-credential", "provider-input", "provider-base-url",
      "provider-api-key", "provider-manual-model", "toggle-api-key", "connect-provider",
      "use-manual-model", "disconnect-provider", "connection-status", "active-config-status",
      "provider-model", "max-steps", "max-model-calls", "max-tool-calls",
>>>>>>> f189121
      "verification-enabled", "toast", "toast-message", "close-toast"
=======
      "verification-enabled", "theme-select", "open-browser", "toast", "toast-message",
      "close-toast"
>>>>>>> edf37eb
=======
      "verification-enabled", "theme-select", "open-browser", "toast", "toast-message",
      "close-toast"
>>>>>>> 18cf7be
=======
      "verification-enabled", "theme-select", "open-browser", "toast", "toast-message",
      "close-toast"
>>>>>>> 70e7334
    ]) ui[toCamel(id)] = byId(id);

    ui.sidebarToggle.addEventListener("click", toggleSidebar);
    ui.workspaceCard.addEventListener("click", selectWorkspace);
    ui.selectWorkspace.addEventListener("click", selectWorkspace);
    ui.runButton.addEventListener("click", startRun);
    ui.sendButton.addEventListener("click", startRun);
    ui.cancelButton.addEventListener("click", cancelRun);
    ui.exportButton.addEventListener("click", exportTrace);
    ui.newRunButton.addEventListener("click", resetForNewRun);
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
    ui.themeSelect.addEventListener("change", () => applyTheme(ui.themeSelect.value, true));
    ui.openBrowser.addEventListener("click", openInBrowser);
>>>>>>> edf37eb
=======
    ui.themeSelect.addEventListener("change", () => applyTheme(ui.themeSelect.value, true));
    ui.openBrowser.addEventListener("click", openInBrowser);
>>>>>>> 18cf7be
=======
    ui.themeSelect.addEventListener("change", () => applyTheme(ui.themeSelect.value, true));
    ui.openBrowser.addEventListener("click", openInBrowser);
>>>>>>> 70e7334
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
    ui.settingsPanel.addEventListener("click", (event) => {
      if (event.target === ui.settingsPanel) closeSettings();
    });
    ui.toggleApiKey.addEventListener("click", toggleApiKeyVisibility);
    ui.connectProvider.addEventListener("click", connectProvider);
    ui.useManualModel.addEventListener("click", useManualModel);
    ui.disconnectProvider.addEventListener("click", disconnectProvider);
    ui.providerModel.addEventListener("change", selectProviderModel);
    ui.closeToast.addEventListener("click", hideToast);
    bindFilterGroup(ui.missionFilters, "data-log-filter", applyMissionFilter);
    bindFilterGroup(ui.timelineFilters, "data-tl-filter", applyTimelineFilter);
    bindNavigation();
    bindToolChips();
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
    ui.themeSelect.value = currentTheme;
    if (httpApi) {
      bridgeReady = true;
      ui.openBrowser.disabled = true;
      ui.openBrowser.textContent = "◎ BROWSER MODE";
      ui.openBrowser.title = "当前已在系统浏览器中运行";
    }
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> edf37eb
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
    updateTaskInput();
    maybeInitialize();
  }

  function toCamel(value) {
    return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  }

  function backendApi() {
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
=======
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return httpApi;
  }

  function backendMode() {
    return httpApi && !(window.pywebview && window.pywebview.api) ? "browser" : "desktop";
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> edf37eb
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
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
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
      showError("gui_dependency_missing", "Desktop bridge does not expose environment defaults.");
=======
      showError("gui_dependency_missing", "PaperClaw bridge does not expose environment defaults.");
>>>>>>> edf37eb
=======
      showError("gui_dependency_missing", "Desktop bridge does not expose model defaults.");
>>>>>>> f189121
=======
      showError("gui_dependency_missing", "PaperClaw bridge does not expose environment defaults.");
>>>>>>> 18cf7be
=======
      showError("gui_dependency_missing", "PaperClaw bridge does not expose environment defaults.");
>>>>>>> 70e7334
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
<<<<<<< HEAD
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
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
      if (!THEMES.has(bootstrap.theme) && response.theme && THEMES.has(response.theme)) {
        applyTheme(response.theme, false);
      }
>>>>>>> edf37eb
=======
      renderProviderConfiguration(response);
>>>>>>> f189121
=======
      if (!THEMES.has(bootstrap.theme) && response.theme && THEMES.has(response.theme)) {
        applyTheme(response.theme, false);
      }
>>>>>>> 18cf7be
=======
      if (!THEMES.has(bootstrap.theme) && response.theme && THEMES.has(response.theme)) {
        applyTheme(response.theme, false);
      }
>>>>>>> 70e7334
    } catch (_error) {
      showError("runtime_error", "Model defaults could not be loaded.");
    }
  }

  function renderProviderConfiguration(response) {
    providerSource = stringValue(response.provider_source, "env").toLowerCase();
    const provider = stringValue(response.provider, "openai-compatible");
    const baseUrl = stringValue(response.base_url, "");
    const model = stringValue(response.model || response.selected_model, "");
    const models = Array.isArray(response.models) ? response.models : (model ? [model] : []);
    const configured = Boolean(response.configured);
    const isManual = providerSource === "manual";
    const manualModel = stringValue(response.model_source, "") === "manual";

    ui.providerInput.value = provider;
    ui.providerBaseUrl.value = baseUrl;
    ui.providerManualModel.value = manualModel ? model : "";
    setText(ui.configSource, isManual ? "Manual in-memory connection" : "Environment variables");
    setText(ui.configProvider, provider);
    setText(ui.configBaseUrl, baseUrl || "not configured");
    setText(ui.configModel, model || "not configured");
    setText(ui.configCredential, configured ? "Configured (hidden)" : `Missing: ${(response.missing || []).join(", ")}`);
    setText(ui.modelLabel, model || (isManual ? "MANUAL" : "ENV"));
    renderModelOptions(models, model, isManual && configured);
    setText(ui.connectionStatus, isManual
      ? (manualModel ? "CONNECTED · MANUAL MODEL" : "CONNECTED")
      : (configured ? "ENV READY" : "NOT CONNECTED"));
    setText(ui.activeConfigStatus, configured
      ? `ACTIVE · ${isManual ? "MANUAL" : "ENV"} · ${model || "model not selected"}`
      : "ACTIVE · NONE");
    setText(ui.providerSummary, configured
      ? `LLM · ${isManual ? "MANUAL" : "ENV"} · ${provider} / ${model || "model"}`
      : `LLM · ENV INCOMPLETE · ${(response.missing || []).join(", ")}`);
    ui.envBadge.textContent = isManual ? "API✓" : (configured ? "ENV✓" : "ENV!");
    ui.envBadge.dataset.configured = configured ? "true" : "false";
    ui.disconnectProvider.disabled = !isManual;
  }

  function renderModelOptions(models, selectedModel, enabled) {
    ui.providerModel.replaceChildren();
    const normalizedModels = [];
    for (const value of models || []) {
      const model = stringValue(value, "").trim();
      if (model && !normalizedModels.includes(model)) normalizedModels.push(model);
    }
    if (!normalizedModels.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Connect provider first";
      ui.providerModel.append(option);
      ui.providerModel.disabled = true;
      return;
    }
    for (const model of normalizedModels) {
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      option.selected = model === selectedModel;
      ui.providerModel.append(option);
    }
    ui.providerModel.disabled = !enabled;
  }

  async function connectProvider() {
    const api = backendApi();
    if (!api || typeof api.connect_provider !== "function") {
      showError("gui_dependency_missing", "Desktop bridge does not support provider connection.");
      return;
    }
    const provider = ui.providerInput.value.trim() || "openai-compatible";
    const baseUrl = ui.providerBaseUrl.value.trim();
    const apiKey = ui.providerApiKey.value.trim();
    const manualModel = ui.providerManualModel.value.trim();
    if (!baseUrl || !apiKey) {
      showError("validation_error", "请输入 Base URL 和 API Key。");
      (!baseUrl ? ui.providerBaseUrl : ui.providerApiKey).focus();
      return;
    }

    clearError();
    ui.connectProvider.disabled = true;
    ui.providerModel.disabled = true;
    setText(ui.connectionStatus, "CONNECTING…");
    try {
      const payload = {
        provider,
        base_url: baseUrl,
        api_key: apiKey
      };
      if (manualModel) payload.model = manualModel;
      const response = await api.connect_provider(payload);
      if (!response || !response.ok) {
        renderBackendError(response);
        const preserved = Boolean(response && response.active_configuration_preserved);
        setText(ui.connectionStatus, preserved
          ? "FAILED · PREVIOUS ACTIVE"
          : "CONNECTION FAILED");
        if (preserved) showToast("Connection failed. Previous provider remains active.");
        return;
      }
      clearApiKeyField();
      renderProviderConfiguration(response);
      const count = numberValue((response.models || []).length);
      const warning = stringValue(response.discovery_warning, "");
      appendMissionMessage("system", "SYSTEM", warning
        ? `Provider connected with manual model fallback. ${warning}`
        : `Provider connected. ${count} models available.`);
      showToast(warning
        ? "Provider connected with an unverified manual model."
        : "Provider connected and model list loaded.");
    } catch (_error) {
      showError("provider_network_error", "Provider connection could not be completed. Previous configuration was not changed.");
      setText(ui.connectionStatus, providerSource === "manual"
        ? "FAILED · PREVIOUS ACTIVE"
        : "CONNECTION FAILED");
    } finally {
      ui.connectProvider.disabled = false;
      if (providerSource === "manual") ui.providerModel.disabled = false;
    }
  }

  async function selectProviderModel() {
    const selected = ui.providerModel.value;
    if (!selected) return;
    const api = backendApi();
    if (!api || typeof api.select_provider_model !== "function") {
      showError("gui_dependency_missing", "Desktop bridge does not support model selection.");
      return;
    }
    ui.providerModel.disabled = true;
    try {
      const response = await api.select_provider_model(selected);
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      providerSource = "manual";
      ui.providerManualModel.value = "";
      setText(ui.configModel, selected);
      setText(ui.modelLabel, selected);
      setText(ui.providerSummary, `LLM · MANUAL · ${stringValue(response.provider, "openai-compatible")} / ${selected}`);
      setText(ui.connectionStatus, "CONNECTED");
      setText(ui.activeConfigStatus, `ACTIVE · MANUAL · ${selected}`);
      ui.envBadge.textContent = "API✓";
      ui.envBadge.dataset.configured = "true";
      ui.disconnectProvider.disabled = false;
      showToast(`Model selected: ${selected}`);
    } catch (_error) {
      showError("runtime_error", "Model selection could not be saved.");
    } finally {
      ui.providerModel.disabled = false;
    }
  }

  async function useManualModel() {
    const selected = ui.providerManualModel.value.trim();
    if (!selected) {
      showError("validation_error", "请输入要使用的模型名称。");
      ui.providerManualModel.focus();
      return;
    }
    const api = backendApi();
    if (!api || typeof api.select_provider_model !== "function") {
      showError("gui_dependency_missing", "Desktop bridge does not support manual model selection.");
      return;
    }
    clearError();
    ui.useManualModel.disabled = true;
    try {
      const response = await api.select_provider_model(selected, true);
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      renderProviderConfiguration(response);
      appendMissionMessage("system", "SYSTEM", `Manual model selected without endpoint verification: ${selected}`);
      showToast(`Manual model selected: ${selected}`);
    } catch (_error) {
      showError("runtime_error", "Manual model selection could not be saved.");
    } finally {
      ui.useManualModel.disabled = false;
    }
  }

  async function disconnectProvider() {
    const api = backendApi();
    if (!api || typeof api.clear_manual_provider !== "function") {
      showError("gui_dependency_missing", "Desktop bridge does not support returning to ENV configuration.");
      return;
    }
    clearError();
    ui.disconnectProvider.disabled = true;
    try {
      const response = await api.clear_manual_provider();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      clearApiKeyField();
      renderProviderConfiguration(response);
      appendMissionMessage("system", "SYSTEM", "Manual provider disconnected. New runs will use environment-backed configuration.");
      showToast(response.configured
        ? "Manual provider cleared. ENV configuration is active."
        : "Manual provider cleared. ENV configuration is incomplete.");
    } catch (_error) {
      showError("runtime_error", "Manual provider could not be cleared.");
      ui.disconnectProvider.disabled = providerSource !== "manual";
    }
  }

  function clearApiKeyField() {
    ui.providerApiKey.value = "";
    ui.providerApiKey.type = "password";
    ui.toggleApiKey.setAttribute("aria-pressed", "false");
    setText(ui.toggleApiKey, "SHOW KEY");
  }

  function toggleApiKeyVisibility() {
    const showing = ui.providerApiKey.type === "text";
    ui.providerApiKey.type = showing ? "password" : "text";
    ui.toggleApiKey.setAttribute("aria-pressed", showing ? "false" : "true");
    setText(ui.toggleApiKey, showing ? "SHOW KEY" : "HIDE KEY");
    ui.providerApiKey.focus();
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
      appendMissionMessage("system", "SYSTEM", `Run accepted. Using ${providerSource === "manual" ? "the manual in-memory provider" : "environment-backed provider configuration"}.`);
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

<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
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
    const normalized = THEMES.has(theme) ? theme : "neo-brutalist";
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
    return "neo-brutalist";
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

<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> edf37eb
=======
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
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
        for (const candidate of ui.sidebarNav.querySelectorAll("[data-nav]")) candidate.classList.remove("active");
        button.classList.add("active");
        const target = button.dataset.nav;
        if (target === "settings") openSettings();
        else if (target !== "console") showToast(`${button.textContent.trim()} is under development in v0.11.`);
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
    ui.settingsPanel.hidden = false;
    ui.providerBaseUrl.focus();
  }

  function closeSettings() {
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
    appendMissionMessage("system", "SYSTEM", "New run workspace prepared. Current model configuration is unchanged.");
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

  document.addEventListener("DOMContentLoaded", bindDom, {once:true});
  window.addEventListener("pywebviewready", markBridgeReady, {once:true});
})();
