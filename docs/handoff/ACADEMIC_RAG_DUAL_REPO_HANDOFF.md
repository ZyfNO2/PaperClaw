# Academic RAG 双仓统一 Handoff

> 最后更新：2026-07-27  
> 适用仓库：`G:\PaperAgent`、`G:\PaperClaw`  
> 状态：`offline_validated / P0 GO blocked`  
> PaperAgent 基线：`16cf771792617164d06d0160df1266cc8bb6cd89`  
> PaperClaw 基线：`28319079210a09ac231a0da10180afd52e8f2af3`

## 1. 文档规则

本文是 Academic RAG 后续开发、优化、验收和发布工作的统一交接入口。
两个仓库保存 byte-equivalent 副本；修改时必须在同一工作批次同步更新两份，
并记录新的双仓 commit SHA。若本文与旧 roadmap、SOP 或 handoff 冲突，以代码、
最新测试证据、当前 SOP hard Gate 和本文的未完成项为准。

PaperClaw 是 `academic.v1`、论文版本、解析/索引、Evidence、Artifact 和 Desktop
的事实源。PaperAgent 是 Query Planning、Evidence Ledger、跨论文推理、
Academic Tailoring 和科学决策的事实源。PaperAgent 不得读取 PaperClaw SQLite、
页面缓存或模型索引。

## 2. 当前已完成

### PaperClaw

- PDF 导入、版本化、PyMuPDF 结构化解析和 content-addressed 页面/对象资产。
- page/section/paragraph/figure/caption/table/table-cell/equation/algorithm/reference
  locator；source hash 校验与旧版本 resolve。
- lexical、hashing dense、optional ColQwen2 visual 和 exact DOI/arXiv channel。
- active index generation、model fingerprint 校验、显式 visual degradation。
- Evidence Bundle、Project Memory、append-only Artifact Store、REST/CLI/Desktop
  Academic 入口。
- PEP 561 `py.typed` 发布标记。
- 107 篇本地语料真实运行：90 ready、7 partial、10 invalid/corrupt；
  45,281 个索引对象；exact smoke top score 1.0。
- 最终离线回归：1033 passed，23 skipped，15 deselected。

### PaperAgent

- `AcademicEvidenceSource.retrieve/resolve` 和 `AcademicArtifactSink` seam。
- identity/method/figure/table/equation/comparison/tailoring routing。
- DOI/arXiv identity 保留；一次 primary、最多一次 corrective 和一次 conflict
  round 的有界控制流。
- accepted/rejected/conflicted Evidence Ledger；Claim 只能引用 accepted evidence。
- Evidence Bundle、Paper Comparison、Baseline Card、Module Card、
  Compatibility Matrix、Experiment Matrix、Method Draft、Review Report 八类草稿。
- `draft → approved/rejected → final` 状态机。
- `PaperClawAcademicEvidenceSource` 与 `PaperClawAcademicArtifactSink` optional
  adapter；真实 PDF 跨仓 tracer 已通过。
- Python 3.11/3.12 full acceptance 各 12 步通过；coverage 均不低于 90%。

### 当前工作树约束

- PaperAgent 的 `.venv-paperagent/`、`output/` 不进入版本控制。
- PaperClaw 的 `data/` 为私人/本地 corpus，不提交原始 PDF。
- 当前分支均为 `codex/academic-rag-p0`；尚未推送、建 PR 或合并。

## 3. 当前不能宣称的能力

- 当前状态不是 Academic RAG P0 GO，也不是科学有效性证明。
- PaperClaw 主 parser 仍是 PyMuPDF；没有正式 Docling adapter。
- Markdown、Text、LaTeX 尚未进入统一 Academic parser pipeline。
- lexical 实现不是完整 BM25；融合不是正式 weighted RRF。
- hashing dense 和 visual-unavailable corpus run 不能代表真实 dense/ColQwen2
  多模态质量。
