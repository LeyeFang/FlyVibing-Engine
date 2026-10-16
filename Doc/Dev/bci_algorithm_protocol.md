# BCI 算法域开发协议（Application/Functions/BCIAlgorithm）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用: epoch 数据集、FBCSP / CCA 算法节点、模型注册表与训练语义。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/bci_algorithm_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/bci_algorithm_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 文件地图 · 2 数据模型（EpochDataset — 神经工程学口径） · 3 算法节点（必要超参模式 + 打包 list） · 4 训练语义（同步等待 — 核心约定） · 5 模型注册与键规则 · 6 空采验证（Stage ④, 2026-10-03 实测） · 7 测试

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/bci_algorithm_protocol.md`。
