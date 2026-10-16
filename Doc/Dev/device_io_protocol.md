# 设备 IO 层开发协议（Application/Functions）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：SerialParallelDevice（串口/并口）、EEGDevice 设备层等硬件集成。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/device_io_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/device_io_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 域地图与两种既有架构 · 2 真实 / 空跑双后端契约（本层核心，MCP 空跑依赖） · 3 数据与落盘约定 · 4 线程模型与自由线程引擎（重要） · 6 Runtime 集成 · 7 设备池 (Device Pool) · 8 品牌服务进程（独立进程 + 协议通信） · 9 测试 · 10 已知坑（实战教训） · 12 两级设备身份与跨机器迁移（`@alias` — 2026-10-12 新增）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/device_io_protocol.md`。
