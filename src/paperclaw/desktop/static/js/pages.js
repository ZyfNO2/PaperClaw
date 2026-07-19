/* PaperClaw Pages
   Renderers and interactions for the mock-driven workbench pages. All DOM
   is built with createElement/textContent; nothing here talks to the Python
   bridge. The Console page stays live (app.js) and is not rendered here.
*/
(() => {
  "use strict";

  const rendered = new Set();
  const sim = { timer: null, durationTimer: null, paused: false };
  const ui = { artifactView: "list", artifactQuery: "", artifactType: "all", runStatus: "all", runRange: "all", runQuery: "", capCategory: "all", capQuery: "", missionFilter: "all", selectedMissionId: null };

  function mock() { return window.PaperClawMock; }
  function shell() { return window.PaperClawShell; }
  function el(tag, className, text) { return shell().el(tag, className, text); }
  function t(key) {
    if (window.PaperClawI18n && window.PaperClawI18n.t) return window.PaperClawI18n.t(key);
    return key;
  }

  /* ======== Shared atoms ======== */
  function statusBadge(status, label) {
    const badge = el("span", "status-badge", (label || status).toUpperCase());
    badge.dataset.status = status;
    return badge;
  }

  function statusDot(status) {
    const dot = el("span", "status-dot");
    dot.dataset.status = status;
    return dot;
  }

  function riskBadge(risk) {
    const tone = risk === "high" ? "danger" : risk === "medium" ? "warning" : "success";
    const badge = el("span", "badge", `${risk.toUpperCase()} RISK`);
    badge.dataset.tone = tone;
    return badge;
  }

  function typeBadge(type, label) {
    const badge = el("span", "badge", label || type.toUpperCase());
    badge.dataset.tone = type === "Tool" ? "tool" : type === "Connector" ? "info" : type === "Skill" ? "success" : "primary";
    return badge;
  }

  function panelCard(titleText, actionsNode) {
    const card = el("div", "card");
    const head = el("div", "panel-head");
    head.append(el("h2", "panel-title", titleText));
    if (actionsNode) head.append(actionsNode);
    card.append(head);
    return card;
  }

  function emptyState(title, desc, actionLabel, onAction) {
    const block = el("div", "state-block");
    block.append(el("div", "state-glyph", "◌"));
    block.append(el("div", "state-title", title));
    if (desc) block.append(el("p", "state-desc", desc));
    if (actionLabel && onAction) {
      const btn = el("button", "btn", actionLabel);
      btn.type = "button";
      btn.addEventListener("click", onAction);
      block.append(btn);
    }
    return block;
  }

  function errorState(title, desc, onRetry) {
    const block = el("div", "state-block");
    block.dataset.tone = "error";
    block.append(el("div", "state-glyph", "✕"));
    block.append(el("div", "state-title", title));
    if (desc) block.append(el("p", "state-desc", desc));
    if (onRetry) {
      const btn = el("button", "btn", t("state.retry"));
      btn.type = "button";
      btn.addEventListener("click", onRetry);
      block.append(btn);
    }
    return block;
  }

  function skeletonRows(count) {
    const stack = el("div", "skeleton-stack");
    for (let i = 0; i < count; i += 1) stack.append(el("div", "skeleton row"));
    return stack;
  }

  function demoGate(root, renderFn) {
    if (shell().isDemo()) { renderFn(); return; }
    root.append(emptyState(
      t("demo.off.title"),
      t("demo.off.desc"),
      t("demo.off.action"),
      () => shell().setPref("demoMode", true)
    ));
  }

  function kv(rows) {
    const list = el("dl", "kv");
    for (const [key, value] of rows) {
      const row = el("div", "kv-row");
      row.append(el("dt", "kv-key", key));
      const dd = el("dd", "kv-value");
      if (value instanceof Node) dd.append(value);
      else dd.textContent = value == null || value === "" ? "—" : String(value);
      row.append(dd);
      list.append(row);
    }
    return list;
  }

  function progressBar(percent, tone) {
    const track = el("div", "progress-track");
    const seg = el("div", "progress-seg");
    seg.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    if (tone) seg.dataset.tone = tone;
    track.append(seg);
    return track;
  }

  function fmtAgo(iso) { return shell().fmtAgo(iso); }
  function fmtBytes(b) { return shell().fmtBytes(b); }
  function fmtDuration(s) { return shell().fmtDuration(s); }
  function fmtDateTime(iso) { return shell().fmtDateTime(iso); }
  function fmtTime(iso) { return shell().fmtTime(iso); }

  /* ======== OVERVIEW ======== */
  function renderOverview() {
    const root = document.getElementById("overview-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const running = data.missions.find((m) => m.id === data.runningMissionId);
      const counts = { succeeded: 0, failed: 0, cancelled: 0 };
      for (const m of data.missions) if (counts[m.status] !== undefined) counts[m.status] += 1;
      const online = data.providers.filter((p) => p.status === "online").length;
      const runtimeStatus = (document.getElementById("run-status") || {}).textContent || "IDLE";

      const stats = el("div", "stat-grid");
      stats.append(
        statCard(t("ov.runtime"), runtimeStatus.toUpperCase(), `v0.30 · sqlite`, runtimeStatus.toLowerCase() === "running" ? "running" : "idle"),
        statCard(t("ov.agent"), running ? "ACTIVE" : "IDLE", running ? running.currentStep : "—", running ? "running" : "idle"),
        statCard(t("ov.providers"), `${online} / ${data.providers.length}`, t("ov.providers.online"), online === data.providers.length ? "ready" : "degraded"),
        statCard(t("ov.capabilities"), String(data.capabilities.filter((c) => c.enabled).length), `${data.capabilities.length} ${t("ov.capabilities.total")}`, "ready")
      );
      root.append(stats);

      const stats2 = el("div", "stat-grid");
      stats2.append(
        statCard(t("ov.succeeded"), String(counts.succeeded), t("ov.runs.hint"), "succeeded"),
        statCard(t("ov.failed"), String(counts.failed), t("ov.runs.hint"), "failed"),
        statCard(t("ov.cancelled"), String(counts.cancelled), t("ov.runs.hint"), "cancelled"),
        statCard(t("ov.artifacts"), String(data.artifacts.length), t("ov.artifacts.hint"), "ready")
      );
      root.append(stats2);

      if (running) {
        const missionCard = panelCard(t("ov.current.mission"), statusBadge(running.status));
        const body = el("div", "panel-body");
        body.append(el("div", "mission-name", running.name));
        const facts = el("div", "mission-facts");
        facts.append(
          el("span", "", running.id),
          el("span", "", `${running.provider} / ${running.model}`),
          el("span", "", `${t("ov.step")} ${running.stepsDone}/${running.stepsTotal}`)
        );
        body.append(facts);
        body.append(el("div", "step-current", running.currentStep));
        body.append(progressBar(running.progress));
        const openBtn = el("button", "btn sm", t("ov.open.missions"));
        openBtn.type = "button";
        openBtn.addEventListener("click", () => { ui.selectedMissionId = running.id; shell().showPage("missions"); });
        body.append(openBtn);
        missionCard.append(body);
        root.append(missionCard);
      }

      const grid = el("div", "overview-grid");

      const projectCard = panelCard(t("ov.project"));
      const projectBody = el("div", "panel-body");
      const titleRow = el("div", "project-title-row");
      titleRow.append(el("span", "project-name", data.project.name));
      titleRow.append(statusBadge(data.project.status));
      const branch = el("span", "badge", `⎇ ${data.project.branch}`);
      branch.dataset.tone = "primary";
      titleRow.append(branch);
      projectBody.append(titleRow);
      projectBody.append(el("p", "project-desc", data.project.description));
      const pfacts = el("div", "project-facts");
      pfacts.append(el("span", "", data.project.path), el("span", "", `${t("ov.indexed")} ${fmtAgo(data.project.lastIndexed)}`));
      projectBody.append(pfacts);
      const actions = el("div", "quick-actions");
      const openProject = el("button", "btn", t("ov.open.project"));
      openProject.type = "button";
      openProject.addEventListener("click", () => shell().showPage("project"));
      const openConsole = el("button", "btn", t("ov.open.console"));
      openConsole.type = "button";
      openConsole.addEventListener("click", () => shell().showPage("console"));
      const openArtifacts = el("button", "btn", t("ov.open.artifacts"));
      openArtifacts.type = "button";
      openArtifacts.addEventListener("click", () => shell().showPage("artifacts"));
      actions.append(openProject, openConsole, openArtifacts);
      projectBody.append(actions);
      projectCard.append(projectBody);
      grid.append(projectCard);

      const recentCard = panelCard(t("ov.recent.runs"));
      const rows = el("div", "list-rows");
      for (const run of data.runs.slice(0, 4)) {
        const row = el("div", "list-row clickable");
        row.append(statusDot(run.status));
        const main = el("div", "list-main");
        main.append(el("div", "list-title", run.mission));
        main.append(el("div", "list-meta", `${run.id} · ${fmtDuration(run.durationSec)} · ${fmtAgo(run.startedAt)}`));
        row.append(main, statusBadge(run.status));
        row.addEventListener("click", () => shell().showPage("runs"));
        rows.append(row);
      }
      recentCard.append(rows);
      grid.append(recentCard);
      root.append(grid);

      const grid2 = el("div", "overview-grid");
      const errorsCard = panelCard(t("ov.recent.errors"));
      const errorRows = el("div", "list-rows");
      const failedMissions = data.missions.filter((m) => m.error).slice(0, 3);
      if (!failedMissions.length) errorRows.append(emptyState(t("ov.no.errors"), null));
      for (const m of failedMissions) {
        const row = el("div", "list-row clickable");
        row.append(statusDot("failed"));
        const main = el("div", "list-main");
        main.append(el("div", "list-title", m.name));
        main.append(el("div", "list-meta", m.error));
        row.append(main);
        row.addEventListener("click", () => { ui.selectedMissionId = m.id; shell().showPage("missions"); });
        errorRows.append(row);
      }
      errorsCard.append(errorRows);
      grid2.append(errorsCard);

      const logsCard = panelCard(t("ov.runtime.logs"));
      const logRows = el("div", "list-rows");
      for (const entry of data.runtimeLogs.slice(0, shell().pref("logLimit") || 6)) {
        const row = el("div", "list-row");
        const level = el("span", "badge", entry.level.toUpperCase());
        level.dataset.tone = entry.level === "error" ? "danger" : entry.level === "warn" ? "warning" : "info";
        row.append(level);
        const main = el("div", "list-main");
        main.append(el("div", "list-meta", entry.message));
        row.append(main, el("span", "event-time", fmtTime(entry.at)));
        logRows.append(row);
      }
      logsCard.append(logRows);
      grid2.append(logsCard);
      root.append(grid2);
    });
  }

  function statCard(label, value, meta, status) {
    const card = el("div", "stat-card");
    card.append(el("span", "stat-label", label));
    const valueRow = el("div", "stat-row");
    if (status) valueRow.append(statusDot(status));
    valueRow.append(el("strong", "stat-value", value));
    card.append(valueRow);
    if (meta) card.append(el("span", "stat-meta", meta));
    return card;
  }

  /* ======== MISSIONS ======== */
  function renderMissions() {
    const root = document.getElementById("missions-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const selected = data.missions.find((m) => m.id === (ui.selectedMissionId || data.runningMissionId)) || data.missions[0];
      ui.selectedMissionId = selected.id;

      const head = el("div", "page-head");
      const filters = el("div", "filters");
      for (const status of ["all", "queued", "running", "waiting", "succeeded", "failed", "cancelled"]) {
        const chip = el("button", `chip${ui.missionFilter === status ? " active" : ""}`, t(`filter.${status}`));
        chip.type = "button";
        chip.addEventListener("click", () => { ui.missionFilter = status; renderMissions(); });
        filters.append(chip);
      }
      head.append(filters);
      const simBtn = el("button", "btn sm", sim.paused ? t("missions.resume") : t("missions.pause"));
      simBtn.type = "button";
      simBtn.addEventListener("click", () => { sim.paused = !sim.paused; simBtn.textContent = sim.paused ? t("missions.resume") : t("missions.pause"); });
      head.append(simBtn);
      root.append(head);

      const summary = panelCard(t("missions.summary"), statusBadge(selected.status));
      const summaryBody = el("div", "mission-summary-body");
      const main = el("div", "mission-summary-main");
      const titleRow = el("div", "mission-title-row");
      titleRow.append(el("span", "mission-name", selected.name));
      main.append(titleRow);
      const facts = el("div", "mission-facts");
      facts.append(
        el("span", "", `${t("missions.task")} ${selected.taskId}`),
        el("span", "", `${t("missions.started")} ${selected.startedAt ? fmtDateTime(selected.startedAt) : "—"}`),
        el("span", "", `${t("missions.provider")} ${selected.provider} / ${selected.model}`),
        el("span", "", `${t("missions.tools")} ${selected.toolCalls}`)
      );
      main.append(facts);
      main.append(el("div", "step-current", `${t("missions.step")} ${selected.stepsDone}/${selected.stepsTotal} · ${selected.currentStep}`));
      if (selected.error) {
        const err = el("div", "public-error");
        err.hidden = false;
        err.textContent = selected.error;
        main.append(err);
      }
      summaryBody.append(main);
      const side = el("div", "mission-summary-main");
      const durationLabel = el("div", "metric-label", t("missions.duration"));
      const durationValue = el("strong", "metric-value", fmtDuration(selected.durationSec));
      durationValue.id = "mission-duration-live";
      side.append(durationLabel, durationValue, progressBar(selected.progress, selected.status === "failed" ? "danger" : selected.status === "succeeded" ? "success" : undefined));
      summaryBody.append(side);
      summary.append(summaryBody);
      root.append(summary);

      const grid = el("div", "missions-grid");
      const listCard = panelCard(t("missions.list"));
      const scroll = el("div", "table-scroll");
      const table = el("table", "table table-clickable");
      const thead = el("thead");
      const headRow = el("tr");
      for (const col of [t("missions.col.id"), t("missions.col.name"), t("missions.col.status"), t("missions.col.progress"), t("missions.col.duration")]) {
        headRow.append(el("th", "", col));
      }
      thead.append(headRow);
      table.append(thead);
      const tbody = el("tbody");
      const visible = data.missions.filter((m) => ui.missionFilter === "all" || m.status === ui.missionFilter);
      if (!visible.length) {
        table.append(tbody);
        scroll.append(table);
        listCard.append(scroll, emptyState(t("missions.empty"), t("missions.empty.hint"), t("missions.clear.filter"), () => { ui.missionFilter = "all"; renderMissions(); }));
      } else {
        for (const m of visible) {
          const tr = el("tr");
          if (m.id === selected.id) tr.classList.add("selected");
          tr.append(el("td", "cell-sub", m.id));
          tr.append(el("td", "cell-main", m.name));
          const statusCell = el("td");
          statusCell.append(statusBadge(m.status));
          tr.append(statusCell);
          const progressCell = el("td");
          progressCell.append(progressBar(m.progress));
          tr.append(progressCell);
          tr.append(el("td", "num", fmtDuration(m.durationSec)));
          tr.addEventListener("click", () => { ui.selectedMissionId = m.id; renderMissions(); });
          tbody.append(tr);
        }
        table.append(tbody);
        scroll.append(table);
        listCard.append(scroll);
      }
      grid.append(listCard);

      const timelineCard = panelCard(t("missions.timeline"));
      const list = el("div", "timeline-list fixed-h");
      for (const event of timelineFor(selected)) {
        const row = el("div", "event-row clickable");
        row.append(el("span", "event-num", String(event.seq).padStart(2, "0")));
        const eventMain = el("div", "event-main");
        eventMain.append(el("div", "event-title", event.title));
        eventMain.append(el("div", "event-meta", event.label));
        row.append(eventMain);
        const right = el("div", "event-right");
        right.append(el("span", "event-time", fmtTime(event.at)));
        const dot = el("span", "event-dot");
        const dotClass = event.kind === "tool" ? "tool" : event.kind === "verify" ? "verify" : event.status === "running" ? "running" : event.status === "failed" ? "failed" : "";
        if (dotClass) dot.classList.add(dotClass);
        right.append(dot);
        row.append(right);
        row.addEventListener("click", () => openStepDetail(selected, event));
        list.append(row);
      }
      timelineCard.append(list);
      grid.append(timelineCard);
      root.append(grid);
    });
  }

  function timelineFor(mission) {
    const detailed = mock().timeline[mission.id];
    if (detailed) return detailed;
    const at = mission.startedAt || new Date().toISOString();
    const base = [
      { seq: 1, kind: "system", title: "mission.queued", label: t("missions.ev.queued"), at, status: "succeeded", agentAction: t("missions.ev.queued.action"), tool: null, result: mission.id, warning: null, error: null },
      { seq: 2, kind: "system", title: "mission.started", label: t("missions.ev.started"), at, status: "succeeded", agentAction: t("missions.ev.started.action"), tool: null, result: mission.taskId, warning: null, error: null }
    ];
    if (mission.status === "waiting") {
      base.push({ seq: 3, kind: "system", title: "mission.waiting", label: mission.currentStep, at, status: "waiting", agentAction: t("missions.ev.waiting.action"), tool: null, result: null, warning: t("missions.ev.waiting.warn"), error: null });
      return base;
    }
    base.push({ seq: 3, kind: "model", title: "model.completed", label: mission.currentStep, at, status: mission.status === "failed" ? "failed" : "succeeded", agentAction: t("missions.ev.model.action"), tool: null, result: `${mission.toolCalls} tool calls`, warning: null, error: mission.error });
    if (mission.status === "succeeded") base.push({ seq: 4, kind: "verify", title: "verification.completed", label: "verification=passed", at, status: "succeeded", agentAction: t("missions.ev.verify.action"), tool: null, result: `${mission.artifacts} artifacts`, warning: null, error: null });
    if (mission.status === "cancelled") base.push({ seq: 4, kind: "system", title: "mission.cancelled", label: t("missions.ev.cancelled"), at, status: "cancelled", agentAction: t("missions.ev.cancelled.action"), tool: null, result: null, warning: null, error: null });
    if (mission.status === "failed") base.push({ seq: 4, kind: "system", title: "mission.failed", label: t("missions.ev.failed"), at, status: "failed", agentAction: t("missions.ev.failed.action"), tool: null, result: null, warning: null, error: mission.error });
    return base;
  }

  function openStepDetail(mission, event) {
    const body = el("div");
    const headRow = el("div", "mission-title-row");
    headRow.append(statusBadge(event.status));
    headRow.append(el("span", "badge", event.kind.toUpperCase()));
    body.append(headRow);
    body.append(kv([
      [t("step.mission"), mission.name],
      [t("step.event"), event.title],
      [t("step.seq"), `#${event.seq}`],
      [t("step.time"), fmtDateTime(event.at)],
      [t("step.agent.action"), event.agentAction],
      [t("step.tool"), event.tool || "—"],
      [t("step.result"), event.result || "—"]
    ]));
    if (event.warning) body.append(callout("warning", event.warning));
    if (event.error) body.append(callout("danger", event.error));
    shell().openInspector(`${mission.id} · ${event.title}`, body);
  }

  function callout(tone, text) {
    const box = el("div", tone === "warning" ? "public-error warning" : "public-error");
    box.hidden = false;
    box.textContent = text;
    return box;
  }

  /* Mission simulator: advances the running mission while the app is open. */
  function startSimulator() {
    if (sim.timer) return;
    sim.timer = window.setInterval(() => {
      if (sim.paused || document.hidden) return;
      const data = mock();
      const running = data.missions.find((m) => m.id === data.runningMissionId);
      if (!running || running.status !== "running") return;
      running.durationSec += 4;
      if (running.progress < 96) running.progress = Math.min(96, running.progress + Math.ceil(Math.random() * 2));
      const durationEl = document.getElementById("mission-duration-live");
      if (durationEl && shell().currentPage() === "missions" && ui.selectedMissionId === running.id) {
        durationEl.textContent = fmtDuration(running.durationSec);
      }
    }, 4000);
  }

  /* ======== PROJECT ======== */
  function renderProject() {
    const root = document.getElementById("project-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const p = data.project;

      const headCard = el("div", "card");
      const headBody = el("div", "project-head-body");
      const titleRow = el("div", "project-title-row");
      titleRow.append(el("span", "project-name", p.name));
      titleRow.append(statusBadge(p.status));
      const branch = el("span", "badge", `⎇ ${p.branch}`);
      branch.dataset.tone = "primary";
      titleRow.append(branch);
      const index = el("span", "badge", p.indexState.toUpperCase());
      index.dataset.tone = "success";
      titleRow.append(index);
      headBody.append(titleRow);
      headBody.append(el("p", "project-desc", p.description));
      const facts = el("div", "project-facts");
      facts.append(
        el("span", "", p.path),
        el("span", "", `${t("project.last.indexed")} ${fmtAgo(p.lastIndexed)}`),
        el("span", "", `${t("project.tracked")} ${p.recentFiles.length}`)
      );
      headBody.append(facts);
      const actions = el("div", "quick-actions");
      const live = el("button", "btn primary", t("project.open.live"));
      live.type = "button";
      live.addEventListener("click", () => {
        const nav = document.getElementById("product-nav");
        if (nav) nav.click();
      });
      const refresh = el("button", "btn", t("project.refresh"));
      refresh.type = "button";
      refresh.addEventListener("click", () => shell().toast(t("project.refresh.toast")));
      const openConsole = el("button", "btn", t("ov.open.console"));
      openConsole.type = "button";
      openConsole.addEventListener("click", () => shell().showPage("console"));
      actions.append(live, refresh, openConsole);
      headBody.append(actions);
      headCard.append(headBody);
      root.append(headCard);

      const grid = el("div", "project-grid");
      const filesCard = panelCard(t("project.recent.files"));
      const fileRows = el("div", "list-rows");
      for (const file of p.recentFiles) {
        const row = el("div", "list-row");
        const main = el("div", "list-main");
        main.append(el("div", "list-title", file.name));
        main.append(el("div", "list-meta", file.path));
        row.append(main, el("span", "list-meta", `${fmtBytes(file.size)} · ${fmtAgo(file.modified)}`));
        fileRows.append(row);
      }
      filesCard.append(fileRows);
      grid.append(filesCard);

      const missionsCard = panelCard(t("project.recent.missions"));
      const missionRows = el("div", "list-rows");
      for (const m of data.missions.slice(0, 5)) {
        const row = el("div", "list-row clickable");
        row.append(statusDot(m.status));
        const main = el("div", "list-main");
        main.append(el("div", "list-title", m.name));
        main.append(el("div", "list-meta", `${m.id} · ${fmtAgo(m.startedAt)}`));
        row.append(main, statusBadge(m.status));
        row.addEventListener("click", () => { ui.selectedMissionId = m.id; shell().showPage("missions"); });
        missionRows.append(row);
      }
      missionsCard.append(missionRows);
      grid.append(missionsCard);

      const artifactsCard = panelCard(t("project.recent.artifacts"));
      const artifactRows = el("div", "list-rows");
      for (const a of data.artifacts.slice(0, 5)) {
        const row = el("div", "list-row clickable");
        const main = el("div", "list-main");
        main.append(el("div", "list-title", a.name));
        main.append(el("div", "list-meta", `${a.type} · ${fmtBytes(a.sizeBytes)} · ${fmtAgo(a.createdAt)}`));
        row.append(main);
        row.addEventListener("click", () => shell().showPage("artifacts"));
        artifactRows.append(row);
      }
      artifactsCard.append(artifactRows);
      grid.append(artifactsCard);
      root.append(grid);
    });
  }

  /* ======== CAPABILITIES ======== */
  function renderCapabilities() {
    const root = document.getElementById("capabilities-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const categories = ["all", ...new Set(data.capabilities.map((c) => c.category))];

      const head = el("div", "page-head");
      const tabs = el("div", "filters");
      for (const category of categories) {
        const chip = el("button", `chip${ui.capCategory === category ? " active" : ""}`, category === "all" ? t("filter.all") : category);
        chip.type = "button";
        chip.addEventListener("click", () => { ui.capCategory = category; renderCapabilities(); });
        tabs.append(chip);
      }
      head.append(tabs);
      const search = el("input", "input filter-search");
      search.type = "search";
      search.placeholder = t("cap.search");
      search.value = ui.capQuery;
      search.addEventListener("input", () => { ui.capQuery = search.value; renderCapabilities(); });
      head.append(search);
      root.append(head);

      const query = ui.capQuery.trim().toLowerCase();
      const visible = data.capabilities.filter((c) =>
        (ui.capCategory === "all" || c.category === ui.capCategory) &&
        (!query || c.name.toLowerCase().includes(query) || c.desc.toLowerCase().includes(query))
      );
      if (!visible.length) {
        root.append(emptyState(t("cap.empty"), t("cap.empty.hint"), t("cap.clear"), () => { ui.capCategory = "all"; ui.capQuery = ""; renderCapabilities(); }));
        return;
      }
      const grid = el("div", "cap-grid");
      for (const cap of visible) grid.append(capCard(cap));
      root.append(grid);
    });
  }

  function capCard(cap) {
    const card = el("div", "card cap-card");
    const head = el("div", "cap-head");
    const titleWrap = el("div");
    titleWrap.append(el("div", "cap-name", cap.name));
    const meta = el("div", "cap-meta");
    meta.append(el("span", "", cap.category), el("span", "", `${t("cap.source")} ${cap.source}`));
    titleWrap.append(meta);
    head.append(titleWrap, typeBadge(cap.type));
    card.append(head);
    card.append(el("p", "cap-desc", cap.desc));
    const statusRow = el("div", "stat-row");
    statusRow.append(statusDot(cap.status));
    statusRow.append(el("span", "tiny", `${cap.status} · ${t("cap.last.used")} ${fmtAgo(cap.lastUsed)}`));
    card.append(statusRow);
    const scopeRow = el("div", "cap-meta");
    for (const scope of cap.scope) scopeRow.append(el("span", "badge", scope));
    card.append(scopeRow);
    const foot = el("div", "cap-foot");
    foot.append(riskBadge(cap.risk));
    const toggle = el("label", "switch");
    const input = el("input");
    input.type = "checkbox";
    input.checked = cap.enabled;
    input.setAttribute("aria-label", `${cap.name} enabled`);
    const track = el("span", "switch-track");
    toggle.append(input, track);
    toggle.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", () => {
      cap.enabled = input.checked;
      shell().toast(`${cap.name} ${cap.enabled ? t("cap.enabled") : t("cap.disabled")}`);
    });
    foot.append(toggle);
    card.append(foot);
    card.addEventListener("click", () => openCapabilityDetail(cap));
    return card;
  }

  function openCapabilityDetail(cap) {
    const body = el("div");
    const row = el("div", "mission-title-row");
    row.append(typeBadge(cap.type), riskBadge(cap.risk));
    body.append(row);
    body.append(kv([
      [t("cap.name"), cap.name],
      [t("cap.category"), cap.category],
      [t("cap.status"), cap.status],
      [t("cap.source"), cap.source],
      [t("cap.last.used"), fmtAgo(cap.lastUsed)],
      [t("cap.scope"), cap.scope.join(", ")],
      [t("cap.desc"), cap.desc]
    ]));
    shell().openModal({
      title: cap.name,
      body,
      actions: [{ label: t("modal.close"), kind: "" }]
    });
  }

  /* ======== ARTIFACTS ======== */
  const ARTIFACT_TYPES = ["markdown", "json", "code", "csv", "image", "log"];

  function renderArtifacts(withSkeleton) {
    const root = document.getElementById("artifacts-root");
    root.replaceChildren();
    demoGate(root, () => {
      if (withSkeleton) {
        root.append(skeletonRows(6));
        window.setTimeout(() => renderArtifacts(false), 550);
        return;
      }
      const data = mock();
      const head = el("div", "page-head");
      const search = el("input", "input filter-search");
      search.type = "search";
      search.placeholder = t("art.search");
      search.value = ui.artifactQuery;
      search.addEventListener("input", () => { ui.artifactQuery = search.value; renderArtifacts(false); });

      const typeSelect = el("select", "select filter-select");
      const allOpt = el("option", "", t("art.type.all"));
      allOpt.value = "all";
      typeSelect.append(allOpt);
      for (const type of ARTIFACT_TYPES) {
        const opt = el("option", "", type.toUpperCase());
        opt.value = type;
        typeSelect.append(opt);
      }
      typeSelect.value = ui.artifactType;
      typeSelect.addEventListener("change", () => { ui.artifactType = typeSelect.value; renderArtifacts(false); });

      const toggleWrap = el("div", "segmented view-toggle");
      for (const view of ["list", "cards"]) {
        const seg = el("button", `segment${ui.artifactView === view ? " active" : ""}`, view === "list" ? t("art.view.list") : t("art.view.cards"));
        seg.type = "button";
        seg.addEventListener("click", () => { ui.artifactView = view; renderArtifacts(false); });
        toggleWrap.append(seg);
      }
      const reload = el("button", "btn sm", t("art.reload"));
      reload.type = "button";
      reload.addEventListener("click", () => renderArtifacts(true));

      const left = el("div", "toolbar-group");
      left.append(search, typeSelect);
      const right = el("div", "toolbar-group");
      right.append(toggleWrap, reload);
      head.append(left, right);
      root.append(head);

      const query = ui.artifactQuery.trim().toLowerCase();
      const visible = data.artifacts.filter((a) =>
        (ui.artifactType === "all" || a.type === ui.artifactType) &&
        (!query || a.name.toLowerCase().includes(query) || a.path.toLowerCase().includes(query))
      );
      if (!visible.length) {
        root.append(emptyState(t("art.empty"), t("art.empty.hint"), t("art.clear"), () => { ui.artifactQuery = ""; ui.artifactType = "all"; renderArtifacts(false); }));
        return;
      }
      if (ui.artifactView === "cards") root.append(artifactCards(visible));
      else root.append(artifactTable(visible));
    });
  }

  function artifactTable(items) {
    const scroll = el("div", "table-scroll");
    const table = el("table", "table table-clickable");
    const thead = el("thead");
    const headRow = el("tr");
    const artCols = [t("art.col.name"), t("art.col.type"), t("art.col.source"), t("art.col.created"), t("art.col.size"), t("art.col.status")];
    for (const [index, col] of artCols.entries()) {
      headRow.append(el("th", index === 2 || index === 3 ? "hide-sm" : "", col));
    }
    thead.append(headRow);
    table.append(thead);
    const tbody = el("tbody");
    for (const a of items) {
      const tr = el("tr");
      const nameCell = el("td");
      const nameMain = el("div", "cell-main ellipsis", a.name);
      const nameSub = el("div", "cell-sub ellipsis", a.path);
      nameCell.append(nameMain, nameSub);
      tr.append(nameCell);
      const typeCell = el("td");
      const tb = el("span", "badge", a.type.toUpperCase());
      tb.dataset.tone = a.type === "markdown" ? "primary" : a.type === "json" ? "info" : a.type === "code" ? "tool" : a.type === "image" ? "warning" : "success";
      typeCell.append(tb);
      tr.append(typeCell);
      tr.append(el("td", "cell-sub hide-sm", a.sourceTask));
      tr.append(el("td", "hide-sm", fmtAgo(a.createdAt)));
      tr.append(el("td", "num", fmtBytes(a.sizeBytes)));
      const statusCell = el("td");
      statusCell.append(statusBadge(a.status === "current" ? "ready" : "cancelled", a.status));
      tr.append(statusCell);
      tr.addEventListener("click", () => openArtifact(a));
      tbody.append(tr);
    }
    table.append(tbody);
    scroll.append(table);
    return scroll;
  }

  function artifactCards(items) {
    const grid = el("div", "artifact-cards");
    for (const a of items) {
      const card = el("div", "card artifact-card");
      card.append(el("div", "artifact-icon", a.type.slice(0, 3).toUpperCase()));
      card.append(el("div", "artifact-name", a.name));
      card.append(el("div", "artifact-meta", `${a.type} · ${fmtBytes(a.sizeBytes)}`));
      card.append(el("div", "artifact-meta", `${a.sourceTask} · ${fmtAgo(a.createdAt)}`));
      card.addEventListener("click", () => openArtifact(a));
      grid.append(card);
    }
    return grid;
  }

  function openArtifact(a) {
    const body = el("div");
    const row = el("div", "mission-title-row");
    row.append(statusBadge(a.status === "current" ? "ready" : "cancelled", a.status));
    const tb = el("span", "badge", a.type.toUpperCase());
    tb.dataset.tone = "primary";
    row.append(tb);
    body.append(row);
    body.append(kv([
      [t("art.name"), a.name],
      [t("art.id"), a.id],
      [t("art.source"), a.sourceTask],
      [t("art.created"), fmtDateTime(a.createdAt)],
      [t("art.size"), fmtBytes(a.sizeBytes)],
      [t("art.path"), a.path]
    ]));
    body.append(el("h3", "section-label", t("art.preview")));
    if (a.preview) body.append(codeBlock(a.preview.lines, a.preview.kind));
    else body.append(emptyState(t("art.no.preview"), t("art.no.preview.hint")));

    const actions = el("div", "quick-actions");
    const copyBtn = el("button", "btn sm", t("art.copy.path"));
    copyBtn.type = "button";
    copyBtn.addEventListener("click", () => shell().copyText(a.path, t("art.copy.done")));
    const downloadBtn = el("button", "btn sm", t("art.download"));
    downloadBtn.type = "button";
    downloadBtn.addEventListener("click", () => shell().toast(t("art.download.toast")));
    const detailBtn = el("button", "btn sm", t("art.details"));
    detailBtn.type = "button";
    detailBtn.addEventListener("click", () => openArtifactModal(a));
    actions.append(copyBtn, downloadBtn, detailBtn);
    body.append(actions);
    shell().openInspector(a.name, body);
  }

  function openArtifactModal(a) {
    const body = el("div");
    body.append(el("p", "muted", t("art.revisions.hint")));
    const rows = el("div", "list-rows");
    for (const [rev, note] of [[2, "current revision"], [1, "initial draft"]]) {
      const row = el("div", "list-row");
      const main = el("div", "list-main");
      main.append(el("div", "list-title", `r${rev} · ${fmtBytes(a.sizeBytes / rev)}`));
      main.append(el("div", "list-meta", note));
      row.append(main, el("span", "event-time", fmtAgo(a.createdAt)));
      rows.append(row);
    }
    body.append(rows);
    shell().openModal({
      title: `${a.name} · ${t("art.revisions")}`,
      body,
      actions: [{ label: t("modal.close"), kind: "" }]
    });
  }

  function codeBlock(lines, kind) {
    const block = el("div", "code-block");
    const head = el("div", "code-head");
    head.append(el("span", "", kind));
    block.append(head);
    const pre = el("pre");
    pre.textContent = lines.join("\n");
    block.append(pre);
    return block;
  }

  /* ======== RUNS ======== */
  function renderRuns() {
    const root = document.getElementById("runs-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const head = el("div", "page-head");
      const filters = el("div", "filters");
      for (const status of ["all", "succeeded", "failed", "cancelled", "waiting"]) {
        const chip = el("button", `chip${ui.runStatus === status ? " active" : ""}`, t(`filter.${status}`));
        chip.type = "button";
        chip.addEventListener("click", () => { ui.runStatus = status; renderRuns(); });
        filters.append(chip);
      }
      const range = el("select", "select filter-select");
      for (const [value, key] of [["all", "runs.range.all"], ["24h", "runs.range.24h"], ["3d", "runs.range.3d"], ["7d", "runs.range.7d"]]) {
        const opt = el("option", "", t(key));
        opt.value = value;
        range.append(opt);
      }
      range.value = ui.runRange;
      range.addEventListener("change", () => { ui.runRange = range.value; renderRuns(); });
      const search = el("input", "input filter-search");
      search.type = "search";
      search.placeholder = t("runs.search");
      search.value = ui.runQuery;
      search.addEventListener("input", () => { ui.runQuery = search.value; renderRuns(); });
      const left = el("div", "toolbar-group");
      left.append(filters);
      const right = el("div", "toolbar-group");
      right.append(range, search);
      head.append(left, right);
      root.append(head);

      const nowMs = Date.now();
      const rangeMs = { "24h": 86400000, "3d": 3 * 86400000, "7d": 7 * 86400000 }[ui.runRange] || null;
      const query = ui.runQuery.trim().toLowerCase();
      const visible = data.runs.filter((r) =>
        (ui.runStatus === "all" || r.status === ui.runStatus) &&
        (!rangeMs || nowMs - new Date(r.startedAt).getTime() <= rangeMs) &&
        (!query || r.mission.toLowerCase().includes(query) || r.id.toLowerCase().includes(query))
      );
      if (!visible.length) {
        root.append(emptyState(t("runs.empty"), t("runs.empty.hint"), t("runs.clear"), () => { ui.runStatus = "all"; ui.runRange = "all"; ui.runQuery = ""; renderRuns(); }));
        return;
      }
      const scroll = el("div", "table-scroll");
      const table = el("table", "table table-clickable");
      const thead = el("thead");
      const headRow = el("tr");
      const runCols = [t("runs.col.id"), t("runs.col.mission"), t("runs.col.status"), t("runs.col.provider"), t("runs.col.model"), t("runs.col.started"), t("runs.col.duration"), t("runs.col.tools"), t("runs.col.artifacts"), t("runs.col.error")];
      for (const [index, col] of runCols.entries()) {
        const th = el("th", index === 3 || index === 4 ? "hide-sm" : "", col);
        headRow.append(th);
      }
      thead.append(headRow);
      table.append(thead);
      const tbody = el("tbody");
      for (const run of visible) {
        const tr = el("tr");
        tr.append(el("td", "cell-sub", run.id));
        tr.append(el("td", "cell-main", run.mission));
        const statusCell = el("td");
        statusCell.append(statusBadge(run.status));
        tr.append(statusCell);
        tr.append(el("td", "hide-sm", run.provider));
        tr.append(el("td", "cell-sub hide-sm", run.model));
        tr.append(el("td", "", fmtDateTime(run.startedAt)));
        tr.append(el("td", "num", fmtDuration(run.durationSec)));
        tr.append(el("td", "num", String(run.toolCalls)));
        tr.append(el("td", "num", String(run.artifacts)));
        const errCell = el("td", "cell-sub ellipsis cell-clip");
        errCell.textContent = run.error || "—";
        tr.append(errCell);
        tr.addEventListener("click", () => openRun(run));
        tbody.append(tr);
      }
      table.append(tbody);
      scroll.append(table);
      root.append(scroll);
    });
  }

  function openRun(run) {
    const body = el("div");
    const row = el("div", "mission-title-row");
    row.append(statusBadge(run.status));
    body.append(row);
    body.append(kv([
      [t("runs.col.id"), run.id],
      [t("runs.col.mission"), run.mission],
      [t("runs.col.provider"), `${run.provider} / ${run.model}`],
      [t("runs.col.started"), fmtDateTime(run.startedAt)],
      [t("runs.col.duration"), fmtDuration(run.durationSec)],
      [t("runs.col.tools"), String(run.toolCalls)],
      [t("runs.col.artifacts"), String(run.artifacts)]
    ]));
    if (run.error) body.append(callout("danger", run.error));
    const openMission = el("button", "btn sm", t("runs.open.mission"));
    openMission.type = "button";
    openMission.addEventListener("click", () => {
      shell().closeInspector();
      ui.selectedMissionId = run.missionId;
      shell().showPage("missions");
    });
    body.append(openMission);
    shell().openInspector(`${run.id} · ${run.mission}`, body);
  }

  /* ======== PROVIDERS ======== */
  function renderProviders() {
    const root = document.getElementById("providers-root");
    root.replaceChildren();
    demoGate(root, () => {
      const data = mock();
      const grid = el("div", "provider-grid");
      for (const provider of data.providers) grid.append(providerCard(provider));
      root.append(grid);

      const demo = panelCard(t("prov.demo.title"));
      const demoBody = el("div", "panel-body");
      const tag = el("span", "demo-tag", "DEMO");
      const note = el("p", "muted", t("prov.demo.desc"));
      const keyRow = el("div", "toolbar-group");
      const keyInput = el("input", "input demo-key-input");
      keyInput.type = "password";
      keyInput.placeholder = t("prov.demo.placeholder");
      keyInput.autocomplete = "off";
      const showBtn = el("button", "btn sm", t("prov.demo.show"));
      showBtn.type = "button";
      showBtn.addEventListener("click", () => {
        keyInput.type = keyInput.type === "password" ? "text" : "password";
        showBtn.textContent = keyInput.type === "password" ? t("prov.demo.show") : t("prov.demo.hide");
      });
      const saveBtn = el("button", "btn sm primary", t("prov.demo.save"));
      saveBtn.type = "button";
      saveBtn.addEventListener("click", () => {
        keyInput.value = "";
        shell().toast(t("prov.demo.saved"));
      });
      keyRow.append(keyInput, showBtn, saveBtn, tag);
      demoBody.append(note, keyRow);
      const settingsLink = el("button", "btn sm", t("prov.demo.settings"));
      settingsLink.type = "button";
      settingsLink.addEventListener("click", () => shell().showPage("settings"));
      demoBody.append(settingsLink);
      demo.append(demoBody);
      root.append(demo);
    });
  }

  function providerCard(provider) {
    const card = el("div", "card provider-card");
    const head = el("div", "provider-head");
    const nameWrap = el("div");
    nameWrap.append(el("div", "provider-name", provider.name));
    nameWrap.append(el("div", "provider-endpoint", provider.endpoint));
    head.append(nameWrap);
    head.append(statusBadge(provider.status));
    card.append(head);
    const facts = el("div", "provider-facts");
    facts.append(
      providerFact(t("prov.model"), provider.model),
      providerFact(t("prov.timeout"), `${provider.timeoutSec}s`),
      providerFact(t("prov.last.check"), fmtAgo(provider.lastCheck)),
      providerFact(t("prov.default"), provider.isDefault ? t("prov.default.yes") : "—")
    );
    card.append(facts);
    const foot = el("div", "provider-foot");
    const toggle = el("label", "switch");
    const input = el("input");
    input.type = "checkbox";
    input.checked = provider.enabled;
    input.setAttribute("aria-label", `${provider.name} enabled`);
    toggle.append(input, el("span", "switch-track"));
    input.addEventListener("change", () => {
      provider.enabled = input.checked;
      if (!provider.enabled) provider.status = "offline";
      else provider.status = provider.id === "prov-ollama" ? "offline" : "online";
      shell().toast(`${provider.name} ${provider.enabled ? t("cap.enabled") : t("cap.disabled")}`);
      renderProviders();
    });
    const check = el("button", "btn sm", t("prov.check"));
    check.type = "button";
    check.addEventListener("click", () => {
      check.disabled = true;
      const spinner = el("span", "spinner");
      check.replaceChildren(spinner);
      window.setTimeout(() => {
        provider.lastCheck = new Date().toISOString();
        check.disabled = false;
        check.textContent = t("prov.check");
        if (provider.status === "unreachable") shell().toast(`${provider.name}: ${t("prov.check.fail")}`);
        else if (!provider.enabled) shell().toast(`${provider.name}: ${t("prov.check.disabled")}`);
        else shell().toast(`${provider.name}: ${t("prov.check.ok")}`);
        renderProviders();
      }, 800);
    });
    foot.append(toggle, check);
    card.append(foot);
    return card;
  }

  function providerFact(label, value) {
    const fact = el("div", "provider-fact");
    fact.append(el("span", "", label), el("strong", "", value));
    return fact;
  }

  /* ======== SETTINGS (static HTML, bind once) ======== */
  function bindSettings() {
    bindSegmented("pref-theme", (value) => shell().setTheme(value));
    bindSegmented("pref-language", (value) => shell().setLocale(value));
    bindSegmented("pref-density", (value) => shell().setPref("density", value));
    bindSegmented("pref-motion", (value) => shell().setPref("motion", value));
    bindSegmented("pref-console-font", (value) => shell().setPref("consoleFont", value));
    bindSegmented("pref-default-view", (value) => shell().setPref("defaultView", value));

    const demoToggle = document.getElementById("pref-demo-mode");
    if (demoToggle) {
      demoToggle.checked = shell().isDemo();
      demoToggle.addEventListener("change", () => shell().setPref("demoMode", demoToggle.checked));
    }
    const logLimit = document.getElementById("pref-log-limit");
    if (logLimit) {
      logLimit.value = String(shell().pref("logLimit") || 200);
      logLimit.addEventListener("change", () => {
        const value = Number(logLimit.value);
        if (Number.isInteger(value) && value >= 20 && value <= 1000) shell().setPref("logLimit", value);
        else logLimit.value = String(shell().pref("logLimit") || 200);
      });
    }
    syncSettingsControls();
  }

  function bindSegmented(id, onChange) {
    const group = document.getElementById(id);
    if (!group) return;
    for (const button of group.querySelectorAll("[data-value]")) {
      button.addEventListener("click", () => {
        onChange(button.dataset.value);
        syncSettingsControls();
      });
    }
  }

  function syncSettingsControls() {
    setSegmentedActive("pref-theme", document.documentElement.dataset.theme || "dark");
    setSegmentedActive("pref-language", window.PaperClawI18n ? window.PaperClawI18n.getLocale() : "en");
    setSegmentedActive("pref-density", shell().pref("density"));
    setSegmentedActive("pref-motion", shell().pref("motion"));
    setSegmentedActive("pref-console-font", shell().pref("consoleFont"));
    setSegmentedActive("pref-default-view", shell().pref("defaultView"));
  }

  function setSegmentedActive(id, value) {
    const group = document.getElementById(id);
    if (!group) return;
    for (const button of group.querySelectorAll("[data-value]")) {
      button.classList.toggle("active", button.dataset.value === value);
    }
  }

  /* ======== Router ======== */
  const renderers = {
    overview: renderOverview,
    missions: renderMissions,
    project: renderProject,
    capabilities: renderCapabilities,
    artifacts: () => renderArtifacts(true),
    runs: renderRuns,
    providers: renderProviders,
    settings: bindSettings
  };

  function ensureRendered(name) {
    const renderer = renderers[name];
    if (!renderer) return;
    if (name === "settings") { syncSettingsControls(); }
    if (rendered.has(name)) return;
    rendered.add(name);
    renderer();
    if (window.PaperClawI18n && window.PaperClawI18n.applyDocument) {
      window.PaperClawI18n.applyDocument(document);
    }
  }

  function rerenderAll() {
    for (const name of Array.from(rendered)) {
      if (name === "settings") continue;
      rendered.delete(name);
    }
    const current = shell().currentPage();
    if (renderers[current]) ensureRendered(current);
  }

  function onDemoChanged() { rerenderAll(); }

  window.addEventListener("paperclaw:locale-changed", () => {
    if (shell() && shell().currentPage) rerenderAll();
  });

  /* Nav badge counts + console cwd mirror (boot-time chrome). */
  function bootChrome() {
    const data = mock();
    const setBadge = (id, value) => {
      const node = document.getElementById(id);
      if (node) node.textContent = String(value);
    };
    if (data) {
      setBadge("missions-nav-badge", data.missions.filter((m) => m.status === "running").length || "");
      setBadge("capabilities-nav-badge", data.capabilities.length);
      setBadge("runs-nav-badge", data.runs.length);
      setBadge("providers-nav-badge", data.providers.filter((p) => p.status === "online").length);
    }
    const source = document.getElementById("workspace-path");
    const target = document.getElementById("console-cwd");
    if (source && target) {
      const sync = () => {
        const value = source.textContent.trim();
        target.textContent = value ? `cwd ${value}` : "—";
      };
      sync();
      new MutationObserver(sync).observe(source, { childList: true, characterData: true, subtree: true });
    }
  }

  window.PaperClawPages = { ensureRendered, onDemoChanged };
  document.addEventListener("DOMContentLoaded", () => { bootChrome(); startSimulator(); }, { once: true });
})();
