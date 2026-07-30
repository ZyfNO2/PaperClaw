# Academic RAG 后续开发任务书

> 适用仓库：`ZyfNO2/PaperClaw`、`ZyfNO2/PaperAgent`  
> 创建日期：2026-07-30  
> 状态：`execution_ready / P0 GO blocked`  
> 本文件必须在两个仓库保持语义一致；实际代码、测试和 CI 证据优先于旧文档描述。

## 1. 当前基线

| 仓库 | 工作分支 | 创建本任务书前 HEAD | 关联 PR | 当前阶段 |
|---|---|---|---|---|
| PaperClaw | `codex/academic-rag-h2-retrieval` | `bd86c817d192447381cd07f2d0850087a5abde56` | Draft PR #76 | H2 主要实现已存在，正式 Gate 未闭合 |
| PaperAgent | `codex/academic-rag-p0` | `726c806a0e0c229d16e7dbb576f8996214e57b09` | Draft PR #65 | P0 基础已存在，H3 尚未闭合 |

统一事实源：`docs/handoff/ACADEMIC_RAG_DUAL_REPO_HANDOFF.md`。本任务书把其中未完成项转换为可连续执行、可测试、可提交的工作包。

## 2. 总体执行顺序

必须按以下顺序执行，不得跳过前置 Gate：

1. **WP-A：PaperClaw H2 收口**；
2. **WP-B：PaperAgent H3 收口**；
3. **WP-C：双仓集成与回归**；
4. **WP-D：H4/H5 真实环境与人工验收准备**。

H2 未通过时，不得把 H3 描述为完成；H3 未通过时，不得进入 P0 GO 或正式发布判定。

## 3. 全局约束

- 开始时重新检查两个仓库的默认分支、目标分支、最新 HEAD、PR、CI、目录结构、相关实现、测试和 Handoff；不要仅依赖本文件中的 SHA。
- 不自动合并 PR，不改为 ready for review，不删除分支，不直接向 `main`/`master` 推送功能代码。
- 优先复用现有 `academic.v1` contract、retriever、adapter、Evidence Ledger、Artifact Store 和测试工具链。
- 禁止新增第二套同名事实模型、第二套 Artifact 持久化 schema 或 PaperAgent 直读 PaperClaw 内部 SQLite/缓存。
- 禁止提交 PDF、模型权重、页面缓存、向量库、数据库、原始日志、Secret 或真实 API Key。
- Mock/Fake/Stub、静态检查和离线测试不得描述为真实模型、真实 LLM、真实 Desktop 或人工验收。
- 每个功能先增加失败用例和 seam-level tracer，再做最小实现；模块关闭时必须保持原路径兼容。
- 所有 Claim、Evidence、locator、版本和 fingerprint 不一致时必须 fail closed。

## 4. WP-A：PaperClaw H2 收口

### A0. 真实状态审计

- 对照 Handoff 的 H2 条目，建立“要求 → 当前实现 → 当前测试 → 缺口”矩阵。
- 检查 PR #76 HEAD 之后是否已有修复提交；确认当前 CI 是否真正运行新增测试，而不是 skipped。
- 将已经完成的条目标记为 `verified`，未运行或缺少真实模型的标记为 `not_verified`/`blocked`，不得重复造轮子。

### A1. 冲突检测契约

实现可测试的 deterministic conflict detector：

- 输入必须是结构化候选、字段、locator、来源版本和 provenance；
- 禁止通过 `stop_reason`、自由文本提示词或字符串关键字猜测冲突；
- 至少覆盖 identity、数值、单位、方向性结论、方法配置和版本冲突；
- 输出稳定的 conflict type、相关 evidence IDs、原因和建议 corrective strategy；
- 对证据不足与真实冲突进行区分；
- 增加正例、反例、顺序无关、重复 evidence、旧版本 locator 和缺字段测试。

### A2. Corrective retrieval

