# v0.43 Implementation Summary

实现了从已托管 PaperVersion 到结构化对象、文本/视觉 generation、统一检索、
Evidence Bundle、Memory 与 Desktop 的本地闭环。

- Parser：PyMuPDF adapter；manifest 绑定 source hash 和 parser fingerprint。
- Objects：页面、章节、段落、图、caption、表、公式、算法、参考文献。
- Index：SQLite + 文件资产；失败事务回滚，成功后原子激活。
- Visual：`VisualEncoder` Protocol 和 `ColQwen2Encoder`，第三方 tensor 不进入公共契约。
- Retrieval：保留 lexical / dense / visual 分数，并提供 expand / resolve / abstention。
- Product：Python、REST、CLI 和 Desktop controller 共用同一 Runtime。

参考现有 Artifact Store 的 content-addressed 与 revision 思路，未复制其数据库表；
复用了现有 Project Memory 与 Artifact 公共接口。
