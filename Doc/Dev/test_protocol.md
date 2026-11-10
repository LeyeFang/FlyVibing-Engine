# 测试协议（Test Protocol）— 隔离 / 档位 / 输出契约 / 场景回放

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

适用：Test/**（测试资产）、Utils/Dev/test_runner.py（统一运行器）、Test/Application/Editor/ui_scenario.py（UI 场景回放）。

## 默认入口（先记这三条 —— 别把门禁当日常）

```powershell
# 内层循环：改哪跑哪（按 Doc/Dev/test_nodes.json 的 covers + ui_map 的 scenarios 选）
python Utils/Dev/test_runner.py --changed
python Utils/Dev/test_runner.py --affected Application/Editor/Services/PortLedger.py
python Utils/Dev/test_runner.py --affected Test/Application/Editor/test_foo.py   # 改测试就跑它自己

# 提交前门禁：全量 core（**不是**每次改动后的默认动作）
python Utils/Dev/test_runner.py --tier core
```

- `--affected/--changed` **永不自动选** `manual` / `live`（交互式 / 需要运行中的编辑器）；
  要跑它们显式 `--tier live` 或 `--tier all`。
- 显式 `--affected <错路径>` → 退出码 2；`--changed` 只命中文档/配置 → 0 tests、退出码 0（都如实打印）。
- 改了测试文件本身、或改了 `scenarios/*.py`，无需查地图 —— 直接跑它自己。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/test_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/test_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 运行方式（agent 默认入口） · 2 档位（tier） · 3 输出契约（每个测试必须遵守） · 4 隔离规则（运行时） · 5 UI 场景回放（ui_scenario） · 6 e2e（live 档）纪律 · 7 测试地图（按域） · 8 新增测试清单

地图与选测的权威数据：`Doc/Dev/test_nodes.json`（`python Utils/Dev/test_map.py check|affected|render`）
+ `Doc/Dev/ui_map.json`。改测试/控件/新增模块时先 `test_map.py check`，否则 `--affected` 会漏。

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/test_protocol.md`。
