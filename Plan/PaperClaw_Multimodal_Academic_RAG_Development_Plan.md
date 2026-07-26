# PaperClaw 多模态论文工作区与 Academic RAG 开发计划

## 1. 产品定位

PaperClaw 作为两个项目的基础设施层，负责：

- 项目工作区与文件生命周期；
- 用户级、项目级与任务级 Memory；
- 论文原始文件、解析产物和研究 Artifact 的版本化存储；
- 文本、页面、图表、公式、算法与关系图索引；
- 统一 EvidenceLocator、检索协议、权限、Trace 与评测；
- 受限 Coding Worker 与 Connector / Skill 运行时。

PaperClaw 不负责最终学术方法判断、baseline 选择或论文写作；这些属于 PaperAgent。

## 2. 目标架构

```text
PDF / Markdown / LaTeX / Supplement / Repository
                |
                v
        Ingestion and Versioning
                |
        +-------+-------------------+
        |                           |
        v                           v
Structured Parsing             Page Rendering
sections / paragraphs          page images
figures / tables               regions / captions
equations / algorithms         layout coordinates
citations / metadata           visual embeddings
        |                           |
        +------------+--------------+
                     v
             Academic Object Store
                     |
       +-------------+-------------+-------------+
       |                           |             |
       v                           v             v
Lexical / Dense Index       Visual Page Index  Relation Graph
BM25 + dense vectors        ColPali-style      paper-method-
field/object indexes        page/object recall dataset-metric-
weighted RRF                multimodal rerank  citation-repo
       |                           |             |
       +-------------+-------------+-------------+
                     v
            Unified Retrieval Service
                     |
              Evidence Bundle API
                     |
                 PaperAgent
```

## 3. 核心数据契约

### 3.1 PaperRecord

必须稳定表示：

- `paper_id`、版本、内容哈希；
- 标题、作者、年份、DOI、arXiv ID；
- 原始文件与来源；
- 章节树、页码、阅读顺序；
- Figure、Table、Equation、Algorithm；
- Reference 与 Citation 边；
- Dataset、Metric、Method、Repository 关系；
- 解析器版本、索引版本与 provenance。

### 3.2 AcademicObject

对象粒度至少包括：

- `document`；
- `page`；
- `section`；
- `paragraph`；
- `figure`；
- `table`；
- `table_cell`；
- `equation`；
- `algorithm`；
- `citation`；
- `repository_link`。

每个对象必须绑定：

- `paper_id` 与版本；
- `page_number`；
- `section_path`；
- `bounding_box`；
- `object_type`；
- 原始文本、图像或结构化内容；
- `source_hash`；
- 可回放的 locator。

### 3.3 EvidenceLocator

统一支持：

```text
paper_id
paper_version
page_number
section_path
object_id
bounding_box
paragraph_index
line_range
table_row / table_column
source_hash
```

任何回答、方法卡片或导出内容都必须能够回到原始证据。

## 4. 开发阶段

## P0-A：论文导入与版本化

### 交付

- PDF、Markdown、纯文本和 LaTeX 文件导入；
- 文件哈希去重；
- 同一论文多版本管理；
- DOI / arXiv / 标题作者元数据归一化；
- Supplement 与代码仓库附件绑定；
- 项目级 Paper Collection；
- 文件修改后的增量重建与旧版本保留。

### 验收

- 重复文件不会产生重复 PaperRecord；
- 更新版本不会覆盖旧证据；
- 每个对象均绑定稳定版本与哈希；
- Windows / Linux 路径行为一致。

## P0-B：结构化论文解析

### 交付

- 页面布局和阅读顺序；
- 章节层级；
- 段落与页码；
- Figure / Caption；
- Table / Cell；
- Equation / Algorithm；
- Reference / Citation；
- 原始页面与对象截图。

解析器优先采用可替换 Adapter，允许接入 Docling、PyMuPDF、GROBID 或其他实现，不把第三方库格式暴露为公共契约。

### 验收

- 解析产物可序列化和重放；
- 图表、公式和章节对象具有准确页面定位；
- 解析失败保留原文件并给出结构化错误；
- 不把 OCR 或 VLM 推断当作原文事实。

## P0-C：多通道索引

### 文本与结构通道

- BM25；
- Transformer dense embedding；
- section-aware 和 object-aware chunking；
- Figure Caption、Table、Equation 独立索引；
- 精确字段索引：数据集、指标、方法名、论文标识符。

### 页面视觉通道

- 整页截图索引；
- Figure / Table 区域索引；
- ColPali / ColQwen 风格 late-interaction 页面表示；
- 原始页面回读；
- 多模态 reranker。

