# Academic RAG 双仓统一 Handoff

> 最后更新：2026-07-28  
> 适用仓库：`ZyfNO2/PaperAgent`、`ZyfNO2/PaperClaw`  
> 状态：`offline_validated / P0 GO blocked`  
> 文档修订：`2026-07-28-remote-alignment-2`

## 0. 远端基线

| 仓库 | 分支 | 对齐前远端基线 | 说明 |
|---|---|---|---|
| PaperAgent | `codex/academic-rag-p0` | `e92b7f6b3ab942526c15f8c4a58116f1413e4537` | 已推送；Academic RAG 实现基线为 `16cf771792617164d06d0160df1266cc8bb6cd89` |
| PaperClaw | `codex/academic-rag-p0` | `537b70bea7cd0ff1e964dd4209cd8ab3cb0cb370` | 已推送；包含 v0.43 Academic RAG 实现和旧版统一 Handoff |
| PaperClaw main | `main` | `5891d87ec2a68f434fe8f728ba9be0999932c325` | 当前主线仍为 v0.38；v0.43 分支尚未合并 |

本文不在正文中自引用本次文档同步产生的 commit。获取包含当前文件的提交：

```powershell
git log -1 --format=%H -- docs/handoff/ACADEMIC_RAG_DUAL_REPO_HANDOFF.md
```

## 1. 文档规则

本文是 Academic RAG 后续开发、优化、验收和发布工作的统一交接入口。
两个仓库保存 byte-equivalent 副本；修改时必须在同一工作批次同步更新两份。
若本文与旧 roadmap、SOP 或 handoff 冲突，以远端代码、最新可复算测试证据、
当前 SOP hard Gate 和本文未完成项为准。

PaperClaw 是 `academic.v1`、论文版本、解析/索引、Evidence、Artifact 和 Desktop
的事实源。PaperAgent 是 Query Planning、Evidence Ledger、跨论文推理、
Academic Tailoring 和科学决策的事实源。PaperAgent 不得直接读取 PaperClaw SQLite、
页面缓存或模型索引。

状态词：

- `verified`：能在指定远端 commit 上复算；
- `offline_validated`：自动化、离线语料或本地模型 Gate 已有记录，但不等于科学有效；
- `pending`：计划内但尚未完成；
- `blocked`：缺少数据、凭据、硬件或人工验收；
- `not_verified`：当前证据不足。

## 2. 当前已完成

### PaperClaw v0.43 分支

以下能力已随 `codex/academic-rag-p0@537b70bea7cd0ff1e964dd4209cd8ab3cb0cb370`
推送到远端：

- PDF 导入、版本化、PyMuPDF 结构化解析和 content-addressed 页面/对象资产；
- page/section/paragraph/figure/caption/table/table-cell/equation/algorithm/reference
  locator；source hash 校验与旧版本 resolve；
- lexical、deterministic local dense fallback、optional ColQwen2 visual 和 exact DOI/arXiv channel；
- active index generation、model fingerprint 校验和显式 visual degradation；
- Evidence Bundle、Project Memory、append-only Artifact Store、REST/CLI/Desktop Academic 入口；
- PEP 561 `py.typed` 发布标记；
- ColQwen2 CUDA/bfloat16 单页 smoke 已记录通过；
- 本地 corpus 报告记录 107 entries：90 ready、7 partial、10 failed；
  有效论文索引 45,281 objects，exact identifier smoke top score 1.0；
- 同步后的最终离线回归记录为 `1032 passed, 23 skipped, 15 deselected`；
- wheel 与 sdist 构建成功。

上述 107-entry 报告属于离线 corpus 运行记录，不等于冻结的 12 篇 blinded
质量验收集，也不等于人工科学审查。

### PaperAgent 分支

以下能力已在 `codex/academic-rag-p0` 远端代码与既有验收记录中体现；
本次仅修改 Handoff，没有重新运行 acceptance：

