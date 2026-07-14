# Tasks

- [x] Task 1: WP1 最小契约回归 + test_report.md 生成
  - [x] SubTask 1.1: 对 Context contract / Repository / Session / ContextBuilder / Compaction / Checkpoint / Resume 运行定向测试
  - [x] SubTask 1.2: 检查文档与实现字段漂移（contracts.py vs SOP §4 最小契约）
  - [x] SubTask 1.3: 确认未增加新的数据库表或恢复状态
  - [x] SubTask 1.4: 生成 `artifacts/v0_04/test_report.md`（M04-01..M04-08 矩阵 + 命令 + 结果 + GO/NO-GO 初判）
- [x] Task 2: WP2 一条集成演示
  - [x] SubTask 2.1: 编写 `tests/integration/test_v0_04_mvp_demo.py`
  - [x] SubTask 2.2: 覆盖 SOP §9 5 阶段：超预算→compaction→保留→Snapshot→Checkpoint→reopen→safe resume→pending mutation→recovery_required
  - [x] SubTask 2.3: 导出 `artifacts/v0_04/mvp_demo_trace.json`（含关键断言证据）
  - [x] SubTask 2.4: 运行测试确认 PASS
- [x] Task 3: WP3 生成 known_limitations.md
  - [x] SubTask 3.1: 按 SOP §10 后续增强边界分类（v0.04.1 候选池 + 不在当前 Gate 的增强项）
  - [x] SubTask 3.2: 写入 `artifacts/v0_04/known_limitations.md`
- [x] Task 4: WP3 生成 implementation_summary.md
  - [x] SubTask 4.1: 按 SOP §11 既有实现参考表说明实际借鉴的契约、测试和失败策略
  - [x] SubTask 4.2: 写入 `artifacts/v0_04/implementation_summary.md`（含 commits 列表、模块清单、设计决策摘要）
- [x] Task 5: WP3 生成 file_manifest.txt
  - [x] SubTask 5.1: 列出 v0.04 新增/修改的源码文件、测试文件、artifact 文件
  - [x] SubTask 5.2: 写入 `artifacts/v0_04/file_manifest.txt`
- [x] Task 6: WP3 文档同步
  - [x] SubTask 6.1: 更新 `README.md` 标注 v0.04 已完成能力
  - [x] SubTask 6.2: 更新 `docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md` 同步已实现部分
- [x] Task 7: WP3 只针对 MVP Claim 的独立 Review
  - [x] SubTask 7.1: 分发 subagent 按 SOP §8 GO/NO-GO 审核（不全量审核增强候选）
  - [x] SubTask 7.2: 处理阻塞项（无 BLOCKER；2 个 HIGH 已在 Phase F 提交前修复，3 个 MEDIUM 登记为 v0.04.1 候选）
- [x] Task 8: Commit 与 SOP 收尾
  - [x] SubTask 8.1: git commit Phase F 全部变更（`ace27d2`）
  - [x] SubTask 8.2: 运行 SOP 完成度 hook（`python .claude/hooks/sop_completion_check.py`）
  - [x] SubTask 8.3: 勾选 SOP §7 WP1-WP3 全部 checkbox

# Task Dependencies

- Task 2 依赖 Task 1（需先确认 M04 测试位置与字段一致性）
- Task 3, 4, 5 可并行（均从已有 SOP / artifacts 提取）
- Task 6 依赖 Task 1-5 完成（文档需引用最终结果）
- Task 7 依赖 Task 1-6 完成
- Task 8 依赖 Task 7 通过
