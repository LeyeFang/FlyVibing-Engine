# UI 设计开发协议（Application/Editor/UI）

> 适用：编辑器面板、节点卡控件（Widget）、样式、Add 菜单、文件对话框、UI 交互测试。
> 业务逻辑（求值/设备/约束规则）不属于本文档 → 见 `node_editor_protocol.md` / `device_io_protocol.md`。

---

## 1. 文件地图（改 UI 先定位）

| 文件 | 职责 |
|---|---|
| `Application/Editor/UI/UIManager.py` | 主菜单栏（File/Edit/View/**Extensions**/Help）— **实际渲染路径**、DockSpace 布局、状态栏；菜单回调 → FileDialog 非阻塞对话框 |
| `Application/Editor/Extensions/ExtensionMenu.py` | `Extensions` 菜单（扩展列表/启停/broken 展示/Rescan）；`draw_extensions_menu()` 供 UIManager 调用；与 `extension.*` ops 同路径（协议见 `Doc/ExtDev/extension_dev_protocol.md`） |
| `Application/Editor/Extensions/ExtensionUI.py` | 扩展 UI 桥 — `ctx.ui.register_window` 实装（ExtensionPanel 异常隔离/重名防护/purge 保险丝；扩展窗口经此进出 UIManager） |
| `Application/Editor/UI/panels/MenuBarPanel.py` | 主菜单栏面板（**当前未注册**，保留文件 — 见 `GUI_STRUCTURE.md`）；View 菜单 = 面板开关 + Show Grid（`toggle_grid_visible` 动作单点 → `Grid.set_visible`，与 `view.set_grid` op 同路径）；Extensions 段与 UIManager 共用 `ExtensionMenu.draw_extensions_menu` |
| `Application/Editor/UI/panels/node_editor/panel.py` | `NodeEditorPanel`：画布渲染、Add 菜单、连线创建、Delete 删除（含级联）、Rearrange 自动布局、Import/Export（经 `Application/Core/NodeGraph/graph_io` 与 agent ops 同源） |
| `Application/Editor/UI/panels/node_editor/widgets/` | 节点内联控件包 — 注册表在 `core.py`（`@register`）；子模块 flow_io / entity_comp / device_siggen / device_gtec / device_pool / epoch / algorithm，**import 即注册**；设备共用助手在 `device_common.py` |
| `Application/Editor/UI/panels/node_editor/visible_pins.py` | 引脚可见性规则注册表（`@rule(node_type)`） |
| `Application/Editor/UI/panels/node_editor/styling.py` | `MENU_SECTIONS`（Add 菜单数据）、`LINK_COLORS`（按 data_type 着色）、node style 颜色 |
| `Application/Editor/UI/FileDialog.py` | 异步文件/目录选择（回调写 props） |
| `Application/Editor/UI/PanelStyle.py` | 全局色板（`ERROR_RED` / `TEXT_DISABLED` 等） |
| `Test/Application/Editor/测试需知.md` | UI 交互测试规范（`InputPipeline`，**禁止**直接注册 GLFW 回调） |

---

## 2. 硬性约定

1. **Widget 只编辑 `inst.props`，不做 IO、不做重计算、不 import 业务/设备层重量级模块**
   （允许读静态常量，如 `EEGDevice` 的选项表；禁止打开设备/文件）。
2. **props 必须可 JSON 序列化**（int/float/str/bool/list/dict）。`NodeCanvas.to_dict()` 会把
   props 写进 `.scene`；写入 numpy 数组/对象引用 → 导出损坏。
3. **控件 ID 唯一**：所有控件 label 必须带 `##..._{nid}` 后缀（例：`f"Buffer##gtec_buf_{nid}"`）。
   同 label 的两个节点会因 imgui ID 冲突互相串值。
4. **节点卡内下拉框一律用 `_ne_combo`**（BeginCombo 实现）。`imgui.combo` 在 node editor
   坐标下弹窗会偏移；`_ne_combo` 已封装正确行为。
