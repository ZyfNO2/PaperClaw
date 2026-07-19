/* PaperClaw Mock Data
   Single source of demo content for the workbench pages. Everything here is
   static presentation data: it never reaches the Python bridge and is never
   persisted. Times for the running mission are computed from load time so
   the demo feels alive without any backend.
*/
(() => {
  "use strict";

  const now = Date.now();
  const minutesAgo = (m) => new Date(now - m * 60000).toISOString();

  const project = {
    name: "PaperClaw",
    path: "G:\\PaperClaw",
    branch: "feat/desktop-workbench-redesign",
    status: "active",
    indexState: "indexed",
    description:
      "面向 Coding / Research 的轻量 Agent Runtime。PocketFlow 风格控制流，" +
      "Context、Tool、Permission、Session、Trace 与 Eval 保持 domain-independent。",
    lastIndexed: minutesAgo(41),
    recentFiles: [
      { name: "index.html", path: "src/paperclaw/desktop/static/index.html", modified: minutesAgo(12), size: 17432 },
      { name: "tokens.css", path: "src/paperclaw/desktop/static/styles/tokens.css", modified: minutesAgo(25), size: 5210 },
      { name: "app.js", path: "src/paperclaw/desktop/static/app.js", modified: minutesAgo(38), size: 27384 },
      { name: "app.py", path: "src/paperclaw/desktop/app.py", modified: minutesAgo(95), size: 26385 },
      { name: "test_static_assets.py", path: "tests/unit/desktop/test_static_assets.py", modified: minutesAgo(180), size: 6890 },
      { name: "AGENTS.md", path: "AGENTS.md", modified: minutesAgo(1440), size: 8120 }
    ]
  };

  const missions = [
    {
      id: "msn-0848", taskId: "task-9f2c71", name: "Capabilities 风险分级复核",
      status: "queued", startedAt: null, durationSec: 0, progress: 0,
      currentStep: "等待调度", stepsDone: 0, stepsTotal: 6,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 0, artifacts: 0, error: null
    },
    {
      id: "msn-0847", taskId: "task-8e1b04", name: "SeededResearch 文献调研：Agent Runtime 评估框架",
      status: "running", startedAt: minutesAgo(14), durationSec: 842, progress: 62,
      currentStep: "tool.web_search · 第 3 轮检索", stepsDone: 8, stepsTotal: 13,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 9, artifacts: 2, error: null
    },
    {
      id: "msn-0846", taskId: "task-7d0a93", name: "v0.30 验收测试修复与回归",
      status: "succeeded", startedAt: minutesAgo(188), durationSec: 1460, progress: 100,
      currentStep: "完成", stepsDone: 12, stepsTotal: 12,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 21, artifacts: 4, error: null
    },
    {
      id: "msn-0845", taskId: "task-6c9f52", name: "Context 压缩策略对比实验",
      status: "succeeded", startedAt: minutesAgo(430), durationSec: 2310, progress: 100,
      currentStep: "完成", stepsDone: 15, stepsTotal: 15,
      provider: "azure-openai", model: "gpt-4.1", toolCalls: 27, artifacts: 3, error: null
    },
    {
      id: "msn-0844", taskId: "task-5b8e31", name: "Provider 连接失败诊断",
      status: "failed", startedAt: minutesAgo(700), durationSec: 318, progress: 38,
      currentStep: "provider.connect 重试耗尽", stepsDone: 5, stepsTotal: 13,
      provider: "anthropic", model: "claude-opus-4.8", toolCalls: 4, artifacts: 1,
      error: "provider_configuration_error: 429 rate limit exceeded after 3 retries"
    },
    {
      id: "msn-0843", taskId: "task-4a7d20", name: "README 与 SOP 文档同步",
      status: "succeeded", startedAt: minutesAgo(1500), durationSec: 690, progress: 100,
      currentStep: "完成", stepsDone: 8, stepsTotal: 8,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 11, artifacts: 2, error: null
    },
    {
      id: "msn-0842", taskId: "task-396c1f", name: "跨领域修复型测试题集生成",
      status: "waiting", startedAt: minutesAgo(1600), durationSec: 145, progress: 22,
      currentStep: "等待人工确认题集范围", stepsDone: 2, stepsTotal: 9,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 3, artifacts: 0, error: null
    },
    {
      id: "msn-0841", taskId: "task-285b0e", name: "Trace 导出与审查报告",
      status: "cancelled", startedAt: minutesAgo(2880), durationSec: 402, progress: 45,
      currentStep: "用户取消", stepsDone: 4, stepsTotal: 9,
      provider: "azure-openai", model: "gpt-4.1", toolCalls: 6, artifacts: 1, error: null
    },
    {
      id: "msn-0840", taskId: "task-174a9d", name: "Capabilities 清单核对",
      status: "succeeded", startedAt: minutesAgo(4300), durationSec: 512, progress: 100,
      currentStep: "完成", stepsDone: 7, stepsTotal: 7,
      provider: "openai-compatible", model: "gpt-5.2-codex", toolCalls: 8, artifacts: 2, error: null
    },
    {
      id: "msn-0839", taskId: "task-06398c", name: "Artifacts 存储迁移验证",
      status: "failed", startedAt: minutesAgo(5760), durationSec: 260, progress: 30,
      currentStep: "workspace 校验失败", stepsDone: 3, stepsTotal: 10,
      provider: "local-ollama", model: "qwen3:32b", toolCalls: 3, artifacts: 0,
      error: "workspace_not_found: E:\\legacy-workspace 不存在或不可读"
    }
  ];

  const timeline = {
    "msn-0847": [
      { seq: 1, kind: "system", title: "mission.queued", label: "任务进入队列", at: minutesAgo(14), status: "succeeded",
        agentAction: "接收用户指令并登记 Mission", tool: null, result: "queue position=1", warning: null, error: null },
      { seq: 2, kind: "system", title: "mission.started", label: "Runtime 开始执行", at: minutesAgo(14), status: "succeeded",
        agentAction: "初始化 Task State 与预算 (max_steps=13)", tool: null, result: "run_id=run-7f3a21", warning: null, error: null },
      { seq: 3, kind: "model", title: "model.started", label: "规划调研提纲", at: minutesAgo(13), status: "succeeded",
        agentAction: "拆解主题：评估维度、对比对象、证据来源", tool: null, result: "outline = 6 sections", warning: null, error: null },
      { seq: 4, kind: "tool", title: "tool.completed", label: "web_search · agent runtime evaluation", at: minutesAgo(12), status: "succeeded",
        agentAction: "第 1 轮检索：通用评估框架", tool: "web_search", result: "12 results · 4 kept", warning: null, error: null },
      { seq: 5, kind: "model", title: "model.completed", label: "汇总第 1 轮证据", at: minutesAgo(10), status: "succeeded",
        agentAction: "提炼评估维度候选：正确性 / 可解释性 / 成本", tool: null, result: "notes.md §1-2 drafted", warning: null, error: null },
      { seq: 6, kind: "tool", title: "tool.completed", label: "file_write · notes/lit-review.md", at: minutesAgo(9), status: "succeeded",
        agentAction: "写入调研笔记初稿", tool: "file_write", result: "artifact=lit-review-notes.md r1", warning: null, error: null },
      { seq: 7, kind: "verify", title: "verification.started", label: "证据覆盖率检查", at: minutesAgo(8), status: "succeeded",
        agentAction: "核对每个评估维度是否有 ≥2 个来源", tool: null, result: "coverage=0.71", warning: "coverage below target 0.8", error: null },
      { seq: 8, kind: "verify", title: "verification.completed", label: "verification=passed · 补充检索建议", at: minutesAgo(8), status: "succeeded",
        agentAction: "接受结果并规划补充检索", tool: null, result: "2 dimensions need more sources", warning: null, error: null },
      { seq: 9, kind: "tool", title: "tool.started", label: "web_search · agent benchmark reproducibility", at: minutesAgo(3), status: "running",
        agentAction: "第 3 轮检索：可复现性证据", tool: "web_search", result: null, warning: null, error: null },
      { seq: 10, kind: "model", title: "model.streaming", label: "整理第 2 轮检索结果…", at: minutesAgo(1), status: "running",
        agentAction: "流式生成对比段落", tool: null, result: null, warning: null, error: null }
    ]
  };

  const capabilities = [
    { id: "cap-file-read", name: "file_read", category: "File Operations", type: "Tool",
      desc: "读取工作区内文本文件，自动截断超长内容并保留行号。", status: "ready", source: "runtime core",
      enabled: true, lastUsed: minutesAgo(9), scope: ["workspace:read"], risk: "low" },
    { id: "cap-file-write", name: "file_write", category: "File Operations", type: "Tool",
      desc: "原子写入工作区文件；覆盖前生成备份并写入 Trace。", status: "ready", source: "runtime core",
      enabled: true, lastUsed: minutesAgo(9), scope: ["workspace:write"], risk: "medium" },
    { id: "cap-shell", name: "shell_exec", category: "Developer Operations", type: "Tool",
      desc: "在受控预算内执行 PowerShell 命令；危险命令需 Permission 放行。", status: "ready", source: "runtime core",
      enabled: true, lastUsed: minutesAgo(26), scope: ["workspace:write", "process:spawn"], risk: "high" },
    { id: "cap-web-search", name: "web_search", category: "Web Operations", type: "Connector",
      desc: "检索公开网页并返回摘要；429 自动 backoff，结果标记为 candidate。", status: "ready", source: "connector:web",
      enabled: true, lastUsed: minutesAgo(3), scope: ["network:egress"], risk: "medium" },
    { id: "cap-paper-fetch", name: "paper_fetch", category: "Web Operations", type: "Connector",
      desc: "按 DOI 拉取论文元数据与 PDF；内容在核验前不作为 verified evidence。", status: "degraded", source: "connector:research",
      enabled: false, lastUsed: minutesAgo(2880), scope: ["network:egress"], risk: "medium" },
    { id: "cap-sqlite", name: "sqlite_store", category: "Runtime Capabilities", type: "Runtime",
      desc: "Task State、Trace 与 Artifact 索引的本地 SQLite 持久化。", status: "ready", source: "runtime core",
      enabled: true, lastUsed: minutesAgo(1), scope: ["workspace:write"], risk: "low" },
    { id: "cap-trace", name: "trace_export", category: "Runtime Capabilities", type: "Runtime",
      desc: "导出 Mission 事件流为 JSON，用于审查与评估回放。", status: "ready", source: "runtime core",
      enabled: true, lastUsed: minutesAgo(188), scope: ["workspace:read"], risk: "low" },
    { id: "cap-pipeline", name: "academic-pipeline", category: "Skills", type: "Skill",
      desc: "文献调研 → 综述撰写 → 自审的编排流水线（SeededResearch domain）。", status: "ready", source: "skill:academic",
      enabled: true, lastUsed: minutesAgo(430), scope: ["workspace:read", "network:egress"], risk: "low" }
  ];

  const artifacts = [
    { id: "art-1042", name: "lit-review-notes.md", type: "markdown", sourceTask: "msn-0847",
      createdAt: minutesAgo(9), sizeBytes: 18420, status: "current", path: "artifacts/msn-0847/lit-review-notes.md",
      preview: { kind: "markdown", lines: ["# Agent Runtime 评估框架调研笔记", "", "## 1. 评估维度候选", "- 正确性：任务完成率 / 验证门禁通过率", "- 可解释性：Trace 完整度、决策可回放", "- 成本：token / 时延 / 工具调用预算", "", "## 2. 待补充", "- [ ] 可复现性证据（第 3 轮检索进行中）"] } },
    { id: "art-1041", name: "sop-compliance-report.md", type: "markdown", sourceTask: "msn-0846",
      createdAt: minutesAgo(150), sizeBytes: 9310, status: "current", path: "artifacts/msn-0846/sop-compliance-report.md",
      preview: { kind: "markdown", lines: ["# v0.30 验收报告", "", "- [x] shutdown 生命周期测试", "- [x] 路径归一化", "- [ ] 浏览器模式端到端", "", "结论：GO（附 1 项 known limitation）"] } },
    { id: "art-1040", name: "trace-msn-0846.json", type: "json", sourceTask: "msn-0846",
      createdAt: minutesAgo(185), sizeBytes: 154220, status: "current", path: "artifacts/msn-0846/trace.json",
      preview: { kind: "code", lines: ["{", "  \"run_id\": \"run-6e2b90\",", "  \"events\": [", "    {\"seq\": 1, \"type\": \"mission.started\"},", "    {\"seq\": 2, \"type\": \"model.started\"}", "  ]", "}"] } },
    { id: "art-1039", name: "fix-test-session.py", type: "code", sourceTask: "msn-0846",
      createdAt: minutesAgo(200), sizeBytes: 4210, status: "current", path: "artifacts/msn-0846/fix-test-session.py",
      preview: { kind: "code", lines: ["def stop_cached_runtimes():", "    # 进程退出前停止缓存的 TaskRuntime", "    for rt in _REGISTRY.values():", "        rt.shutdown(timeout=2.0)"] } },
    { id: "art-1038", name: "capability-matrix.csv", type: "csv", sourceTask: "msn-0845",
      createdAt: minutesAgo(400), sizeBytes: 2960, status: "current", path: "artifacts/msn-0845/capability-matrix.csv",
      preview: { kind: "code", lines: ["capability,compression,loss", "goal,none,0", "constraints,summary,low", "evidence_refs,reference,none"] } },
    { id: "art-1037", name: "architecture-overview.png", type: "image", sourceTask: "msn-0845",
      createdAt: minutesAgo(420), sizeBytes: 240118, status: "current", path: "artifacts/msn-0845/architecture.png",
      preview: null },
    { id: "art-1036", name: "experiment-results.json", type: "json", sourceTask: "msn-0845",
      createdAt: minutesAgo(428), sizeBytes: 52440, status: "current", path: "artifacts/msn-0845/results.json",
      preview: { kind: "code", lines: ["{ \"compression\": \"summary\",", "  \"retention\": 0.87,", "  \"cost_delta\": -0.31 }"] } },
    { id: "art-1035", name: "review-notes.md", type: "markdown", sourceTask: "msn-0843",
      createdAt: minutesAgo(1490), sizeBytes: 6100, status: "superseded", path: "artifacts/msn-0843/review-notes.md",
      preview: { kind: "markdown", lines: ["# 文档同步审查", "", "- README 与 SOP checkbox 对齐", "- 新增 v0.30 handoff 链接"] } },
    { id: "art-1034", name: "benchmark-log.txt", type: "log", sourceTask: "msn-0844",
      createdAt: minutesAgo(698), sizeBytes: 12880, status: "current", path: "artifacts/msn-0844/provider-benchmark.log",
      preview: { kind: "code", lines: ["10:02:11 connect -> 429 (retry 1/3)", "10:02:31 connect -> 429 (retry 2/3)", "10:03:01 connect -> 429 (retry 3/3)", "10:03:01 abort: provider_configuration_error"] } },
    { id: "art-1033", name: "decision-register.md", type: "markdown", sourceTask: "msn-0840",
      createdAt: minutesAgo(4290), sizeBytes: 7450, status: "current", path: "artifacts/msn-0840/decision-register.md",
      preview: { kind: "markdown", lines: ["# 决策登记册", "", "| 决策 | 理由 |", "| --- | --- |", "| SQLite 优先 | 无评估证据前不引入向量库 |"] } }
  ];

  const providers = [
    { id: "prov-openai", name: "openai-compatible", model: "gpt-5.2-codex",
      endpoint: "https://api.openai.com/v1", status: "online", enabled: true,
      isDefault: true, timeoutSec: 60, lastCheck: minutesAgo(6) },
    { id: "prov-azure", name: "azure-openai", model: "gpt-4.1",
      endpoint: "https://zyf-resource.openai.azure.com", status: "degraded", enabled: true,
      isDefault: false, timeoutSec: 90, lastCheck: minutesAgo(32) },
    { id: "prov-anthropic", name: "anthropic", model: "claude-opus-4.8",
      endpoint: "https://api.anthropic.com", status: "unreachable", enabled: true,
      isDefault: false, timeoutSec: 60, lastCheck: minutesAgo(700) },
    { id: "prov-ollama", name: "local-ollama", model: "qwen3:32b",
      endpoint: "http://127.0.0.1:11434", status: "offline", enabled: false,
      isDefault: false, timeoutSec: 30, lastCheck: minutesAgo(5760) }
  ];

  const runtimeLogs = [
    { at: minutesAgo(15), level: "info", message: "runtime started · v0.30 · sqlite store attached" },
    { at: minutesAgo(14), level: "info", message: "provider check: openai-compatible online (env source)" },
    { at: minutesAgo(14), level: "info", message: "mission msn-0847 queued → running" },
    { at: minutesAgo(8), level: "warn", message: "verification coverage 0.71 below target 0.8 — supplementary search planned" },
    { at: minutesAgo(5), level: "info", message: "tool budget: 9/20 tool calls used for run-7f3a21" },
    { at: minutesAgo(1), level: "error", message: "connector paper_fetch degraded: 2 consecutive timeouts" }
  ];

  const runs = missions
    .filter((m) => m.status !== "running" && m.status !== "queued")
    .map((m) => ({
      id: `run-${m.taskId.slice(5)}`, mission: m.name, missionId: m.id, project: project.name,
      status: m.status, provider: m.provider, model: m.model,
      startedAt: m.startedAt, durationSec: m.durationSec,
      toolCalls: m.toolCalls, artifacts: m.artifacts, error: m.error
    }));

  window.PaperClawMock = {
    project, missions, timeline, capabilities, artifacts, providers, runtimeLogs, runs,
    runningMissionId: "msn-0847"
  };
})();
