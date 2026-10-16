# 节点编辑器业务逻辑开发协议

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：节点类型定义、求值器（evaluator）、图约束、执行引擎、图文档（agent 消费）、程序化构图（GraphBuilder）、agent 通道（CLI + MCP, FlyVibing-User-And-Developer-U…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/node_editor_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/node_editor_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 域地图 · 2 执行模型（写求值器前必须理解） · 3 新增节点完整清单（10 步，缺一不可） · 4 Dry-Run（MCP 空跑）契约 — CRITICAL · 5 图约束（graph_constraints.py 模式） · 6 测试模式 · 7 已知坑（实战教训，按代价排序）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/node_editor_protocol.md`。