5. **默认值在首次绘制时补齐**（幂等，见 `InitGtecDevice` 的设备名、`ComponentAdd` 的组件下拉）；
   不要每帧无条件改写 props。
6. **不适用输入用灰显**：`imgui.begin_disabled()/end_disabled()`（例：滤波器截止频率按其类型
   灰显），与求值器的"不生效"语义保持一致。
7. **菜单标签 = 节点卡片标题**（`NodeTypeDef.label`），点选后所见即所得；
   菜单条目必须对应已注册类型。
8. **跨节点删除联动不要写进 UI 渲染逻辑**：规则集中在
   `Application/Core/NodeGraph/graph_constraints.py`，由 `panel._handle_deletion` 调用（见下）。
9. 字符串/文本：中文注释与日志可用；**UI 标签尽量 ASCII**，不要用字体可能缺失的符号（emoji 等）。
10. `_draw_menu_item` 里连续两次 `imgui.close_current_popup()` 是级联菜单定位所必需，
    **不要"顺手修复"**。
11. **动作单点（Action Single-Point）**：新增/修改 GUI 动作时，业务逻辑必须收敛为一个可被
    agent op 复用的 Controller/类方法（正例：`MenuBarPanel.toggle_grid_visible`、
    `SelectionController`、`SceneBrowserController.add_entity`）；禁止"只存在于面板回调里"。
    完成后再更新 §10 映射表 — 守卫测试强制三方一致
    （`Test/Application/Editor/test_action_contract.py`）。
12. **禁止静默吞错**：UI/控制器路径中的 `except` 必须打印显式告警（教训 2026-10-08：
    `select_with_gizmo` 的 NameError 被裸 except 吞掉 → MCP 选中长期无 gizmo）。

---

## 3. Add 菜单（MENU_SECTIONS）约定

- 顶级页按建图工作流排序：`Event → Flow → Basic → Variable → Math → Time → Scene → Debug → IO`。
- 页内 ≤3 项平铺；更多按语义分组（组头不可点击，仅视觉分区）。
- 新增节点：在对应分组追加 `("标签", "类型名")`；兼容保留的旧节点**不出现**在菜单
  （在节点定义文件内注释说明，例：`node_types/math.py`、`node_types/entity.py`）。
- **菜单完备性自检**（曾在真实项目中漏掉 Event 页与 EntitySetRenderVisible）：
  新增/重构后跑一次"注册表 vs 菜单"核对（遍历 `_TYPES`，除 legacy 名单外都必须可达）。

---

## 4. 自动布局（Rearrange）与卡片高度

`panel._auto_layout` 需要估算每张卡的高度：`V_HEADER + pins*V_PER_PIN (+V_WIDGET_EXTRA)`。

- **新增带内联控件的节点类型，必须加入 `panel.py` 的 `_WIDGET_NODES` 集合**，
  否则 Rearrange 后卡片重叠。
- 卡片高度 ≈ pin 行数 × 24px 与控件高度取大者；控件行数多（如 `InitGtecDevice`）时宁可留白。

---

## 5. 删除交互与级联

- Delete 键删除选中节点/连线；节点删除调用 `gtec_cascade_deletes(canvas, ids)` 先做级联扩展
  （当前规则：Gtec `InitGtecDevice ⇄ KillGtecDevice` 强制成对；规则函数保持纯数据、无 imgui）。
- 级联删除必须打印 `[Delete] Cascade ...` 日志，便于排查。

---

## 6. 文件/目录选择

- 统一用 `FileDialog.open_directory(cb, start_dir=...)` / `open_json` / `open_text` /
  `open_export_dir`（导出专用父目录选择），回调里写 props（异步，不阻塞帧）。
- 主菜单新增项：逻辑回调放 `UIManager._on_* / _do_*`（模式参照 File ▸ Export...）；
  工程/导出类操作不直接写盘，统一交 `ProjectManager`（见 `project_export_protocol.md`）。
