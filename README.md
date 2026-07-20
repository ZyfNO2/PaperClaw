# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

当前开发版本：**0.35.0**。v0.35 在真实 Redis/PostgreSQL Multi-Agent Runtime 之外，补齐了
本地语义向量检索、weighted RRF、证据感知 reranker，以及可复现的科研质量评测。

## 当前能力主线

```text
Team Plan
  -> SQLite or Redis Streams Message Bus
  -> Coordinator / Worker / Reviewer
  -> SQLite or PostgreSQL terminal state + ordered Outbox
  -> durable Trace / Aggregate Eval

Project Knowledge
  -> BM25 + persistent local semantic vectors
  -> weighted reciprocal-rank fusion
  -> evidence-aware citation-preserving reranker
  -> retrieval / citation / grounding / abstention / cost evaluation
```

`Coordinator` 仍是唯一调度权威。Hybrid Retrieval 继续使用已有 `RetrievalCandidate`、
`RankedResult`、版本 Hash 和 `ChunkLocator`，没有引入旁路 Citation 模型。

## 安装

```bash
python -m pip install -e ".[dev]"
```

分布式后端：

```bash
python -m pip install -e ".[distributed]"
```

## v0.35 Hybrid Retrieval

公开组件：

```python
from paperclaw.retrieval import (
    EvidenceAwareReranker,
    HybridRetriever,
    RetrievalBackendAdapter,
    RerankedHybridRetriever,
    SQLiteBM25Retriever,
    SQLiteHashingVectorRetriever,
    WeightedRRFConfig,
)
```

链路：

```text
SQLiteBM25Retriever
  + SQLiteHashingVectorRetriever
  -> HybridRetriever(weighted RRF)
  -> RerankedHybridRetriever(EvidenceAwareReranker)
  -> version/hash/locator-bound candidates
```

### 本地语义向量

`SQLiteHashingVectorRetriever`：

- 使用 word、word bigram 与 character n-gram；
- signed feature hashing；
- sparse L2-normalized vector；
- SQLite 持久化；
- encoder fingerprint；
- corpus fingerprint；
- 原子 corpus replace 与 bounded upsert；
- deterministic cosine ranking；
- 保留 document/version/content/source/chunk-config hash 与完整 `ChunkLocator`。

这是一个真实的本地向量检索后端，但**不是 transformer embedding**，也不声称等价于托管
Embedding API 或外部向量数据库。

### Weighted RRF

兼容原有 tuple API：

```python
HybridRetriever(
    (
        ("bm25", bm25, 1.0),
        ("semantic", semantic, 1.4),
    )
)
```

也支持显式命名配置：

```python
HybridRetriever(
    (
        RetrievalBackendAdapter("bm25", bm25),
        RetrievalBackendAdapter("semantic", semantic),
    ),
    config=WeightedRRFConfig(
        backend_weights={"bm25": 1.0, "semantic": 1.4},
        candidate_pool_size=50,
    ),
)
```

融合要求所有 backend 返回同一 active corpus，并对同一 `chunk_id` 保持一致的 Citation
Identity。冲突会 fail-closed。

### Evidence-aware Reranker

Reranker 使用可观察信号：

- exact phrase；
- query-token coverage；
- display name、source URI、heading path 与 locator range overlap；
- original rank prior；
- bounded length penalty；
- source diversity penalty。

Reranker 只修改排序和诊断 Score，不修改文档版本、内容 Hash、Locator 或 Citation Identity。

## v0.35 Research Quality Eval

CLI：

```bash
paperclaw-retrieval-quality \
  --benchmark examples/v0_35/research-quality-benchmark.json \
  --predictions examples/v0_35/hybrid-predictions.json \
  --baseline examples/v0_35/lexical-baseline.json
```

当前指标：

- Recall@5 / Recall@10；
- MRR；
- nDCG@10；
- Document Recall@10；
- Citation Precision / Recall；
- Grounded Claim Rate；
- Required Claim Coverage；
- Answer Term Coverage；
- Abstention Accuracy；
- latency；
- input/output/total tokens；
- estimated cost；
- baseline delta。

