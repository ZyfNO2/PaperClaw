# PaperClaw Academic RAG Batch 5 收口任务书

## 1. 任务定位

本任务只完成 PaperClaw 的 Batch 5 剩余工程闭环，不进入 PaperAgent Query Planner、Evidence Reasoning、Relation Graph、Coding Worker、真实论文 Benchmark 或 P0 Release 宣告。

当前基线：

- 仓库：`ZyfNO2/PaperClaw`
- 分支：`codex/academic-rag-h2-retrieval`
- 文档 head：`cd813f0957c427e1534d999e076c9ed2916a2d68`
- 已验证实现 head：`1715ced1eebf9f36a394001e27f3ead51712a8a5`
- 已有索引契约：`AcademicIndexEntry`、`AcademicIndexManifest`、`AcademicObjectIndex`
- 索引版本：`academic-object-index.v1`
- 已有服务 seam：`RetrievalService.search`、locator resolve、neighbor expansion、asset byte budget、SHA-256 fail-closed、`EvidenceBundle`
- 已有真实 PDF tracer：parse → index → search → locator resolve → PNG readback

开始开发前必须重新检查分支 HEAD、相关实现、数据库 schema、API router、OpenAPI 生成方式、现有测试和 Handoff，不得仅依赖本任务书覆盖更晚实现。

## 2. 本批次目标

完成以下四个能力并形成可由 PaperAgent 稳定消费的公开契约：

1. 论文版本感知的增量 upsert；
2. 旧版本删除、索引收敛及幽灵结果防护；
3. stale schema/index/fingerprint 的显式拒绝与受控迁移或重建路径；
4. `RetrievalService` REST/OpenAPI 暴露及跨仓 canonical fixture。

完成后状态仍应是：

```text
Batch 5: COMPLETE
P0 Release: NO-GO / pending real benchmark and human acceptance
```

## 3. 强制边界

### 3.1 禁止提前实现

本批次不得实现或扩展：

- Query classification、decomposition、rewrite 或 routing policy；
- bounded corrective retrieval 的高级推理策略；
- LLM/VLM 调用；
- baseline/module/gap/compatibility/experiment reasoning；
- Relation Graph；
- Coding Worker；
- 真实论文 Benchmark 或人工专家评分；
- 无关 Runtime、Desktop 或多 Agent 重构。

### 3.2 受保护内容

不得提交：

- `data/`；
- 真实或受保护 PDF；
- `output/`；
- 虚拟环境；
- Secret、Token、API Key；
- 与本任务无关的生成产物。

必须在提交前检查 tracked/untracked 状态并运行待发布范围 secret scan。

### 3.3 实现原则

- 复用既有 `AcademicRuntime`、papers/version store、SQLite 事务、router、OpenAPI 和测试工具链。
- 不另建平行索引或平行 REST 框架。
- 不用未解释的全量 rebuild 冒充增量 upsert。
- 任何 identity、schema、hash、locator 或 asset 校验失败必须 fail closed，不能降级为“空成功”。
- 保持现有 Python `RetrievalService` 为业务语义真源；REST 层只做验证、调用和序列化。

## 4. Workstream A：增量版本 upsert

### 4.1 身份与同步单位

以 canonical identity 为边界：

```text
project_id
+ paper_id
+ version_id
+ source_hash
+ object_id
+ object_type
+ page_number
```

增量同步必须区分：

- 新 paper；
- 既有 paper 的新 version；
- 同 version、同 source hash 的幂等重放；
- 同 version identity 但 source hash 或 canonical object set 冲突；
- 未变化对象；
- 新增、更新、删除对象。

### 4.2 必须行为

实现最小、原子、可重启的同步入口。命名应服从现有架构，可为 `sync`、`upsert_version` 或等价 service 方法，但不得把调用者暴露给内部 SQL。

要求：

- 同一输入重复执行，active snapshot 和 manifest content hash 不变；
- 新 version upsert 后，旧 version 仍可按显式 version filter 检索，默认 active-version 语义必须与 papers/version store 一致；
- 只改动目标 paper/version 相关索引项，不重写无关论文；
- generation 激活必须原子化，进程中断不能留下“ready 但不完整”的 generation；
- manifest 从持久化真相生成，不从调用参数拼装假快照；
- 重启后 snapshot、搜索结果和 locator resolve 保持确定性；
- corpus hash、model/encoder fingerprint 和 index version 必须参与 stale 判定；
- 冲突输入应返回明确错误，不得覆盖原有 canonical identity。

