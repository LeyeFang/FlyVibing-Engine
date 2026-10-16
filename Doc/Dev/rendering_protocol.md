# 渲染器开发协议（验证体系 + 开发规范）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

改 Application/Core/Renderer/、Resource/Shaders/、渲染命令/材质/纹理上传路径前必读。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/rendering_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/rendering_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 后端现状（一等公民声明） · 2 架构 · 3 开发规范（Checklist） · 4 验证体系（本章建立） · 5 Agent 工具链 · 6 已知问题 / 发现（验证体系产出） · 7 渲染目标（离屏 RT） · 8 光照体系（运行链路） · 9 能力矩阵（概要）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/rendering_protocol.md`。