- PaperClaw 尚未形成可校准的 conflict detector；PaperAgent corrective round
  尚未根据失败原因产生新的 query/channel strategy。
- PaperAgent 当前八类 Artifact 是 evidence-bound deterministic draft，
  不是经过真实 LLM 完成的深入跨论文科学分析。
- PaperAgent adapter 可注入，但 PaperClaw Desktop 尚未完成 optional extension
  的产品级发现、装载、任务恢复和完整 UI 审批闭环。
- 107 条 corpus entry 中有 10 条不是可解析的有效 PDF；不得修改内容或忽略失败
  来提高成功率。
- 尚无冻结的 12 篇验收集、32 个 blinded retrieval labels、2 个跨论文人工金标。
- 没有本轮真实 LLM trace、Native Desktop 人工点击记录和最终 Artifact 人工审批。

## 4. P0 收口执行计划

以下阶段必须按顺序完成。每阶段在两仓各使用范围单一 commit，并同步本文。

### H0：发布基线与 corpus 冻结

- [ ] 推送双仓当前分支并建立关联 PR；记录 CI run 和最终 head SHA。
- [ ] 为 107 条 corpus 生成许可/来源/有效性状态，不提交全文。
- [ ] 对 10 条 invalid/corrupt input 执行重新获取、隔离或明确排除决策；
  保留原 hash 和失败原因。
- [ ] 从有效语料冻结 12 篇：裂缝检测、三维重建/立体匹配、分割、
  主材料各 3 篇。
- [ ] 提交只含 metadata/hash/license/status 的 corpus manifest。

完成条件：双仓 clean tracked worktree；manifest digest 可复算；原 PDF 仍 untracked。

### H1：canonical parser 与 locator 完整化

- [ ] 将 PaperClaw parser 重构为 `PyMuPDFAdapter` 与 `DoclingAdapter`，
  对外仍只暴露 `ingest/parse/index/retrieve/expand/resolve`。
- [ ] 增加 Markdown、Text、LaTeX ingestion。
- [ ] 加密、损坏、扫描件、页面渲染失败统一返回结构化 `partial/failed`；
  不以未分类异常结束任务。
- [ ] 明确 `extracted` 与 OCR/VLM/heuristic `inferred` provenance。
- [ ] Table Cell 行列身份、Equation、Caption、Algorithm、Reference/Citation
  locator contract tests 全绿。
- [ ] 对同文件重复 ingest/parse/index 和 paper version 更新做幂等/旧 locator
  replay 验收。

完成条件：选定 12 篇全部产生 manifest；所有可标注对象具有 page 和有效 bbox；
旧版本 locator resolve fail-closed。

### H2：正式多通道 Retrieval

- [ ] 实现 named retrievers：BM25、SentenceTransformer、ColQwen2、exact field。
- [ ] page、region crop、Figure、Table、Cell、Equation 分别入索引。
- [ ] 使用 weighted RRF；Trace 保存各 channel 原始分、权重、fingerprint 和降级。
- [ ] 支持 project/paper/object/section filters 与 max-char budget。
- [ ] 实现可测试的 conflict detection；禁止用 `stop_reason` 字符串猜测冲突。
- [ ] corrective retrieval 根据 insufficiency/conflict 产生可解释 rewrite，
  同时强制保留 DOI/arXiv/title identity。
- [ ] CUDA OOM、模型缺失、index corruption 和 fingerprint drift 均有确定终态；
  visual 问题不得返回 `sufficient`。
- [ ] 增量索引与 active generation 切换不得全量破坏旧 locator。

完成条件：

| 指标 | Gate |
|---|---:|
| Document Recall@5 | ≥ 0.90 |
| Page Recall@5 | ≥ 0.80 |
| Object Recall@5 | ≥ 0.75 |
| Table Cell exact accuracy | ≥ 0.85 |
| Locator page accuracy | 1.00 |
| bbox IoU≥0.5 比例 | ≥ 0.80 |
| Abstention accuracy | ≥ 0.90 |

