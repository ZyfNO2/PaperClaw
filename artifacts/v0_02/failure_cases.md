# PaperClaw v0.02 失败样例与防线

## 1. 无关成功命令冒充验证

- 场景：`echo ok`
- 预期：不能满足 `claim-verification-command`
- 结果：Verify failed

## 2. 修改后未重新验证

- 场景：先运行成功命令，再编辑文件，随后直接 `done`
- 预期：`verified_after_last_write=false`
- 结果：Verify failed

## 3. pytest 失败后直接尝试完成

- 场景：`pytest -q` exit 1 后直接 `done`
- 预期：不能 accept
- 结果：Reflection 只能 repair / blocked，不能越过 Gate

## 4. Reflection 伪造或删减证据

- 场景：引用未知 evidence，或删减 `failed_claim_ids`
- 预期：validator 拒绝
- 结果：停止为 `invalid_reflection_output:*`

## 5. 同一失败重复出现

- 场景：相同 failure signature 连续重复
- 预期：达到上限后停止
- 结果：`verification_failed` / `blocked`
