# 节点编辑器业务逻辑开发协议

> 适用：节点类型定义、求值器（evaluator）、图约束、执行引擎、图文档（agent 消费）、
> 程序化构图（GraphBuilder）、MCP 校验（Utils/NodeEditor）。
> UI 表现层协议见 `ui_protocol.md`；设备/IO 后端协议见 `device_io_protocol.md`。
>
> **位置约定（2026-09 迁移）**：运行时本体位于 `Application/Core/NodeGraph/**`
> （与编辑器/imgui 零耦合，边界由 `Test/Application/Core/test_node_graph_boundary.py` 守卫）；
> 编辑器交互层位于 `Application/Editor/UI/panels/node_editor/**`。

---

## 1. 域地图

| 层 | 文件 | 说明 |
|---|---|---|
| 数据模型 | `Application/Core/NodeGraph/data_model.py` | `PinDef` / `NodeTypeDef` / `NodeInstance` / `LinkInstance`（无 imgui 依赖） |
| 类型注册表 | `Application/Core/NodeGraph/node_types/*.py` | 每文件一类；`_reg()` 注册进 `_TYPES`；颜色常量在 `node_types/__init__.py` |
| 执行引擎 | `Application/Core/NodeGraph/evaluator_engine.py` | `ExecutionContext`（pin/var/timer/dry_run/**宿主注入**）、`GraphEvaluator`（exec 遍历 + 懒求值）、`_EVALUATORS` 注册表 |
| 求值器 | `Application/Core/NodeGraph/evaluators/*.py` | 每文件一域；`register_evaluator()`；导入触发在 `Application/Core/NodeGraph/__init__.py` |
| 画布 | `Application/Core/NodeGraph/canvas.py` | `NodeCanvas`：节点/连线 CRUD、`pin_ids` 实例化、序列化（**存档契约**） |
| 图约束 | `Application/Core/NodeGraph/graph_constraints.py` | 跨节点联动（删除级联 + 静态校验函数）；纯数据、无 imgui |
| 场景内嵌文档 | `Application/Core/NodeGraph/graph_rules.py` | `_NODE_GRAPH_RULES`，每次导出 scene 时附带（外部 agent 读） |
| 编辑器交互层 | `Application/Editor/UI/panels/node_editor/**` | 画布渲染 / Add 菜单 / 内联控件 / 级联删除交互 / 自动布局（imgui） |
| MCP 参考文档 | `Utils/NodeEditor/rules.md` | 构图 agent 必读；节点表 / 连线规则 / 模式 |
| MCP 工具 | `Utils/NodeEditor/{mcp_server,mcp_server_ref,mcp_server_validate,mcp_server_build}.py` | build / apply / get_rules / validate |
| 校验器 | `Utils/NodeEditor/node_graph_validator.py` | L1 静态 + L2 干跑（**MCP 空跑核心**） |
| 构图器 | `Utils/NodeEditor/graph_builder.py` | 程序化构图 + `validate()`；节点 helper（含 gtec_*） |

> 旧路径 `Application/Editor/UI/controllers/node_editor/` 仅保留包级 re-export shim（弃用）；
> 新代码一律使用上表路径。

---

## 2. 执行模型（写求值器前必须理解）

- 触发：`GraphEvaluator.trigger(event_type)` 遍历所有 `category == "Event"` 的同名事件节点，
  沿 exec 输出 DFS（`_walk_exec`），同一 trigger 内节点只执行一次。
- 数据节点（无 exec pin）**懒求值**：任一输出被 `_read_input` 读取时触发其 evaluator；
  环检测由 `_eval_guard` 保证（每次 trigger 重置）。
- 每次 trigger 会**清空** `ctx._pin_values`；pin 值作用域 = 单次 trigger。
- 变量 `ctx.set_var/get_var` 跨 trigger 持久；Timer 用 `ctx.create_timer/get_timer/set_timer`。
- 有状态节点用 `g.get_state(nid, key, default)` / `g.set_state(nid, key, value)`（如 Delay）。
- 阻塞语义：节点可设 `_blocked=True` 暂停 exec 链（Delay / TimeTrigger / Branch 手动走分支）。
- pin 约定：`exec_in` / `exec_out`；多路 exec 用 `out_0..out_N`；数据 pin 用语义名
  （`Value` / `Result` / `In_0..`）。`data_type` 决定连线颜色（`styling.LINK_COLORS`：
  exec/float/int/bool/vec3/string/entity_ref/variant；新类型需补色）。
- 类型转换：`_read_input` 返回原始值（可能 str/int/ndarray）；需要 float 时用 math.py 的
  `_read_data_input`，需要原始类型时参考 `evaluators/io.py._read_input_raw` 模式。
- 事件节点 pin 名为 **`exec`**（不是 exec_in/exec_out）；GraphBuilder 固定事件 ID 161/163/166，
  连线写法 `g.link(GS, "exec", node, "exec_in")`。

---

## 3. 新增节点完整清单（10 步，缺一不可）

1. `node_types/<域>.py`：`_reg(NodeTypeDef(type_name, label, category, COLOR, pins, props_text))`；
   `category` 只对 Event 特殊（触发匹配用）。
2. `node_types/__init__.py`：新域文件 `from . import xxx` + 颜色常量。
3. 菜单：`panels/node_editor/styling.py` `MENU_SECTIONS` 对应分组加 `(label, type_name)`；
   **label 必须等于 NodeTypeDef.label**。
4. 控件：`panels/node_editor/widgets.py` `@register("TypeName")`；默认值幂等初始化；控件 ID 带 `_{nid}`。
5. 自动布局：`panels/node_editor/panel.py` `_WIDGET_NODES` 加入该类型（有内联控件必须加）。
6. 引脚可见性（可选）：`panels/node_editor/visible_pins.py` `@rule("TypeName")`。
7. 求值器：`evaluators/<域>.py` 实现 + `register_evaluator()`；
   并在 `Application/Core/NodeGraph/__init__.py` 的 `from .evaluators import (...)` 中加模块名。
8. 删除联动/校验（如涉及跨节点规则）：`graph_constraints.py` 增加纯函数；
   `panel._handle_deletion` 与 `node_graph_validator.validate_static` 各自接入。
9. 文档：`graph_rules.py`（场景内嵌）+ `Utils/NodeEditor/rules.md`（MCP agent）+
   `Utils/NodeEditor/graph_builder.py` helper（推荐）。
10. 测试：无头单元测试或干跑断言（见 §6）；MCP `validate_graph` 必须通过。

> 兼容保留的旧节点：**保留注册但菜单不出现**，在定义文件注释说明替代关系
> （例：`math.py` 的 MathAdd 系列、`entity.py` 的 EntityAddMesh/EntityAddCamera）。

---

## 4. Dry-Run（MCP 空跑）契约 — CRITICAL

`validate_graph(max_frames>0)` 会以 `ctx.dry_run=True` 模拟执行整图。求值器必须：

```python
if ctx.dry_run:
    ctx.emit_log(node_id, "TypeName", "action", "参数与真实路径一致")
    return
# 真实副作用（写文件 / 开设备 / 发串口 / 改场景）
```

- `ctx.emit_log(node_id, node_type, action, detail)`：干跑校验器的日志通道
  （`validate_graph` 汇总 `events_by_type` / `by action`，测试可断言）。
- **禁止**在干跑中：开线程、开设备、写文件、改真实场景、导入重依赖。
- 真实模式失败要**记录并继续**（`emit_log(..., "error", ...)` + print），不得向上抛异常
  （否则整帧执行中断）。参考 `evaluators/gtec.py` + `Functions/EEGDevice` 空跑后端的写法。
- 纯数据节点（如 GetGtecData）干跑中只有在输出**被读取**时才会求值 —— 测试/校验图要保证
  至少有一条数据连线消费它的输出，否则不会出现在干跑事件里。

---

## 5. 图约束（graph_constraints.py 模式）

- 业务规则示例：Gtec `InitGtecDevice ⇄ KillGtecDevice` 强制成对。
- 两部分配套实现：
  - `gtec_cascade_deletes(canvas, ids)`：编辑器删除时扩展为级联删除集合（UI 调用）。
  - `gtec_pairing_errors(nodes_dict)`：静态校验错误列表（`node_graph_validator.validate_static` 第 6 步调用）。
- 绑定规则写进模块 docstring，并与 `rules.md` 同步（agent 依据它构图）。
- 规则函数必须**纯数据、无 imgui**，便于被 UI / 校验器 / 测试三处复用。

---

## 6. 测试模式

- **干跑全链路**（零硬件零 UI）：`GraphBuilder` 构图 → `validate_static()` → `g.validate(max_frames=N)`
  → 断言 `report.passed` 且 `dry_run["events_by_type"]` 含预期节点。
  范例：`Test/Application/Functions/test_gtec_device.py::test_graph_dry_run`。
- 约束测试：纯 dict 调 `gtec_pairing_errors`；`NodeCanvas` + `gtec_cascade_deletes` 测级联。
- 边界守卫（改动节点图包后必跑）：`python Test/Application/Core/test_node_graph_boundary.py` —
  源码扫描禁止 `Application.Editor` / `imgui_bundle` 导入，且阻断导入时运行时链路必须仍可导入。
- 迭代开发时可直接用 Pylance 代码片段工具跑无头断言（无需落盘测试文件）。

---

## 7. 已知坑（实战教训，按代价排序）

1. **菜单漂移**：曾出现节点已注册但菜单不可达（Event 页整体缺失、`EntitySetRenderVisible`
   不在菜单）→ 新增节点后必须核对"注册表 ↔ 菜单"。
2. **标签不一致**：`Constant` 卡片标题曾是 `"Scale"`（历史误名）→ 菜单/文档/卡片三处对齐；
   改名要注意 `graph_rules.py` 中给 agent 的说明同步。
3. **pin_ids 是实例级**：JSON 连线引用 `inst.pin_ids`（画布/导入导出/MCP 均如此），
   手写图时给每 pin 分配全局唯一数值；重复会导致连线错乱。
4. **事件节点 pin 名是 `exec`**：`chain()` 对事件节点不适用，直接 `link(GS, "exec", ...)`。
5. **重依赖 import 副作用**：`pygds` import 会连带 matplotlib/pywin32；设备后端必须懒导入，
   否则 MCP 干跑在无设备机器上直接崩。
6. **自由线程（-Xgil=0）下的数据竞争**：跨线程共享结构必须加锁（见 device_io_protocol §4）；
   实机采集中"图线程读缓冲 / 采集线程写缓冲"是典型场景。
7. **文档三处不同步**：`rules.md`（MCP agent）、`graph_rules.py`（导出场景内嵌）、
   `Doc/Dev`（本目录）—— 改节点后三处一起改，避免 agent 依据旧文档构图。
8. **legacy 节点误入菜单**：兼容节点应在代码注释标明"菜单不出现"，避免后人误加。