- 根据 insufficiency/conflict 类型生成结构化 rewrite、channel 调整、filter 放宽或 budget 调整；
- DOI、arXiv ID、规范化 title identity 必须保留，不得在 rewrite 中丢失；
- 总 corrective round 仍保持有界，避免循环；
- Trace 记录 primary reason、rewrite、channel/filter/budget 变化、结果差异和终止原因；
- 增加“无变化 rewrite”“重复候选”“冲突未解决”“预算耗尽”测试。

### A3. 索引与检索完整性

确认并补齐：

- page、region crop、Figure、Table、Cell、Equation 分别可进入索引并可追溯到 canonical locator；
- project/paper/object/section filters 在所有参与通道中语义一致；
- max-char/max-result/budget 在正确边界执行；
- named retrievers 的真实启用条件、模型 fingerprint 和 degraded 状态可观察；
- 模型缺失、OOM、index corruption、fingerprint drift 均产生确定终态；
- 增量索引和 active generation 切换不破坏旧 locator，失败切换不得污染 active generation。

### A4. H2 质量 Gate 基础设施

- 保留现有 frozen index benchmark；禁止重新索引导致 benchmark 漂移而不记录 generation/fingerprint。
- 建立版本化 question/gold schema，支持 document/page/object/table-cell/locator/bbox/abstention 指标。
- 为 32 个 blinded questions 提供生成模板、校验器、评分器和 anti-leakage 检查；人工 gold label 本身如未提供，应标记 `blocked_by_human_labeling`，不得伪造。
- 输出至少以下指标：Document Recall@5、Page Recall@5、Object Recall@5、Table Cell exact accuracy、Locator page accuracy、bbox IoU≥0.5 比例、Abstention accuracy。
- 阈值沿用统一 Handoff；任何一项未达到时状态为 `REVISE`，不得写成 H2 PASS。

### A5. PaperClaw 验证与提交

必须执行并记录：

- 与 conflict/corrective/index/benchmark 直接相关的定向测试；
- Academic RAG 全套测试；
- 仓库现有全量回归、lint/type/build；
- 能触发的 GitHub Actions，并核对新增测试实际被运行；
- 真实 SentenceTransformer/ColQwen2/GPU 未执行时明确标记 pending/blocked。

提交要求：

- 小步 commit，信息可追踪；
- 更新 Handoff 的真实状态、命令、测试数量、CI run、HEAD 和未验证部分；
- 不在没有证据时勾选 H2 完成。

## 5. WP-B：PaperAgent H3 收口

只有 WP-A 达到可复算的 H2 工程 Gate 后开始。

### B0. Adapter factory 与版本诊断

- 将 PaperClaw adapter 注册为正式 optional extension factory；
- 检查 `academic.v1` schema/version/capability，缺依赖或版本不兼容时给出结构化诊断；
- Python 3.11 只做 structural adapter 验证，真实 PaperClaw integration 使用受支持环境；
- 禁止 silent fallback 到不兼容或伪造的 evidence source。

### B1. Query Planner contract

Planner 必须结构化输出：

- decomposition；
- normalized query/rewrite；
- channel 选择；
- project/paper/object/section filters；
- result/character/token budget；
- corrective reason 和停止条件。

增加序列化 fixture、预算边界、identity 保留、无效 filter、重复 corrective 和向后兼容测试。

### B2. Accepted-only LLM context

- 真实或模拟 LLM 调用入口只能消费 accepted Evidence Ledger；
- rejected/conflicted evidence 不得进入生成上下文；
- prompt/context manifest 保存 evidence IDs、locator、版本和预算，不保存 Secret；
- 当 accepted evidence 不足时必须 abstain/REVISE，不得生成无来源结论。

### B3. Claim 与 citation/locator 校验

- 每个 Claim 必须绑定可 resolve 的 canonical locator；
- 增加 claim/evidence semantic mismatch、错误引用对象、旧版本 locator、不可 resolve locator 和跨论文串线检查；
- critical unsupported claim、citation mismatch、false GO 必须作为 hard failure；
- 所有修复和拒绝记录进入 append-only revision history。

