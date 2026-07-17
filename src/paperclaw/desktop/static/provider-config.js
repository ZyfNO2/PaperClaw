(() => {
  "use strict";

  const bootstrapToken = readBootstrapToken();
  const httpApi = bootstrapToken ? createHttpApi(bootstrapToken) : null;
  const ui = {};
  let initialized = false;
  let connecting = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    for (const id of [
      "config-source", "config-provider", "config-base-url", "config-model",
      "config-credential", "provider-base-url", "provider-api-key",
      "provider-key-toggle", "provider-connect", "provider-model",
      "provider-reset", "provider-connect-status", "provider-summary",
      "env-badge", "model-label", "verification-enabled", "gate-mode-status"
    ]) ui[toCamel(id)] = byId(id);

    ui.providerKeyToggle.addEventListener("click", toggleKeyVisibility);
    ui.providerConnect.addEventListener("click", connectProvider);
    ui.providerModel.addEventListener("change", selectModel);
    ui.providerReset.addEventListener("click", resetToEnvironment);
    ui.verificationEnabled.addEventListener("change", renderGateMode);
    renderGateMode();
    maybeLoadDefaults();
  }

  function toCamel(value) {
    return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  }

  function backendApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return httpApi;
  }

  async function maybeLoadDefaults() {
    if (!initialized) return;
    const api = backendApi();
    if (!api || typeof api.get_defaults !== "function") return;
    try {
      const response = await api.get_defaults();
      if (response && response.ok) renderProviderState(response);
    } catch (_error) {
      setStatus("Provider defaults could not be loaded.", "error");
    }
  }

  async function connectProvider() {
    if (connecting) return;
    const baseUrl = ui.providerBaseUrl.value.trim();
    const apiKey = ui.providerApiKey.value.trim();
    if (!baseUrl || !apiKey) {
      setStatus("Base URL 和 API Key 均不能为空。", "error");
      return;
    }

    const api = backendApi();
    if (!api || typeof api.connect_provider !== "function") {
      setStatus("当前桌面桥接不支持模型发现。", "error");
      return;
    }

    connecting = true;
    ui.providerConnect.disabled = true;
    ui.providerModel.disabled = true;
    setStatus("正在连接并读取模型列表……", "pending");
    try {
      const response = await api.connect_provider({
        base_url: baseUrl,
        api_key: apiKey,
        provider: "openai-compatible"
      });
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      ui.providerApiKey.value = "";
      ui.providerApiKey.type = "password";
      ui.providerKeyToggle.textContent = "显示";
      renderProviderState(response);
      setStatus(`连接成功，可用模型 ${response.available_models.length} 个。`, "success");
    } catch (_error) {
      setStatus("连接失败：桌面桥接未返回有效结果。", "error");
    } finally {
      connecting = false;
      ui.providerConnect.disabled = false;
      ui.providerModel.disabled = ui.providerModel.options.length === 0;
    }
  }

  async function selectModel() {
    const model = ui.providerModel.value;
    if (!model) return;
    const api = backendApi();
    if (!api || typeof api.select_provider_model !== "function") return;
    ui.providerModel.disabled = true;
    setStatus("正在切换模型……", "pending");
    try {
      const response = await api.select_provider_model(model);
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      renderProviderState(response);
      setStatus(`已选择模型：${model}`, "success");
    } catch (_error) {
      setStatus("模型切换失败。", "error");
    } finally {
      ui.providerModel.disabled = false;
    }
  }

  async function resetToEnvironment() {
    const api = backendApi();
    if (!api || typeof api.clear_provider_config !== "function") {
      setStatus("当前桌面桥接不支持恢复 ENV。", "error");
      return;
    }
    try {
      const response = await api.clear_provider_config();
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      ui.providerModel.replaceChildren();
      ui.providerModel.disabled = true;
      setStatus("已恢复为环境变量配置。", "success");
      await maybeLoadDefaults();
    } catch (_error) {
      setStatus("恢复 ENV 配置失败。", "error");
    }
  }

  function renderProviderState(response) {
    const source = response.provider_source === "manual" ? "Manual connection" : "Environment variables";
    const provider = text(response.provider, "openai-compatible");
    const baseUrl = text(response.base_url, "not configured");
    const model = text(response.model, "not configured");
    const configured = Boolean(response.configured);

    ui.configSource.textContent = source;
    ui.configProvider.textContent = provider;
    ui.configBaseUrl.textContent = baseUrl;
    ui.configModel.textContent = model;
    ui.configCredential.textContent = configured ? "Configured (hidden)" : `Missing: ${(response.missing || []).join(", ")}`;
    ui.providerBaseUrl.value = response.base_url || "";

    if (Array.isArray(response.available_models)) {
      populateModels(response.available_models, response.model);
    }

    const prefix = response.provider_source === "manual" ? "MANUAL" : "ENV";
    ui.providerSummary.textContent = configured
      ? `LLM · ${prefix} · ${provider} / ${model}`
      : `LLM · ${prefix} INCOMPLETE · ${(response.missing || []).join(", ")}`;
    ui.modelLabel.textContent = model;
    ui.envBadge.textContent = response.provider_source === "manual" ? "API✓" : (configured ? "ENV✓" : "ENV!");
    ui.envBadge.dataset.configured = configured ? "true" : "false";
  }

  function populateModels(models, selected) {
    const fragment = document.createDocumentFragment();
    const seen = new Set();
    for (const value of models) {
      const model = text(value, "").trim();
      if (!model || seen.has(model)) continue;
      seen.add(model);
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      option.selected = model === selected;
      fragment.append(option);
    }
    ui.providerModel.replaceChildren(fragment);
    if (selected && seen.has(selected)) ui.providerModel.value = selected;
    ui.providerModel.disabled = seen.size === 0;
  }

  function toggleKeyVisibility() {
    const showing = ui.providerApiKey.type === "text";
    ui.providerApiKey.type = showing ? "password" : "text";
    ui.providerKeyToggle.textContent = showing ? "显示" : "隐藏";
  }

  function renderGateMode() {
    ui.gateModeStatus.textContent = ui.verificationEnabled.checked
      ? "Verify 与 Reflection Gate 已开启。"
      : "Verify 与 Reflection Gate 已关闭；任务完成后直接结束。";
  }

  function renderError(response) {
    const code = response && response.error_code ? response.error_code : "runtime_error";
    const message = response && response.error_message ? response.error_message : "Provider connection failed.";
    setStatus(`${code}: ${message}`, "error");
  }

  function setStatus(message, state) {
    ui.providerConnectStatus.textContent = message;
    ui.providerConnectStatus.dataset.state = state;
  }

  function readBootstrapToken() {
    if (!window.location.hash) return "";
    try {
      return new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    } catch (_error) {
      return "";
    }
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
      const payload = await response.json();
      return payload;
    }
    return {
      get_defaults: () => invoke("get_defaults", []),
      connect_provider: (request) => invoke("connect_provider", [request]),
      select_provider_model: (model) => invoke("select_provider_model", [model]),
      clear_provider_config: () => invoke("clear_provider_config", [])
    };
  }

  function text(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return String(value);
  }

  document.addEventListener("DOMContentLoaded", bind, {once:true});
  window.addEventListener("pywebviewready", maybeLoadDefaults);
})();
