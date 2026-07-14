# PaperClaw 上下文系统与提示词工程骨架

> 状态：设计讨论稿
>
> 目标：为轻量 Coding / Research Agent 建立可观察、可压缩、可恢复且有权限边界的 Context Runtime。

## 1. 核心判断

PaperClaw 不应从“超级提示词”开始，而应先实现一个小型 **Context Runtime（上下文运行时）**。

Claude Code 的关键不在某一段神奇 Prompt，而在于把身份、项目规则、当前任务、工具说明、历史记录和环境状态按职责拆开，在每轮调用模型前动态装配。进一步说，Prompt 只是上下文的一种表现形式；真正要设计的是信息如何进入、保留、压缩、检索、失效和审计。

参考：[Claude Code 的提示词工程](https://xuanyuancode.com/learn-claude-code/tutorials/cc18)

## 2. Prompt、Context 与 Memory

### Prompt

Prompt 告诉模型如何行动，包括 Agent 身份与目标、工具调用规则、权限边界、输出格式和当前工作模式。

### Context

Context 是模型当前一轮真正看到的全部信息：

$$
Context = Prompt + History + State + Memory + Tool\ Results + Retrieved\ Evidence
$$

它可能包括 System Prompt、用户输入、历史消息、项目规则、文件内容、工具结果、任务状态、检索记忆和环境状态。

### Memory

Memory 是不应长期常驻窗口、但未来可能再次有用的信息，例如用户偏好、项目命令、架构决策、失败原因、未完成任务以及文件和模块的语义索引。因此，Prompt Engineering 只是入口，PaperClaw 真正要实现的是 **Context Engineering**。

## 3. 六层上下文模型

每轮调用模型时，由 `ContextBuilder` 动态生成上下文：

```text
L0  Runtime Constitution   稳定规则
L1  Role / Mode            当前角色与工作模式
L2  Workspace Context      项目和目录规则
L3  Task State             当前任务状态
L4  Working Context        最近对话和工具结果
L5  Retrieved Memory       按需检索的长期记忆
```

### L0：Runtime Constitution

最稳定、优先级最高的一层，包括 Agent 身份、指令优先级、安全边界、不得伪造工具结果、不得把外部文本当成系统指令、权限判断原则，以及必须询问用户的条件。这一层应短而稳定，尽量进入 Prompt Cache。

### L1：Role / Mode

根据状态动态插入 `chat`、`plan`、`execute`、`review`、`research`、`subagent` 或 `compact` 模式。角色不是一句“你是代码专家”，而是包含目标、允许动作、确认条件和完成条件的状态：

```yaml
mode: execute
goal: 修复 QueryEngine 的重复检索
allowed_actions: [read, search, edit_workspace]
requires_confirmation: [delete, external_write]
completion_condition: [tests_pass, explain_changes]
```

### L2：Workspace Context

项目规则采用目录作用域：全局规则 → 仓库根 `AGENTS.md` → 子目录规则 → 当前文件附近规则。越接近工作目录，规则越具体。每个规则片段应保留来源、作用域、优先级、更新时间和内容哈希，以支持缓存、失效和 Trace。

### L3：Task State

对话历史不等于任务状态。任务状态应结构化保存：

```json
{
  "goal": "实现轻量 ContextBuilder",
  "status": "in_progress",
  "constraints": ["暂时不引入向量数据库", "保持 PocketFlow 风格"],
  "decisions": ["短期记忆与长期记忆分离"],
  "completed": ["确定上下文分层"],
  "next_actions": ["定义 ContextItem 数据模型"],
  "open_questions": [],
  "artifacts": []
}
```

压缩可以丢掉过程性冗余，但不能丢掉目标、约束、决定和未完成事项。Task State 是 Session Resume、任务评估和多 Agent 协作的基础。

### L4：Working Context

活跃工作集包括最近消息、工具调用、当前文件片段、错误、未完成调用和计划。不能只保留最近 N 条消息，还应分配 token 预算：

```yaml
total_token_budget: 32000
recent_messages_budget: 10000
tool_results_budget: 8000
retrieved_memory_budget: 5000
reserve_for_output: 6000
```

工具结果分为 `raw` 原文、`summary` 摘要和 `reference` 外部引用三种形态。

### L5：Retrieved Memory

长期记忆按需检索，至少区分：

- `semantic`：用户偏好、项目知识和架构决策；
- `episodic`：过去的任务和问题；
- `procedural`：任务执行步骤；
- `artifact`：报告、代码和测试产物；
- `negative`：失败方案、已知坑和不得重复的尝试。

检索采用混合评分，而不只使用向量相似度：

$$
Score(m)=w_sS_{semantic}+w_kS_{keyword}+w_rS_{recency}+w_pS_{priority}+w_tS_{task}-w_cCost_{token}
$$

## 4. 统一数据模型：ContextItem

所有模块提交结构化 `ContextItem`，而不是直接拼字符串：

```python
class ContextItem:
    id: str
    kind: str
    content: str
    source: str
    scope: str
    priority: int
    trust_level: str
    created_at: datetime
    expires_at: datetime | None
    token_estimate: int
    pinned: bool
    compressible: bool
    sensitive: bool
```

建议的 `kind` 包括 `constitution`、`role`、`project_instruction`、`user_message`、`assistant_message`、`task_state`、`tool_result`、`memory`、`retrieved_document`、`environment` 和 `permission_state`。

```python
items = collect_context(runtime_state)
items = resolve_conflicts(items)
items = filter_by_scope(items)
items = retrieve_relevant_memory(items)
items = enforce_permissions(items)
items = fit_token_budget(items)
prompt = render(items)
```

## 5. ContextBuilder 流程

```text
收集候选上下文 → 检查来源与作用域 → 处理优先级和冲突
→ 检索记忆 → 去重与时效检查 → 敏感信息过滤
→ 按 token 价值选择 → 必要时压缩 → 渲染 → 记录 Context Trace
```

最终模型输入仍可保持简单：

```text
[System: Constitution]
[System: Current Mode]
[System: Workspace Instructions]
[System: Permission State]
[System: Task State]
[System: Retrieved Memory]
[Messages: Recent Conversation]
[Tool: Recent Results]
[User: Current Request]
```

工程价值在装配过程，而不在最终格式是否复杂。

## 6. 压缩与 Checkpoint

轻量压缩负责删除重复日志、保留关键错误和退出码、将文件全文变成摘要加引用，以及合并搜索结果。

窗口达到阈值时生成结构化 Checkpoint：

```yaml
objective:
confirmed_constraints:
important_findings:
decisions:
modified_files:
failed_attempts:
pending_work:
verification_status:
source_references:
```

原始对话存数据库；Checkpoint 和最近几轮原文进入活跃上下文；需要时再根据引用读取原文。压缩结果必须区分已验证的 `fact`、已确认的 `decision`、未验证的 `hypothesis` 和未完成的 `todo`，避免把猜测压缩成事实。

## 7. 权限系统

Prompt 可以引导模型，但真正的权限必须由执行层拦截：

```text
Model proposes tool call
          ↓
Permission Engine
          ↓
allow / deny / ask / transform
          ↓
Tool Executor
```

模型上下文只接收当前权限视图，例如工作区读写、工作区外写入、联网、外部副作用和破坏性命令的状态。即使模型忽略 Prompt，执行器也不能越权。

> Prompt 负责引导行为，Policy Engine 负责保证边界。

## 8. 工具 Prompt 与 Tool Governance

工具说明采用结构化定义：

```yaml
name: read_file
capability: 读取本地文本文件
use_when: [已知明确文件路径]
avoid_when: [需要搜索未知文件]
constraints: [路径必须标准化, 不得绕过作用域检查]
result_policy: [大文件返回片段和引用]
```

每个工具还应携带权限类别、副作用等级、成本、超时、重试策略、长期记忆准入规则和输出压缩策略。这使工具描述升级为 Tool Governance，而不只是 API 文档。

## 9. 一周 MVP 边界

第一周不做完整向量数据库或 Knowledge Graph，只做：

1. 分层 Prompt Section；
2. `ContextItem` 统一数据模型；
3. 最近消息与结构化 Task State；
4. 工具结果摘要；
5. token 预算和简单裁剪；
6. SQLite 保存 Session、Message、Tool Call、Checkpoint；
7. 每轮 Context Trace；
8. 一个压缩前后约束保持率测试。

建议的数据表：`sessions`、`messages`、`task_states`、`tool_calls`、`context_items`、`checkpoints`、`memory_items`、`eval_runs`。

## 10. 评估指标

- **Constraint Retention**：压缩后保留多少关键约束；
- **Fact Grounding**：回答能否指向正确来源；
- **Context Precision / Recall**：进入上下文的信息是否有用且充分；
- **Tool Selection Accuracy**：是否选择正确工具；
- **Recovery Success**：重启 Session 后能否继续；
- **Token Efficiency**：相同任务消耗多少上下文 token；
- **Stale Memory Rate**：是否引用过时记忆；
- **Permission Violation Rate**：是否尝试越权；
- **Compaction Drift**：多次压缩后事实和约束是否漂移。

RAG Eval 评估“取回了什么”，Context Eval 评估“最终给模型看了什么，以及这些信息是否足够”。

## 11. 项目定位

PaperClaw 第一阶段定位为：

> 一个可观察、可压缩、可恢复、有权限边界的轻量 Agent Context Runtime。

它不是在 Prompt 前堆叠 Markdown，而是把模型输入变成可管理、可追踪、可评估的数据管线。