### 融合

- Named Retriever Adapter；
- weighted RRF；
- object type、section、paper 与 project filter；
- citation identity preservation；
- query-dependent fusion weights。

### 验收

- 图架构问题可以命中页面或 Figure；
- 表格数值问题可以命中 Table / Cell；
- 公式问题可以命中 Equation 与解释段落；
- 所有候选保留准确 locator。

## P0-D：统一 Retrieval Service

提供稳定接口：

```text
retrieve(query, project_scope, channels, filters, budget)
rerank(query, candidates, policy)
expand(candidate, neighborhood_policy)
resolve(locator)
```

返回：

- 候选对象；
- 文本与视觉分数；
- fusion / rerank 解释；
- EvidenceLocator；
- source hash；
- retrieval trace；
- 证据充分性状态。

## P0-E：Memory 与 Artifact 集成

### Memory 分层

- `UserMemory`：长期研究偏好；
- `ProjectMemory`：研究目标、baseline 决策、限制与术语；
- `TaskState`：当前检索计划与待确认事项；
- `ExecutionTrace`：不进入长期 Memory，只保存摘要和证据索引。

### Artifact

- Evidence Bundle；
- Paper Comparison；
- Baseline Card；
- Module Card；
- Compatibility Matrix；
- Experiment Matrix；
- Method Draft；
- Review Report。

所有 Artifact 继续使用 append-only revision 与来源链。

## P1-A：论文关系图

建立以下边：

```text
Paper -> proposes -> Method
Paper -> uses -> Dataset
Paper -> evaluates_with -> Metric
Paper -> compares_with -> Baseline
Paper -> contains -> Figure/Table/Equation
Paper -> cites -> Paper
Paper -> links_to -> Repository
Method -> implemented_by -> Repository
```

Graph 作为多跳探索和关系过滤辅助，不替代原始证据检索。

## P1-B：质量评测

### 检索指标

- Recall@K；
- MRR；
- nDCG；
- Document Recall；
- Page Recall；
- Object Recall；
- Citation Precision / Recall。

### 抽取指标

- Figure / Table / Equation 分类准确率；
- Table Cell 数值准确率；
- Dataset / Metric / Method 字段准确率；
- EvidenceLocator 准确率。

### 生成指标

- Grounded Claim Rate；
- Claim Coverage；
- Unsupported Claim Rate；
- Abstention Accuracy；
- 成本、延迟与上下文长度。

必须区分合成评测、离线真实论文评测和人工专家评测。

## P2：受限 Coding Worker

PaperClaw 提供通用但受限的仓库能力：

- 读取论文关联仓库；
- 符号、定义、引用和调用关系查询；
- 受限文件 Patch；
- allowlisted subprocess；
- 测试、lint 和最小实验；
- verified / pending / blocked Handoff。

默认禁止：

- 自动推送主分支；
- 任意 Shell；
- 未经范围限制的大规模重构；
- 把 Mock 测试描述为真实复现。

## 5. PaperClaw 与 PaperAgent 接口

PaperClaw 输出：

```text
ProjectContext
MemorySnapshot
PaperRecord
AcademicObject
EvidenceCandidate
EvidenceBundle
EvidenceLocator
RetrievalTrace
ArtifactRevision
CodingWorkerResult
```

PaperAgent 不直接访问底层 SQLite、页面缓存或向量实现，只通过公共协议使用这些能力。

## 6. 非目标

当前阶段不优先：

- Pixel-grounded 端到端检索模型训练；
- 公开多租户服务；
- 扩展市场；
- 更复杂的分布式调度；
- 为了通用 Coding 功能继续扩大底层范围。

## 7. 推荐实施顺序

```text
1. PaperRecord + PDF ingest + versioning
2. Structured parser + page/object locators
3. Page rendering + Figure/Table/Equation extraction
4. Dense text index + visual page index
5. Unified multimodal retrieval and reranking
6. Evidence Bundle API
7. PaperAgent integration contract
8. Relation graph
9. Real-paper benchmark and human review
10. Narrow Coding Worker integration
```

## 8. 完成判定

第一阶段 GO 条件：

- 用户上传单篇或多篇论文后可稳定建档；
- 文本、页面和对象三个粒度均可检索；
- 架构图、表格数值、公式和方法段落问题均有定位证据；
- PaperAgent 可以通过公共协议完成一次跨论文分析；
- 回答和 Artifact 可以回到原始页面与区域；
- 真实论文评测与合成测试明确区分。
