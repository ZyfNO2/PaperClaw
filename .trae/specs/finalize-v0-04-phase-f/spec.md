# Finalize v0.04 Phase F: MVP 收口与留档 Spec

## Why

v0.04 的 Phase A-E 已交付全部核心模块（Context 契约、Session 持久化、PocketFlow 适配器、ContextBuilder、Compaction、Safe resume boundary），单元测试 344 passed / 1 skipped。SOP 已重构为 MVP 收口版（§7 收口工作包 WP1-WP3 + §8 8 个 Gate 场景 + §9 最小交付）。Phase F 的目标是闭合 WP1-WP3，让 v0.04 达到 §8 GO 标准。已实现的增强代码可保留但不自动进入 Gate（SOP §3.2）。

## What Changes

- **WP1 — 最小契约回归**：对 Context contract、Repository、Session、ContextBuilder、Compaction、Checkpoint、Resume 运行定向测试；修正文档与实现字段漂移；确认未增加新的数据库表或恢复状态
- **WP2 — 一条集成演示**：编写 `tests/integration/test_v0_04_mvp_demo.py`，覆盖 SOP §9 演示流程 5 阶段（长任务→超预算→压缩→保留→Snapshot→Checkpoint→reopen→safe resume→pending mutation→recovery_required），导出 `mvp_demo_trace.json`
- **WP3 — 最小留档**：生成 SOP §9 交付物清单的 5 个文件
  - `artifacts/v0_04/test_report.md`（M04-01..M04-08 测试矩阵 + 命令 + 结果）
  - `artifacts/v0_04/mvp_demo_trace.json`
  - `artifacts/v0_04/known_limitations.md`（按 SOP §10 后续增强边界分类）
  - `artifacts/v0_04/implementation_summary.md`（按 SOP §11 借鉴表说明实际借鉴）
  - `artifacts/v0_04/file_manifest.txt`
- **WP3 — 文档同步**：更新 `README.md` 标注 v0.04 已完成能力；更新 `docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md` 反映已实现部分
- **WP3 — 独立 Review**：分发 subagent 只针对 MVP Claim（§8 GO/NO-GO）审核，不全量审核增强候选

## Impact

- Affected specs: v0.04 Context/Session/SQLite MVP（SOP §7 WP1-WP3, §8 Gate, §9 交付, §10 边界, §11 参考）
- Affected code:
  - 新增：`tests/integration/test_v0_04_mvp_demo.py`
  - 新增 artifacts：`artifacts/v0_04/{test_report.md, mvp_demo_trace.json, known_limitations.md, implementation_summary.md, file_manifest.txt}`
  - 修改：`README.md`、`docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md`
  - 不修改：`src/paperclaw/**` 源码（除非 WP1 发现字段漂移或 bug）

## ADDED Requirements

### Requirement: M04 Gate 验证报告

系统 SHALL 输出 `artifacts/v0_04/test_report.md`，记录 SOP §8 测试矩阵 M04-01..M04-08 每一项的实际测试命令、通过/失败状态、失败根因（若有）。报告末尾给出 GO/NO-GO 初判。

#### Scenario: 全部 M04 通过
- **WHEN** 运行 M04-01..M04-08 对应测试
- **THEN** test_report.md 标注全部 PASS，附 pytest 输出摘要，初判为 GO

#### Scenario: 某项 M04 失败
- **WHEN** 某项测试失败
- **THEN** test_report.md 标注 FAIL，附失败根因与修复建议；主线程在 Phase F 内修复后重跑

### Requirement: 端到端集成演示

系统 SHALL 提供 `tests/integration/test_v0_04_mvp_demo.py`，以单条 pytest 测试形式演示 SOP §9 流程，并导出 `mvp_demo_trace.json` 作为可复现证据。

#### Scenario: 演示成功
- **WHEN** 运行 test_v0_04_mvp_demo.py
- **THEN** 测试 PASS，mvp_demo_trace.json 包含 5 阶段证据：超预算触发、compaction summary、required constraint 保留、Checkpoint 提交、reopen、safe resume 决策为 ok、pending mutation 注入后决策为 recovery_required

### Requirement: 最小交付物清单

系统 SHALL 在 `artifacts/v0_04/` 下提供 SOP §9 列出的 5 个文件，每个文件内容真实反映当前实现状态，不得填充占位文本。更细的 JSON artifact 可保留但不要求为了填满旧清单继续制造报告。

### Requirement: 文档同步

系统 SHALL 更新 `README.md` 标注 v0.04 已完成能力（不描述未实现能力为已完成）；`docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md` 同步已实现部分，未实现部分保持 Roadmap 标注。

### Requirement: 只针对 MVP Claim 的独立 Review

系统 SHALL 分发 subagent 按 SOP §8 GO/NO-GO 标准审核 MVP Claim，不全量审核增强候选。Review 范围：M04-01..M04-08 全 pass、一条集成演示可复现、未出现 Context 跨 scope 泄漏、未丢失 required constraint / Evidence ref、未自动重放未知副作用、交付物只描述已验证能力。

## MODIFIED Requirements

### Requirement: v0.04 完成判定

SOP §8 GO 标准要求 M04-01..M04-08 全 pass、一条集成演示可复现、未出现 Context 跨 scope 泄漏、未丢失 required constraint / Evidence ref、未自动重放未知副作用、交付物只描述已验证能力。数据库 upgrade、并发 writer、自动 recovery 等增强项失败不阻止 v0.04 MVP GO，因为它们已不在当前 Gate（SOP §8 NO-GO 末尾）。Phase F 完成后，v0.04 可宣布 GO。
