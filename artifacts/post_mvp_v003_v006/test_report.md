# v0.03–v0.06 Post-MVP 选做切片测试报告

## 被测提交

- SQLite Doctor：`6f42a06d2c00d6d9c43974d2ac62f6881b8505a1`
- Verification Inspector：`973139a6e7c2e5544c6b4f3b2285fbf64f2ed930`

## 自动化结果

GitHub Actions run `29363818831` / run #42：

- Windows pytest：380 passed；
- failed：0；
- skipped：0；
- Ruff high-signal checks：PASS。

测试 artifact：`pytest-results-29363818831`，对应 branch head `973139a6e7c2e5544c6b4f3b2285fbf64f2ed930`。

## 新增验证

### SQLite Doctor

- migrated database 返回 `ok` 和当前 schema version；
- missing database 返回 `DATABASE_NOT_FOUND`；
- corrupt database 返回 `SQLITE_DATABASE_ERROR`；
- CLI 输出结构化 JSON 并使用退出码区分健康/不健康。

### Verification Inspector

- TUI headless run 存在 Inspector；
- verification aggregate 正确渲染；
- `/new` 可清理 Inspector 状态；
- Bridge 保持 UI-local monotonic sequence；
- raw verification checks / observed command output 不进入 UI payload；
- 原有 duplicate submit、cooperative cancel、narrow layout 仍通过。

## 验证边界

以下未被自动化结果证明：

- 用户真实 SQLite 数据库副本的健康状态；
- Windows Terminal 中 Inspector 的实际可读性；
- Live Provider 产生真实 VerificationResult 后的交互展示；
- v0.06 原有真实 task/cancel/resize 验收。

这些项目保持 `PENDING REAL TEST`，没有把 FakeModel、headless Textual 或 SQLite fixture 描述为真实端到端验证。
