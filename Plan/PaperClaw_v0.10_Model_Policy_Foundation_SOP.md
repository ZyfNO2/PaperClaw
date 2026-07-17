# PaperClaw v0.10 Static Model Policy Foundation SOP

> 状态：Implementation complete / CI pending  
> 分支：`feat/v0.10-model-policy-foundation`  
> 基线：`main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`  
> 范围：只冻结静态模型选择、成本估算和 bounded fallback 合同；不接 Runtime。

## 最小合同

- `ModelRequestProfile`
- `ModelCandidate`
- `ModelExclusion`
- `ModelPolicyDecision`
- `FallbackAttempt`
- `ModelFailureCategory`
- `StaticModelPolicyRouter`

## 路由事实

只允许以下结构化事实影响选择：

- required capability；
- estimated input tokens / output reserve；
- context window；
- structured-output requirement；
- cost ceiling；
- static preference rank；
- enabled flag；
- explicit user override。

不得使用 hidden reasoning 或自由文本“难度判断”。

## Fallback

允许：network、rate-limit、server error。

禁止自动 fallback：authentication、permission、invalid request、context overflow、structured-output failure、unknown。

Context overflow 后续必须回到 v0.08 Context reduction；本切片不直接切换模型掩盖约束丢失。

## 明确非目标

- Runtime / Provider wiring；
- dynamic provider health；
- 多云 Gateway；
- 自动竞价；
- Prompt Cache；
- 多租户计费；
-在线学习 Router。

## Gate

- candidate 输入顺序不影响 decision/fingerprint；
- capability/context/structured/cost/disabled filter 正确；
- explicit override fail-closed；
- fallback chain 有界；
-禁用错误类别不得切换模型；
- decision metadata 不含 Prompt 或 hidden reasoning；
- 全仓库非 live pytest 与 Ruff 通过。