Groundedness 使用显式 `claim_support` observation 和人工维护的相关性标签，不让答案生成模型
给自己打分。评测结论取决于 benchmark 标签质量。

## Team Runtime

### SQLite 模式

```bash
paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --bus-backend sqlite \
  --database .paperclaw/team-bus.sqlite3 \
  --state-backend sqlite \
  --state-database .paperclaw/team-choreography.sqlite3 \
  --trace-database .paperclaw/traces.sqlite3
```

### Redis + PostgreSQL 模式

```bash
export PAPERCLAW_REDIS_URL="redis://localhost:6379/0"
export PAPERCLAW_POSTGRES_DSN="postgresql://paperclaw:paperclaw@localhost:5432/paperclaw"

paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --bus-backend redis \
  --redis-url "$PAPERCLAW_REDIS_URL" \
  --state-backend postgres \
  --postgres-dsn "$PAPERCLAW_POSTGRES_DSN" \
  --trace-database .paperclaw/traces.sqlite3
```

v0.34 提供：

- Redis Streams Topic；
- Lua 原子 Sequence、Capacity、Idempotency 与 append；
- Consumer Group 与 `XAUTOCLAIM`；
- 乱序物理 Ack、连续逻辑 Ack Cursor；
- PostgreSQL Attempt、Terminal Snapshot 与 Ordered Outbox；
- `FOR UPDATE SKIP LOCKED` Claim；
- 两个独立进程共享 Consumer Group 的真实验收。

v0.33 提供：

```text
Coordinator result
  -> terminal state + ordered Outbox in one transaction
  -> exact-idempotent publication
  -> mark delivered
  -> request Ack
```

并包含 durable cancellation、fault injection、retryable/permanent/unknown 分类和 DLQ。

v0.32 提供稳定身份：

```text
request_id -> team_run_id(request_id) -> durable Trace -> Aggregate Eval
```

查询：

```bash
paperclaw-observe \
  --database .paperclaw/traces.sqlite3 \
  --request-id interview-research-check \
  --pricing examples/v0_31/pricing.example.json
```

## Capability Catalog

```bash
paperclaw capabilities --format json
paperclaw capabilities --status shipped
paperclaw capabilities --surface cli
```

v0.35 新增：

```text
retrieval.semantic_hybrid [foundation]
evaluation.research_quality [shipped]
```

## 开发与验收

```bash
python -m pytest -q \
  tests/unit/retrieval/test_v035_semantic_quality.py \
  tests/unit/retrieval

paperclaw-retrieval-quality \
  --benchmark examples/v0_35/research-quality-benchmark.json \
  --predictions examples/v0_35/hybrid-predictions.json \
  --baseline examples/v0_35/lexical-baseline.json \
  --format text

python -m pytest -q -m "not real_llm and not distributed"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
```

## 安全与架构边界

- Secret 不写入 Manifest、Message Bus、ExecutionRequest、Trace 或 Artifact metadata；
- Message delivery 是 at-least-once，不是 exactly-once；
- PostgreSQL 和 Redis 不构成同一分布式事务；
- Trace projection 仍为 SQLite reference backend；
- 外部 Tool 副作用仍要求 Tool-level idempotency；
- Redis Cluster cross-slot Lua、Kafka 和 NATS 未声明实现；
- 本地 hashing vector 不等于 transformer embedding；
- 质量评测不等于未经标注的通用事实正确率；
- Project-scoped Skills / Connectors 属于 v0.36。

## 版本路线

1. **v0.32**：Team Run、Trace、Eval 闭环；
2. **v0.33**：恢复、取消、Outbox、幂等与故障注入；
3. **v0.34**：PostgreSQL + Redis Streams 多进程运行；
4. **v0.35**：Hybrid Retrieval 与科研质量评测；
5. **v0.36**：Project-scoped Skills / Connectors。
