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
  const OBSERVER_OPTIONS = {subtree: true, childList: true, characterData: true};

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
      "toast.close": "Close notification",
      "workspace.label": "WORKSPACE",
      "sidebar.env": "BRIDGE",
      "nav.overview": "Overview",
      "nav.missions": "Missions",
      "nav.project": "Project",
      "nav.capabilities": "Capabilities",
      "nav.artifacts": "Artifacts",
      "nav.runs": "Runs",
      "nav.providers": "Providers",
      "nav.product": "◫ PRODUCT (LIVE)",
      "page.overview": "OVERVIEW",
      "page.missions": "MISSIONS",
      "page.project": "PROJECT",
      "page.capabilities": "CAPABILITIES",
      "page.artifacts": "ARTIFACTS",
      "page.runs": "RUNS",
      "page.providers": "PROVIDERS",
      "page.settings": "SETTINGS",
      "inspector.close": "Close inspector",
      "settings.page": "PREFERENCES & RUNTIME",
      "settings.page.sub": "Interface preferences apply immediately. Runtime configuration is live.",
      "settings.done": "✓ DONE",
      "settings.preferences": "PREFERENCES",
      "pref.theme": "Theme",
      "pref.theme.desc": "Dark or light workbench surface",
      "pref.language": "Language",
      "pref.language.desc": "Interface language",
      "pref.density": "Density",
      "pref.density.desc": "Row and control compactness",
      "pref.comfortable": "Comfortable",
      "pref.compact": "Compact",
      "pref.motion": "Animation",
      "pref.motion.desc": "Interface micro-transitions",
      "pref.on": "On",
      "pref.off": "Off",
      "pref.defaultview": "Default view",
      "pref.defaultview.desc": "Page shown at launch",
      "pref.consolefont": "Console font size",
      "pref.consolefont.desc": "Mission log and code blocks",
      "pref.demomode": "Demo mode",
      "pref.demomode.desc": "Populate mock pages with demo data",
      "pref.loglimit": "Log lines shown",
      "pref.loglimit.desc": "Applies to runtime and timeline lists (20–1000)",
      "filter.queued": "QUEUED",
      "filter.running": "RUNNING",
      "filter.waiting": "WAITING",
      "filter.succeeded": "SUCCEEDED",
      "filter.failed": "FAILED",
      "filter.cancelled": "CANCELLED",
      "state.retry": "RETRY",
      "demo.off.title": "Demo mode is off",
      "demo.off.desc": "This page renders mock data while demo mode is on. Turn it back on to preview the workbench.",
      "demo.off.action": "ENABLE DEMO MODE",
      "ov.runtime": "Runtime",
      "ov.agent": "Agent",
      "ov.providers": "Providers",
      "ov.providers.online": "online",
      "ov.capabilities": "Capabilities",
      "ov.capabilities.total": "registered",
      "ov.succeeded": "Succeeded",
      "ov.failed": "Failed",
      "ov.cancelled": "Cancelled",
      "ov.runs.hint": "recent missions",
      "ov.artifacts": "Artifacts",
      "ov.artifacts.hint": "stored outputs",
      "ov.current.mission": "CURRENT MISSION",
      "ov.step": "step",
      "ov.open.missions": "OPEN MISSIONS",
      "ov.project": "CURRENT PROJECT",
      "ov.indexed": "indexed",
      "ov.open.project": "OPEN PROJECT",
      "ov.open.console": "OPEN CONSOLE",
      "ov.open.artifacts": "VIEW ARTIFACTS",
      "ov.recent.runs": "RECENT RUNS",
      "ov.recent.errors": "RECENT ERRORS",
      "ov.no.errors": "No recent errors",
      "ov.runtime.logs": "RUNTIME LOGS",
      "missions.summary": "MISSION",
      "missions.task": "task",
      "missions.started": "started",
      "missions.provider": "provider",
      "missions.tools": "tool calls",
      "missions.step": "step",
      "missions.duration": "DURATION",
      "missions.list": "MISSIONS",
      "missions.col.id": "ID",
      "missions.col.name": "NAME",
      "missions.col.status": "STATUS",
      "missions.col.progress": "PROGRESS",
      "missions.col.duration": "DURATION",
      "missions.empty": "No missions in this state",
      "missions.empty.hint": "Try a different status filter.",
      "missions.clear.filter": "CLEAR FILTER",
      "missions.timeline": "TIMELINE",
      "missions.pause": "❚❚ PAUSE SIM",
      "missions.resume": "▶ RESUME SIM",
      "missions.ev.queued": "Mission queued",
      "missions.ev.queued.action": "Instruction accepted and registered",
      "missions.ev.started": "Runtime started",
      "missions.ev.started.action": "Task state and budgets initialized",
      "missions.ev.waiting.action": "Waiting on external confirmation",
      "missions.ev.waiting.warn": "Human input required to continue",
      "missions.ev.model.action": "Model reasoning completed",
      "missions.ev.verify.action": "Verification gate evaluated",
      "missions.ev.cancelled": "Cancelled by user",
      "missions.ev.cancelled.action": "Cancellation requested",
      "missions.ev.failed": "Mission failed",
      "missions.ev.failed.action": "Unrecoverable error reached",
      "step.mission": "Mission",
      "step.event": "Event",
      "step.seq": "Sequence",
      "step.time": "Time",
      "step.agent.action": "Agent action",
      "step.tool": "Tool",
      "step.result": "Result",
      "project.last.indexed": "last indexed",
      "project.tracked": "recent files",
      "project.open.live": "◫ PRODUCT (LIVE)",
      "project.refresh": "REFRESH INDEX",
      "project.refresh.toast": "Project index refresh requested (mock).",
      "project.recent.files": "RECENT FILES",
      "project.recent.missions": "RECENT MISSIONS",
      "project.recent.artifacts": "RECENT ARTIFACTS",
      "cap.search": "Search capabilities…",
      "cap.empty": "No capabilities match",
      "cap.empty.hint": "Adjust the category or search query.",
      "cap.clear": "CLEAR FILTERS",
      "cap.source": "source",
      "cap.last.used": "last used",
      "cap.enabled": "enabled",
      "cap.disabled": "disabled",
      "cap.name": "Name",
      "cap.category": "Category",
      "cap.status": "Status",
      "cap.scope": "Permission scope",
      "cap.desc": "Description",
      "art.search": "Search artifacts…",
      "art.type.all": "ALL TYPES",
      "art.view.list": "LIST",
      "art.view.cards": "CARDS",
      "art.reload": "RELOAD",
      "art.col.name": "NAME",
      "art.col.type": "TYPE",
      "art.col.source": "SOURCE TASK",
      "art.col.created": "CREATED",
      "art.col.size": "SIZE",
      "art.col.status": "STATUS",
      "art.empty": "No artifacts match",
      "art.empty.hint": "Adjust the type filter or search query.",
      "art.clear": "CLEAR FILTERS",
      "art.name": "Name",
      "art.id": "Artifact ID",
      "art.source": "Source task",
      "art.created": "Created",
      "art.size": "Size",
      "art.path": "Path",
      "art.preview": "PREVIEW",
      "art.no.preview": "No preview available",
      "art.no.preview.hint": "Binary artifacts cannot be previewed in the workbench.",
      "art.copy.path": "COPY PATH",
      "art.copy.done": "Artifact path copied.",
      "art.download": "DOWNLOAD",
      "art.download.toast": "Download is mocked in this build.",
      "art.details": "DETAILS",
      "art.revisions": "REVISIONS",
      "art.revisions.hint": "Revision history (mock).",
      "runs.search": "Search runs…",
      "runs.range.all": "ALL TIME",
      "runs.range.24h": "LAST 24H",
      "runs.range.3d": "LAST 3 DAYS",
      "runs.range.7d": "LAST 7 DAYS",
      "runs.empty": "No runs match",
      "runs.empty.hint": "Adjust status, time range, or search.",
      "runs.clear": "CLEAR FILTERS",
      "runs.col.id": "RUN ID",
      "runs.col.mission": "MISSION",
      "runs.col.status": "STATUS",
      "runs.col.provider": "PROVIDER",
      "runs.col.model": "MODEL",
      "runs.col.started": "STARTED",
      "runs.col.duration": "DURATION",
      "runs.col.tools": "TOOLS",
      "runs.col.artifacts": "ARTIFACTS",
      "runs.col.error": "ERROR",
      "runs.open.mission": "OPEN MISSION",
      "prov.demo.title": "API KEY (VISUAL DEMO)",
      "prov.demo.desc": "Demo-only field: nothing is stored or sent. Real provider connections live in Settings → Runtime Configuration.",
      "prov.demo.placeholder": "sk-demo-••••••••••••",
      "prov.demo.show": "SHOW",
      "prov.demo.hide": "HIDE",
      "prov.demo.save": "SAVE (DEMO)",
      "prov.demo.saved": "Demo only — the key was not stored.",
      "prov.demo.settings": "OPEN RUNTIME CONFIG",
      "prov.model": "Model",
      "prov.timeout": "Timeout",
      "prov.last.check": "Last check",
      "prov.default": "Default",
      "prov.default.yes": "DEFAULT",
      "prov.check": "CHECK NOW",
      "prov.check.fail": "still unreachable (mock)",
      "prov.check.disabled": "enable the provider first",
      "prov.check.ok": "reachable (mock)",
      "modal.close": "CLOSE"
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
      "toast.close": "关闭提示",
      "workspace.label": "工作区",
      "sidebar.env": "桥接",
      "nav.overview": "总览",
      "nav.missions": "任务",
      "nav.project": "项目",
      "nav.capabilities": "能力",
      "nav.artifacts": "产物",
      "nav.runs": "运行记录",
      "nav.providers": "Provider",
      "nav.product": "◫ PRODUCT（实时）",
      "page.overview": "总览",
      "page.missions": "任务",
      "page.project": "项目",
      "page.capabilities": "能力",
      "page.artifacts": "产物",
      "page.runs": "运行记录",
      "page.providers": "PROVIDER",
      "page.settings": "设置",
      "inspector.close": "关闭详情面板",
      "settings.page": "偏好设置与运行时",
      "settings.page.sub": "界面偏好即时生效；运行时配置为真实连接。",
      "settings.done": "✓ 完成",
      "settings.preferences": "偏好设置",
      "pref.theme": "主题",
      "pref.theme.desc": "深色或浅色工作台外观",
      "pref.language": "语言",
      "pref.language.desc": "界面语言",
      "pref.density": "密度",
      "pref.density.desc": "行高与控件紧凑程度",
      "pref.comfortable": "舒适",
      "pref.compact": "紧凑",
      "pref.motion": "动效",
      "pref.motion.desc": "界面微过渡动画",
      "pref.on": "开",
      "pref.off": "关",
      "pref.defaultview": "默认视图",
      "pref.defaultview.desc": "启动时显示的页面",
      "pref.consolefont": "Console 字号",
      "pref.consolefont.desc": "任务日志与代码块字号",
      "pref.demomode": "演示模式",
      "pref.demomode.desc": "用演示数据填充 Mock 页面",
      "pref.loglimit": "日志显示数量",
      "pref.loglimit.desc": "作用于运行时与时间线列表（20–1000）",
      "filter.queued": "排队中",
      "filter.running": "运行中",
      "filter.waiting": "等待中",
      "filter.succeeded": "成功",
      "filter.failed": "失败",
      "filter.cancelled": "已取消",
      "state.retry": "重试",
      "demo.off.title": "演示模式已关闭",
      "demo.off.desc": "此页面在演示模式开启时展示 Mock 数据。重新开启即可预览工作台。",
      "demo.off.action": "开启演示模式",
      "ov.runtime": "Runtime",
      "ov.agent": "Agent",
      "ov.providers": "Provider",
      "ov.providers.online": "在线",
      "ov.capabilities": "能力",
      "ov.capabilities.total": "已注册",
      "ov.succeeded": "成功",
      "ov.failed": "失败",
      "ov.cancelled": "已取消",
      "ov.runs.hint": "最近任务",
      "ov.artifacts": "产物",
      "ov.artifacts.hint": "已存储输出",
      "ov.current.mission": "当前任务",
      "ov.step": "步骤",
      "ov.open.missions": "打开任务页",
      "ov.project": "当前项目",
      "ov.indexed": "已索引",
      "ov.open.project": "打开项目",
      "ov.open.console": "打开控制台",
      "ov.open.artifacts": "查看产物",
      "ov.recent.runs": "最近运行",
      "ov.recent.errors": "最近错误",
      "ov.no.errors": "近期无错误",
      "ov.runtime.logs": "运行时日志",
      "missions.summary": "任务",
      "missions.task": "任务 ID",
      "missions.started": "开始",
      "missions.provider": "Provider",
      "missions.tools": "工具调用",
      "missions.step": "步骤",
      "missions.duration": "持续时间",
      "missions.list": "任务列表",
      "missions.col.id": "ID",
      "missions.col.name": "名称",
      "missions.col.status": "状态",
      "missions.col.progress": "进度",
      "missions.col.duration": "耗时",
      "missions.empty": "该状态下暂无任务",
      "missions.empty.hint": "请尝试其他状态筛选。",
      "missions.clear.filter": "清除筛选",
      "missions.timeline": "时间线",
      "missions.pause": "❚❚ 暂停模拟",
      "missions.resume": "▶ 继续模拟",
      "missions.ev.queued": "任务已入队",
      "missions.ev.queued.action": "指令已接收并登记",
      "missions.ev.started": "Runtime 已启动",
      "missions.ev.started.action": "Task State 与预算已初始化",
      "missions.ev.waiting.action": "等待外部确认",
      "missions.ev.waiting.warn": "需要人工输入才能继续",
      "missions.ev.model.action": "模型推理完成",
      "missions.ev.verify.action": "验证门禁已评估",
      "missions.ev.cancelled": "已被用户取消",
      "missions.ev.cancelled.action": "已请求取消",
      "missions.ev.failed": "任务失败",
      "missions.ev.failed.action": "遇到不可恢复错误",
      "step.mission": "任务",
      "step.event": "事件",
      "step.seq": "序号",
      "step.time": "时间",
      "step.agent.action": "Agent 动作",
      "step.tool": "工具",
      "step.result": "结果",
      "project.last.indexed": "最近索引",
      "project.tracked": "最近文件",
      "project.open.live": "◫ PRODUCT（实时）",
      "project.refresh": "刷新索引",
      "project.refresh.toast": "已请求刷新项目索引（Mock）。",
      "project.recent.files": "最近文件",
      "project.recent.missions": "最近任务",
      "project.recent.artifacts": "最近产物",
      "cap.search": "搜索能力…",
      "cap.empty": "没有匹配的能力",
      "cap.empty.hint": "请调整分类或搜索词。",
      "cap.clear": "清除筛选",
      "cap.source": "来源",
      "cap.last.used": "最近使用",
      "cap.enabled": "已启用",
      "cap.disabled": "已停用",
      "cap.name": "名称",
      "cap.category": "分类",
      "cap.status": "状态",
      "cap.scope": "权限范围",
      "cap.desc": "描述",
      "art.search": "搜索产物…",
      "art.type.all": "全部类型",
      "art.view.list": "列表",
      "art.view.cards": "卡片",
      "art.reload": "重新加载",
      "art.col.name": "名称",
      "art.col.type": "类型",
      "art.col.source": "来源任务",
      "art.col.created": "创建时间",
      "art.col.size": "大小",
      "art.col.status": "状态",
      "art.empty": "没有匹配的产物",
      "art.empty.hint": "请调整类型筛选或搜索词。",
      "art.clear": "清除筛选",
      "art.name": "名称",
      "art.id": "产物 ID",
      "art.source": "来源任务",
      "art.created": "创建时间",
      "art.size": "大小",
      "art.path": "路径",
      "art.preview": "预览",
      "art.no.preview": "暂无可预览内容",
      "art.no.preview.hint": "二进制产物无法在工作台内预览。",
      "art.copy.path": "复制路径",
      "art.copy.done": "产物路径已复制。",
      "art.download": "下载",
      "art.download.toast": "当前版本为模拟下载。",
      "art.details": "详情",
      "art.revisions": "修订版本",
      "art.revisions.hint": "修订历史（Mock）。",
      "runs.search": "搜索运行记录…",
      "runs.range.all": "全部时间",
      "runs.range.24h": "最近 24 小时",
      "runs.range.3d": "最近 3 天",
      "runs.range.7d": "最近 7 天",
      "runs.empty": "没有匹配的运行记录",
      "runs.empty.hint": "请调整状态、时间范围或搜索词。",
      "runs.clear": "清除筛选",
      "runs.col.id": "运行 ID",
      "runs.col.mission": "任务",
      "runs.col.status": "状态",
      "runs.col.provider": "PROVIDER",
      "runs.col.model": "模型",
      "runs.col.started": "开始时间",
      "runs.col.duration": "耗时",
      "runs.col.tools": "工具",
      "runs.col.artifacts": "产物",
      "runs.col.error": "错误",
      "runs.open.mission": "打开任务",
      "prov.demo.title": "API KEY（视觉演示）",
      "prov.demo.desc": "仅作视觉演示：内容不会被保存或发送。真实的 Provider 连接位于 设置 → 运行时配置。",
      "prov.demo.placeholder": "sk-demo-••••••••••••",
      "prov.demo.show": "显示",
      "prov.demo.hide": "隐藏",
      "prov.demo.save": "保存（演示）",
      "prov.demo.saved": "仅演示——Key 未被保存。",
      "prov.demo.settings": "打开运行时配置",
      "prov.model": "模型",
      "prov.timeout": "超时",
      "prov.last.check": "最近检查",
      "prov.default": "默认",
      "prov.default.yes": "默认",
      "prov.check": "立即检查",
      "prov.check.fail": "仍然不可达（Mock）",
      "prov.check.disabled": "请先启用该 Provider",
      "prov.check.ok": "连接正常（Mock）",
      "modal.close": "关闭"
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
  let observer = null;
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
      const parentTag = node.parentElement && node.parentElement.tagName;
      if (parentTag === "SCRIPT" || parentTag === "STYLE" || parentTag === "NOSCRIPT") continue;
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

  function observeDocument() {
    if (observer && document.body) observer.observe(document.body, OBSERVER_OPTIONS);
  }

  function scheduleDocumentRefresh() {
    if (applying || observerQueued) return;
    observerQueued = true;
    window.setTimeout(() => {
      observerQueued = false;
      if (observer) observer.disconnect();
      try {
        applyDocument(document);
      } finally {
        observeDocument();
      }
    }, 0);
  }

  function bind() {
    const selector = document.getElementById("language-select");
    if (selector) {
      selector.value = locale;
      selector.addEventListener("change", () => setLocale(selector.value, true));
    }
    applyDocument(document);
    observer = new MutationObserver(scheduleDocumentRefresh);
    observeDocument();
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
