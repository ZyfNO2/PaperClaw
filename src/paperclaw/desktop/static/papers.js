(() => {
  "use strict";
  const root = () => document.getElementById("papers-root");
  const workspace = () => (document.getElementById("workspace-path")?.textContent || "").trim();
  const api = () => window.PaperClawBackend?.api || null;
  const node = (tag, cls, text) => {
    const item = document.createElement(tag);
    if (cls) item.className = cls;
    if (text != null) item.textContent = text;
    return item;
  };

  async function load() {
    const target = root();
    if (!target) return;
    target.replaceChildren();
    const head = node("div", "page-head");
    const title = node("div", "page-head-main");
    title.append(node("span", "page-head-title", "PAPER LIBRARY"));
    title.append(node("span", "page-head-sub", "Managed originals, candidate metadata and immutable versions."));
    const button = node("button", "btn primary", "IMPORT PAPER");
    button.type = "button";
    button.addEventListener("click", importPaper);
    head.append(title, button);
    target.append(head);
    if (!workspace() || !api()) {
      target.append(node("div", "state-block", "Select a PaperClaw workspace to manage papers."));
      return;
    }
    const response = await api().list_papers(workspace(), 100);
    if (!response.ok) {
      target.append(node("div", "state-block", response.message || "Paper library could not be loaded."));
      return;
    }
    const badge = document.getElementById("papers-nav-badge");
    if (badge) badge.textContent = String(response.papers.length);
    if (!response.papers.length) {
      target.append(node("div", "state-block", "No papers imported."));
      return;
    }
    const list = node("div", "card-list");
    for (const paper of response.papers) {
      const row = node("button", "card list-card");
      row.type = "button";
      row.append(node("strong", "", String(paper.metadata.title.value || paper.paper_id)));
      row.append(node("span", "tiny mono", `v${paper.current_version_number} · ${paper.metadata.title.status}`));
      row.addEventListener("click", () => showPaper(paper.paper_id));
      list.append(row);
    }
    target.append(list);
  }

  async function importPaper() {
    if (!api() || !workspace()) return;
    const picked = await api().select_paper_source();
    if (!picked.ok || !picked.source_path) return;
    const response = await api().import_paper(workspace(), picked.source_path, null);
    if (!response.ok) return;
    await load();
    await showPaper(response.result.paper.paper_id);
  }

  async function showPaper(paperId) {
    const target = root();
    const [paperResponse, versionsResponse] = await Promise.all([
      api().get_paper(workspace(), paperId),
      api().list_paper_versions(workspace(), paperId)
    ]);
    if (!paperResponse.ok || !versionsResponse.ok) return;
    const paper = paperResponse.paper;
    target.replaceChildren();
    const back = node("button", "btn subtle", "← PAPERS");
    back.type = "button";
    back.addEventListener("click", load);
    target.append(back, node("h2", "page-head-title", String(paper.metadata.title.value || paper.paper_id)));
    const meta = node("div", "card");
    meta.append(node("p", "tiny mono", `metadata revision ${paper.metadata_revision}`));
    for (const [key, value] of Object.entries(paper.metadata)) {
      const shown = Array.isArray(value.value) ? value.value.join(", ") : value.value;
      meta.append(node("p", "", `${key}: ${shown || "—"} [${value.status}]`));
    }
    const form = node("form", "card");
    const fields = {};
    for (const name of ["title", "authors", "year", "doi", "arxiv_id", "language"]) {
      const label = node("label", "provider-field");
      label.append(node("span", "", name.toUpperCase()));
      const input = node("input", "");
      const value = paper.metadata[name].value;
      input.value = Array.isArray(value) ? value.join("; ") : value || "";
      input.maxLength = name === "title" ? 1000 : 500;
      if (name === "year") input.inputMode = "numeric";
      fields[name] = input;
      label.append(input);
      form.append(label);
    }
    const confirm = node("button", "btn primary", "CONFIRM METADATA");
    confirm.type = "submit";
    form.append(confirm);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const patch = {
        title: fields.title.value,
        authors: fields.authors.value.split(/[;,]/).map((part) => part.trim()).filter(Boolean),
        doi: fields.doi.value,
        arxiv_id: fields.arxiv_id.value,
        language: fields.language.value
      };
      if (fields.year.value.trim()) {
        const year = Number(fields.year.value);
        if (!Number.isInteger(year) || year < 1 || year > 9999) return;
        patch.year = year;
      }
      const response = await api().confirm_paper_metadata(
        workspace(), paper.paper_id, patch, paper.metadata_revision
      );
      if (response.ok) await showPaper(paper.paper_id);
    });
    const versions = node("div", "card");
    versions.append(node("h3", "panel-title", "VERSIONS"));
    for (const version of versionsResponse.versions) {
      versions.append(node("p", "mono", `v${version.version_number} · ${version.format} · ${version.byte_length} bytes · ${version.sha256.slice(0, 12)}`));
    }
    target.append(meta, form, versions);
  }

  const pages = window.PaperClawPages;
  if (pages) {
    const original = pages.ensureRendered;
    pages.ensureRendered = (name) => {
      if (name === "papers") { load(); return; }
      original(name);
    };
  }
})();
