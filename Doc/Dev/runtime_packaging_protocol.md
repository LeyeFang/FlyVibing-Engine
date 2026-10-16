# 运行时打包 / 游戏导出开发协议（Runtime Packaging & Game Export）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：Application/PlayerEntry.py、Application/Runtime/PlayerBootstrap.py、Application/Core/Project/（运行时工程加载）、Utils/Dev/（打包流…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/runtime_packaging_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/runtime_packaging_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 决策记录（2026-09-28 锁定） · 2 文件地图 · 3 播放器契约 · 4 导出包结构（v1） · 5 打包流水线（开发机） · 6 边界与守卫 · 7 已知缺口 / 后续

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/runtime_packaging_protocol.md`。
