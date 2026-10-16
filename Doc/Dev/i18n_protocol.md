# UI 语言适配协议（i18n）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

读者：改编辑器 UI / 菜单 / 面板 / 检查器文案的主应用开发者；贡献语言目录的翻译者；写扩展 UI 的社区开发者（另见 Doc/ExtDev/extension_dev_protocol.md §7）。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/i18n_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/i18n_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 主旨 · 2 角色分工 · 3 键规范 · 4 不翻译边界表（**唯一裁决处**） · 5 运行时契约（`Application/Editor/I18n.py`） · 6 守卫三层（验证机制） · 7 新增语言 Runbook（全量适配门槛） · 8 语言表（当前） · 9 迁移棘轮与现状 · 10 证据与测试映射 · 11 扩展侧约定（[M1] 落地）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/i18n_protocol.md`。
