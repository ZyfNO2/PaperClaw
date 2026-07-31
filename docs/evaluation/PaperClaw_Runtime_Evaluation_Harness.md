# PaperClaw Runtime Evaluation Harness

## 目标与边界

本 Harness 补齐 Case → Runtime/recorded execution → durable Trace → deterministic scoring →
unified report 的编排闭环。它扩展 `paperclaw.eval`，不创建第二套 Trace、ToolRegistry、
Message Bus 或 research/retrieval evaluator。

不在本阶段实现：Web/Desktop 评估页、人工标注平台、审批中心、自动批准、Prompt 优化、
多 Judge 投票、真实 Provider 默认执行或 distributed 默认执行。

## 现有能力矩阵

| 能力 | 当前模块与输入 | 输出 | 本次处理 |
|---|---|---|---|
| Trace 聚合 | `paperclaw.eval.aggregate` + durable `TraceReader` | latency/reliability/token/cost | 直接复用 |
| Research 结果评分 | `paperclaw.research_eval` dataset + results | JSON/Markdown | 报告引用，不复制指标 |
| Retrieval 质量 | `paperclaw.retrieval.quality_eval` benchmark + predictions | Recall/MRR/nDCG/citation/grounding | 报告引用，不复制指标 |
| Runtime Case 执行 | 缺失 | — | 新增 recorded/durable adapter 与 Runner |
| Multi-Agent trajectory | durable Trace 中的 team events | workflow/role metrics | 新增规则评分 |
| HumanGate | 无生产领域对象；仅有 permission denial | — | 新增最小 Gate event 评估语义，不实现审批平台 |

## Case Contract

`schema_version` 固定为 `1`。Loader 对顶层、request、expectation、limits 和 expected_gate
执行 fail-fast unknown-field 校验；terminal state 与 role 直接引用现有 MultiAgent 枚举。
Case digest 是 canonical JSON 的 SHA-256，因此不受映射字段顺序影响；Runner 按 case_id
排序，因此 dataset 行顺序不影响汇总结果。

离线 Case 通过 `metadata.trace_fixture` 引用仓库内 Trace v1 JSONL。路径必须留在 workspace
内。Local/live/distributed Case 通过 `metadata.run_id` 与 `--trace-database` 读取现有 SQLite
Trace；Harness 不执行或复制外部副作用。

## 指标与判定

- Workflow：terminal match、Team Plan coverage、required role、assignment、Worker completion、
  Reviewer accept/rework/loop、orphan/unfinished/step limit。
- Tool/Policy：required/allowed/forbidden Tool、生产 schema validation observation、failure、
  timeout、duplicate、permission denial/bypass、Extension call-time recheck。
- Reliability：retry/recovery/exhaustion、duplicate successful attempt、Outbox、Ack、DLQ、
  cancellation、claim recovery、terminal consistency。保持 at-least-once 语义。
- Trace：start/terminal、sequence、Tool call/result、terminal 后非法事件、Secret marker、
  token/cost known/unknown。
- HumanGate：expected/missing/unexpected Gate、reason/action match、WAITING_APPROVAL、Gate 前后
  受保护动作。Runner 永不批准 Gate。

确定性 safety failure 始终优先于可选 Judge。当前 MVP 不实现 LLM Judge；CLI 对
`--enable-llm-judge` fail closed。

## Report

每次运行生成 manifest、summary、Markdown、per-case result、Trace reference，以及对现有
aggregate/research/retrieval evaluator 的兼容引用。Offline Fake/recorded 成本不计入 live
平均值；未知 token/cost 为 `null`，不是 0。

## 既有实现参考

| 仓库/版本 | 文件 | 借鉴目标 | 禁止照搬 |
|---|---|---|---|
| PaperClaw `5891d87` | `eval/aggregate.py`, `trace/*`, `multiagent/*`, `projects/extension_execution.py` | Trace/枚举/权限/指标事实 | 第二套 Runtime/Trace/Tool validation |
| PaperClaw `5891d87` | `research_eval/*`, `retrieval/quality_eval.py` | 研究与检索指标复用 | 重写 Recall/MRR/nDCG/citation |

本次没有迁移外部仓库代码，因此无新增 attribution 或 license 义务。
