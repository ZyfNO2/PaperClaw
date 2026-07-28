# PaperClaw Academic v1 公共契约

`academic.v1` 是 PaperClaw 与 PaperAgent 之间论文事实数据的唯一公共契约。
PaperClaw 拥有 schema、序列化、论文对象存储和 locator resolve；PaperAgent
拥有 Query Planning、Evidence Ledger 与科学决策状态。

冻结的顶层对象为 `PaperRecord`、`AcademicObject`、`EvidenceLocator`、
`EvidenceBundle`、`MemorySnapshot` 和 `ArtifactRevision`。Canonical JSON Schema
位于 `contracts/academic.v1.schema.json`，golden payload 位于
`contracts/academic.v1.golden.json`；package 内副本必须保持 byte-equivalent。

## Locator 与坐标

- 页码从 1 开始。
- bbox 使用 PDF point，原点为页面左上角，顺序为 `x0, y0, x1, y1`。
- 稳定身份为 `paper_id + version_id + source_hash + object_id`。
- `resolve` 同时核验完整 locator 坐标、当前论文版本以及所有关联资产 SHA-256。
- 旧版本、source hash 漂移、坐标漂移、资产缺失或资产损坏均 fail closed。

## 解析与存储

解析 manifest 先以 `staging` 写入规范化对象表，全部对象、关系和资产引用成功后，
才原子切换为 `ready` 或 `partial`。`failed` 与 `stale` manifest 不对检索和 resolve
可见。0.43 legacy JSON manifest 仅在 source identity 可验证时 backfill；否则保留
为 `stale` 审计记录并要求重新解析。

`AcademicLocator` 仅保留一个发布周期的 Python import alias；wire payload、REST、
CLI、Desktop 和新代码统一使用 `EvidenceLocator`。