- 展示长路径时截断（`...` + 尾段），完整路径不占卡片宽度。

---

## 7. 数据结构联动（引用型 props）

- 引用其它节点的 props（变量名 / Timer 名 / 设备 / 设备池 / epoch 数据集 / BCI 模型）用**画布扫描 + 下拉框**模式：
  `_collect_var_names`、`_collect_timer_names`（widgets.py）。
- 设备引用节点（Start/Stop/Kill/Get）= **池 + 设备二级下拉**（`_device_name_field`）：
  数据源 `graph_constraints.device_inventory`（画布 Init 节点 × 池分配，与校验器同一套键规则）；
  `(Auto)` = 空名 → 运行时池内唯一设备自动绑定；当前值不在列表保留 `(unlisted)` 项。
- 设备池节点：Create = 池名输入框；Add / Kill = `_draw_pool_picker`（Add 禁 Auto、Kill 允许）。
- 绑定目标消失时的行为要明确：Timer 回退 `global`；设备引用显示 `(unlisted)` 保留配置
  （不阻断编辑，运行时由求值器报错）。

---

## 8. 测试

- UI 交互测试需要 GL 窗口；鼠标/键盘统一走 `InputPipeline`（见 `Test/Application/Editor/测试需知.md`）。
- **业务正确性不要依赖 UI 测试**：把逻辑放进 evaluators / 设备层，用 MCP 干跑与无头单元测试覆盖
  （`Test/Application/Functions/test_gtec_device.py` 是范例）。
- 场景化 UI 回归：`python Test/Application/Editor/ui_scenario.py scenarios/<name>.py`
  （真实面板 + 输入注入 + PNG 快照，含完整 ImGui 界面；`--preview` 交互预览）。
- 批量运行 / 档位（core/gui/heavy/live）/ 沙箱与输出契约：`Doc/Dev/test_protocol.md`
  （`python Utils/Dev/test_runner.py`）。

---

## 9. PIE 窗口设置（ScenePanel ⚙ Settings）

- **位置**：Scene Information 卡片，`Stopped` 状态行下方 `⚙ Settings` 按钮（图标用
  `icons_fontawesome_6.ICON_FA_GEAR`，`getattr` 兑底）→ `pie_settings_popup` 弹层。
- **选项**：显示模式（窗口化 / 无边窗口 / 独占全屏）+ 窗口化尺寸（预设 1280×720 / 1600×900 /
  1920×1080 + 宽高输入；非窗口化时尺寸控件 disabled）。**下次 Run 生效**。
- **持久化**：`Application/Editor/Config/PIE.json`（`{"mode", "width", "height"}`；
  懒加载 + 修改即存；尺寸 clamp 320..7680；缺失/损坏 → 默认值不报错）。
  ⚠ 手写该文件用无 BOM UTF-8（PS 5.1 `Set-Content -Encoding UTF8` 带 BOM → JSON 解析失败回默认值）。
- **应用链**：`SimulationController._apply_pie_window_prefs(game_type)`（Play 消费时、
  `GameRuntime.start` 之前）→ `RuntimeWindow.apply_start_preferences(mode, w, h)`
  （`_window_mode` + `_default_size_override`）→ `Window._compute_default_size` 读取覆盖。
  Overlay 场景 + 独占全屏 → 自动回退 borderless（透明窗口不兼容独占全屏）。
- **测试**：`Test/Application/Editor/test_pie_settings.py`（core；持久化/钳位/映射/Overlay 回退）。

---

## 10. Action 契约（GUI ↔ agent op 映射）

> 单一权威表：每个 op ↔ 对应 UI 入口（同路径）↔ 触发的 GUI 状态联动。
> 守卫：`Test/Application/Editor/test_action_contract.py` 强制本表 ↔ `engine_editor_mcp.ops.OPS`
> ↔ `LiveCommandServer._register_ops()` 三方集合相等；新增/删除 op 必须同步本表。

**同步机制图例**

