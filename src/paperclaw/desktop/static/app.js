(() => {
  "use strict";

  const MAX_TIMELINE_ROWS = 300;
  const POLL_INTERVAL_MS = 300;
  const ACTIVE_STATUSES = new Set(["starting", "running", "stopping"]);

  const ui = {};
  let domReady = false;
  let bridgeReady = false;
  let pollInFlight = false;
  let pollTimer = null;
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
    ui.task = byId("task");
    ui.runButton = byId("run-button");
    ui.cancelButton = byId("cancel-button");
    ui.runStatus = byId("run-status");
    ui.modelCalls = byId("model-calls");
    ui.toolCalls = byId("tool-calls");
    ui.lastSequence = byId("last-sequence");
    ui.verificationStatus = byId("verification-status");
    ui.verificationSummary = byId("verification-summary");
    ui.timeline = byId("timeline");
    ui.clearTimeline = byId("clear-timeline");
    ui.finalResult = byId("final-result");
    ui.publicError = byId("public-error");

    ui.toggleKey.addEventListener("click", toggleKeyVisibility);
    ui.runButton.addEventListener("click", startRun);
    ui.cancelButton.addEventListener("click", cancelRun);
    ui.selectWorkspace.addEventListener("click", selectWorkspace);
    ui.clearTimeline.addEventListener("click", () => ui.timeline.replaceChildren());

    maybeInitialize();
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
      enable_verification_gate: ui.verificationEnabled.checked
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
    setText(ui.modelCalls, numberValue(snapshot.model_calls));
    setText(ui.toolCalls, numberValue(snapshot.tool_calls));
    setText(ui.lastSequence, numberValue(snapshot.last_sequence));
    setText(ui.verificationStatus, stringValue(snapshot.verification_status, "not run"));
    setText(
      ui.verificationSummary,
      stringValue(snapshot.verification_summary, "No verification summary yet.")
    );
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
      ui.selectWorkspace
    ]) {
      field.disabled = active;
    }
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

  document.addEventListener("DOMContentLoaded", bindDom, { once: true });
  window.addEventListener("pywebviewready", markBridgeReady, { once: true });
})();
