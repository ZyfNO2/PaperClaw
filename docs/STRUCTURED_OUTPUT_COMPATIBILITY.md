# Structured Output 兼容性与降级策略

> Status: ACTIVE ENGINEERING POLICY  
> Scope: PaperClaw Provider adapter、模型调用边界与后续结构化输出扩展  
> Last updated: 2026-07-17

## 1. 背景

OpenAI-compatible 只表示请求与响应大体遵循 OpenAI Chat Completions 形状，不代表代理、网关或模型完整支持 OpenAI 的所有扩展能力。

已知示例：DeepSeek V4 Flash 通过 OpenCode 代理调用时，不支持：

```json
{
  "response_format": {
    "type": "json_schema"
  }
}
```

因此，PaperClaw 不得根据“OpenAI-compatible”这一标签推定 `json_schema`、`json_object`、tool calling、reasoning 字段或 streaming 的真实支持情况。

## 2. PaperClaw 当前行为

当前 OpenAI-compatible adapter 位于：

```text
src/paperclaw/models/adapters/openai_compat.py
```

当前请求体仅包含普通 Chat Completions 字段：

```python
{
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0,
}
```

当前实现不发送 `response_format`。

Provider 返回后，adapter 负责：

```text
OpenAI-compatible response
→ provider response normalization
→ ModelTurn(content, reasoning, metadata)
```

当前边界是正确的：

- Provider adapter 负责传输、错误归一化、重试和响应归一化；
- Runtime 消费标准化后的 `ModelTurn`；
- 不依赖代理原生 Structured Outputs 才能完成基本模型调用；
- 不把 Provider 的兼容性声明当作能力证明。

## 3. 强制原则

### 3.1 能力必须显式声明或探测

如果未来增加结构化输出支持，必须区分以下能力：

```text
supports_json_schema
supports_json_object
supports_tool_calling
supports_reasoning_field
supports_streaming
```

能力来源只能是：

1. 受版本控制的静态 Provider/Model profile；
2. 可重复执行的 capability probe；
3. 已记录的真实 Provider 验收结果。

未知能力一律按 `false` 处理。

### 3.2 `response_format` 必须按能力条件注入

允许的降级顺序：

```text
native json_schema
→ native json_object
→ prompt-only JSON
→ plain text
```

当 Provider 或模型不支持某项能力时，请求体中必须完全移除对应字段，而不是继续发送并等待代理忽略。

禁止：

```python
payload["response_format"] = {
    "type": "json_schema",
    "json_schema": schema,
}
```

除非 capability profile 明确声明 `supports_json_schema=True`。

### 3.3 Provider adapter 不承担业务 Schema 语义

PaperClaw adapter 可以负责：

- 提取 `content`；
- 提取公开的 `reasoning` / `reasoning_content`；
- 归一化 token usage、finish reason、request ID；
- 区分网络错误、限流、认证错误和无效响应；
- 执行有界 retry。

PaperClaw adapter 不应直接绑定具体业务 Pydantic schema，也不应在 Provider 层决定论文规划、检索、评估等业务对象是否合法。

结构化业务合同应由上层能力或调用方拥有。

## 4. 推荐扩展接口

未来需要结构化输出时，建议引入明确模式：

```python
from enum import StrEnum


class StructuredOutputMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_ONLY = "prompt_only"
    NONE = "none"
```

Provider 能力建议表示为：

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_json_schema: bool = False
    supports_json_object: bool = False
    supports_tool_calling: bool = False
    supports_reasoning_field: bool = False
    supports_streaming: bool = False
```

请求构造逻辑必须返回最终采用的模式，便于 Trace 和验收：

```text
requested_mode
resolved_mode
capability_source
fallback_reason
```

## 5. 响应兼容规则

OpenAI-compatible 响应可能将可消费内容放在不同字段：

```text
choices[0].message.content
choices[0].message.reasoning_content
choices[0].message.reasoning
```

PaperClaw 可以归一化这些字段，但必须遵守：

- `content` 是默认可执行输出；
- reasoning 仅作为兼容性来源和受控观测信息；
- 不持久化完整私有思维过程；
- 不把空 content 自动视为成功；
- 无法归一化时返回明确的 ProviderError；
- 不用空字符串、空对象或空列表掩盖 Provider 失败。

## 6. 重试边界

结构化输出失败与网络失败必须区分。

可以重试的典型情况：

- transient disconnect；
- timeout；
- 429；
- 部分 5xx；
- Provider 返回无效 JSON envelope。

不应由 Provider retry 直接解决的情况：

- 业务 JSON schema 不符合；
- Pydantic validation 失败；
- semantic validation 失败；
- 模型返回了错误业务结论。

Provider retry 继续保持有界，禁止无限重试。

## 7. 测试要求

未来修改 Structured Output 支持时，至少覆盖：

| 场景 | 必须验证 |
|---|---|
| Provider 不支持 json_schema | 请求体不存在 `response_format` |
| Provider 支持 json_schema | 请求字段与 schema 形状正确 |
| 只支持 json_object | 自动降级到 `json_object` |
| 两种都不支持 | 自动降级到 prompt-only 或 plain text |
| content 正常 | 正确生成 `ModelTurn.content` |
| content 为空、reasoning 有值 | 按明确策略归一化，不静默成功 |
| malformed provider response | 返回 typed ProviderError |
| retryable network failure | 在预算内重试 |
| non-retryable authentication failure | 不重试 |
| capability 未知 | fail-closed，不发送扩展字段 |

Fake、Mock 与真实 Provider 测试必须分开报告。

## 8. 禁止事项

- 禁止因为 endpoint 是 `/chat/completions` 就假定支持 OpenAI 全部扩展；
- 禁止无条件发送 `response_format=json_schema`；
- 禁止通过捕获所有异常后返回空结果来维持流程；
- 禁止把业务 JSON repair 塞进底层网络 retry；
- 禁止在日志、Trace 或异常中泄露 API key；
- 禁止把 Mock/Fake 兼容测试写成真实 Provider 已验证；
- 禁止引入无界 formatter/retry 递归。

## 9. 当前结论

PaperClaw 当前“不发送 `response_format`，只做普通 completion 与响应归一化”的实现，应继续作为兼容性 baseline。

只有在项目明确引入结构化输出合同后，才增加 capability-gated 的 `json_schema/json_object` 支持。未被证明支持的 Provider/Model 一律走降级路径。