### H3：PaperAgent 科学推理与 Artifact

- [ ] 将 PaperClaw adapter 作为 PaperAgent optional extension 的正式 factory，
  提供版本检查和缺依赖诊断。
- [ ] Query Planner 输出 decomposition、rewrite、channel、filters、budget 和
  corrective reason。
- [ ] 让真实 LLM 只消费 accepted Evidence Ledger；rejected/conflicted evidence
  不进入 claim generation。
- [ ] 每个生成 Claim 强制绑定可 resolve locator，并执行 citation/claim mismatch
  检查。
- [ ] 实现两篇以上 Paper Comparison、Baseline/Module extraction、
  Compatibility analysis、Experiment design 和 Method Draft。
- [ ] 证据不足、不可复现、license/shape/semantic 冲突必须进入 REVISE/NO-GO；
  false GO 为硬失败。
- [ ] 所有八类 Artifact 写入 PaperClaw append-only store；禁止 PaperAgent
  建立第二套持久化 schema。

完成条件：两个跨论文场景均生成八类 evidence-bound Artifact；critical
unsupported claim、citation mismatch、false GO 均为 0。

### H4：Desktop 与人工审批闭环

- [ ] PaperClaw Desktop 发现并加载 PaperAgent optional extension，无循环依赖。
- [ ] 导入、parse/index progress、structured failure、channel/budget/Trace 可见。
- [ ] Claim → locator → PDF page/bbox、Figure/Table/Equation 可点击回读。
- [ ] Evidence Ledger 展示 accepted/rejected/conflicted 及原因。
- [ ] 长任务支持 cancel、restart recovery、progress trace 和 bounded failure。
- [ ] Methodology、Compatibility Matrix、Experiment Matrix 未批准不能 final/export。
- [ ] Approve/Reject 只追加 revision；Reject 原因和历史永久保留。
- [ ] 完成 Native Windows Desktop 人工点击 checklist 和脱敏截图。

完成条件：用户本人完成
导入→解析→查询→证据回读→跨论文分析→审批→final export。

### H5：真实验收与 P0 GO

- [ ] 为 12 篇 corpus 建立 32 个 blinded questions：文字、Figure、Table、
  Equation 各 8 个。
- [ ] 冻结 2 个 baseline/module tailoring 场景和人工 expected decisions。
- [ ] 在 RTX 4070 SUPER 12GB 跑真实 SentenceTransformer/ColQwen2 benchmark；
  CPU fallback 单独报告为 partial。
- [ ] 运行真实 OpenAI-compatible LLM；保存 provider、model、budget、Trace、
  Evidence、Artifact revisions，不保存 secret。
- [ ] 至少一名人工 reviewer 审批或拒绝最终产物并记录理由。
- [ ] 分开报告 synthetic、真实论文离线、GPU、真实 LLM 和人工结果。
- [ ] 两仓 full CI、wheel/package、Desktop smoke、SOP completion check 全绿。

只有全部 hard Gate 通过后，才允许把状态改为 `P0 GO / release_accepted`。

## 5. P1 开发与优化计划

P1 不得在 P0 hard Gate 未闭合时改写 P0 契约。

### P1-A：Relation Graph

- Paper→Paper citation、Paper→Method、Method→Dataset、Method→Metric、
  Claim→Evidence 关系。
- 图只保存可追溯 edge；LLM 推断 edge 标为 `inferred`，不得提升为事实。
- 支持 related work、方法谱系、冲突证据和 novelty overlap 查询。

### P1-B：质量平台

- 可版本化 gold labels、corpus splits、model/index fingerprints 和 run manifests。
- Recall、MRR/nDCG、bbox IoU、abstention、citation mismatch、unsupported claim、
  false GO/NO-GO、repair success、latency、VRAM、cost dashboard。
