# UI 大文件拆分计划（执行前必读）

> 状态：**部分执行** — `widgets.py` 已拆包（2026-10-05，见 §3.1 执行结果）；`panel.py` / `ScenePanel.py` 待执行。
> 目标：把编辑器 UI 最大文件压到 ≤ ~500 行/文件。
> 安全网：core 档 19/19 + 场景回放（`panels_smoke` / `menu_smoke` / `node_editor_smoke`）+ 截图对比 ——
> 拆分是**纯搬移**，重跑即可验证；搬迁期间禁止夹带逻辑修改。

## 1. 现状（实测行数）

| 文件 | 行数 | 问题 |
|---|---|---|
| `Application/Editor/UI/panels/node_editor/widgets.py` | **1626** | 47 个 `@register` + 10 个家族节全混一个文件 |
| `Application/Editor/UI/panels/node_editor/panel.py` | **1143** | 画布渲染 / 交互 / 导入导出 / 校验 UI 四合一 |
| `Application/Editor/UI/panels/ScenePanel.py` | **978** | header / 实体树 / 右键菜单 / 属性检查器 四合一 |
| `Application/Editor/UI/UIManager.py` | ~400 | 可接受（不动） |

## 2. 拆分手法（两种，皆为低风险机械搬移）

**A. Mixin 拆法（`panel.py` / `ScenePanel.py`）** — 方法体**原样**搬进 mixin 类，类声明聚合：

```python
class ScenePanel(_TreeMixin, _InspectorMixin, _SceneIOMixin, BasePanel): ...
```

优点：方法体零改动（`self.*` 调用不破）；对外 `from ....ScenePanel import ScenePanel` 不变。

**B. 注册表拆法（`widgets.py`）** — 改包 `widgets/`：
`__init__.py` 保留注册表与 `draw_node_widgets`，子模块 `from . import flow, entity_comp, ...`（import 即注册）；
对外 `from .widgets import draw_node_widgets` 不变。子模块共享的辅助（`_ne_combo` / Timer 名称收集）移入 `helpers.py`。

## 3. 目标结构（按实测行区间）

### 3.1 `widgets.py` → `widgets/` 包

| 新模块 | 内容 | 行数(估) |
|---|---|---|
| `__init__.py` | `@register` 注册表 + `draw_node_widgets` + 子模块 re-export | ~60 |
| `helpers.py` | `_ne_combo` / 静态辅助 / Timer 名称收集（现 L46-165） | ~120 |
| `flow_io.py` | PrintString … StringConst（含 ScalarMath/Compare/Timer*/Var*）（现 L170-699） | ~530 |
| `entity_comp.py` | EntitySpawn/Get / Component* / VecMath（现 L701-967） | ~265 |
| `device_siggen.py` | IO▸SigGen 家族（现 L970-1136） | ~167 |
| `device_pool.py` | IO▸Pool 家族（现 L1267-1330） | ~64 |
| `epoch.py` | Epoch 家族（现 L1332-1444） | ~113 |
| `algorithm.py` | FBCSP/CCA 家族（现 L1446-1626） | ~181 |

（`flow_io.py` 仍偏大 — 执行时可把 Timer 组再切出 `timers.py`。）

**执行结果（2026-10-05）**：已按上表完成（`_device_name_field` 抽为 `device_common.py` 供设备节点共用）。
实际行数：core 165 / flow_io 542 / entity_comp 276 / algorithm 190 / device_siggen 124 /
epoch 121 / device_pool 72 / device_common 59 / `__init__` 29（原 1626）——注册表守恒 46 个 @register，
`panel.py` 导入面不变（`from .widgets import draw_node_widgets`）。
**顺带修复**：加强后的 `node_editor_smoke`（7 子模块各画一个代表节点）暴露 `EpochCount/Clear/Save` widget
自上线起就崩溃（把 `NodeInstance` 直接传给只吃序列化 dict 的 `epoch_source_keys`）——单源适配器
`graph_constraints.nodes_as_dicts(canvas)` 修复，epoch/algorithm 两个 picker 共用。

### 3.2 `panel.py` → mixin 拆分（同包 `node_editor/`）

| 文件 | 内容 | 行数(估) |
|---|---|---|
| `panel.py` | 类聚合 + `draw` 编排 + `_draw_scene_info` + `_draw_add_popup` | ~420 |
| `canvas_draw.py` | `_draw_nodes` / `_draw_pins` / `_draw_links` | ~120 |
| `interaction.py` | `_handle_link_creation` / `_handle_deletion` | ~70 |
| `io_dialogs.py` | import/export popup + `_do_import` / `_do_export` | ~180 |
| `validate_ui.py` | `_draw_validate_button` / `_draw_validate_popup` / `_draw_report_window` | ~215 |

### 3.3 `ScenePanel.py` → `scene_panel/` 包（保留 re-export shim 或改包名，取决于 import 点）

| 文件 | 内容 | 行数(估) |
|---|---|---|
| `panel.py` | 类聚合 + `draw` + `_draw_header` / `_draw_controls` / `_draw_viewport_mode` | ~290 |
| `scene_io.py` | `_on_save/load_scene` / `_do_*` / 材质回调（现 L57-135） | ~85 |
| `entity_tree.py` | `_draw_entity_tree` / 工具条 / prefab / 右键菜单（现 L344-584） | ~170 |
| `inspector.py` | `_draw_entity_summary` / mesh/material/color/add-component（现 L585-978） | ~395 |

## 4. 执行顺序与验证（每步独立验证）

1. **基线**：`test_runner --tier core` 19/19 + 3 个 scenario 全绿 + 存快照到 `Test/_runs/`。
2. 拆 `widgets.py` → 跑 `node_editor_smoke`（画布绘制）+ 全 core。
3. 拆 `panel.py` → 同上。
4. 拆 `ScenePanel.py` → 跑 `panels_smoke` + 全 core。
5. 收尾：全量复跑 + （可选）实机 e2e 截图对比；更新 `ui_protocol.md` 文件地图行。

## 5. 干扰面检查（动手前必查）

```powershell
# 导入面（谁在用旧路径）
Select-String -Path Application -Include *.py -Recurse -Pattern 'from .*ScenePanel import|from .widgets import|from .panel import'
# 注册数量守恒（拆分前后应同为 47）
Select-String -Path Application\Editor\UI\panels\node_editor\widgets.py -Pattern '@register\("' | Measure-Object
```

- `Test/` 全目录脱管（gitignore）→ **场景快照是唯一视觉基线**，拆分前后各存一组。
- 拆完立即跑 runner；失败信息里有日志路径（`Test/_runs/run_*/logs/`）定位。