- `AcademicEvidenceSource.retrieve/resolve` 和 `AcademicArtifactSink` seam；
- identity/method/figure/table/equation/comparison/tailoring routing；
- DOI/arXiv identity 保留；一次 primary、最多一次 corrective 和一次 conflict round；
- accepted/rejected/conflicted Evidence Ledger；Claim 只能引用 accepted evidence；
- Evidence Bundle、Paper Comparison、Baseline Card、Module Card、Compatibility Matrix、
  Experiment Matrix、Method Draft、Review Report 八类 evidence-bound deterministic drafts；
- `draft → approved/rejected → final` 状态机；
- PaperClaw optional evidence/artifact adapters 和跨仓 PDF tracer；
- Python 3.11/3.12 acceptance 与 coverage Gate 的既有记录。

### 当前仓库约束

- 两仓远端开发分支均为 `codex/academic-rag-p0`；
- PaperClaw v0.43 尚未合并到 `main`；
- 本轮尚未建立关联 PR，也尚未记录对应 CI run URL/ID；
- PaperAgent 的 `.venv-paperagent/`、`output/` 不进入版本控制；
- PaperClaw 的 `data/` 为私人/本地 corpus，不提交原始 PDF；
- 模型权重、页面缓存、向量、数据库、原始日志和 Secret 不提交；
- 本文同步完成后停止，不继续执行 H0–H5。

## 3. 当前不能宣称的能力

- 当前状态不是 Academic RAG P0 GO，也不是科学有效性证明；
- PaperClaw v0.43 尚未合并到 `main`，不得描述为主线正式发布；
- 主 parser 仍是 PyMuPDF；没有正式 Docling adapter；
- Markdown、Text、LaTeX 尚未进入统一 Academic parser pipeline；
- lexical 不是完整 BM25，融合不是正式 weighted RRF；
- deterministic dense fallback 不能代表 SentenceTransformer 质量；
- 单页 ColQwen2 smoke 不能代表 12 篇或大 corpus 的视觉检索质量与吞吐；
- 扫描 PDF 未启用 OCR，复杂双栏、公式和表格允许明确 partial；
- 尚未形成可校准的 conflict detector；
- PaperAgent corrective round 尚未验证能按失败原因生成新的 query/channel strategy；
- 当前八类 Artifact 是 evidence-bound deterministic draft，不是经真实 LLM
  和人工专家确认的深入科学分析；
- Desktop 尚未完成 Native Windows 全流程点击验收和完整人工审批闭环；
- 尚无冻结的 12 篇验收集、32 个 blinded retrieval labels、2 个跨论文人工金标；
- 没有本轮真实 LLM trace 和最终 Artifact 人工审批；
- 不包含 Relation Graph、完整 Academic RAG benchmark、联网题录核验或全文 PDF 编辑器。

## 4. P0 收口执行计划

以下阶段必须按顺序完成。本文同步结束后不自动继续执行。

### H0：发布基线与 corpus 冻结

- [x] PaperAgent `codex/academic-rag-p0` 已推送；
- [x] PaperClaw `codex/academic-rag-p0` 已推送；
- [x] 两仓统一 Handoff 已同步；
- [ ] 建立关联 PR，并记录两仓 final head SHA 和 CI run URL/ID；
- [ ] 为 107 条 corpus 生成许可、来源和有效性 manifest，不提交全文；
- [ ] 对 10 条 failed/invalid/corrupt input 执行重新获取、隔离或明确排除决策，
  保留原 hash 和失败原因；
- [ ] 从有效语料冻结 12 篇：裂缝检测、三维重建/立体匹配、分割、主材料各 3 篇；
- [ ] 提交只含 metadata/hash/license/status 的 frozen corpus manifest。

完成条件：两仓 clean tracked worktree；branch/commit/CI 可复算；manifest digest 可复算；
原 PDF 保持 untracked。

### H1：canonical parser 与 locator 完整化

- [ ] 增加正式 `DoclingAdapter`，不改变公共 Academic contract；
- [ ] 增加 Markdown、Text、LaTeX ingestion；
- [ ] 扫描件 OCR/VLM/heuristic 结果使用 `inferred` provenance；
- [ ] 加密、损坏、扫描件、渲染失败统一返回结构化 `partial/failed`；
- [ ] 冻结 12 篇上的 Table Cell 行列身份、Equation、Caption、Algorithm、
  Reference/Citation locator contract tests 全绿；
