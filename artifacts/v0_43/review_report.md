# Independent Review Report

Review scope: `5891d87..23b8c49`

初审发现四个 blocking issue，均在 follow-up 修复：

1. existing generation A→B→A 未重新激活：已原子切换 active generation，并增加回归；
2. corpus hash 漏掉视觉对象：已纳入 object type、source hash 与 asset hash；
3. Unified Retrieval 契约未接产品路径：`RetrievalRequest`、channels、budget、
   `RetrievalTrace`、channel scores 与 model fingerprint 已贯通 Runtime、REST、CLI、
   Desktop 和 Evidence Bundle；
4. 视觉索引一次性批量加载页面：改为逐页有界推理，inference CUDA OOM 时清理
   cache 并降级 CPU。
5. 复审发现 active generation 与当前 encoder 可能静默不兼容：retrieval 现强制
   校验 runtime/index model fingerprint；失配要求重建，并有回归测试。

同时修复 locator 完整反序列化，并产出 paragraph/table-cell locator。

剩余 P1/P2 风险记录在 `known_limitations.md`；Native Desktop 与 107 篇语料仍为
最终人工 Gate。
