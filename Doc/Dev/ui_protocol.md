# UI 设计开发协议（Application/Editor/UI）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：编辑器面板、节点卡控件（Widget）、样式、Add 菜单、文件对话框、UI 交互测试。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/ui_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/ui_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 文件地图（改 UI 先定位） · 2 硬性约定 · 3 Add 菜单（MENU_SECTIONS）约定 · 4 自动布局（Rearrange）与卡片高度 · 5 删除交互与级联 · 6 文件/目录选择 · 7 数据结构联动（引用型 props） · 8 测试 · 9 PIE 窗口设置（Settings 面板 ▸ Export 页） · 10 Action 契约（GUI ↔ agent op 映射） · 11 GUI 自由度分级与审核闭环（2026-10-11 立项） · 12 文本与字形安全（2026-10-11 — "?" 现象根治） · 13 Settings 面板与设置体系（2026-10-12）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/ui_protocol.md`。
