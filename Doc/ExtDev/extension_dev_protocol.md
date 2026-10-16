# 扩展开发规范协议（Extension Development Protocol）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

读者: 外部/无上下文的开发者与 agent（模拟社区生态 — 只有本文件 + 仓库即可开工）。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline extdev/extension_dev_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show extdev/extension_dev_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 适用范围与阅读顺序 · 2 快速上手（最小扩展） · 3 目录与命名规范 · 4 manifest 参考（extension.json） · 5 生命周期契约 · 6 ctx 能力总表（M0 实装 vs 规划） · 7 UI 规范（`ctx.ui` — `register_window` 已实装 2026-10-11） · 8 节点包规范（`[M1]` 设计） · 9 MCP/CLI 服务规范（增量扫描生态 — 本协议的生态核心） · 10 线程规范（现状纪律 + `[M2]` 受管模型） · 11 设置与数据目录 · 12 测试规范（扩展必带自测） · 13 实装地图（M0 → M3） · 14 提交检查单（无上下文 agent 开工前自查）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/extension_dev_protocol.md`。