| 代号 | 含义 |
|---|---|
| `D` | 数据层直读 — Immediate-mode 面板每帧从同一数据源读取（SceneManager / Grid / SimulationController / canvas），op 写数据层即自动同步 |
| `C` | 回调/失效链 — 必须显式触发（`SelectionController` 回调通知、`EditorGizmoLayer.invalidate_*`、`TransformGizmo` 状态机） |
| `Q` | 命令队列 — `enqueue` → 渲染线程 StartFrame 执行（GPU 资源/显隐/高亮） |

| op | UI 入口（同路径；`—` = 诊断/内部/无面板入口） | GUI 状态联动 | 机制 |
|---|---|---|---|
| `sim.play` | Scene Information ▸ ▶ Run | Run/Pause/Stop 按钮态、状态行文本、PIE 窗口设置生效 | D + Q |
| `sim.stop` | ■ Stop | 按钮态、状态行、PIE overlay 复位 | D + Q |
| `sim.state` | 状态行文本（Stopped/Running） | — | D |
| `view.set_mode` | Scene Type 3D/2D/Overlay 按钮 | 按钮高亮、编辑器视口相机投影、`scene.game_type`（决定 PIE 相机） | D + C |
| `view.set_grid` | View 菜单 ▸ Show Grid | 菜单勾选态、视口网格显隐 | D + Q |
| `camera.get` | Inspector 选中摄像机实体 | — | D |
| `camera.set` | Inspector Camera 字段 | Inspector 回显、视口/PIE 相机生效 | D + Q |
| `renderer.snapshot` | —（渲染器诊断） | — | — |
| `threads.snapshot` | —（线程诊断；`Utils/Dev/thread_probe.py` 同数据源） | — | — |
| `entity.list` | Entities 树 | — | D |
| `entity.get` | Inspector 检视区 | — | D |
| `entity.add` | 工具条 + New / 空区右键 New Entity | 树新增行；**自动选中**（高亮 + Inspector + 轮廓 + gizmo 隐藏） | D + C |
| `entity.rename` | Inspector 名称框 | 树条目文本 | D |
| `entity.delete` | 工具条 🗑 / 右键 Delete | 树删除；**选中级联清理**（自身或祖先被删 → 轮廓/gizmo 同步清除） | D + C |
| `entity.transform` | Inspector Transform / gizmo 拖拽 | Inspector 数值、gizmo 位置、轮廓位置 | D + C |
| `entity.visible` | 行首眼图标 | 眼图标态、视口显隐（含子孙递归） | D + Q |
| `entity.reparent` | 树拖拽 | 树层级、世界变换 | D |
| `selection.get` | Inspector 标题（Entity #id） | — | D |
| `selection.set` | 视口点选（G/R/S 模式）/ 树点击 | Inspector 切换实体、**树自动展开祖先（reveal）**、轮廓高亮、gizmo 显示（默认 true） | C |
| `selection.clear` | 树空白点击 | 全清（数据层 + 轮廓 + gizmo） | C |
| `component.types` | Inspector Add Component 列表 | — | D |
| `component.list` | Inspector 组件区 | — | D |
| `component.add` | Inspector Add Component | 组件区出现该段；MeshRenderer 自动绑 Cube 网格 | D + Q |
| `component.remove` | 组件区 `-` 按钮 | 组件段消失；MeshRenderer 同步注销 GPU 资源 | D + Q |
| `component.get` | Inspector 字段 | — | D |
| `component.set` | Inspector 字段编辑 | 字段回显、材质/网格/颜色视口更新、**数值范围钳制**（`FIELD_CLAMPS`） | D + Q |
| `scene.list` | Scene 下拉列表 | — | D |
| `scene.switch` | Scene 下拉选择 | 场景名/实体树/节点图/视口模式全量刷新、**选中清理** | D + C |
| `scene.create` | + New Scene | 新场景**成为活跃**（同 switch 全链 + 选中清理） | D + C |
| `scene.save` | 💾 | —（落盘） | — |
| `scene.load` | 📂 | 同 switch 全链 + 选中清理 | D + C |
| `resource.list` | Resources 面板 | — | D |
| `resource.find` | Resources 搜索 | — | D |
| `resource.material.get` | 材质检视 / Inspector 材质区 | — | D |
| `graph.list` | Node Editor 画布（同一 canvas 实例） | — | D |
| `graph.add` | Add 菜单 | 画布出现节点 | D |
| `graph.link` | 引脚拖拽连线 | 画布连线、下游控件引用下拉更新 | D |
| `graph.set_props` | 节点卡控件 | 卡片字段回显（引用型 props 联动见 §7） | D |
| `graph.validate.start` | 工具条 Validate | 校验任务状态（报告窗口） | D |
| `graph.validate.state` | Validate 窗口轮询 | — | D |
| `graph.validate.report` | Validate 报告窗口 | 报告展示；点击条目聚焦节点（UI 侧行为） | D |
| `graph.validate.cancel` | Validate 窗口 Cancel | — | D |
| `graph.export` | 工具条/菜单 Export | —（落盘） | — |
| `graph.import` | 工具条/菜单 Import（validate_first） | 画布整体替换、场景 node_graph 同步 | D |
| `project.open` | File ▸ Open Project | 场景/资源/节点图全量重载、选中清理 | D + C |
| `project.save` | File ▸ Save Project / Save As | 场景文件落盘、窗口标题去脏标 | — |
| `project.export` | File ▸ Export… | 审计日志输出；目标目录旧导出被干净重建（`output/` 实验数据保留） | — |
| `extension.list` | Extensions 菜单（列表本体） | 扩展状态/贡献 op 清单查询（扩展 op 发现入口） | D |
| `extension.enable` | Extensions 菜单 ▸ 勾选启用 | 勾选态、装载日志、`ext.<id>.*` op 注册（增量扫描） | D + C |
| `extension.disable` | Extensions 菜单 ▸ 取消勾选 | 勾选态、卸载 + 扩展 op 注销 | D + C |
| `frame.request` / `frame.fetch` | —（内部；`engine_capture` 封装） | — | — |
| `editor.quit` | 窗口关闭按钮 | 全链清理退出（PIE 先行停止） | — |

