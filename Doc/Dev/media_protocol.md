# 动态媒体协议（M1 v2: 节点驱动 GIF/图像）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

改 Application/Core/Media/**（MediaSystem）、MediaPlayer 组件、ShowMedia 节点、TextureUpdateCommand 链前必读。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/media_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/media_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 架构决议（v2） · 2 数据流（PIE） · 3 ShowMedia 节点（IO ▸ Media） · 4 MediaSystem API（`Application/Core/Media/MediaSystem.py`） · 5 组件与注册 · 6 渲染命令链（与 v1 相同） · 7 测试与验收（v2 已通过） · 8 已知边界 / 后续 · 9 文件地图（v2）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/media_protocol.md`。
