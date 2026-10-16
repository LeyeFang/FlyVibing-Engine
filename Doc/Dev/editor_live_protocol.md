# 编辑器实时命令总线 / MCP 热注入协议（Editor Live）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：Application/Editor/Services/LiveCommandServer.py（编辑器侧总线）、FlyVibing-User-And-Developer-Utils/packages/editor-mcp/**（…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/editor_live_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/editor_live_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 架构与线程纪律 · 2 端点与配置 · 3 协议（NDJSON + 二进制尾帧） · 4 op 表（v2 基础 13 条 — 2026-09-28 实机验证；v3 容器表见 §4.1） · 5 agent 通道（MCP / CLI / Skill — v0.4.0 混合形态） · 6 新增一个 op 的步骤（扩展清单） · 7 故障排查 · 8 测试与验收 · 9 路线（后续阶段） · 10 容器补全跟进（Follow-ups — 2026-09-28 盘点）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/editor_live_protocol.md`。
