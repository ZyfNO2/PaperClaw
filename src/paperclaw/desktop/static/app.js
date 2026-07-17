(() => {
  "use strict";

  const MAX_TIMELINE_ROWS = 300;
  const POLL_INTERVAL_MS = 300;
  const TOAST_DURATION_MS = 3200;
  const ACTIVE_STATUSES = new Set(["starting", "running", "stopping"]);

  const ui = {};
  let domReady = false;
  let bridgeReady = false;
  let pollInFlight = false;
  let pollTimer = null;
  let toastTimer = null;
  let frontendSubmitting = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function bindDom() {
    if (domReady) {
      return;
    }
    domReady = true;
    ui.provider = byId("provider");
    ui.baseUrl = byId("base-url");
    ui.apiKey = byId("api-key");
    ui.toggleKey = byId("toggle-key");
    ui.model = byId("model");
    ui.workspace = byId("workspace");
    ui.selectWorkspace = byId("select-workspace");
    ui.verificationEnabled = byId("verification-enabled");
    ui.maxSteps = byId("max-steps");
    ui.maxModelCalls = byId("max-model-calls");
    ui.maxToolCalls = byId("max-tool-calls");
    ui.task = byId("task");
    ui.taskCount = byId("task-count");
    ui.clearTask = byId("clear-task");
    ui.runButton = byId("run-button");
    ui.cancelButton = byId("cancel-button");
    ui.runStatus = byId("run-status");
    ui.summaryStatus = byId("summary-status");
    ui.modelCalls = byId("model-calls");
    ui.toolCalls = byId("tool-calls");
    ui.lastSequence = byId("last-sequence");
    ui.verificationStatus = byId("verification-status");
    ui.verificationSummary = byId("verification-summary");
    ui.timeline = byId("timeline");
    ui.clearTimeline = byId("clear-timeline");
    ui.finalResult = byId("final-result");
    ui.publicError = byId("public-error");
    ui.runIdLabel = byId("run-id-label");
    ui.workspaceLabel = byId("workspace-label");
    ui.providerLabel = byId("provider-label");
    ui.modelLabel = byId("model-label");
    ui.underDevelopToast = byId("under-develop-toast");
    ui.underDevelopMessage = byId("under-develop-message");
    ui.closeToast = byId("close-toast");
    ui.statusDot = document.querySelector(".run-control-panel .status-dot");

    ui.toggleKey.addEventListener("click", toggleKeyVisibility);
    ui.runButton.addEventListener("click", startRun);
    ui.cancelButton.addEventListener("click", cancelRun);
    ui.selectWorkspace.addEventListener("click", selectWorkspace);
    ui.clearTimeline.addEventListener("click", () => ui.timeline.replaceChildren());
    ui.clearTask.addEventListener("click", clearTask);
    ui.closeToast.addEventListener("click", hideUnderDevelop);
    ui.task.addEventListener("input", updateTaskCount);
    ui.provider.addEventListener("input", updateFooterLabels);
    ui.model.addEventListener("input", updateFooterLabels);
    ui.workspace.addEventListener("input", updateFooterLabels);

    bindPlannedControls();
    updateTaskCount();
    updateFooterLabels();
    maybeInitialize();
  }

  function bindPlannedControls() {
    for (const element of document.querySelectorAll("[data-under-develop]")) {
      const featureName = element.getAttribute("data-under-develop") || "This feature";
      element.addEventListener("click", (event) => {
        event.preventDefault();
        showUnderDevelop(featureName);
      });
      if (element.getAttribute("role") === "button" && element.tagName !== "BUTTON") {
        element.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            showUnderDevelop(featureName);
          }
        });
      }
    }
  }

  function showUnderDevelop(featureName) {
    if (!ui.underDevelopToast || !ui.underDevelopMessage) {
      return;
    }
    setText(ui.underDevelopMessage, `${featureName} is Under Develop and will be enabled in a later release.`);
    ui.underDevelopToast.hidden = false;
    if (toastTimer !== null) {
      window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(hideUnderDevelop, TOAST_DURATION_MS);
  }

  function hideUnderDevelop() {
    if (toastTimer !== null) {
      window.clearTimeout(toastTimer);
      toastTimer = null;
    }
    if (ui.underDevelopToast) {
      ui.underDevelopToast.hidden = true;
    }
  }

  function clearTask() {
    ui.task.value = "";
    updateTaskCount();
    ui.task.focus();
  }

  function updateTaskCount() {
    setText(ui.taskCount, `${ui.task.value.length} / 100000`);
  }

  function updateFooterLabels() {
    setText(ui.workspaceLabel, stringValue(ui.workspace.value, "not selected"));
    setText(ui.providerLabel, stringValue(ui.provider.value, "not selected"));
    setText(ui.modelLabel, stringValue(ui.model.value, "not selected"));
  }

  function markBridgeReady() {
    bridgeReady = true;
    maybeInitialize();
  }

  function maybeInitialize() {
    if (!domReady || !bridgeReady) {
      return;
    }
    refreshState();
    if (pollTimer === null) {
      pollTimer = window.setInterval(pollBackend, POLL_INTERVAL_MS);
    }
  }

  function backendApi() {
    if (!window.pywebview || !window.pywebview.api) {
      return null;
    }
    return window.pywebview.api;
  }

  async function refreshState() {
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "Desktop bridge is not available.");
      return;
    }
    try {
      const response = await api.get_state();
      if (response && response.ok && response.state) {
        renderSnapshot(response.state);
      } else {
        renderBackendError(response);
      }
    } catch (error) {
      showError("runtime_error", "Desktop state could not be loaded.");
    }
  }

  async function pollBackend() {
    if (pollInFlight) {
      return;
    }
    const api = backendApi();
    if (!api) {
      return;
    }
    pollInFlight = true;
    try {
      const response = await api.poll_events(200);
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      for (const item of response.items || []) {
        if (item.kind === "event" && item.event) {
          appendTimelineRow(item.event);
        } else if (item.kind === "snapshot" && item.snapshot) {
          renderSnapshot(item.snapshot);
        }
      }
    } catch (error) {
      showError("runtime_error", "Desktop event polling failed.");
    } finally {
      pollInFlight = false;
    }
  }

  async function startRun() {
    if (frontendSubmitting || ACTIVE_STATUSES.has(ui.runStatus.textContent)) {
      showError("run_already_active", "A run is already active in this window.");
      return;
    }
    clearError();
    frontendSubmitting = true;
    updateControls("starting");
    const payload = {
      provider: ui.provider.value,
      base_url: ui.baseUrl.value,
      api_key: ui.apiKey.value,
      model: ui.model.value,
      workspace: ui.workspace.value,
      task: ui.task.value,
      enable_verification_gate: ui.verificationEnabled.checked,
      max_steps: boundedInteger(ui.maxSteps.value, 12),
      max_model_calls: boundedInteger(ui.maxModelCalls.value, 10),
      max_tool_calls: boundedInteger(ui.maxToolCalls.value, 20)
    };

    try {
      const api = backendApi();
      if (!api) {
        showError("gui_dependency_missing", "Desktop bridge is not available.");
        updateControls("idle");
        return;
      }
      const response = await api.start_run(payload);
      payload.api_key = "";
      if (!response || !response.ok) {
        renderBackendError(response);
        updateControls("idle");
        return;
      }
      ui.apiKey.value = "";
      ui.apiKey.type = "password";
      ui.toggleKey.textContent = "Show";
      ui.toggleKey.setAttribute("aria-pressed", "false");
      setText(ui.finalResult, "Run in progress...");
      updateControls(response.status || "starting");
    } catch (error) {
      showError("runtime_error", "Run could not be started.");
      updateControls("idle");
    } finally {
      payload.api_key = "";
      frontendSubmitting = false;
    }
  }

  async function cancelRun() {
    clearError();
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "Desktop bridge is not available.");
      return;
    }
    ui.cancelButton.disabled = true;
    try {
      const response = await api.cancel_run();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      updateControls(response.status || "stopping");
    } catch (error) {
      showError("runtime_error", "Cancel request could not be sent.");
    }
  }

  async function selectWorkspace() {
    clearError();
    const api = backendApi();
    if (!api) {
      showError("gui_dependency_missing", "Desktop bridge is not available.");
      return;
    }
    try {
      const response = await api.select_workspace();
      if (!response || !response.ok) {
        renderBackendError(response);
        return;
      }
      if (response.workspace) {
        ui.workspace.value = response.workspace;
        updateFooterLabels();
      }
    } catch (error) {
      showError("runtime_error", "Workspace picker could not be opened.");
    }
  }

  function toggleKeyVisibility() {
    const visible = ui.apiKey.type === "text";
    ui.apiKey.type = visible ? "password" : "text";
    ui.toggleKey.textContent = visible ? "Show" : "Hide";
    ui.toggleKey.setAttribute("aria-pressed", visible ? "false" : "true");
  }

  function renderSnapshot(snapshot) {
    const status = stringValue(snapshot.status, "unknown");
    setText(ui.runStatus, status);
    setText(ui.summaryStatus, titleCase(status));
    setText(ui.modelCalls, numberValue(snapshot.model_calls));
    setText(ui.toolCalls, numberValue(snapshot.tool_calls));
    setText(ui.lastSequence, numberValue(snapshot.last_sequence));
    setText(ui.verificationStatus, stringValue(snapshot.verification_status, "not run"));
    setText(
      ui.verificationSummary,
      stringValue(snapshot.verification_summary, "No verification summary yet.")
    );
    setText(ui.runIdLabel, stringValue(snapshot.run_id, "not started"));
    updateStatusDot(status);
    if (snapshot.final_result) {
      setText(ui.finalResult, snapshot.final_result);
    } else if (snapshot.terminal && status !== "completed") {
      setText(ui.finalResult, "No final result was produced.");
    }
    if (snapshot.error_code || snapshot.error_message) {
      showError(
        stringValue(snapshot.error_code, "runtime_error"),
        stringValue(snapshot.error_message, "PaperClaw runtime failed.")
      );
    } else if (!ACTIVE_STATUSES.has(status)) {
      clearError();
    }
    updateControls(status);
  }

  function updateStatusDot(status) {
    if (!ui.statusDot) {
      return;
    }
    ui.statusDot.classList.remove("connected");
    if (status === "completed" || status === "running") {
      ui.statusDot.classList.add("connected");
    }
  }

  function appendTimelineRow(row) {
    const item = document.createElement("li");
    const sequence = document.createElement("span");
    const label = document.createElement("span");
    sequence.className = "timeline-sequence";
    sequence.textContent = `#${numberValue(row.sequence)}`;
    label.textContent = stringValue(row.label, stringValue(row.event_type, "event"));
    item.append(sequence, label);
    ui.timeline.append(item);
    while (ui.timeline.children.length > MAX_TIMELINE_ROWS) {
      ui.timeline.firstElementChild.remove();
    }
    ui.timeline.scrollTop = ui.timeline.scrollHeight;
  }

  function updateControls(status) {
    const active = ACTIVE_STATUSES.has(status) || frontendSubmitting;
    ui.runButton.disabled = active;
    ui.cancelButton.disabled = !active || status === "stopping";
    for (const field of [
      ui.provider,
      ui.baseUrl,
      ui.model,
      ui.workspace,
      ui.verificationEnabled,
      ui.maxSteps,
      ui.maxModelCalls,
      ui.maxToolCalls,
      ui.selectWorkspace
    ]) {
      field.disabled = active;
    }
    setText(ui.summaryStatus, titleCase(status));
  }

  function renderBackendError(response) {
    showError(
      response && response.error_code ? response.error_code : "runtime_error",
      response && response.error_message
        ? response.error_message
        : "Desktop operation failed."
    );
  }

  function showError(code, message) {
    ui.publicError.hidden = false;
    ui.publicError.textContent = `${stringValue(code, "runtime_error")}: ${stringValue(
      message,
      "Desktop operation failed."
    )}`;
  }

  function clearError() {
    ui.publicError.hidden = true;
    ui.publicError.textContent = "";
  }

  function setText(element, value) {
    element.textContent = String(value);
  }

  function stringValue(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") {
      return fallback;
    }
    return String(value);
  }

  function numberValue(value) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.floor(number) : 0;
  }

  function boundedInteger(value, fallback) {
    const number = Number(value);
    if (!Number.isInteger(number) || number < 1 || number > 1000) {
      return fallback;
    }
    return number;
  }

  function titleCase(value) {
    const text = stringValue(value, "idle");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  document.addEventListener("DOMContentLoaded", bindDom, { once: true });
  window.addEventListener("pywebviewready", markBridgeReady, { once: true });
})();