- [ ] 重复 ingest/parse/index 和 paper version 更新执行幂等与旧 locator replay 验收。

完成条件：冻结 12 篇全部产生 manifest；所有可标注对象具有 page 和有效 bbox；
旧版本 locator resolve fail-closed。

### H2：正式多通道 Retrieval

- [ ] named retrievers：BM25、SentenceTransformer、ColQwen2、exact field；
- [ ] page、region crop、Figure、Table、Cell、Equation 分别入索引；
- [ ] weighted RRF；Trace 保存各 channel 原始分、权重、fingerprint 和降级；
- [ ] project/paper/object/section filters 与 max-char budget；
- [ ] 可测试 conflict detection，禁止依赖 `stop_reason` 字符串猜测；
- [ ] corrective retrieval 根据 insufficiency/conflict 产生可解释 rewrite，
  并保留 DOI/arXiv/title identity；
- [ ] OOM、模型缺失、index corruption、fingerprint drift 有确定终态；
- [ ] 增量索引与 active generation 不破坏旧 locator。

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

- [ ] PaperClaw adapter 作为 PaperAgent optional extension 正式 factory，
  提供版本检查和缺依赖诊断；
- [ ] Query Planner 输出 decomposition、rewrite、channel、filters、budget、corrective reason；
- [ ] 真实 LLM 只消费 accepted Evidence Ledger；
- [ ] 每个 Claim 绑定可 resolve locator，并执行 citation/claim mismatch 检查；
- [ ] 完成多论文 Comparison、Baseline/Module extraction、Compatibility、
  Experiment design 和 Method Draft；
- [ ] 证据不足、不可复现、license/shape/semantic 冲突进入 REVISE/NO-GO；
- [ ] 八类 Artifact 写入 PaperClaw append-only store，禁止第二套持久化 schema。

完成条件：两个跨论文场景生成八类 evidence-bound Artifact；critical unsupported claim、
citation mismatch、false GO 均为 0。

### H4：Desktop 与人工审批闭环

- [ ] Desktop 发现并加载 PaperAgent optional extension，无循环依赖；
- [ ] 导入、parse/index progress、structured failure、channel/budget/Trace 可见；
- [ ] Claim → locator → PDF page/bbox、Figure/Table/Equation 可点击回读；
- [ ] Evidence Ledger 展示 accepted/rejected/conflicted 和原因；
- [ ] 长任务支持 cancel、restart recovery、progress trace 和 bounded failure；
- [ ] 未批准的 Methodology、Compatibility Matrix、Experiment Matrix 不得 final/export；
- [ ] Approve/Reject 只追加 revision，Reject 原因和历史永久保留；
- [ ] 完成 Native Windows Desktop 人工点击 checklist 和脱敏截图。

完成条件：用户本人完成
导入→解析→查询→证据回读→跨论文分析→审批→final export。

### H5：真实验收与 P0 GO

- [ ] 为 12 篇 corpus 建立 32 个 blinded questions：文字、Figure、Table、Equation 各 8 个；
- [ ] 冻结 2 个 baseline/module tailoring 场景和人工 expected decisions；
- [ ] 在目标 GPU 上运行真实 SentenceTransformer/ColQwen2 benchmark；
- [ ] 运行真实 OpenAI-compatible LLM，保存 provider、model、budget、脱敏 Trace、
  Evidence 和 Artifact revisions；
- [ ] 至少一名人工 reviewer 审批或拒绝并记录理由；
- [ ] 分开报告 synthetic、真实论文离线、GPU、真实 LLM 和人工结果；
- [ ] 两仓 full CI、wheel/package、Desktop smoke、SOP completion check 全绿。

只有全部 hard Gate 通过后，才允许改为 `P0 GO / release_accepted`。

## 5. P1 开发与优化计划