- Human/LLM judge 只能补充主观维度，不能覆盖 deterministic hard failures。
- 加入 regression threshold、drift detection 和跨版本对比。

### P1-C：解析与检索性能

- page/object embedding batch、显存自适应、OOM retry、缓存配额和 LRU。
- 增量 parse/index、内容去重、并发导入、事务恢复和 index compaction。
- 大 corpus streaming，避免一次性将全部对象或视觉 embedding 载入内存。
- 记录 p50/p95 latency、吞吐、峰值 RAM/VRAM 和 cold-start。

### P1-D：产品质量

- Desktop accessibility、键盘操作、空态/错误态、超长任务和离线模式。
- Corpus/license/privacy UI，支持删除、版本保留和数据导出说明。
- Artifact diff、review comments、批量审批保护和导出 provenance appendix。
- Windows wheel/installer、optional model download、磁盘空间预检和升级迁移。

## 6. P2 计划

### 受限 Coding Worker

- 只消费 approved Experiment Matrix/Method Draft，不自主决定科学 GO。
- workspace sandbox、命令 allowlist、资源预算、checkpoint/undo、patch review。
- 生成 config、adapter、实验脚本和测试；禁止自动修改论文正文或执行高成本训练。
- 每次执行绑定 Artifact revision、commit、environment fingerprint 和 Trace。

### Connector / Skill 扩展

- HTTP/MCP 只能作为次级 adapter，不替代 P0 Python interface。
- 外部文献、代码仓库、数据集和实验平台 connector 必须有权限、许可、
  provenance、rate limit 和 secret-redaction contract。
- Skill 只组织工作流，不得绕过 Evidence、Artifact review 或 Permission Gate。

### 非目标

- 公开多租户、通用 IDE、自动论文投稿、无界 autonomous research、
  PixelRAG 训练和大规模分布式服务不自动进入当前 roadmap。

## 7. 跨阶段工程规则

- 新能力先写 seam-level tracer test，再做最小实现。
- PaperClaw canonical contract 变更必须先加 serialization fixture，再同步
  PaperAgent adapter；禁止双仓各自新增同名事实模型。
- Python 3.11 只验证 PaperAgent structural adapter；真实 PaperClaw integration
  在 Python 3.12 验证。
- 不降低 strict Mypy、coverage、abstention 或 source-hash Gate。
- 模型、corpus、缓存、数据库、日志和 secret 不提交 Git。
- 每阶段保存命令、summary、coverage、wheel SHA-256、corpus/model fingerprint
  和双仓 commit SHA。
- 自动化通过不等于 live/scientific/human validation。
- 任何缺失证据、冲突、版本漂移或无法 resolve 的 Claim 必须 fail closed。

## 8. 推荐验证命令

PaperAgent：

```powershell
python scripts/local_acceptance.py --profile full --continue-on-error
pytest tests/academic -q
```

PaperClaw：

```powershell
python -m pytest -q -m "not real_llm and not process_acceptance and not distributed"
python scripts/academic_corpus_acceptance.py `
  --corpus data/paper_corpus `
  --workspace build/corpus-acceptance-<timestamp> `
  --output artifacts/v0_43/real_corpus_report.json
python .claude/hooks/sop_completion_check.py
```

跨仓 real tracer 的环境要求：

```text
Python 3.12
PaperAgent editable install
PaperClaw 0.43 editable/wheel install
PyMuPDF
```

## 9. 下一执行者起点

1. 先读取本文和两仓 `AGENTS.md`，检查 `git status` 与上述 commit。
2. 不恢复或提交 `.venv-paperagent/`、`output/`、PaperClaw `data/`。
3. 从 H0 开始，不直接跳到 P1/P2。
4. 首个需要用户输入的 Gate 是 corpus 许可/替换决定、Provider credentials
   和 Native Desktop Artifact 审批。
5. 未获得上述证据前，状态保持 `offline_validated / P0 GO blocked`。
