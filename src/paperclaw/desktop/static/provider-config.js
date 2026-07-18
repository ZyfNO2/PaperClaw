(() => {
  "use strict";

  const bootstrapToken = readBootstrapToken();
  const httpApi = bootstrapToken ? createHttpApi(bootstrapToken) : null;
  const ui = {};
  let initialized = false;
  let connecting = false;
  let providerSource = "env";

  function byId(id) {
    return document.getElementById(id);
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    for (const id of [
      "config-source", "config-provider", "config-base-url", "config-model",
      "config-credential", "provider-base-url", "provider-api-key",
      "provider-manual-model", "provider-key-toggle", "provider-connect",
      "provider-model", "provider-reset", "use-manual-model",
      "disconnect-provider", "active-config-status", "provider-connect-status",
      "provider-summary", "env-badge", "model-label", "verification-enabled",
      "gate-mode-status"
    ]) ui[toCamel(id)] = byId(id);

    ui.providerKeyToggle.addEventListener("click", toggleKeyVisibility);
    ui.providerConnect.addEventListener("click", connectProvider);
    ui.providerModel.addEventListener("change", selectModel);
    ui.providerReset.addEventListener("click", resetToEnvironment);
    ui.useManualModel.addEventListener("click", useManualModel);
    ui.disconnectProvider.addEventListener("click", disconnectProvider);
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
    const manualModel = ui.providerManualModel.value.trim();
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
      const payload = {
        base_url: baseUrl,
        api_key: apiKey,
        provider: "openai-compatible"
      };
      if (manualModel) payload.model = manualModel;
      const response = await api.connect_provider(payload);
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      clearCredentialInput();
      renderProviderState(response);
      const models = modelList(response);
      if (response.discovery_warning) {
        setStatus(response.discovery_warning, "warning");
      } else {
        setStatus(`连接成功，可用模型 ${models.length} 个。`, "success");
      }
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

  async function useManualModel() {
    const selected = ui.providerManualModel.value.trim();
    if (!selected) {
      setStatus("请输入要使用的模型名称。", "error");
      ui.providerManualModel.focus();
      return;
    }
    const api = backendApi();
    if (!api || typeof api.select_provider_model !== "function") {
      setStatus("当前桌面桥接不支持手动模型选择。", "error");
      return;
    }
    ui.useManualModel.disabled = true;
    try {
      const response = await api.select_provider_model(selected, true);
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      renderProviderState(response);
      setStatus(`已选择模型：${selected}`, "warning");
    } catch (_error) {
      setStatus("模型切换失败。", "error");
    } finally {
      ui.useManualModel.disabled = false;
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
      clearManualUi();
      setStatus("已恢复为环境变量配置。", "success");
      await maybeLoadDefaults();
    } catch (_error) {
      setStatus("恢复 ENV 配置失败。", "error");
    }
  }

  async function disconnectProvider() {
    const api = backendApi();
    if (!api || typeof api.clear_manual_provider !== "function") {
      setStatus("当前桌面桥接不支持断开手动 Provider。", "error");
      return;
    }
    ui.disconnectProvider.disabled = true;
    try {
      const response = await api.clear_manual_provider();
      if (!response || !response.ok) {
        renderError(response);
        return;
      }
      clearManualUi();
      renderProviderState(response);
      setStatus(
        response.configured
          ? "手动 Provider 已断开，ENV 配置继续生效。"
          : "手动 Provider 已断开，但 ENV 配置不完整。",
        response.configured ? "success" : "warning"
      );
    } catch (_error) {
      setStatus("断开手动 Provider 失败。", "error");
      ui.disconnectProvider.disabled = providerSource !== "manual";
    }
  }

  function clearManualUi() {
    clearCredentialInput();
    ui.providerModel.replaceChildren();
    ui.providerModel.disabled = true;
    ui.providerManualModel.value = "";
  }

  function clearCredentialInput() {
    ui.providerApiKey.value = "";
    ui.providerApiKey.type = "password";
    ui.providerKeyToggle.textContent = "显示";
  }

  function renderProviderState(response) {
    providerSource = response.provider_source === "manual" ? "manual" : "env";
    const source = providerSource === "manual" ? "Manual connection" : "Environment variables";
    const provider = text(response.provider, "openai-compatible");
    const baseUrl = text(response.base_url, "not configured");
    const model = text(response.model || response.selected_model, "not configured");
    const configured = Boolean(response.configured);
    const verified = response.model_verified !== false;
    const models = modelList(response);

    ui.configSource.textContent = source;
    ui.configProvider.textContent = provider;
    ui.configBaseUrl.textContent = baseUrl;
    ui.configModel.textContent = verified ? model : `${model} (unverified)`;
    ui.configCredential.textContent = configured ? "Configured (hidden)" : `Missing: ${(response.missing || []).join(", ")}`;
    ui.providerBaseUrl.value = response.base_url || "";
    if (providerSource === "manual" && response.model_source === "manual") {
      ui.providerManualModel.value = response.model || response.selected_model || "";
    }

    if (models.length) populateModels(models, response.model || response.selected_model);

    const prefix = providerSource === "manual" ? "MANUAL" : "ENV";
    const modelDisplay = verified ? model : `${model} · UNVERIFIED`;
    ui.providerSummary.textContent = configured
      ? `LLM · ${prefix} · ${provider} / ${modelDisplay}`
      : `LLM · ${prefix} INCOMPLETE · ${(response.missing || []).join(", ")}`;
    ui.modelLabel.textContent = modelDisplay;
    ui.envBadge.textContent = providerSource === "manual" ? "API✓" : (configured ? "ENV✓" : "ENV!");
    ui.envBadge.dataset.configured = configured ? "true" : "false";
    ui.disconnectProvider.disabled = providerSource !== "manual";
    ui.activeConfigStatus.textContent = configured
      ? `ACTIVE · ${prefix} · ${modelDisplay}`
      : "ACTIVE · NONE";
  }

  function modelList(response) {
    if (Array.isArray(response.available_models)) return response.available_models;
    if (Array.isArray(response.models)) return response.models;
    return response.model ? [response.model] : [];
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
    if (response && response.active_configuration_preserved) {
      const source = text(response.active_provider_source, "previous").toUpperCase();
      ui.activeConfigStatus.textContent = `ACTIVE · ${source} · ${text(response.active_model, "model")}`;
      setStatus(`${code}: ${message} · Previous provider remains active`, "warning");
      return;
    }
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
      return response.json();
    }
    return {
      get_defaults: () => invoke("get_defaults", []),
      connect_provider: (request) => invoke("connect_provider", [request]),
      select_provider_model: (model, allowUnlisted = false) => invoke("select_provider_model", [model, allowUnlisted]),
      clear_provider_config: () => invoke("clear_provider_config", []),
      clear_manual_provider: () => invoke("clear_manual_provider", [])
    };
  }

  function text(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return String(value);
  }

  document.addEventListener("DOMContentLoaded", bind, {once:true});
  window.addEventListener("pywebviewready", maybeLoadDefaults);
})();
