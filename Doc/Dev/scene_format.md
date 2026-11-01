# `.scene` 文件格式（实体 / 节点图 / 数据模型）

> ★ 本页正文已 CLI 化（2026-11-01）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：需要直接读写 `.scene` JSON 的场景/工具开发（实体组件字段、节点图 pin id 与引脚名
两套表示、编辑器坐标 vs GL 坐标、未注册节点类型的处理）。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/scene_format                          # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/scene_format#<节号|标题片段>             # 单节内容
engine-editor-cli doc search 坐标                                        # 跨主题检索
```

章节：1 顶层结构 · 2 实体条目（`position_*` + `local_pos_*`） · 3 节点图（`links` 是 pin 级） · 4 坐标系 · 5 手改流程 · 6 批量改的安全做法

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/scene_format.md`。
