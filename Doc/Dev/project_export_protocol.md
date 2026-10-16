# 项目 / 导出开发协议（Project & Export）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：ProjectManager（.myproj）、EditorHost 场景 I/O、主菜单 File 项（UIManager）、FileDialog 目录选择、资源路径规则与自包含导出。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/project_export_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/project_export_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 职责与文件地图 · 2 路径规则（核心） · 3 Save Project / Save As 行为契约 · 4 Export Project Bundle（自包含导出，已实现） · 5 开发清单（新增/修改工程与导出行为时） · 6 Game Export（已实现 v1 — 打包细节见 `runtime_packaging_protocol.md`） · 7 已知坑（实战教训）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/project_export_protocol.md`。
