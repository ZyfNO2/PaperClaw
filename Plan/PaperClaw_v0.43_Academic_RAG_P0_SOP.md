# PaperClaw v0.39-v0.43 Academic RAG P0 SOP

状态：`offline_validated`  
范围：P0-A～P0-E；P1 关系图与完整 benchmark 后置。

## Gate

- [x] v0.39：PaperVersion 绑定的 page / section / paragraph 解析与幂等 manifest
- [x] v0.40：figure / caption / table / equation / algorithm / reference 对象与 locator
- [x] v0.41：文本、视觉多通道索引与 active generation 原子切换
- [x] v0.42：retrieve / expand / resolve、通道解释、充分性与 abstention
- [x] v0.43：Evidence Bundle、研究 Artifact、Memory、REST / CLI / Desktop 闭环
- [x] `vidore/colqwen2-base` snapshot revision 与 shard SHA-256 校验
- [x] ColQwen2 单页 GPU live inference 与性能记录
- [ ] Windows Native Desktop 点击验收及 107 篇冻结语料报告

## 硬边界

- candidate metadata 与 inferred OCR/VLM 结果不升级为 verified evidence。
- PaperAgent 只依赖公开 Retrieval 接口，不读取 SQLite、PyMuPDF 或模型缓存。
- 模型变更以 fingerprint 生成新 index generation。
- 私人 PDF、模型权重、页面缓存、向量和原始运行日志不提交 Git。

## 发布判定

自动测试和 Review 完成后状态最多为 `offline_validated`。上述两项人工/真实模型
Gate 均完成且 completion check 为 0 pending 后，才可宣布 Academic RAG P0 GO。
