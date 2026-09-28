# UI 设计开发协议（Application/Editor/UI）

> 适用：编辑器面板、节点卡控件（Widget）、样式、Add 菜单、文件对话框、UI 交互测试。
> 业务逻辑（求值/设备/约束规则）不属于本文档 → 见 `node_editor_protocol.md` / `device_io_protocol.md`。

---

## 1. 文件地图（改 UI 先定位）

| 文件 | 职责 |
|---|---|
| `Application/Editor/UI/UIManager.py` | 主菜单栏（File/Edit/View/Help）、DockSpace 布局、状态栏；菜单回调 → FileDialog 非阻塞对话框 |
| `Application/Editor/UI/panels/node_editor/panel.py` | `NodeEditorPanel`：画布渲染、Add 菜单、连线创建、Delete 删除（含级联）、Rearrange 自动布局、Import/Export |
| `Application/Editor/UI/panels/node_editor/widgets.py` | 节点内联控件注册表（`@register(node_type)`）；combo/变量名/Timer名/Gtec设备等辅助 |
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

- 引用其它节点的 props（变量名 / Timer 名 / Gtec 设备名）用**画布扫描 + 下拉框**模式：
  `_collect_var_names`、`_collect_timer_names`、`_collect_gtec_device_names`（widgets.py）。
- 绑定目标消失时的行为要明确：Timer 回退 `global`；Gtec 显示 `(not registered)` 提示
  （不阻断编辑，运行时由求值器报错）。

---

## 8. 测试

- UI 交互测试需要 GL 窗口；鼠标/键盘统一走 `InputPipeline`（见 `Test/Application/Editor/测试需知.md`）。
- **业务正确性不要依赖 UI 测试**：把逻辑放进 evaluators / 设备层，用 MCP 干跑与无头单元测试覆盖
  （`Test/Application/Functions/test_gtec_device.py` 是范例）。
