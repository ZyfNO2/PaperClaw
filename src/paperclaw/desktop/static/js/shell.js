/* PaperClaw Shell
   App-shell controller: page navigation, UI preferences, inspector drawer,
   modal, toast bridging, and shared formatters. Mock pages never touch the
   Python bridge; the live Console wiring stays in app.js.
*/
(() => {
  "use strict";

  const PREFS_KEY = "paperclaw.ui.v1";
  const SMALL_SCREEN = "(max-width: 1100px)";

  const PAGES = {
    overview: { sectionId: "page-overview", titleKey: "page.overview", fallback: "OVERVIEW" },
    console: { sectionId: "page-console", titleKey: "console.title", fallback: "CONSOLE" },
    missions: { sectionId: "page-missions", titleKey: "page.missions", fallback: "MISSIONS" },
    project: { sectionId: "page-project", titleKey: "page.project", fallback: "PROJECT" },
    capabilities: { sectionId: "page-capabilities", titleKey: "page.capabilities", fallback: "CAPABILITIES" },
    artifacts: { sectionId: "page-artifacts", titleKey: "page.artifacts", fallback: "ARTIFACTS" },
    runs: { sectionId: "page-runs", titleKey: "page.runs", fallback: "RUNS" },
    providers: { sectionId: "page-providers", titleKey: "page.providers", fallback: "PROVIDERS" },
    settings: { sectionId: "settings-panel", titleKey: "page.settings", fallback: "SETTINGS" }
  };

  const state = {
    current: "console",
    previous: "console",
    prefs: {
      density: "comfortable",
      motion: "on",
      consoleFont: "md",
      defaultView: "console",
      demoMode: true,
      logLimit: 200
    },
    inspectorOpen: false,
    modalOpen: false,
    toastTimer: null
  };

  const els = {};

  function byId(id) { return document.getElementById(id); }

  function init() {
    els.app = byId("app");
    els.pageTitle = byId("page-title");
    els.inspector = byId("inspector");
    els.inspectorBackdrop = byId("inspector-backdrop");
    els.inspectorTitle = byId("inspector-title");
    els.inspectorBody = byId("inspector-body");
    els.closeInspector = byId("close-inspector");
    els.modalRoot = byId("modal-root");
    els.toast = byId("toast");
    els.toastMessage = byId("toast-message");

    loadPrefs();
    applyPrefs();
    bindChrome();
    document.addEventListener("keydown", onEscape);

    if (window.matchMedia(SMALL_SCREEN).matches && els.app) {
      els.app.classList.add("sidebar-collapsed");
    }

    const initial = PAGES[state.prefs.defaultView] ? state.prefs.defaultView : "console";
    showPage(PAGES[initial] ? initial : "console", { force: true });
  }

  /* ======== Navigation ======== */
  function showPage(name, options = {}) {
    const target = PAGES[name];
    if (!target) return;
    if (name === state.current && !options.force) return;

    for (const key of Object.keys(PAGES)) {
      const section = byId(PAGES[key].sectionId);
      if (section) section.hidden = key !== name;
    }
    const nav = byId("sidebar-nav");
    if (nav) {
      for (const button of nav.querySelectorAll("[data-nav]")) {
        button.classList.toggle("active", button.dataset.nav === name);
      }
    }
    state.previous = state.current;
    state.current = name;

    if (els.pageTitle) {
      els.pageTitle.dataset.i18n = target.titleKey;
      if (window.PaperClawI18n && typeof window.PaperClawI18n.applyDocument === "function") {
        window.PaperClawI18n.applyDocument(document);
      } else {
        els.pageTitle.textContent = target.fallback;
      }
    }
    if (window.PaperClawPages && typeof window.PaperClawPages.ensureRendered === "function") {
      window.PaperClawPages.ensureRendered(name);
    }
    if (window.matchMedia(SMALL_SCREEN).matches && els.app) {
      els.app.classList.add("sidebar-collapsed");
    }
  }

  function backFromSettings() {
    showPage(state.previous && state.previous !== "settings" ? state.previous : "console");
  }

  /* ======== Preferences ======== */
  function loadPrefs() {
    try {
      const raw = window.localStorage.getItem(PREFS_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw);
      if (stored && typeof stored === "object") Object.assign(state.prefs, stored);
    } catch (_error) { /* restricted storage: keep defaults */ }
  }

  function savePrefs() {
    try {
      window.localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
    } catch (_error) { /* restricted storage: session-only prefs */ }
  }

  function applyPrefs() {
    const root = document.documentElement;
    root.dataset.density = state.prefs.density === "compact" ? "compact" : "comfortable";
    root.dataset.motion = state.prefs.motion === "off" ? "off" : "on";
    root.dataset.consoleFont = state.prefs.consoleFont || "md";
  }

  function setPref(key, value) {
    state.prefs[key] = value;
    applyPrefs();
    savePrefs();
    if (key === "demoMode" && window.PaperClawPages && typeof window.PaperClawPages.onDemoChanged === "function") {
      window.PaperClawPages.onDemoChanged(Boolean(value));
    }
  }

  function isDemo() { return Boolean(state.prefs.demoMode); }
  function pref(key) { return state.prefs[key]; }

  function setTheme(name) {
    const select = byId("theme-select");
    if (!select) return;
    select.value = name;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setLocale(name) {
    if (window.PaperClawI18n && typeof window.PaperClawI18n.setLocale === "function") {
      window.PaperClawI18n.setLocale(name, true);
    }
  }

  /* ======== Inspector drawer ======== */
  function openInspector(title, content) {
    if (!els.inspector) return;
    els.inspectorTitle.textContent = title;
    els.inspectorBody.replaceChildren(content);
    els.inspectorBackdrop.hidden = false;
    els.inspector.hidden = false;
    window.requestAnimationFrame(() => els.inspector.classList.add("open"));
    state.inspectorOpen = true;
  }

  function closeInspector() {
    if (!els.inspector || !state.inspectorOpen) return;
    els.inspector.classList.remove("open");
    state.inspectorOpen = false;
    window.setTimeout(() => {
      if (!state.inspectorOpen) {
        els.inspector.hidden = true;
        els.inspectorBackdrop.hidden = true;
      }
    }, 220);
  }

  /* ======== Modal ======== */
  function openModal({ title, body, actions = [] }) {
    if (!els.modalRoot) return;
    const card = el("div", "modal-card");
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");

    const head = el("div", "modal-head");
    const titleEl = el("h2", "modal-title", title);
    const closeBtn = el("button", "icon-btn", "×");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Close dialog");
    closeBtn.addEventListener("click", closeModal);
    head.append(titleEl, closeBtn);

    const bodyEl = el("div", "modal-body");
    bodyEl.append(body);

    card.append(head, bodyEl);
    if (actions.length) {
      const foot = el("div", "modal-foot");
      for (const action of actions) {
        const btn = el("button", `btn${action.kind ? ` ${action.kind}` : ""}`, action.label);
        btn.type = "button";
        btn.addEventListener("click", () => {
          if (action.onClick) action.onClick();
          if (action.keepOpen !== true) closeModal();
        });
        foot.append(btn);
      }
      card.append(foot);
    }

    els.modalRoot.replaceChildren(card);
    els.modalRoot.hidden = false;
    state.modalOpen = true;
    closeBtn.focus();
  }

  function closeModal() {
    if (!els.modalRoot || !state.modalOpen) return;
    els.modalRoot.hidden = true;
    els.modalRoot.replaceChildren();
    state.modalOpen = false;
  }

  /* ======== Toast bridge ======== */
  function toast(message) {
    if (window.PaperClawToast) {
      window.PaperClawToast(message);
      return;
    }
    if (!els.toast) return;
    els.toastMessage.textContent = String(message);
    els.toast.hidden = false;
    if (state.toastTimer !== null) window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => { els.toast.hidden = true; }, 3200);
  }

  /* ======== Clipboard ======== */
  async function copyText(value, toastMessage) {
    try {
      await window.navigator.clipboard.writeText(String(value));
      toast(toastMessage || "已复制到剪贴板。");
    } catch (_error) {
      toast("Clipboard unavailable in this context.");
    }
  }

  /* ======== Shared DOM + format helpers ======== */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function fmtBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return "—";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(2)} MB`;
  }

  function fmtDuration(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
    if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
    return `${s}s`;
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleTimeString([], { hour12: false });
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour12: false })}`;
  }

  function fmtAgo(iso) {
    if (!iso) return "—";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "—";
    const diff = Math.max(0, Date.now() - then);
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  /* ======== Event plumbing ======== */
  function bindChrome() {
    if (els.closeInspector) els.closeInspector.addEventListener("click", closeInspector);
    if (els.inspectorBackdrop) els.inspectorBackdrop.addEventListener("click", closeInspector);
    if (els.modalRoot) {
      els.modalRoot.addEventListener("click", (event) => {
        if (event.target === els.modalRoot) closeModal();
      });
    }
  }

  function onEscape(event) {
    if (event.key !== "Escape") return;
    if (state.modalOpen) { closeModal(); return; }
    if (state.inspectorOpen) { closeInspector(); }
  }

  window.PaperClawShell = {
    PAGES,
    showPage,
    backFromSettings,
    currentPage: () => state.current,
    setPref,
    pref,
    isDemo,
    setTheme,
    setLocale,
    openInspector,
    closeInspector,
    openModal,
    closeModal,
    toast,
    copyText,
    el,
    fmtBytes,
    fmtDuration,
    fmtTime,
    fmtDateTime,
    fmtAgo
  };

  document.addEventListener("DOMContentLoaded", init, { once: true });
})();
