# 节点图校验协议（引擎内服务）

> ★ 本页正文已 CLI 化（2026-10-17）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

消费者：agent / 开发者。改校验规则、干跑语义、报告格式、Validate UI、图导入导出时必读本文。状态：2026-10-02 落地（v4）；2026-10-17 校验实现单一化 —— L1 规则唯一实现迁至离线工具包 fly…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/graph_validation_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/graph_validation_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 定位（单一事实源） · 2 输入源 · 3 检查规则（L1 静态） · 4 干跑语义（L2） · 5 任务模型（ValidationService） · 6 报告格式（UI / MCP / 文件三端同构） · 7 UI 行为（Node Editor 面板） · 8 图导入导出（GraphIO） · 9 测试与基线 · 10 扩展指引

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/graph_validation_protocol.md`。
