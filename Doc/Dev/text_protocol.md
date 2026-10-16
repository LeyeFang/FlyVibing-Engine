# 文字显示系统协议

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

改 Application/Functions/Text/**、TextDisplay 组件、SetText 节点、文字光栅化/动态纹理绑定路径前必读。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/text_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/text_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 域地图 · 2 两种形态（核心使用场景） · 3 TextDisplay 组件字段 · 4 数据流与更新策略（auto 画布） · 5 驱动通道 · 6 注册点清单（新增/排查时对照） · 7 测试与验收 · 8 已知限制 / 后续 · 9 交叉引用

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/text_protocol.md`。