### B4. 八类 Artifact

完成并验证：

1. Evidence Bundle；
2. Paper Comparison；
3. Baseline Card；
4. Module Card；
5. Compatibility Matrix；
6. Experiment Matrix；
7. Method Draft；
8. Review Report。

要求：

- 全部由 accepted evidence 驱动；
- 明确区分 `verified`、`inferred`、`proposed`、`unknown`；
- provenance、license、shape、semantic、normalization、mask、ordering、gradient、loss、compute 冲突可触发 REVISE/NO-GO；
- 只写入 PaperClaw append-only Artifact Store，不新增第二套持久化；
- 未批准 Artifact 不得进入 final/export。

### B5. 两个跨论文场景

- 固定两个 baseline/module tailoring 场景；
- 每个场景覆盖 retrieval → ledger → conflict/corrective → eight artifacts → review decision；
- expected decision 和关键 Claim 需要人工金标；未获得人工金标时，完成 schema、runner 和 evidence package 后标记 blocked；
- critical unsupported claim、citation mismatch、false GO 目标均为 0。

### B6. PaperAgent 验证与提交

必须执行并记录定向测试、全量回归、strict mypy、coverage、build、双仓 tracer 和实际 CI。真实 LLM 未运行时，不得把 deterministic draft 或 FakeModel 测试描述为真实科学分析。

## 6. WP-C：双仓集成与回归

- 固定 PaperClaw/PaperAgent exact commit pair、schema digest、wheel digest 和环境 fingerprint；
- 验证真实 PDF import → parse → index → retrieve → resolve → PaperAgent ledger → Artifact revision → locator/asset readback；
- 验证 PaperClaw 不可用、版本不兼容、locator 失效、artifact 写入失败和恢复路径；
- 两仓 Handoff 必须同步更新且不存在相互矛盾的完成声明；
- 保持 Draft PR，不自动合并。

## 7. WP-D：H4/H5 准备与阻塞边界

仅在 WP-A～WP-C 完成后推进：

- Desktop 展示 progress、structured failure、channel/budget/Trace、Evidence Ledger、Claim → locator → page/bbox 回读、审批和 revision history；
- Native Windows 全流程点击、真实 GPU benchmark、真实 OpenAI-compatible LLM、人工 reviewer 和脱敏截图属于真实验收；
- 当前环境无法完成的真实操作，先完成 runner、配置模板、数据校验、日志规范和 checklist，然后输出精确人工步骤；
- 只有 Handoff 的全部 H5 hard Gate 通过，才允许改为 `P0 GO / release_accepted`。

## 8. 完成判定

### GO

- H2/H3 需求映射完整；
- 关键定向测试、全量回归、CI 和跨仓 tracer 可复算；
- benchmark/人工/真实模型能力按实际证据标记；
- critical unsupported claim、citation mismatch、false GO 均为 0；
- 没有 Secret、原始 PDF、模型或本地缓存进入 Git。

### REVISE

- 实现存在但机制、指标、兼容性或证据不完整；
- 质量 Gate 未达到；
- 人工 gold/真实模型尚缺，但代码和基础设施可继续修复。

### BLOCKED

- 只剩真实 GPU、真实 LLM、Native Windows 点击、人工金标或 reviewer 审批；
- 必须明确说明阻塞原因、用户操作、命令、预期结果、需要返回的日志/截图/产物。

## 9. 最终 Handoff 要求

每个工作包结束时提交 commit，并在最终 Handoff 中包含：

- 仓库、分支、PR、最终 commit SHA；
- 已完成内容和主要文件；
- 需求完成矩阵；
- 关键架构决定；
- 已运行命令、测试数量、CI run 与结果；
- Mock/Fake/离线/真实 GPU/真实 LLM/人工验收的明确区分；
- 未验证能力、已知限制和 stop condition；
- 下一位开发者的准确接手步骤。
