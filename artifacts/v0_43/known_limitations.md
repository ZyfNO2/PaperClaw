# Known Limitations

- Native Desktop click-through 与 107 篇私人语料验收由用户集中在最终 Gate 执行。
- 扫描 PDF 不启用 OCR；复杂双栏、公式和表格允许明确 partial。
- 默认 dense 通道使用 deterministic local fallback；安装 academic extra 后可接入
  Transformer encoder。
- Visual encoder 可选；未加载时结果明确记录 `visual unavailable`，不会伪装为视觉命中。
- 首次 ColQwen2 加载约 13 秒（当前单页 CUDA smoke），批量吞吐需在最终语料验收记录。
- 本轮不含论文关系图、全文 PDF 编辑器、联网题录核验或完整 Academic RAG benchmark。
