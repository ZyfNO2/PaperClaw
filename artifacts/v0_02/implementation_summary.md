# PaperClaw v0.02 实现摘要

## 目标

让 `done` 不再等于“直接完成”，而是先进入 Verify，再由有界 Reflection 决定接受、修复、重验或阻塞。

## 本次落地

- 将完成语义改为 `DoneProposal`
- 新增 `TaskClaim` / `VerificationPlan` / `VerificationCheck` / `VerificationEvidence` / `VerificationResult`
- 新增 `ReflectionDecision` 及结构化 parser / validator
- 新增 `VerifyDoneProposalNode` 与 `ReflectNode`
- 新增 feature flag：`--enable-verification-gate`
- 新增内存态 trace 事件，支持导出 Verify / Reflection 过程
- 新增文件 hash 检查与 pytest / 相关命令结果摘要提取
- 新增 Reflection 防篡改校验：不能伪造 evidence、不能在失败时 accept、不能删减 failed claims

## 兼容性

- Gate 默认关闭，v0.01 路径仍可复现；
- Gate 关闭时仍保留旧 `done` 事件，避免打破既有测试与调试输出；
- Gate 打开后，完成路径变为 `done_proposed -> verify -> reflect -> done|blocked`。

## 风险与现实观察

- Verify 已能阻止“无关成功命令冒充验证”和“修改后未重验直接完成”；
- 真实模型仍可能先走一两步低质量修复尝试，再被 Gate 拉回正确路径；
- `bash` 仍可越过 `file_write` / `file_edit` 的更细粒度约束，因此 Permission Engine 仍是后续必做项。

## 收尾 Review 结论

- Verify 目前基于工作区文件、运行 history、bash metadata 和 pytest 摘要生成 `VerificationResult`，没有把模型自述当作客观 Evidence。
- Reflection 经过 `validate_reflection_decision()` 二次校验，不能伪造 `evidence_ids`、不能在 Verify 未通过时 `accept`、也不能删减 required `failed_claim_ids`。
- feature flag 默认关闭，v0.01 兼容路径仍保留；启用 `--enable-verification-gate` 后才切换到 `done_proposed -> verify -> reflect`。
- 文档侧已同步到 `44 passed, 1 skipped` 的当前测试基线，并将 v0.02 SOP 状态收口为已完成。
