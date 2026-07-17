# PaperClaw v0.09 MCP Protocol Foundation — Phase A Handoff

## 1. 状态

- 状态：`PHASE_A_COMPLETE / OFFLINE_VALIDATED / THIRD_PARTY_INTEROP_NOT_VERIFIED`
- 仓库：`ZyfNO2/PaperClaw`
- 基线：`main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`
- 分支：`feat/v0.09-mcp-protocol-foundation`
- Draft PR：`#21`
- 最终 implementation commit：`f872a815f3ecf8f358a442580716fc46ab0e85f2`
- Handoff/docs commit：以 PR #21 当前 branch HEAD 为准；最终 SHA 在交付回复中记录。

本 Handoff 只宣告 **v0.09 Phase A 协议层完成**，不宣告完整 v0.09 MCP Tool Gateway MVP 完成。

## 2. 已完成内容

- 冻结 MCP `2025-11-25` 协议版本；
- 实现 `MCPServerConfig`、`MCPServerIdentity`、`MCPConnectionState`；
- 实现 `MCPCapabilitySnapshot`、`MCPToolDescriptor`；
- 实现 `MCPInvocationRequest`、`MCPInvocationResult`、`MCPError`；
- 实现本地 stdio JSON-RPC transport baseline；
- 实现 `connect → initialize → discover → call → close` 生命周期；
- 实现 `notifications/initialized` 与 request timeout cancellation；
- 实现分页 `tools/list` 与 discovery 原子提交；
- 实现保守、确定性、不可变的 Tool schema normalization；
- unknown / unsupported schema fail-closed；
- Server instructions 不保留正文、不进入 Prompt；
- 实现 deterministic fake MCP Server；
- 覆盖 timeout、disconnect、invalid JSON、wrong ID、invalid response、version mismatch、invalid result；
- stdio response 使用有界 `readline(max_message_bytes + 1)`，避免超大无换行响应先无界分配。

## 3. 明确未接入

- `ToolRegistry`；
- Permission / approval；
- capability selection / Top-K；
- Prompt 或 ContextOrchestrator；
- MCP Resources / Prompts；
- Trace、Run Budget、Agent Runtime；
- 远程写操作、副作用重试或幂等策略；
- 多 Server 路由、冲突处理、健康评分；
- capability cache / stale refresh / reconnect。

这些是后续 Phase B/C 或 Post-MVP 工作，不是本 PR 的缺失项。

## 4. 主要文件

### Runtime

- `src/paperclaw/mcp/__init__.py`
- `src/paperclaw/mcp/contracts.py`
- `src/paperclaw/mcp/schema.py`
- `src/paperclaw/mcp/transport.py`
- `src/paperclaw/mcp/session.py`

### Tests

- `tests/fixtures/fake_mcp_server.py`
- `tests/unit/test_mcp_protocol_foundation.py`

### Documentation / artifacts

- `Plan/PaperClaw_v0.09_MCP_Protocol_Foundation_Phase_A_SOP.md`
- `artifacts/v0_09/implementation_summary.md`
- `artifacts/v0_09/test_report.md`
- `artifacts/v0_09/known_limitations.md`
- `artifacts/v0_09/file_manifest.txt`
- `artifacts/v0_09/phase_a_protocol_foundation.md`
- `docs/handoff/PaperClaw_v0.09_MCP_Protocol_Foundation_Phase_A_HANDOFF.md`

## 5. 关键架构决定

1. **协议层独立**：`paperclaw.mcp` 不导入 Agent、Tool、Permission、Harness、Context 或 Trace。
2. **同步 single-flight**：Phase A 不引入 async framework 或 request multiplexing。
3. **生命周期严格**：initialize 前不能 discover/call；Tool 必须 discovery 成功后才能调用。
4. **协议故障 terminal**：timeout、disconnect、invalid JSON/response/ID/result 使 session 进入 `FAILED` 并关闭 transport，防止迟到响应污染后续请求。
5. **Discovery 原子性**：分页中任一页失败时不提交部分 Tool 集合。
6. **Schema fail-closed**：高级组合、引用、未知关键字和未知语义拒绝归一化。
7. **Prompt 隔离**：Server `instructions` 只记录被忽略的布尔事实，不保存正文。
8. **Secret 边界**：environment value 不进入 config fingerprint 或错误 metadata。
9. **结果类型收缩**：Phase A 只接受 text block 与 object `structuredContent`。
10. **无第二套 Runtime**：本 PR 不创建 MCP 专用 Agent、Registry、Permission 或 Trace 路径。

