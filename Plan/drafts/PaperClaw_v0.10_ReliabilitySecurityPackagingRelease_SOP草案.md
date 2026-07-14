# PaperClaw v0.10：可靠性、安全加固、打包与可复现发布 SOP 草案

> 状态：后期 SOP 草案，依赖 v0.05–v0.09 核心契约稳定  
> 目标：从干净环境安装、运行、升级、恢复、评估和演示 PaperClaw，并对安全边界、许可证和已知限制做诚实声明

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md)，并重新检查所有 vendored / adapted 实现的 license、commit 与 dirty 状态。

## 目录

- [目标、债务与 Sandbox 选型](#1-目标与非目标)
- [版本、跨平台与安全](#4-phase-arelease-contract-与版本冻结)
- [恢复、供应链与交互降级](#7-phase-dsqlitebackup-与-crash-recovery)
- [CI、Demo 与发布检查](#10-phase-gci性能与-demo-fixture)
- [风险、遗漏与发布 Gate](#12-风险预案)
- [交付与参考](#15-预期交付)

## 1. 目标与非目标

### 目标

- Windows 11 干净环境可安装、运行、卸载；
- WSL / Ubuntu 至少通过 contract test；
- Secret 不进入输出、Trace、DB 和 export；
- SQLite 可 migration、backup、restore 和 crash recovery；
- wheel / sdist 可构建并 clean-install；
- CI 阻止功能、安全、许可证和迁移回归；
- Offline demo 可重复；
- Release 有 manifest、checksum、SBOM、NOTICE 和 known limitations。

### 非目标

- 宣称 native mode 是 OS sandbox；
- 多租户云安全；
- 插件市场和任意第三方代码加载；
- 分布式数据库 / Worker；
- 自动执行不可逆 migration；
- 支持所有 Shell 方言；
- 自动 PyPI 发布作为 MVP 必需条件。

## 2. 当前可见漂移与债务

执行 v0.10 前重新核对，当前已观察到：

- package version 在 `pyproject.toml`、`paperclaw/__init__.py`、Model User-Agent 等位置可能多处硬编码；
- Roadmap 使用 `v0.01`，包使用 `0.0.1`，语义未统一；
- 当前 BashTool 实际是 Windows PowerShell executor，不是通用 Bash；
- regex denylist 不是 sandbox；
- FileWrite / FileEdit 需要 atomic replace 和 expected hash；
- `.env` 来源和 workspace 关系需明确；
- 尚未形成 CI、锁文件、SBOM、release workflow；
- 根 LICENSE 与 vendored PocketFlow 的版权归属需要拆清；
- dirty worktree 不能用于正式发布。

## 3. Shell / Sandbox 选型

### 方案 A：Native-first + Optional Sandbox Adapter（推荐）

```text
ShellExecutor
  ├── WindowsPowerShellExecutor
  ├── PwshExecutor
  ├── PosixExecutor
  └── Wsl / Container Sandbox Adapter（optional）
```

优点：兼容当前项目、一月内可落地、面试可解释。  
限制：native mode 只有应用级 Permission 和 workspace boundary，不能宣称强隔离。

### 方案 B：Container-first

优点：隔离、环境和资源限制更强。  
风险：Windows path、Docker Desktop、网络、mount、性能和 TUI 复杂度高。

v0.10 采用方案 A，方案 B 作为 opt-in executor。

## 4. Phase A：Release Contract 与版本冻结

- 支持矩阵：Windows 11 + Python 3.12/3.13 Tier 1；WSL/Ubuntu Tier 2；
- 明确 Windows PowerShell 5.1、pwsh 7、POSIX backend 范围；
- 推荐 milestone `v0.10` 映射 package `0.10.0`；
- 版本唯一来源为 package metadata，CLI、User-Agent、Trace 从 `importlib.metadata` 读取；
- 定义 ReleaseManifest：commit、dirty、package/schema/policy/prompt/fixture version、OS/Python、lock hash；
- 冻结 CLI exit code、stdout/stderr 和 JSON output contract；
- dirty build 拒绝或明确标记 development build。

Gate：wheel metadata、`paperclaw --version`、User-Agent、Trace manifest 完全一致。

## 5. Phase B：跨平台 Shell 与 Path Contract

- `BashTool` 名称保持兼容，但内部记录 `shell_backend/version/encoding`；
- Windows 不假设 POSIX 语法，WSL/Linux 不尝试启动不存在的 Windows PowerShell；
- workspace 在创建时绑定平台，不自动翻译任意 Windows/WSL 路径；
- 覆盖空格、中文、盘符、UNC、长路径、保留名、CRLF/LF、junction/symlink；
- timeout 后清理整个 process tree；
- Ctrl+C / cancel 行为稳定；
- ToolResult contract 跨 backend 一致，不要求 shell 文本逐字相同。

## 6. Phase C：Permission、安全与 Secret

- PermissionEngine 在 executor 前强制 `allow/ask/deny/sandbox`；
- policy 输入包括 tool、normalized args、workspace、side effect、network、role、task scope；
- denylist 仅 defense-in-depth；解析不确定时 ask/sandbox/deny；
- URL 工具校验 scheme、host、IP、redirect，防 localhost、link-local、metadata IP 和 DNS rebinding；
- Secret 只来自 env / explicit secret provider，不写 DB/Trace/fixture；
- 统一 redactor 覆盖 Prompt、tool output、exception、HTTP body、dataclass repr；
- sandbox profile 记录 network、filesystem、CPU、memory、time、process 限制；
- 每次运行标记 `isolation_level=application|wsl|container`；
- malicious README/PDF/网页不得提升权限。

Gate：secret canary 在 stdout/stderr/Trace/DB/export 中为 0；native UI 明示未 OS 隔离。

## 7. Phase D：SQLite、Backup 与 Crash Recovery

- Repository 隔离 SQL；`foreign_keys=ON`、WAL、busy_timeout；
- `schema_migrations(version, checksum, applied_at, app_version)`；
- migration 单事务，启动前 backup；过新 DB refuse-open；
- 不自动 destructive downgrade；
- backup 使用 SQLite online backup API，不能只复制活跃 WAL 的 `.db`；
- backup manifest + checksum + restore drill；
- 文件修改：同目录 temp → flush/fsync → `os.replace`；
- FileEdit expected hash + optimistic concurrency；
- Tool 状态：proposed → authorized → started → succeeded/failed/unknown；
- started 后崩溃标记 `unknown_outcome`，副作用工具不自动重放；
- append-only event 与 snapshot 使用 transaction / outbox；
- 重启清理 lease、orphan child process、pending permission。

Gate：故障注入后 `integrity_check` 通过，恢复不重复 write/bash，backup 可还原 Session/Trace。

## 8. Phase E：Supply Chain、License 与 Packaging

- 锁定 direct + transitive dependencies，CI frozen install；
- Runtime / dev / optional TUI / eval dependencies 分离；
- CI：ruff、pytest、build、clean install、`pip check`、wheel/sdist smoke；
- dependency vulnerability、secret、license scan；
- 生成 CycloneDX 或 SPDX SBOM；
- 固定 PocketFlow 来源 commit；
- PaperClaw LICENSE 与 third-party PocketFlow MIT / NOTICE 分离；
- Draftpaper-loop 等许可未审清时只借鉴思想；
- 构建物解包检查，不含 `.env`、tmp、secret、绝对路径和 artifacts；
- 生成 sha256、Release Manifest、Changelog、THIRD_PARTY / NOTICE。

Gate：clean venv 安装和卸载成功；构建物 license / provenance 完整。

## 9. Phase F：CLI / TUI 降级

- 人类输出与 `--json` 分离；diagnostic 走 stderr；
- SIGINT 第一次取消当前 Run，第二次强制退出；
- 非交互环境遇到 permission ask 时 fail-closed 或使用显式 policy；
- Textual 是 optional extra；无 TTY、TERM=dumb、窄终端自动回退 CLI；
- 不展示 hidden CoT，只展示 reason summary、Evidence、policy decision；
- TUI 只消费 Event / Snapshot，不直连 Tool / DB；
- Event burst 有 bounded queue、coalescing 和 backpressure；
- 退出时明确处理后台任务和 pending Permission。

## 10. Phase G：CI、性能与 Demo Fixture

### CI

- Windows Tier 1：unit / integration / packaging 必跑；
- Ubuntu Tier 2：contract / compatibility；
- slow / network / real-model Eval 单独 workflow；
- PR 默认不需要真实 API Key。

### Offline Demo

- FakeModel；
- 固定 workspace fixture；
- fixed clock / UUID / seed；
- expected Event sequence / diff / VerificationResult；
- 无网络、无用户 Secret、无本机绝对路径。

### 性能基线

先测 baseline 再冻结阈值：

- CLI cold start；
- first event latency；
- SQLite append；
- 1000 event Replay；
- TUI steady memory；
- Context build latency；
- cancellation latency；
- Hybrid retrieval latency / cost。

性能回归需绑定 commit 和 config，不能凭感觉宣称优化。

## 11. Phase H：Release Candidate Checklist

- [ ] 工作树 clean，tag/version/changelog/manifest 一致；
- [ ] SOP hook、测试和 CI 通过；
- [ ] Windows Tier 1 clean install 通过；
- [ ] DB migrate / backup / restore / crash drill 通过；
- [ ] Permission bypass / Secret canary / SSRF / path escape corpus 通过；
- [ ] wheel / sdist / metadata / pip check 通过；
- [ ] dependency / secret / license scan 和 SBOM 完成；
- [ ] THIRD_PARTY / NOTICE / PocketFlow attribution 核对；
- [ ] Offline demo 无网络、无真实 Key、无绝对路径；
- [ ] Known Limitations 明确 native 非 sandbox、Tier 2 范围、DB 兼容窗口；
- [ ] artifact sha256、release notes、rollback instructions 和 support matrix；
- [ ] 安装、升级、拒绝危险降级、卸载、数据保留测试；
- [ ] final commit 后独立 Review 与 completion hook。

## 12. 风险预案

| 风险 | 概率/影响 | 预案 |
|---|---|---|
| Shell denylist 绕过 | 高/高 | Policy + ask + optional sandbox |
| Windows 子进程残留 | 高/高 | Job Object / process tree cleanup fixture |
| WAL 假备份 | 中/高 | online backup API + restore drill |
| Unknown outcome 重复副作用 | 中/高 | idempotency + reconcile，禁止自动重放 |
| `.env` / HTTP / tool 泄密 | 中/极高 | central redactor + canary |
| WSL path / newline 差异 | 高/中 | platform-bound workspace + contract tests |
| TUI consumer 拖垮 Runtime | 中/中 | bounded queue，delta 可合并，terminal event 不丢 |
| migration 中断 | 中/高 | transaction + prebackup + checksum |
| supply-chain 恶意更新 | 低/极高 | lock、audit、最小依赖、人工 merge |
| Demo 依赖真实 API | 高/中 | Offline fixture 是 Release Artifact |

## 13. 用户可能遗漏的发布难点

- 版本唯一来源；
- LICENSE ownership 与第三方 attribution；
- Permission 不等于 sandbox；
- crash 后 `unknown_outcome`；
- SQLite WAL backup 必须恢复演练；
- 文件写入也需要 atomic / hash / TOCTOU；
- CI permission prompt 会挂死；
- 先 redact 再 truncate；
- TUI resize、encoding、Ctrl+C 和 backpressure；
- `.env` 不应隐式信任任意 workspace；
- wheel 可能带入本机路径和 secret；
- 升级可恢复不代表安全降级；
- demo 的时间、UUID、seed 必须固定。

## 14. GO / Waiver / NO-GO

- `GO`：Release Checklist 全部硬门通过。
- `Waiver`：仅允许非 Tier 1 性能或低优先级 TUI 视觉问题，必须有 owner / deadline。
- `NO-GO`：Secret 泄露、数据损坏、越权执行、migration 不可恢复、许可证不明、构建物含本机敏感内容。

## 15. 预期交付

```text
artifacts/v0_10/
├── release_manifest.json
├── support_matrix.md
├── security_report.md
├── migration_restore_report.md
├── performance_baseline.json
├── SBOM.json
├── THIRD_PARTY.md
├── checksums.txt
├── known_limitations.md
└── offline_demo/
```

## 16. 参考

- [`PaperClaw_v0.02-v0.10_SOP总路线与风险推演.md`](../PaperClaw_v0.02-v0.10_SOP总路线与风险推演.md)
- [`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md)
