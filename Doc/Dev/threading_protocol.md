# 线程开发协议（线程治理 + 实时探针）

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：任何新开线程 / 跨线程通信 / 服务进程集成（例：品牌设备独立进程 + 引擎侧通信线程）。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/threading_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/threading_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 线程清单（2026-10-05 实况, `threads.snapshot` 可随时核对） · 2 跨线程三通道（只许这三种）+ 禁止项 · 3 新线程检查单（四步，缺一不可） · 4 实时探针（人 / agent 双通道） · 5 压力 / 竞态测试（已落地） · 6 启动/就绪与边界守卫（已落地）

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/threading_protocol.md`。