## 6. 测试与 CI

### 本地定向验证

环境：Linux / Python 3.13.5。

```text
PYTHONPATH=src python -m pytest tests/unit/test_mcp_protocol_foundation.py -q
16 passed in 17.40s
```

```text
PYTHONPATH=src python -m ruff check src/paperclaw/mcp \
  tests/unit/test_mcp_protocol_foundation.py \
  tests/fixtures/fake_mcp_server.py --select E9,F63,F7,F82
All checks passed!
```

`python -m compileall -q src/paperclaw/mcp tests`：PASS。

### GitHub Actions

最终 implementation commit CI：

- commit：`f872a815f3ecf8f358a442580716fc46ab0e85f2`
- run：`29513038780`
- Windows Server 2025 / Python 3.12；
- pytest：`521 passed, 0 failed, 0 skipped`；
- pytest exit status：`0`；
- Ruff E9/F63/F7/F82：`PASS`；
- artifact：`pytest-results-29513038780`；
- digest：`sha256:dc3544da93c5e235554d942264146bb2e2facceb3bd0261f57bbd9bd531a0a15`。

此前 implementation commit `a8bdb860658624cecac6c89f360f1ea2cb7193ea`
的 run `29512513387` 已验证：521 passed，0 failed，0 skipped，exit status 0，
Ruff PASS；artifact digest
`sha256:cb37600cea88ce1f98430183d6b95811c3719a9a8d63d54dcd728542be6eacc3`。

### 测试性质

- contract/schema 测试：离线单元测试；
- lifecycle/error 测试：真实本地 subprocess + stdio pipe，但 Server 是 deterministic fake；
- 未调用真实第三方 MCP Server；
- 未调用 Provider、Agent Runtime、ToolRegistry 或 Permission；
- 不把 Fake/Mock 测试描述为真实第三方 E2E。

## 7. SOP completion check

在包含本次 SOP、artifacts、Handoff 与 Git metadata 的 staged checkout 中，按仓库
`sop_completion_check.py` 的 checkbox 与 generic handoff contract 复核：

- SOP checkbox：17/17 completed；
- pending checkbox：0；
- generic v0.09 handoff artifacts：4/4 present；
- 缺失交接物：0。

当前执行容器无法解析 `github.com`，因此不能从 GitHub 重新 clone 完整仓库并直接
运行原始 hook 文件；该限制不影响 GitHub Actions 的完整 checkout 与全量测试。
本报告不把 contract-equivalent staged check 伪装成原始 hook 的 live execution。

## 8. 已知限制

- local stdio transport only；
- one active request per session；
- one Server per session；
- no reconnect / refresh / cache / health scoring；
- conservative JSON Schema subset；
- no schema-based argument validation yet；
- no image/audio/resource result support；
- no real third-party MCP Server interoperability validation；
- no Windows physical-process interoperability beyond GitHub Actions subprocess tests。

## 9. 下一位开发者接手步骤

Phase B 应从 normalized contract 接入现有执行路径，不能绕开现有 Tool contract：

1. 从 `main` 已合并状态重新确认 PR #21 的最终 SHA；
2. 为 `MCPToolDescriptor` 编写现有 `Tool` contract adapter；
3. 通过既有 `ToolRegistry → validate → Permission → execute` 路径注册；
4. 在真实 arguments 上二次验证 schema 与 Permission；
5. 接入 Run timeout / cancellation / call budget；
6. 先 redact 再 truncate，再进入既有 Trace；
7. 保证 MCP Server unavailable 不影响本地 Tool；
8. 使用独立 PR，不在 Phase A 分支继续堆 Context 或 capability selection。

建议验证命令：

```powershell
python -m pytest tests/unit/test_mcp_protocol_foundation.py -q
python -m pytest --basetemp=tmp/pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python .claude/hooks/sop_completion_check.py
```

## 10. 最终判断

`GO — Phase A protocol foundation complete.`

完整 v0.09 仍为 `PARTIAL`，因为 Registry、Permission、Trace 与 Context 接入属于
后续 Phase，且本 PR 明确禁止实现。
