# 运行时 UI 协议（场景驱动 UI）

> ★ 本页正文已 CLI 化。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

改 `Application/Core/UI/**`、`Core/Scene/UIComponents.py`、`Runtime/RuntimeUILayer.py`、
`OpenGLUI.py`、`Core/NodeGraph/**/ui.py` 或 `Examples/UIShowcase` 前必读：UI 组件
（UICanvas/UIRect/UIPanel/UILabel/UIButton/UIToggle/UISlider/UISelect）、布局与锚点、
绘制顺序与命中、控件交互与控件值、按钮/控件动作、UI 事件到 `OnUIClick`（配合
`SetUIVisible`/`GetUIValue`）、ESC 策略、线程模型、overlay 穿透联动。

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                              # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/runtime_ui_protocol              # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/runtime_ui_protocol#<节号|标题片段>  # 单节内容
engine-editor-cli doc search <关键词>                              # 跨主题检索
```

章节：1 域地图 · 2 组件字段表（含开关/滑条/选择三皮肤） · 3 布局规则 · 4 绘制顺序与命中 ·
5 按钮动作 + 5.1 UI 事件→节点（SetUIVisible / OnUIClick / GetUIValue） · 6 ESC 策略与内置兜底 ·
7 线程模型 · 8 Overlay 穿透联动 · 9 编辑器预览 · 10 测试与验收 · 11 未实现 · 12 已知限制 · 13 交叉引用

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/runtime_ui_protocol.md`。