**规则**

1. **双向覆盖**：(a) 每个 op 必须在本表登记且有 UI 同路径或明确标 `—`；(b) 每个 UI 动作要么
   有 op 同路径，要么在本表明确标注 agent-only（当前无 agent-only 动作 — 全部 UI 动作均可被 op 驱动）。
2. **选中链唯一入口**：任何选中写入（UI 点选 / op / 控制器）必须经 `SelectionController` —
   它一步同步四件套：`SceneBrowserController`（数据层）→ `OutlinerID`（轮廓）→
   `TransformGizmo`（gizmo 状态机）→ `_notify_selection_changed()`（相机/光图标失效回调）。
   任何"改变实体存在性/场景归属"的操作（delete / scene.switch/load/create / project.open）
   完成后必须收敛到 `SelectionController` 清理选中（当前实现点：
   `SceneBrowserController.delete_entity`、`EditorHost._clear_editor_selection`）。
3. **面板 reveal**：`ScenePanel` 检测到选中变化（不论来源）→ 强制展开该实体祖先链一次
   （`imgui.set_next_item_open`），保证视口点选 / MCP 选中嵌套实体时树中可见。
4. **新增 op 全链检查单**（第 6 步为 GUI 契约步）：
   ① `LiveCommandServer` 注册实现 → ②`ops.py` 加 OpSpec → ③ docgen 重生成 ops.md →
   ④ 本表加行（UI 入口/联动/机制）→ ⑤ `test_editor_mcp_package` + `test_action_contract` 通过 →
   ⑥ 若触达 GUI 状态：按联动列验收（必要时补 e2e 截图证据）。

---

## 11. GUI 自由度分级与审核闭环（2026-10-11 立项）