P1 不得在 P0 hard Gate 未闭合时改写 P0 契约。

### P1-A：Relation Graph

- Paper→Paper citation、Paper→Method、Method→Dataset、Method→Metric、Claim→Evidence；
- edge 必须绑定 provenance 和 locator；LLM 推断 edge 标为 `inferred`；
- 图只用于候选发现与关系约束，不替代原始证据。

### P1-B：质量平台

- 版本化 gold labels、corpus splits、model/index fingerprints 和 run manifests；
- Recall、MRR/nDCG、bbox IoU、abstention、citation mismatch、unsupported claim、
  false GO/NO-GO、repair success、latency、VRAM、cost；
- Human/LLM judge 不能覆盖 deterministic hard failures；
- regression threshold、drift detection 和跨版本对比。

### P1-C：性能和产品质量

- embedding batch、显存自适应、OOM retry、缓存配额和 LRU；
- 增量 parse/index、并发导入、事务恢复、index compaction 和 streaming；
- p50/p95 latency、吞吐、峰值 RAM/VRAM 和 cold-start；
- Desktop accessibility、错误态、Artifact diff、privacy UI、安装和迁移。

## 6. P2 计划

### 受限 Coding Worker

- 只消费 approved Experiment Matrix/Method Draft，不自主决定科学 GO；
- workspace sandbox、命令 allowlist、资源预算、checkpoint/undo、patch review；
- 生成 config、adapter、实验脚本和测试；禁止自动修改论文正文或执行高成本训练；
- 每次执行绑定 Artifact revision、commit、environment fingerprint 和 Trace。

### Connector / Skill 扩展

- HTTP/MCP 只能作为次级 adapter，不替代 P0 Python interface；
- Connector 必须有权限、许可、provenance、rate limit 和 secret-redaction contract；
- Skill 不得绕过 Evidence、Artifact review 或 Permission Gate。

非目标：公开多租户、通用 IDE、自动投稿、无界 autonomous research、PixelRAG 训练、
大规模分布式服务。

## 7. 跨阶段工程规则

- 新能力先写 seam-level tracer test，再做最小实现；
- PaperClaw canonical contract 变更先加 serialization fixture，再同步 PaperAgent adapter；
- 禁止双仓各自新增同名事实模型；
- Python 3.11 只验证 PaperAgent structural adapter；真实 PaperClaw integration 在 3.12 验证；
- 不降低 strict Mypy、coverage、abstention 或 source-hash Gate；
- 每阶段保存命令、summary、coverage、wheel SHA-256、corpus/model fingerprint
  和双仓 commit SHA；
- 自动化通过不等于 live/scientific/human validation；
- 缺失证据、冲突、版本漂移或无法 resolve 的 Claim 必须 fail closed。

## 8. 推荐验证命令

PaperAgent：

```powershell
git checkout codex/academic-rag-p0
git rev-parse HEAD
python scripts/local_acceptance.py --profile full --continue-on-error
pytest tests/academic -q
```

PaperClaw：

```powershell
git checkout codex/academic-rag-p0
git rev-parse HEAD
python -m pytest -q -m "not real_llm and not process_acceptance and not distributed"
python scripts/academic_corpus_acceptance.py `
  --corpus data/paper_corpus `
  --workspace build/corpus-acceptance-<timestamp> `
  --output artifacts/v0_43/real_corpus_report.json
python .claude/hooks/sop_completion_check.py
python -m build
```

跨仓 tracer 环境：Python 3.12、PaperAgent editable install、PaperClaw 0.43
editable/wheel install、PyMuPDF。

## 9. 下一执行者起点

本文同步完成后停止，不继续执行 H0–H5。

下一批次从 H0 剩余事项开始：

1. 建立两仓关联 PR，记录 final head SHA 和 CI run；
2. 生成 corpus license/source/status manifest；
3. 处理 10 条 failed/invalid/corrupt 输入；
4. 冻结 12 篇验收集；
5. 未完成 Native Desktop、真实 LLM、blinded labels 和人工审批前，状态保持
   `offline_validated / P0 GO blocked`。