### 4.3 测试矩阵

至少覆盖：

1. empty → version v1；
2. v1 幂等重放；
3. v1 → v2 增量追加；
4. v2 仅部分对象变化；
5. 第二篇论文 upsert 不改变第一篇论文条目；
6. source hash/locator identity 冲突 fail closed；
7. upsert 中途失败后 active generation 保持旧完整状态；
8. SQLite 重启后 manifest byte/canonical-equivalent；
9. 检索能按 paper/version 约束返回正确对象；
10. 不产生重复 lexical/visual index rows。

## 5. Workstream B：旧版本删除与幽灵结果防护

### 5.1 删除语义

删除操作必须由 papers/version canonical store 驱动，不能只删除 manifest 展示项。

明确区分：

- 从 active index 移除一个 version；
- 删除整个 paper 的全部 index rows；
- 源 PaperRecord/managed original 是否仍保留，由既有 papers 生命周期决定；本任务不得擅自删除原始资产；
- locator 指向已删除 version 时必须得到显式 not-found/stale 结果。

### 5.2 幽灵结果验收

删除后必须验证：

- lexical、visual、neighbor expansion 都不再返回已删除对象；
- manifest entries 不包含已删除 version；
- 搜索缓存如存在，必须失效或绑定 generation；
- 旧 locator resolve fail closed；
- 服务重启后仍无幽灵结果；
- 删除一个 version 不影响同 paper 其他 version；
- 删除最后一个 version 后该 paper 不再出现在默认检索域。

### 5.3 测试矩阵

至少包含：

- v1+v2 删除 v1；
- 删除 active version 后的 active-version 决策；
- 删除全部 versions；
- 删除后立即 search；
- 删除后 restart 再 search；
- neighbor expansion 不返回已删除邻居；
- locator resolve、page asset、region asset 均拒绝已删除 version；
- 删除事务失败时保持旧 snapshot 完整。

## 6. Workstream C：stale schema/index 拒绝与迁移

### 6.1 必须识别的 stale 状态

- `ACADEMIC_SCHEMA_VERSION` 不匹配；
- `ACADEMIC_INDEX_VERSION` 不匹配；
- model/encoder fingerprint 不匹配；
- corpus hash 与 canonical papers/version 集不一致；
- manifest content hash 不匹配；
- active generation 缺失、非 `ready` 或部分表缺行；
- locator JSON 可解析但 canonical object 已不存在；
- asset hash 与实际 bytes 不一致。

### 6.2 处理策略

采用显式策略，不允许静默 reinterpret：

- 可以安全且确定性迁移时，提供版本化 migration；
- 不能证明安全迁移时，拒绝读取并要求 rebuild；
- rebuild 必须生成新 generation，经完整验证后再原子激活；
- 旧 generation 的清理必须与当前恢复/审计需求兼容；
- 错误类型和 REST 状态必须可被调用者区分：not ready、stale schema、stale index、fingerprint mismatch、integrity failure、not found。

### 6.3 测试矩阵

使用临时 SQLite fixture 注入 stale/corrupt 状态，至少覆盖：

- schema version 修改；
- index version 修改；
- fingerprint 修改；
- manifest hash 篡改；
- 缺失 index row；
- orphan locator；
- asset bytes 篡改；
- rebuild 后恢复；
- restart 后仍正确拒绝或恢复。

不得通过仅 mock `snapshot()` 返回值来代替真实持久化测试。

## 7. Workstream D：RetrievalService REST/OpenAPI

### 7.1 架构要求

先检查 PaperClaw 现有 API router、项目资源鉴权/路径边界、错误模型、Pydantic/OpenAPI 生成方式和 `/v1/projects/{project_id}/papers` 风格。沿用既有规范，不另建 Web 应用。

REST 层必须调用正式 `RetrievalService`，不得复制 search、neighbor、asset budget 或 locator validation 逻辑。

### 7.2 最小公开能力

至少暴露以下语义；最终路径按现有 router 规范确定并在 OpenAPI 中冻结：

1. search：接收 project、query、paper/version/object filters、top-k、neighbor count、asset byte budget 等已存在的 bounded 参数，返回 canonical `EvidenceBundle`；
2. resolve locator：按 canonical locator 返回结构化对象及允许的 asset metadata；
3. page/region asset readback：仅在既有安全边界内返回 bytes 或现有文件响应，不接受任意路径；
4. index status/manifest inspection：返回可公开的 version、generation、hash、ready/stale 状态，不泄露本地绝对路径或内容。

