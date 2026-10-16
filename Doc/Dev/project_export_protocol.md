# 项目 / 导出开发协议（Project & Export）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 在这里只做**大方向指引** ——
> 回答"面对什么问题 / 去哪获得内容"；具体内容按节走 CLI（避免整篇加载）。

## 面对什么问题

项目保存 / 另存 / 导出链的行为契约：`.myproj` 读写、资源路径规则（builtin/相对/绝对）、
Save As 工程文件夹提交点、自包含导出（Export Bundle）与游戏打包（Game Export）、开发清单与实战坑。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                        # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/project_export_protocol    # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/project_export_protocol#3     # 单节内容（# 为序号或标题片段）
engine-editor-cli doc search 提交点                           # 跨主题检索
```

章节：1 职责与文件地图 · 2 路径规则 · 3 Save / Save As 契约（含工程文件夹提交点）·
4 Export Bundle · 5 开发清单 · 6 Game Export · 7 已知坑（实战教训）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/project_export_protocol.md`。
背景与迁移方案：`Doc/Dev/doc_cli_plan.md`。