> 动机：控件选择与业务目标不匹配（枚举值域用自由文本框等）反复出现 →
> 把「自由度」变成设计期显式决策 + 审核期可判定清单。

### 11.1 自由度模型（先定级，再选控件）

| 级别 | 定义 | 判据 | 允许控件族 | 示例 |
|---|---|---|---|---|
| **L0 低自由度** | 分支写死（固定动作/结果） | 用户无法表达集合外的值 | Button / Checkbox / 确认弹窗 / 菜单项 | 「确认关闭?」弹窗；显示开关（Toggle） |
| **L1 中自由度** | 受控枚举（有限已知集合） | 值域可完整枚举且**已实现** | Combo / 单选组 / 弹出选择菜单 | Light 类型二选一；Add Component 弹出类型菜单；波特率列表；COM 口列表 |
| **L2 高自由度** | 开放输入（值域不可枚举） | 用户可表达任意合法值 | InputText / 可编辑 Label / 多行框 **+ 后台约束管理**（clamp/校验/解析） | entity 改名；文件路径；数值范围字段（经 `FIELD_CLAMPS`） |

### 11.2 硬性规则

1. **匹配规则**：控件族必须与自由度级别匹配。**L1 枚举以自由文本框呈现 = 违规**
   （反例：`Light.light_type` 曾以文本框呈现 → 2026-10-11 修复）。
2. **假自由度禁令**：L1 选择集只允许登记**已实现且测试过**的值 —
   不得为未实现功能预留下拉项（例：`MediaPlayer.fit` 的 contain/cover 未实现 → 暂不登记）。
3. **L2 约束义务**：每个 L2 控件必须存在后台约束路径（`FIELD_CLAMPS` 钳制 / 路径校验 /
   解析回退），否则不得上线（违反 = 无限输入直通业务层）。
4. **单点声明**：枚举字段选择集登记于 `Application/Core/Scene/ComponentRegistry.FIELD_CHOICES`
   （单一权威；检查器经 `SceneBrowserController.get_component_fields` 消费）；
   数值范围登记 `FIELD_CLAMPS`（同文件）。

### 11.3 开发标注义务（主程）

- 每个新交互控件在实现处必须**可判定自由度级别与业务目的**：
  - 数据驱动字段控件 → 经 `FIELD_CHOICES` / `FIELD_CLAMPS` 声明（自动携带级别）；
  - 手工控件（按钮 / 专属编辑区）→ 代码注释标注 `[自由度: L0/L1/L2] 目的: ...`；
- 新字段/动作同时适用 §10（op 双向覆盖 + 新增 op 全链检查单）。

### 11.4 Reviewer 审核清单（不通过即返回）

| # | 检查项 |
|---|---|
| 1 | 自由度级别已标注，且与控件族匹配（L1 非文本框；L0 非输入类） |
| 2 | L1 选择集登记于 `FIELD_CHOICES` 且全部值已实现 |
| 3 | L2 存在后台约束路径（clamp / 校验 / 解析） |
| 4 | 业务目的陈述与控件自由度自洽（目的 → 允许级别 → 实际控件，三步对照） |
| 5 | 涉及新 op/动作时，§10 Action 契约行已补且计数守卫通过 |
| 6 | （扩展窗口）`close_policy` 已声明 + `on_ui_event` 收尾 + `UIExtensionBase` 继承 —— `review_extension.py` 自动查（ExtDev 协议 §7） |

### 11.5 反例库与审计记录

| 日期 | 位置 | 问题 | 处置 |
|---|---|---|---|
| 2026-10-11 | `Light.light_type` 检查器 | L1 枚举以自由文本框呈现 | `FIELD_CHOICES` 登记 + `ScenePanel` Combo 渲染（同批修复 `TextDisplay.align`） |
| 待审计 | 全部通用组件字段（ScenePanel 通用检视） | 逐个核对 str/数值字段的应有自由度与约束 | 分批进行，新发现入本表 |

