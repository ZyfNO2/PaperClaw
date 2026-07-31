(() => {
  "use strict";

  const REQUEST_TIMEOUT_MS = 10000;
  const bootstrap = readBootstrap();
  const diagnostics = { activeRequests: 0, lastErrorCode: null, lastSuccessAt: null };

  function publicError(code, message) {
    return {
      ok: false,
      error_code: String(code || "runtime_error"),
      error_message: String(message || "PaperClaw operation failed.")
    };
  }

  function readBootstrap() {
    const result = { token: "", theme: "" };
    try {
      const values = new URLSearchParams(window.location.hash.slice(1));
      result.token = values.get("token") || "";
      result.theme = values.get("theme") || "";
      if (result.token || result.theme) {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      }
    } catch (_error) {
      return result;
    }
    return result;
  }

  async function invokeHttp(method, args) {
    if (!bootstrap.token) return publicError("permission_denied", "Browser bridge token is missing.");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    diagnostics.activeRequests += 1;
    try {
      const response = await window.fetch(`/api/${method}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-PaperClaw-Token": bootstrap.token
        },
        body: JSON.stringify({ args }),
        signal: controller.signal
      });
      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        return publicError("invalid_response", "Browser bridge returned invalid JSON.");
      }
      if (!payload || typeof payload !== "object" || typeof payload.ok !== "boolean") {
        return publicError("invalid_response", "Browser bridge response is incomplete.");
      }
      if (!payload.ok) diagnostics.lastErrorCode = payload.error_code || "runtime_error";
      else {
        diagnostics.lastErrorCode = null;
        diagnostics.lastSuccessAt = new Date().toISOString();
      }
      return payload;
    } catch (error) {
      const timedOut = error && error.name === "AbortError";
      const code = timedOut ? "timeout" : "connection_error";
      diagnostics.lastErrorCode = code;
      return publicError(code, timedOut
        ? "Browser bridge request timed out."
        : "Browser bridge is unavailable.");
    } finally {
      window.clearTimeout(timeout);
      diagnostics.activeRequests -= 1;
    }
  }

  function invokeDesktop(method, args) {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge || typeof bridge[method] !== "function") {
      return Promise.resolve(publicError("bridge_method_missing", "Desktop bridge method is unavailable."));
    }
    try {
      return Promise.resolve(bridge[method](...args)).then((payload) => {
        if (!payload || typeof payload !== "object" || typeof payload.ok !== "boolean") {
          return publicError("invalid_response", "Desktop bridge response is incomplete.");
        }
        return payload;
      }, () => publicError("runtime_error", "Desktop bridge operation failed."));
    } catch (_error) {
      return Promise.resolve(publicError("runtime_error", "Desktop bridge operation failed."));
    }
  }

  function invoke(method, args) {
    return window.pywebview && window.pywebview.api
      ? invokeDesktop(method, args)
      : invokeHttp(method, args);
  }

  const api = {
    get_defaults: () => invoke("get_defaults", []),
    get_state: () => invoke("get_state", []),
    start_run: (request) => invoke("start_run", [request]),
    cancel_run: () => invoke("cancel_run", []),
    poll_events: (limit, clientId) => invoke("poll_events", [limit, clientId]),
    select_workspace: () => invoke("select_workspace", []),
    select_paper_source: () => invoke("select_paper_source", []),
    set_theme: (theme) => invoke("set_theme", [theme]),
    open_in_browser: (theme) => invoke("open_in_browser", [theme]),
    connect_provider: (request) => invoke("connect_provider", [request]),
    select_provider_model: (model, allowUnlisted) => invoke("select_provider_model", [model, allowUnlisted]),
    clear_provider_config: () => invoke("clear_provider_config", []),
    clear_manual_provider: () => invoke("clear_manual_provider", []),
    get_product_overview: (workspace) => invoke("get_product_overview", [workspace]),
    get_capabilities: (maturity, surface) => invoke("get_capabilities", [maturity, surface]),
    get_project_status: (workspace) => invoke("get_project_status", [workspace]),
    refresh_project_index: (workspace) => invoke("refresh_project_index", [workspace]),
    list_artifacts: (workspace, filters) => invoke("list_artifacts", [workspace, filters]),
    get_artifact: (workspace, artifactId) => invoke("get_artifact", [workspace, artifactId]),
    export_artifact: (workspace, artifactId, relativePath, revisionNumber, overwrite) =>
      invoke("export_artifact", [workspace, artifactId, relativePath, revisionNumber, overwrite]),
    import_paper: (workspace, sourcePath, paperId) => invoke("import_paper", [workspace, sourcePath, paperId]),
    list_papers: (workspace, limit) => invoke("list_papers", [workspace, limit]),
    get_paper: (workspace, paperId) => invoke("get_paper", [workspace, paperId]),
    list_paper_versions: (workspace, paperId) => invoke("list_paper_versions", [workspace, paperId]),
    confirm_paper_metadata: (workspace, paperId, patch, revision) =>
      invoke("confirm_paper_metadata", [workspace, paperId, patch, revision])
  };

  window.PaperClawBackend = {
    api,
    bootstrap,
    mode: () => window.pywebview && window.pywebview.api ? "desktop" : "browser",
    diagnostics: () => ({ ...diagnostics })
  };
})();
