(() => {
  "use strict";

  const STORAGE_KEY = "paperclaw.locale.v1";
  const SUPPORTED = new Set(["zh-CN", "en"]);
  const DYNAMIC_IDS = new Set([
    "workspace-name", "workspace-path", "run-subtitle", "provider-summary",
    "event-meta", "verification-summary", "config-source", "config-provider",
    "config-base-url", "config-model", "config-credential", "model-label",
    "provider-connect-status", "active-config-status", "gate-mode-status",
    "toast-message", "public-error"
  ]);

  const messages = {
    en: {
      "sidebar.collapse": "Collapse sidebar",
      "workspace.select": "Select workspace",
      "workspace.loading": "Loading…",
      "workspace.waiting": "Waiting for desktop bridge",
      "nav.main": "Main navigation",
      "nav.console": "Console",
      "nav.trace": "Trace",
      "nav.sessions": "Sessions",
      "nav.team": "Team",
      "nav.settings": "Settings",
      "run.new": "+ NEW RUN",
      "console.title": "CONSOLE",
      "console.subtitle": "Agent runtime monitor · run=not-started",
      "search.placeholder": "Search mission log…",
      "search.aria": "Search mission log",
      "run.execute": "▶ EXECUTE",
      "run.stop": "■ STOP",
      "run.export": "⇩ EXPORT TRACE",
      "run.workspace": "▣ WORKSPACE",
      "toolbar.theme": "THEME",
      "toolbar.language": "LANGUAGE",
      "toolbar.languageAria": "Select interface language",
      "toolbar.browser": "◎ OPEN IN BROWSER",
      "provider.unchecked": "LLM · ENV NOT CHECKED",
      "mission.title": "MISSION LOG",
      "mission.filterAria": "Mission log filters",
      "filter.all": "ALL",
      "filter.system": "SYSTEM",
      "filter.you": "YOU",
      "filter.agent": "AGENT",
      "filter.model": "MODEL",
      "filter.tool": "TOOL",
      "filter.verify": "VERIFY",
      "mission.initial": "PaperClaw desktop bridge is initializing. LLM configuration can use environment variables or a manual provider connection.",
      "task.label": "Task",
      "task.placeholder": "Enter an instruction or use / commands…",
      "task.clear": "CLEAR",
      "task.hint": "Enter to execute · Shift+Enter for newline · /cancel to stop",
      "status.title": "RUN STATUS",
      "metric.model": "Model Calls",
      "metric.tool": "Tool Calls",
      "metric.events": "Events",
      "metric.verification": "Verification",
      "metric.bounded": "bounded runtime",
      "metric.queued": "0 queued",
      "metric.notRun": "not run",
      "progress.title": "PIPELINE PROGRESS",
      "progress.aria": "Run progress",
      "timeline.title": "EVENT TIMELINE",
      "timeline.filterAria": "Event filters",
      "settings.title": "MODEL CONNECTION & RUNTIME CONFIG",
      "settings.close": "Close settings",
      "config.source": "Source",
      "config.environment": "Environment variables",
      "config.provider": "Provider",
      "config.baseUrl": "Base URL",
      "config.model": "Model",
      "config.credential": "Credential",
      "config.notChecked": "Not checked",
      "provider.title": "MANUAL PROVIDER CONNECTION",
      "provider.baseUrl": "BASE URL",
      "provider.apiKey": "API KEY",
      "provider.show": "Show",
      "provider.manualModel": "MODEL (OPTIONAL FALLBACK)",
      "provider.manualPlaceholder": "Use when /models is unavailable",
      "provider.availableModel": "AVAILABLE MODEL",
      "provider.modelAria": "Select an available API model",
      "provider.connect": "CONNECT & LOAD MODELS",
      "provider.useManual": "USE MANUAL MODEL",
      "provider.useEnv": "USE ENV",
      "provider.disconnect": "DISCONNECT",
      "provider.initialStatus": "Enter a Base URL and API key. If /models is unavailable, provide an optional model name. Credentials stay only in this Python process memory.",
      "provider.activeUnchecked": "ACTIVE · NOT CHECKED",
      "budget.steps": "MAX STEPS",
      "budget.models": "MODEL CALLS",
      "budget.tools": "TOOL CALLS",
      "gate.enable": "Enable verification & reflection gate",
      "gate.enabled": "Verify and Reflection Gate are enabled.",
      "toast.close": "Close notification"
    },
    "zh-CN": {
      "sidebar.collapse": "折叠侧边栏",
      "workspace.select": "选择工作区",
      "workspace.loading": "加载中…",
      "workspace.waiting": "等待桌面桥接",
      "nav.main": "主导航",
      "nav.console": "控制台",
      "nav.trace": "追踪",
      "nav.sessions": "会话",
      "nav.team": "团队",
      "nav.settings": "设置",
      "run.new": "+ 新建任务",
      "console.title": "控制台",
      "console.subtitle": "Agent 运行监控 · run=未开始",
      "search.placeholder": "搜索任务日志…",
      "search.aria": "搜索任务日志",
      "run.execute": "▶ 执行",
      "run.stop": "■ 停止",
      "run.export": "⇩ 导出追踪",
      "run.workspace": "▣ 工作区",
      "toolbar.theme": "主题",
      "toolbar.language": "语言",
      "toolbar.languageAria": "选择界面语言",
      "toolbar.browser": "◎ 在浏览器中打开",
      "provider.unchecked": "LLM · 尚未检查 ENV",
      "mission.title": "任务日志",
      "mission.filterAria": "任务日志筛选",
      "filter.all": "全部",
      "filter.system": "系统",
      "filter.you": "你",
      "filter.agent": "Agent",
      "filter.model": "模型",
      "filter.tool": "工具",
      "filter.verify": "验证",
      "mission.initial": "PaperClaw 桌面桥接正在初始化。LLM 可使用环境变量或手动连接 Provider。",
      "task.label": "任务",
      "task.placeholder": "输入指令或使用 / 命令…",
      "task.clear": "清空",
      "task.hint": "Enter 执行 · Shift+Enter 换行 · /cancel 停止",
      "status.title": "运行状态",
      "metric.model": "模型调用",
      "metric.tool": "工具调用",
      "metric.events": "事件",
      "metric.verification": "验证",
      "metric.bounded": "受限运行时",
      "metric.queued": "0 个排队事件",
      "metric.notRun": "尚未运行",
      "progress.title": "流程进度",
      "progress.aria": "运行进度",
      "timeline.title": "事件时间线",
      "timeline.filterAria": "事件筛选",
      "settings.title": "模型连接与运行配置",
      "settings.close": "关闭设置",
      "config.source": "来源",
      "config.environment": "环境变量",
      "config.provider": "Provider",
      "config.baseUrl": "Base URL",
      "config.model": "模型",
      "config.credential": "凭据",
      "config.notChecked": "尚未检查",
      "provider.title": "手动连接 Provider",
      "provider.baseUrl": "BASE URL",
      "provider.apiKey": "API KEY",
      "provider.show": "显示",
      "provider.manualModel": "模型（可选回退）",
      "provider.manualPlaceholder": "当 /models 不可用时填写",
      "provider.availableModel": "可用模型",
      "provider.modelAria": "选择当前 API 可访问的模型",
      "provider.connect": "连接并加载模型",
      "provider.useManual": "使用手动模型",
      "provider.useEnv": "使用 ENV",
      "provider.disconnect": "断开连接",
      "provider.initialStatus": "填写 Base URL 与 API Key 后连接。若服务不支持 /models，可填写可选模型名；凭据仅保存在本次 Python 进程内存中。",
      "provider.activeUnchecked": "ACTIVE · 尚未检查",
      "budget.steps": "最大步骤数",
      "budget.models": "模型调用数",
      "budget.tools": "工具调用数",
      "gate.enable": "启用验证与反思门禁",
      "gate.enabled": "Verify 与 Reflection Gate 已开启。",
      "toast.close": "关闭提示"
    }
  };

  const dynamicPairs = [
    ["Loading…", "加载中…"],
    ["Waiting for desktop bridge", "等待桌面桥接"],
    ["LLM · ENV NOT CHECKED", "LLM · 尚未检查 ENV"],
    ["Environment variables", "环境变量"],
    ["Manual connection", "手动连接"],
    ["Not checked", "尚未检查"],
    ["not configured", "未配置"],
    ["Configured (hidden)", "已配置（已隐藏）"],
    ["0 queued", "0 个排队事件"],
    ["not run", "尚未运行"],
    ["Workspace updated.", "工作区已更新。"],
    ["Cancellation requested.", "已请求取消任务。"],
    ["Browser mode opened on a protected localhost URL.", "已通过受保护的本地地址打开浏览器模式。"],
    ["Trace export prepared.", "追踪导出文件已准备。"],
    ["Provider defaults could not be loaded.", "无法加载 Provider 默认配置。"],
    ["Base URL 和 API Key 均不能为空。", "Base URL and API Key are required."],
    ["当前桌面桥接不支持模型发现。", "The desktop bridge does not support model discovery."],
    ["正在连接并读取模型列表……", "Connecting and loading the model list…"],
    ["连接失败：桌面桥接未返回有效结果。", "Connection failed: the desktop bridge returned no valid result."],
    ["正在切换模型……", "Switching model…"],
    ["模型切换失败。", "Model switch failed."],
    ["当前桌面桥接不支持恢复 ENV。", "The desktop bridge does not support restoring ENV configuration."],
    ["已恢复为环境变量配置。", "Environment-variable configuration restored."],
    ["恢复 ENV 配置失败。", "Failed to restore ENV configuration."],
    ["Verify 与 Reflection Gate 已开启。", "Verify and Reflection Gate are enabled."],
    ["Verify 与 Reflection Gate 已关闭；任务完成后直接结束。", "Verify and Reflection Gate are disabled; the run will end after completion is proposed."],
    ["显示", "Show"],
    ["隐藏", "Hide"]
  ];

  let locale = resolveInitialLocale();
  let applying = false;
  let observerQueued = false;
  const dynamicLookup = new Map();
  for (const [english, chinese] of dynamicPairs) {
    const pair = {en: english, "zh-CN": chinese};
    dynamicLookup.set(english, pair);
    dynamicLookup.set(chinese, pair);
  }

  function resolveInitialLocale() {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.has(stored)) return stored;
    } catch (_error) {}
    const browser = String(window.navigator.language || "").toLowerCase();
    return browser.startsWith("zh") ? "zh-CN" : "en";
  }

  function t(key, variables = {}) {
    const value = (messages[locale] && messages[locale][key]) || messages.en[key] || key;
    return value.replace(/\{(\w+)\}/g, (_match, name) => String(variables[name] ?? ""));
  }

  function matchingElements(root, selector) {
    const result = [];
    if (root instanceof Element && root.matches(selector)) result.push(root);
    if (root.querySelectorAll) result.push(...root.querySelectorAll(selector));
    return result;
  }

  function applyDocument(root = document) {
    if (applying) return;
    applying = true;
    try {
      document.documentElement.lang = locale;
      for (const element of matchingElements(root, "[data-i18n]")) {
        if (!DYNAMIC_IDS.has(element.id)) {
          const value = t(element.dataset.i18n);
          if (element.textContent !== value) element.textContent = value;
        }
      }
      for (const element of matchingElements(root, "[data-i18n-placeholder]")) {
        const value = t(element.dataset.i18nPlaceholder);
        if (element.getAttribute("placeholder") !== value) element.setAttribute("placeholder", value);
      }
      for (const element of matchingElements(root, "[data-i18n-aria-label]")) {
        const value = t(element.dataset.i18nAriaLabel);
        if (element.getAttribute("aria-label") !== value) element.setAttribute("aria-label", value);
      }
      translateDynamicText(root);
      const selector = document.getElementById("language-select");
      if (selector && selector.value !== locale) selector.value = locale;
    } finally {
      applying = false;
    }
  }

  function translateDynamicText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const raw = node.nodeValue || "";
      const trimmed = raw.trim();
      if (!trimmed) continue;
      const pair = dynamicLookup.get(trimmed);
      const translated = pair ? pair[locale] : translatePattern(trimmed);
      if (translated === trimmed) continue;
      const start = raw.indexOf(trimmed);
      node.nodeValue = raw.slice(0, start) + translated + raw.slice(start + trimmed.length);
    }
  }

  function translatePattern(value) {
    let match = /^Agent runtime monitor · run=(.*)$/.exec(value);
    if (match) return locale === "en" ? value : `Agent 运行监控 · run=${match[1] === "not-started" ? "未开始" : match[1]}`;
    match = /^Agent 运行监控 · run=(.*)$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `Agent runtime monitor · run=${match[1] === "未开始" ? "not-started" : match[1]}`;
    match = /^(\d+) dropped$/.exec(value);
    if (match) return locale === "en" ? value : `丢弃 ${match[1]} 个`;
    match = /^丢弃 (\d+) 个$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `${match[1]} dropped`;
    match = /^Missing: (.*)$/.exec(value);
    if (match) return locale === "en" ? value : `缺少：${match[1]}`;
    match = /^缺少：(.*)$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `Missing: ${match[1]}`;
    match = /^连接成功，可用模型 (\d+) 个。$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `Connected. ${match[1]} models available.`;
    match = /^Connected\. (\d+) models available\.$/.exec(value);
    if (match) return locale === "en" ? value : `连接成功，可用模型 ${match[1]} 个。`;
    match = /^已选择模型：(.*)$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `Selected model: ${match[1]}`;
    match = /^Selected model: (.*)$/.exec(value);
    if (match) return locale === "en" ? value : `已选择模型：${match[1]}`;
    match = /^Theme: (.*)$/.exec(value);
    if (match) return locale === "en" ? value : `主题：${match[1]}`;
    match = /^主题：(.*)$/.exec(value);
    if (match) return locale === "zh-CN" ? value : `Theme: ${match[1]}`;
    return value;
  }

  function setLocale(nextLocale, persist = true) {
    if (!SUPPORTED.has(nextLocale)) return false;
    locale = nextLocale;
    if (persist) {
      try { window.localStorage.setItem(STORAGE_KEY, locale); } catch (_error) {}
    }
    applyDocument(document);
    window.dispatchEvent(new CustomEvent("paperclaw:locale-changed", {detail: {locale}}));
    return true;
  }

  function bind() {
    const selector = document.getElementById("language-select");
    if (selector) {
      selector.value = locale;
      selector.addEventListener("change", () => setLocale(selector.value, true));
    }
    applyDocument(document);
    const observer = new MutationObserver(() => {
      if (applying || observerQueued) return;
      observerQueued = true;
      window.queueMicrotask(() => {
        observerQueued = false;
        applyDocument(document);
      });
    });
    observer.observe(document.body, {subtree: true, childList: true, characterData: true});
  }

  window.PaperClawI18n = {
    t,
    getLocale: () => locale,
    setLocale,
    applyDocument,
    supportedLocales: () => Array.from(SUPPORTED)
  };
  document.addEventListener("DOMContentLoaded", bind, {once: true});
})();