### 7.3 契约要求

- 请求和响应必须有 canonical schema；
- OpenAPI 的 `EvidenceBundle`、locator、object、asset 引用使用 canonical `$ref`，不得复制漂移结构；
- 明确 bounded defaults 和 hard limits；
- 无效 top-k、neighbor count、asset byte budget 在进入业务层前拒绝；
- project/paper/version 不存在、stale index、integrity failure 使用稳定错误码/状态；
- JSON 序列化确定性字段语义与 Python 对象一致；
- 不在 JSON 中嵌入无限制 PNG/base64；
- 响应不得泄露 managed-original 绝对路径、SQLite 路径或 secret。

### 7.4 OpenAPI 与 fixture

生成或维护：

- Retrieval REST OpenAPI canonical schema；
- 至少一套成功 search fixture；
- locator resolve fixture；
- stale/integrity error fixture；
- asset budget 截断 fixture；
- 对应 PaperAgent 消费 fixture。

fixture 必须来自真实 serializer/endpoint 测试，不得手写一个未经过运行路径的“理想响应”。对共享文件定义稳定 canonical JSON 和 SHA-256，并与 PaperAgent 仓库进行 byte-equivalent 或明确 canonical-equivalent 校验。

## 8. 跨仓实施顺序

1. PaperClaw 先冻结 Python 语义和 REST/OpenAPI；
2. 生成 canonical fixtures；
3. PaperAgent 只按已冻结契约实现消费与验证；
4. 两仓运行跨仓 fixture 校验；
5. 最后再更新两仓 byte-equivalent Handoff。

不得让 PaperAgent 反向定义 PaperClaw 服务字段。

## 9. 验证要求

### 9.1 定向验证

必须运行并记录：

- 增量 upsert/version tests；
- delete/ghost-result tests；
- stale/migration/rebuild tests；
- RetrievalService Python regression；
- REST endpoint tests；
- OpenAPI schema tests；
- real PDF parse→sync→REST search→resolve→PNG readback tracer；
- restart persistence tests；
- cross-repo fixture producer tests。

### 9.2 全量验证

按仓库既有方式运行：

- Ruff/lint/format；
- mypy 或既有类型检查；
- Windows/Ubuntu 适用测试；
- full pytest；
- wheel/sdist build；
- Gitleaks 待发布范围扫描。

必须明确区分离线 tracer 与真实科学质量验收。不得把 fixture、Mock、离线 PDF tracer 写成真实 Benchmark。

## 10. 完成标准

只有全部满足时 Batch 5 才可标记完成：

- 增量 upsert 不依赖无条件全量 rebuild；
- 版本删除后不存在 lexical/visual/neighbor/cache 幽灵结果；
- stale schema/index/fingerprint/integrity 状态均 fail closed；
- 可安全迁移或明确 rebuild，不静默兼容；
- REST/OpenAPI 与 Python service 语义一致；
- PaperAgent 能通过 canonical fixture 消费成功、错误和 budget 状态；
- restart、clean clone、build、CI 全绿；
- 两仓 Handoff Git blob 再次完全一致；
- 真实论文 Benchmark 和人工验收仍标记 `pending`；
- `P0 Release` 仍标记 `NO-GO`。

## 11. 提交与 Handoff

按合理节点拆分提交，建议但不强制：

1. `feat(academic): add incremental version index sync`
2. `fix(academic): remove stale versions and ghost retrieval hits`
3. `fix(academic): reject and rebuild stale object indexes`
4. `feat(api): expose academic retrieval service contracts`
5. `test(academic): freeze retrieval REST cross-repo fixtures`
6. `docs(academic): close Batch 5 handoff`

最终 Handoff 必须记录：

- 分支和最终 SHA；
- 实际修改文件；
- 数据迁移/重建策略；
- REST 路径、OpenAPI schema 与 fixture hash；
- 所有测试、CI run 和 skipped 项；
- clean clone 与构建结果；
- 未执行的真实 Benchmark/人工验收；
- 已知限制；
- 下一阶段只能在 Batch 5 GO 后进入 Query Planner。

不要自动合并默认分支，不要删除现有分支，不要把 P0 状态写成 GO。