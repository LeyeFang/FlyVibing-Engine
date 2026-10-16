# 扩展体系架构协议（Extensions Architecture）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

状态: 已执行（2026-10-11）— §2 改名已落地（旧名 shim 过渡）; §7 M0 骨架已交付（实装地图见 Doc/ExtDev/extension_dev_protocol.md §13）。本文档职责 = 归档"三层高度…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/extension_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/extension_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 三层高度模型（依赖方向铁律） · 2 Plugin 审计与重构决议 · 3 切入架构 — 三档侵入模型 · 4 兼容与破坏面削减机制（跨扩展兼容性） · 5 贡献点目录（开发者能力面） · 6 守卫与验收（计划） · 7 分期对接（与扩展蓝图 M0-M3） · 8 拍板记录（2026-10-11）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/extension_protocol.md`。
