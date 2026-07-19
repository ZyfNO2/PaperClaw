(() => {
  "use strict";

  const browserToken = readBrowserToken();
  const httpApi = browserToken ? createHttpApi(browserToken) : null;
  const ui = {};
  let ready = false;
  let activeTab = "overview";
  let currentArtifact = null;

  function readBrowserToken() {
    try {
      if (!window.location.hash) return "";
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
      const value = await response.json();
      if (!value || typeof value !== "object") throw new Error("Invalid product response");
      return value;
    }
    return {
      get_product_overview: (workspace) => invoke("get_product_overview", [workspace]),
      get_capabilities: (maturity, surface) => invoke("get_capabilities", [maturity, surface]),
      get_project_status: (workspace) => invoke("get_project_status", [workspace]),
      refresh_project_index: (workspace) => invoke("refresh_project_index", [workspace]),
      list_artifacts: (workspace, filters) => invoke("list_artifacts", [workspace, filters]),
      get_artifact: (workspace, artifactId) => invoke("get_artifact", [workspace, artifactId]),
      export_artifact: (workspace, artifactId, relativePath, revisionNumber, overwrite) =>
        invoke("export_artifact", [workspace, artifactId, relativePath, revisionNumber, overwrite])
    };
  }

  function backend() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return httpApi;
  }

  function bind() {
    if (ready) return;
    ready = true;
    for (const id of [
      "product-nav", "product-badge", "open-product", "product-panel", "close-product",
      "product-status", "product-overview", "capability-list", "project-details",
      "artifact-list", "artifact-detail", "reload-project", "refresh-project-index",
      "reload-artifacts"
    ]) ui[toCamel(id)] = document.getElementById(id);
    if (!ui.productPanel) return;

    ui.productNav.addEventListener("click", () => openPanel("overview"));
    ui.openProduct.addEventListener("click", () => openPanel("overview"));
    ui.closeProduct.addEventListener("click", closePanel);
    ui.productPanel.addEventListener("click", (event) => {
      if (event.target === ui.productPanel) closePanel();
    });
    for (const button of ui.productPanel.querySelectorAll("[data-product-tab]")) {
      button.addEventListener("click", () => selectTab(button.dataset.productTab || "overview"));
    }
    ui.reloadProject.addEventListener("click", loadProject);
    ui.refreshProjectIndex.addEventListener("click", refreshProject);
    ui.reloadArtifacts.addEventListener("click", loadArtifacts);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !ui.productPanel.hidden) closePanel();
    });
  }

  function toCamel(value) {
    return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  }

  function workspace() {
    const value = document.getElementById("workspace-path");
    const text = value ? value.textContent.trim() : "";
    if (!text || text === "Waiting for desktop bridge" || text === "not selected") return "";
    return text;
  }

  async function openPanel(tab) {
    ui.productPanel.hidden = false;
    selectTab(tab);
    await loadOverview();
  }

  function closePanel() {
    ui.productPanel.hidden = true;
    currentArtifact = null;
  }

  function selectTab(tab) {
    activeTab = tab;
    for (const button of ui.productPanel.querySelectorAll("[data-product-tab]")) {
      button.classList.toggle("active", button.dataset.productTab === tab);
    }
    for (const pane of ui.productPanel.querySelectorAll("[data-product-pane]")) {
      pane.hidden = pane.dataset.productPane !== tab;
    }
    if (tab === "capabilities") loadCapabilities();
    else if (tab === "project") loadProject();
    else if (tab === "artifacts") loadArtifacts();
  }

  async function loadOverview() {
    const root = workspace();
    if (!root) {
      status("Select a workspace before opening product foundations.", true);
      renderEmpty(ui.productOverview, "No workspace selected.");
      return;
    }
    const api = backend();
    if (!api || typeof api.get_product_overview !== "function") {
      status("Desktop product bridge is unavailable.", true);
      return;
    }
    status("Loading product overview…");
    try {
      const response = await api.get_product_overview(root);
      if (!ok(response)) return;
      const overview = response.overview || {};
      ui.productOverview.replaceChildren(
        stat("Project", nested(overview, ["project", "state"], "absent")),
        stat("Artifacts", number(overview.artifact_count)),
        stat("Capabilities", number(overview.capability_count)),
        stat("Foundation", number(nested(overview, ["capability_maturity", "foundation"], 0)))
      );
      ui.productBadge.textContent = String(number(overview.artifact_count));
      status(`Workspace product state loaded · ${root}`);
    } catch (_error) {
      status("Product overview could not be loaded.", true);
    }
  }

  async function loadCapabilities() {
    const api = backend();
    if (!api || typeof api.get_capabilities !== "function") return;
    status("Loading capability catalog…");
    try {
      const response = await api.get_capabilities(null, null);
      if (!ok(response)) return;
      const values = nested(response, ["catalog", "capabilities"], []);
      ui.capabilityList.replaceChildren(...values.map(renderCapability));
      status(`${values.length} capability records loaded.`);
    } catch (_error) {
      status("Capability catalog could not be loaded.", true);
    }
  }

  async function loadProject() {
    const root = workspace();
    if (!root) return status("Select a workspace first.", true);
    const api = backend();
    if (!api || typeof api.get_project_status !== "function") return;
    status("Loading project status…");
    try {
      const response = await api.get_project_status(root);
      if (!ok(response)) return;
      renderProject(response.project || {});
      status(`Project state: ${text(nested(response, ["project", "state"], "unknown"))}`);
    } catch (_error) {
      status("Project status could not be loaded.", true);
    }
  }

  async function refreshProject() {
    const root = workspace();
    if (!root) return status("Select a workspace first.", true);
    const api = backend();
    if (!api || typeof api.refresh_project_index !== "function") return;
    ui.refreshProjectIndex.disabled = true;
    status("Refreshing project knowledge index…");
    try {
      const response = await api.refresh_project_index(root);
      if (!ok(response)) return;
      status(response.rebuilt ? "Project knowledge index rebuilt." : "Project knowledge index is already current.");
      await loadProject();
      await loadOverview();
    } catch (_error) {
      status("Project knowledge refresh failed.", true);
    } finally {
      ui.refreshProjectIndex.disabled = false;
    }
  }

  async function loadArtifacts() {
    const root = workspace();
    if (!root) return status("Select a workspace first.", true);
    const api = backend();
    if (!api || typeof api.list_artifacts !== "function") return;
    status("Loading artifacts…");
    try {
      const response = await api.list_artifacts(root, {limit: 50});
      if (!ok(response)) return;
      const values = response.artifacts || [];
      if (!values.length) renderEmpty(ui.artifactList, "No product artifacts in this workspace.");
      else ui.artifactList.replaceChildren(...values.map(renderArtifactButton));
      ui.productBadge.textContent = String(number(response.count));
      status(`${number(response.count)} artifacts loaded.`);
    } catch (_error) {
      status("Artifacts could not be loaded.", true);
    }
  }

  async function loadArtifact(artifactId) {
    const root = workspace();
    const api = backend();
    if (!root || !api || typeof api.get_artifact !== "function") return;
    status(`Loading ${artifactId}…`);
    try {
      const response = await api.get_artifact(root, artifactId);
      if (!ok(response)) return;
      currentArtifact = response.bundle;
      renderArtifactDetail(response.bundle);
      status(`Artifact ${artifactId} loaded.`);
    } catch (_error) {
      status("Artifact detail could not be loaded.", true);
    }
  }

  async function exportLatest() {
    if (!currentArtifact || !currentArtifact.artifact) return;
    const root = workspace();
    const api = backend();
    if (!root || !api || typeof api.export_artifact !== "function") return;
    const artifactId = currentArtifact.artifact.artifact_id;
    status(`Exporting ${artifactId}…`);
    try {
      const response = await api.export_artifact(root, artifactId, null, null, false);
      if (!ok(response)) return;
      status(`Exported: ${response.workspace_relative_path}`);
    } catch (_error) {
      status("Artifact export failed.", true);
    }
  }

  function renderCapability(item) {
    const row = element("article", "product-row");
    row.append(
      element("strong", "", `${text(item.capability_id)} · ${text(item.maturity)}`),
      element("p", "", text(item.summary)),
      element("code", "", `${text(item.introduced_version)} · ${(item.surfaces || []).join(", ")}`)
    );
    for (const limit of item.limitations || []) row.append(element("p", "", `Limit: ${text(limit)}`));
    return row;
  }

  function renderProject(project) {
    const manifest = project.manifest || {};
    const validation = project.validation || {};
    const index = project.index || {};
    ui.projectDetails.replaceChildren(
      keyValues([
        ["State", project.state || "unknown"],
        ["Name", manifest.name || "—"],
        ["Project ID", manifest.project_id || "—"],
        ["Knowledge paths", (manifest.knowledge_paths || []).join(", ") || "—"],
        ["Skills", (manifest.enabled_skills || []).join(", ") || "—"],
        ["Connectors", (manifest.enabled_connectors || []).join(", ") || "—"],
        ["Validation", validation.ok === true ? "valid" : validation.ok === false ? "invalid" : "—"],
        ["Index", index.reason || "—"],
        ["Current", index.current === true ? "yes" : index.current === false ? "no" : "—"]
      ])
    );
  }

  function renderArtifactButton(item) {
    const button = element("button", "artifact-row");
    button.type = "button";
    button.append(
      element("strong", "", text(item.title)),
      element("span", "tiny", `${text(item.artifact_type)} · r${number(item.latest_revision_number)} · ${text(item.artifact_id)}`)
    );
    button.addEventListener("click", () => loadArtifact(item.artifact_id));
    return button;
  }

  function renderArtifactDetail(bundle) {
    const artifact = bundle.artifact || {};
    const revisions = bundle.revisions || [];
    const header = keyValues([
      ["Title", artifact.title || "—"],
      ["Artifact ID", artifact.artifact_id || "—"],
      ["Type", artifact.artifact_type || "—"],
      ["Project", nested(artifact, ["source", "project_id"], "—")],
      ["Run", nested(artifact, ["source", "run_id"], "—")],
      ["Task", nested(artifact, ["source", "task_id"], "—")],
      ["Trace", nested(artifact, ["source", "trace_id"], "—")]
    ]);
    const exportButton = element("button", "btn primary", "EXPORT LATEST");
    exportButton.type = "button";
    exportButton.addEventListener("click", exportLatest);
    const revisionList = element("div", "product-list");
    for (const revision of revisions) {
      const row = element("div", "revision-row");
      row.append(
        element("strong", "", `r${number(revision.revision_number)}`),
        element("code", "", `${text(revision.media_type)} · ${number(revision.byte_length)} bytes · ${text(revision.content_hash).slice(0, 12)}`),
        element("span", "tiny", text(revision.message || ""))
      );
      revisionList.append(row);
    }
    ui.artifactDetail.replaceChildren(header, exportButton, revisionList);
  }

  function keyValues(rows) {
    const list = element("dl", "product-kv");
    for (const [key, value] of rows) {
      list.append(element("dt", "", key), element("dd", "", text(value)));
    }
    return list;
  }

  function stat(label, value) {
    const item = element("div", "product-stat");
    item.append(element("strong", "", text(value)), element("span", "", label));
    return item;
  }

  function renderEmpty(target, message) {
    target.replaceChildren(element("p", "tiny", message));
  }

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = text(value);
    return node;
  }

  function status(message, isError = false) {
    ui.productStatus.textContent = message;
    ui.productStatus.dataset.state = isError ? "error" : "ok";
  }

  function ok(response) {
    if (response && response.ok) return true;
    status(
      response && response.error_message ? response.error_message : "Product operation failed.",
      true
    );
    return false;
  }

  function nested(value, path, fallback) {
    let current = value;
    for (const key of path) {
      if (!current || typeof current !== "object" || !(key in current)) return fallback;
      current = current[key];
    }
    return current === null || current === undefined ? fallback : current;
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0;
  }

  function text(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  document.addEventListener("DOMContentLoaded", bind);
  window.addEventListener("pywebviewready", bind);
})();
