# Doc/ExtDev — 扩展开发者文档（社区）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

读者：为引擎编写扩展（Extension）的社区开发者 —— 引擎团队以外的开发者，以及无上下文的 AI agent（本区文档自包含：开发扩展不需要阅读 Doc/Dev/ 内部协议）。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline extdev/README                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show extdev/README#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 从这里开始 · 2 官方示例扩展（对照学习 — 推荐先读源码） · 3 获取方式与生态（过渡期 → 目标） · 4 硬性约定速览（详细见规范全文） · 5 文档地图（本区）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/README.md`。
