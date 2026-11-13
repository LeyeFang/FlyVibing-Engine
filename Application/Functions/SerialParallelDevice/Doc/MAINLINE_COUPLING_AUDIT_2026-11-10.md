# 主线耦合审计 —— 串并口扩展（2026-11-10）

> **签发（主线开发者）**: FlyVibing Engine 主线（Mainline）— 引擎架构与主线维护
> **日期**: 2026-11-10
> **读者**: Serial/Parallel 扩展现任维护者与后续接手人
> **性质**: **只读审计，未改动任何引擎代码**（本次仅新增本文）。本文是工作单 + 验收标准，不是立刻动手的通知。
> **处置协议**: 主线**冻结现状、保留兼容** → 扩展侧在不破坏用户的前提下重做 → 扩展侧回执（§12）→ 主线执行移出（§11）。**未收到回执前，主线不动这些代码。**
>
> **✅ 2026-11-14 主线完成迁移**：P0 全部改走接缝 `Core.Extension.OptionalExtensions`；
> `Core/DeviceRegistry.py` **已删除**（实现唯一在本扩展），核心只留能力凭据
> `Application.Core.DeviceAliases` + manifest `device_aliases` 声明式发现；
> SPD 专属的 C 类余债仅剩 3 处（`visible_pins.py` / `group_layout.py` ×2，等 pack 扩展点）。
> **收尾交接与不变量见 `Doc/HANDOFF_2026-11-14_engine_decoupling.md`**（本文 §12 已更新）。

---

## 0. 结论与为什么不能马上移

**结论**: 扩展自身 2428 行是干净的（`extension.py` 通过 `ctx.*` 注入取能力，不 import 编辑器层）。问题在**反向**——主线为了让这个扩展能跑，替它写了约 **1300 行**资产，外加一个 **141 行**的核心模块。

按引擎的"依赖倒置"原则（引擎不依赖扩展；扩展依赖引擎提供的契约），以下都应该由扩展自己持有。但**现在不能一次性移走**，原因有三条，都是真实约束：

1. **存量工程**：`MI-SSSEP` 系列的 `.scene` 里直接写着 `"node_type": "SerialSend"` / `"ParallelSend"`，属性键是 `port` / `baud_rate` / `address` / `mode` / `format`。这些是数据中心，不是代码。
2. **已导出成品**：`Paradigm/rst/MI-SSSEP` 等成品包是快照，内含当时的 `Application/` 副本。它们不受仓库迁移影响，但**过渡期禁止出现"旧扩展代码 + 新 Core"的混搭**。
3. **面板与 agent 通道**：`ext.device.*` 9 个 op 是面板按钮、CLI、MCP 三方共用的同一实现（`_guard` → `_op_*`）。改名等于断掉所有自动化脚本。

因此本文的定位是：**把"欠账"显式记账、划清归属、给出可验收的重做清单**，让扩展侧按自己的节奏还。

---

## 1. 审计口径

**"侵入"的定义**：主线（`Application/` 中除本扩展目录外的部分、`Test/`、`Examples/`、`Doc/`）出现该扩展的**名字、路径、语义、资产**，并且满足任一条：

- 删掉/改名扩展目录 → 主线会坏（import 失败、PIE/导出崩溃）；
- 删掉/改名 → 主线测试会红；
- 主线文档把扩展语义写成了引擎规范。

**统计口径**（排除项，否则数字失真）：
`__pycache__`、`Utils/Dev/Installer/build`（551 MB 源码副本）、`Test/TestProject/**/dist`、`Test/_runs`、`Test/_gtec_archive_20261016`（事故归档）、`Resource/runtime/Lib`、以及**其他扩展自己的目录**（本地夹具设备扩展、`missssep/` 里提到 SPD 是它们的文档，不算主线）。

**分级**：

| 级别 | 含义 |
|---|---|
| **P0** | 反向硬依赖：扩展不在 → 引擎起不来或主线守卫测试红 |
| **P1** | 主线核心模块承载扩展语义（概念正确、实现是 SPD 方言） |
| **P2** | 编辑器/离线校验器的通用代码里出现 SPD 专有词汇 |
| **P3** | 资产归属错位（能跑，但东西放错了地方） |

---

## 2. 总量

| 维度 | 数值 |
|---|---|
| 扩展自身体量 | **2428 行**（`extension.py` 1037 / vendored `_inpout.py` 407 / 其余 984） |
| 声明能力 | `["ops","nodes","ui","graph"]` · 9 个 `ext.device.*` op · 1 个 node pack |
| 主线 `Application/` 引用 | **14 个文件 / 28 行**（附录 A） |
| 其中"专为 SPD 而写"的核心模块 | **1 个：`Core/DeviceRegistry.py`，141 行** |
| 主线测试中的 SPD 内容 | **15 个文件 / 98 行命中**；5 个专用测试文件共 **1030 行**（附录 B） |
| 主线 `Examples/` 依赖 SPD 节点 | **4 个工程** |
| 离线校验器里的 SPD 专有逻辑 | **约 37 行**（在工具仓，不在引擎仓） |
| 注释/文档字符串级点名 | **8 处** |

---

## 3. P0 — 反向硬依赖（必须先解）

`Application/Runtime/` 里有 4 处直接调用本扩展。**注意：这三处没有 try/except 兜底**，而同文件里 `VirtualDevice` / `BCIAlgorithm` 都有——说明当年是"默认它在"。

| # | 位置 | 内容 | 后果 |
|---|---|---|---|
| P0-1 | `Runtime/GameRuntime.py:122` | PIE `init()` 内 `from ... import start as spd_start` → `spd_start("runtime")` | 目录改名/删除 → `ImportError`。该行虽在 `try`(110) 内，但 `except`(144) 会调 `cls.stop()`，而 `stop()` 第一句就是 `:177` 的同一 import → **兜底也炸** |
| P0-2 | `Runtime/GameRuntime.py:163` | `run()`（导出模式）中裸 import + `start("runtime")` | **完全无 try**，成品启动即崩 |
| P0-3 | `Runtime/GameRuntime.py:177` | `stop()` 中裸 import + `stop("runtime")` | 停止路径同样崩 |
| P0-4 | `Runtime/PlayerBootstrap.py:424` | `stop_all()` | 有 `try/except Exception: pass` → 不崩，但功能**静默丢失** |
| P0-5 | `Test/Application/Core/test_node_graph_boundary.py:78` | `_RUNTIME_CHAIN` 含 `Application.Functions.SerialParallelDevice`，且断言"在 imgui/Editor 阻断器下必须可导入" | **把反向依赖固化成规范**。删扩展 → 主线守卫测试红 |
| P0-6 | `Test/Application/Core/test_thread_boundary.py:42` | `SPAWN_SITES` 键 `Functions/SerialParallelDevice/api.py: delegated:.../io_thread.py` | 线程边界守卫点名扩展文件；扩展内部结构调整 → 主线测试红 |
| P0-7 | `Application/Functions/SerialParallelDevice/api.py:36` | `start()` 内**不查询**扩展启用状态 | `extension.disable id=device` 与 `FVE_EXTENSIONS_BUNDLED=off` **都阻止不了** `GameRuntime` 把它 import 起来并拉起 `spd-io` 线程。对运行时而言"关掉扩展"是假的 |

**P0-7 单独说明**：这不是扩展侧的 bug，而是缺少契约——扩展没有"引擎启动/停止时通知我"的入口，所以只能由主线硬编码调用，硬编码自然也就绕过了启用状态。**这条只能由主线先补钩子**（见 §8.1）。

---

## 4. P1 — 主线核心模块承载扩展语义

### 4.1 `Application/Core/DeviceRegistry.py`（141 行，100% 为 SPD 而写）

| 事实 | 证据 |
|---|---|
| 公开面 | `path / load / all / get / resolve / describe / is_ref / parse_ref / valid_name / bind / unbind / set_hint / _reset_for_tests` |
| 错误文案写死 SPD | `:120-122` → `bind it in the Serial/Parallel panel (or via ext.device.bind_alias name=COMx)` |
| 全仓引用者 | 只有 4 类：本扩展、本扩展的测试、`Editor/.../widgets/core.py:69`、离线校验器（工具仓） |
| 其他 Core 模块引用者 | **0** |
| 概念通用性 | 高：逻辑名 → 机器端点、`%APPDATA%/MyGameEngine/devices.json`、`MGE_DEVICES_FILE` 沙箱、跨机器迁移 |
| 实现方言程度 | 高：文案、命名（`port`/`baud`/`address`）、注释全部串并口 |

**判断**：这是两件事粘在一起——**"机器侧端点台账"是引擎级关注点**（任何 transport 扩展都用得上），**"串并口方言"是扩展知识**。所以不建议整体搬走，建议 §8 里的 3.1 二选一。

### 4.2 `Application/Core/NodeGraph/graph_rules.py`（372 行中的约 13 行）

`:225-237` 的 "IO Nodes" 表格与说明里硬编码了：

- `SerialSend` 的 pin 表与 props（`format: string/bytes, port, baud_rate, prefix/suffix`）；
- `ParallelSend` 的 pin 表与 props（`address: int (0x3FF8 LPT1, 0x3FF0 LPT2, 0x3FE8 LPT3)`、`value: 1-255`）；
- 4 行编码语义（UTF-8 / float32 LE、prefix/suffix 拼帧、uint8 + 5ms 自动复位）。

**为什么是 P1 而不是 P3**：这个文件是引擎**对外提供给 agent / 开发者的节点图规则正文**。扩展语义被写进了核心规范，而不是由 node pack 贡献。`NodePackRegistry.register()` 的 pack 结构里已经有 `props_text` 字段——**待确认它是否被 `graph_rules` 消费**（本次未验证）。

### 4.3 注释 / docstring 级（8 处，各 1–2 行）

| 位置 | 内容 |
|---|---|
| `Core/NodeGraph/node_types/io.py:4` | "SerialSend / ParallelSend 已于 2026-10-20 迁到设备扩展 `Application/Functions/SerialParallelDevice/node_pack.py`" |
| `Core/NodeGraph/node_types/__init__.py:79` | 枚举三个扩展的 `node_pack.py` 路径 |
| `Core/NodeGraph/evaluator_engine.py:24` | 点名 `SerialSend, ParallelSend` 为副作用求值器 |
| `Core/NodeGraph/evaluators/io.py:4` | "已迁到设备扩展" |
| `Core/NodeGraph/node_packs.py` docstring | 示例直接写 `"type": "SerialSend"` / `"id": "device", "name": "Device (Serial/Parallel)"` |
| `Editor/.../widgets/flow_io.py:126-128` | "卡片控件改由设备扩展 node_pack.fields 自动渲染" |
| `Editor/.../visible_pins.py:28` | `@rule("SerialSend")`（`rule()` 的用法示例） |
| `Editor/.../widgets/core.py:31` | `@register("SerialSend")`（`register()` 的用法示例） |

**建议**：保留"迁移记录"的事实价值，但去掉具体目录与类型名（改成"扩展节点包"）。

---

## 5. P2 — 编辑器与离线校验器的词汇耦合

| # | 位置 | 内容 | 体量 |
|---|---|---|---|
| P2-1 | `Editor/UI/panels/node_editor/widgets/core.py:66-87` | 通用声明字段渲染器里的 `if kind == "serial_port":` 分支：枚举 COM 口 + 从 `DeviceRegistry.all()` 拼 `@name` 下拉。当前**唯一消费方**是本扩展的 `node_pack.py` fields | ~22 行 |
| P2-2 | `Editor/UI/panels/node_editor/group_layout.py:43` | `WIDGET_TYPES` 硬编码 `"ParallelSend", "SerialSend"`（用于给卡片预留控件高度；同集合还有 SigGen/BCI 类型） | 1 行 + 判定 |
| P2-3 | 工具仓 `packages/node-editor/src/flyvibing_node_editor/node_graph_validator.py:515-550` | 通用 L1 校验器内置 `_check_device_aliases()`：扫所有 props 里以 `@` 开头的字符串 → import `DeviceRegistry` → 报 `device_alias_unresolved`，文案写 "Serial/Parallel panel" 与 `ext.device.bind_alias` | ~37 行 |

**为什么这三处要泛化而不是搬走**：

- P2-1：`serial_port` 本质是"带动态候选来源的枚举"，引擎应有通用形态；否则下一个扩展（比如脑电放大器候选列表）只能再写一个 `kind == "xxx_port"`。
- P2-2：卡片高度应问"这个类型有没有声明字段/自定义控件"，而不是维护一张类型名清单。清单每加一个扩展就要改主线。
- P2-3：校验器的职责是"报无法解析的引用"，**`@alias` 的语义和提示文案应由提供该语义的扩展给出**。当前形态下，任何不装 SPD 的环境跑离线校验都会去打 `Application.Core.DeviceRegistry`（有 try/except 兜底成 warning，但 warning 本身就是噪声）。

> **跨仓提醒**：P2-3 的代码在工具仓（`FlyVibing-User-And-Developer-Utils`），引擎仓的 `Core/NodeGraph/validation/checks.py` 只是薄适配器。改这里要动工具仓，需同步 `Utils/ExtDev/NodeEditor` 的发布。

---

## 6. P3 — 资产归属

### 6.1 测试：1030 行扩展测试住在主线测试树

| 文件 | 行数 |
|---|---|
| `Test/Application/Functions/test_serial_parallel_device.py` | 432 |
| `Test/Application/Functions/test_device_alias.py` | 282 |
| `Test/Application/Functions/test_device_autobind.py` | 157 |
| `Test/Application/Functions/test_spd_monitor.py` | 100 |
| `Test/Device/com3_listener.py` | 59 |

另有 **9 个通用测试**里硬编码 SPD 路径或断言：`test_node_pack.py`（大量断言，24 行命中）、`test_export_extension_scope.py`（:52/:59/:111）、`test_pulse_examples.py`（:91/:121/:132）、`test_editor_mcp_package.py:90`、`test_imgui_input_flags.py:139`、`test_extension_review.py`（:68/:114/:119）、`test_extension_python.py:144`、`test_mi_groups.py:98`、`test_node_graph_boundary.py` / `test_thread_boundary.py`（已列 P0）。

**优先级说明**：这一项**不违反运行时依赖方向**（测试不参与引擎启动），所以是 P3；但 P0-5 / P0-6 和"通用测试硬编码具体扩展"是两回事，前者必须改，后者只是维护成本。

**现状约束**：`Utils/Dev/test_map.py` 是**中心清单**（当前 107 个节点），只发现 `Test/` 下的文件；扩展目录内自带测试**没有发现机制**。所以"测试搬进扩展"需要主线先扩 test_map（长期项），短期只能做"通用测试去具体化"。

### 6.2 示例工程：4 个依赖 SPD 节点的工程留在主线 `Examples/`

| 工程 | 发送节点数 | 备注 |
|---|---|---|
| `Examples/MI` | 3 | 可能是"实验范式演示"而非"设备演示"——**归属存疑，见 §8.2-6** |
| `Examples/RestingState` | 2 | 同上 |
| `Examples/ParallelPulse` | 1 | 明确的设备示例（并口脉冲） |
| `Examples/SerialPulse` | 1 | 明确的设备示例（串口脉冲） |

另有 `Examples/tools/pulse_pipeline.py` 与 `apply_pulse_pipeline.py` 生成上述两个 pulse 工程。

**机制已经就绪**：`ctx.examples` + `ExtensionExamplesRegistry` + `File ▸ Open Example` + 禁用扩展的一键启用提示，上一阶段已实现并实测。**本扩展是目前唯一没有使用它的官方示例扩展**（目录内无 `Examples/`）。

> **待主线确认**：`builtin` 且 `always_on` 的扩展，其 `Examples/` 是否会被 `UIManager._example_dirs()` 收录——本次**未实测**。这是 P3-2 动工前的第一个验证项。

---

## 7. 不该动的（合规边界）

以下看似"侵入"，实际是**正确的机制本身**，移出时应保留：

| 项 | 为什么保留 |
|---|---|
| `Application/Functions/official_extensions.json` 的 `{"id":"device","dir":"SerialParallelDevice"}` | builtin 声明机制本身。**builtin ≠ 允许反向依赖**；它只意味着"随引擎分发、默认启用" |
| `.gitignore` 的 `!Application/Functions/SerialParallelDevice/` | 白名单机制，与上面配对 |
| `extension.json` | 扩展自己的 manifest（`id` / `capabilities` / `python.mode=engine` / `requires=[]`） |
| `ctx.ops / ctx.nodes / ctx.ui / ctx.graph / ctx.examples` 注入口 | 正确的倒置：引擎提供接口，扩展实现 |
| `NodePackRegistry` 的 `Application/Functions/**/node_pack.py` 自动发现 | 正确的倒置：引擎按目录发现，不 import 具体模块 |
| `Editor/ProjectManager.py::extension_dirs_for_types` | 导出时按节点类型反查扩展目录——**按需发现**，方向正确 |
| `Doc/Dev/device_io_protocol.md` | 已是 14 行指针桩，正文在工具仓 `docs_content/dev/`（`doc show dev/device_io_protocol#...`）。位置正确 |
| 各 `.scene` 里的 `SerialSend` / `ParallelSend` | 消费方数据，不是依赖 |
| `Doc/Dev/test_nodes.json|md` | `Utils/Dev/test_map.py` 生成物 |

---

## 8. 扩展侧重做工作单

### 8.1 分工总表

**关键前提**：P0 只能由主线先补钩子，扩展侧无法单独完成。主线承诺**只做增量**（新增可选契约，不动现有路径），扩展侧可在钩子上线后切换；切换完成前旧路径继续可用 —— 这就是"保留兼容"的具体含义。

| # | 目标 | 现状 | 主线先给 | 扩展侧再做 | 级别 |
|---|---|---|---|---|---|
| 1 | 引擎生命周期通知 | 主线裸 import 扩展 | **新增 lifecycle 钩子**（manifest 或 `ctx` 上的可选项），引擎启动/停止时回调已加载扩展；且**尊重启用状态** | 在 `extension.py` 实现对应回调，内部调 `start("runtime")` / `stop("runtime")` / `stop_all()` | P0 |
| 2 | 端点台账归属 | `Core/DeviceRegistry.py` | 若选 3.1b：**改名去方言**（建议 `EndpointRegistry` / `MachineEndpoints`），错误文案改为"由绑定方提供"；**路径与 `MGE_DEVICES_FILE` 语义不变** | 若选 3.1a：整体搬进扩展，`serial_manager` 改 import；若选 3.1b：只改文案与命名适配 | P1 |
| 3 | 节点语义文档 | `graph_rules.py` 硬写表格 | **确认 `props_text` 是否被 `graph_rules` 消费**；没消费则补消费点 | 在 `node_pack.py` 补全 `props_text`（含编码语义与取值范围） | P1 |
| 4 | 端口选择控件 | 核心 `kind == "serial_port"` | **新增 `kind: "enum"` + `choices_source`**（或等价的候选来源回调） | `fields` 里改用通用 kind，候选来源指向本扩展 | P2 |
| 5 | 卡片高度 | `WIDGET_TYPES` 硬编码类型名 | 泛化成 `fields_for(t) or has_registered_widget(t)` | 无需做 | P2 |
| 6 | 离线校验 | 校验器内置 `@alias` 检查 | **校验器增加可注册 checker / 引用解析器贡献点** + 通用 `unresolved_ref` 规则 | 提供 `@alias` 检查实现与提示文案 | P2 |
| 7 | 示例工程 | 主线 `Examples/` | 确认 builtin 扩展的 `Examples/` 被收录（§6.2 待确认项） | 两个 pulse 工程（可能含 MI / RestingState，见 §8.2-6）迁到本目录 `Examples/` | P3 |
| 8 | 测试归属 | 主线 `Test/` | 长期：`test_map` 支持扩展内测试目录 | 短期不动；长期随主线迁移 | P3 |
| 9 | 注释去具体化 | 8 处点名 | 主线改（不需要扩展配合） | 无需做 | P3 |

### 8.2 逐项要点

**1) 生命周期钩子** — 这是整套欠账的**唯一真正需要新契约**的地方。
它同时解决三件事：P0-1..P0-4 的裸 import、P0-7 的"关掉也不生效"、以及 §附录 C 里 `VirtualDevice` / `BCIAlgorithm` 的同类补丁。
验收：`extension.disable id=device` + PIE 启动 → **不得**出现 `spd-io` 线程；重新 enable 后 PIE 正常。

**2) 端点台账 —— 需要你裁决 3.1a / 3.1b**

- **3.1a 严格搬走**：`Core/DeviceRegistry.py` 删除，文件进扩展目录。
  - 优点：彻底干净，符合"引擎不认识设备"。
  - 代价：离线校验器（不加载扩展的运行环境）**再也无法**在 PIE 之前报"别名未绑定"。需要把该校验降级为"仅在扩展加载时可用"，或让校验器通过某种注册表发现端点台账。
- **3.1b 泛化留下**（主线倾向）：改名 + 去方言，成为"机器侧端点台账"这一引擎级设施。
  - 优点：保留"换机器前就能看见别名未绑定"这个已被验证有用的能力；`devices.json` 路径与格式不动，用户无感。
  - 代价：`Core/` 仍保留一个只被一个扩展使用的模块（但概念上是通用的）。

**主线建议 3.1b**，理由：跨机器迁移提示的价值来自"**在设备扩展在场之前**就能校验"，一旦搬进扩展，这条能力必然退化。但这需要你确认——若你认为"引擎不该认识任何设备概念"，就走 3.1a，主线会把校验器同步降级。

**3) 节点语义文档**
理想终态：`graph_rules.py` 里删掉 `SerialSend` / `ParallelSend` 两行与 4 行语义，由 `graph.types` 实时发现 + `doc show dev/...` 提供。但离线 agent（不启动引擎）仍需要一份可读的节点表——所以要么 `props_text` 被核心消费，要么保留表格但在标题注明"由 device 扩展提供，扩展停用后无效"。
验收：删掉 `graph_rules.py` 的两行后，`graph.types owner=device` 能返回完整 pin + props 描述。

**4) 端口控件**
关键是不能让第二个设备扩展再写一个 `kind == "xxx_port"`。`choices_source` 的形态可以是：`{"kind":"enum","choices_source":"device.ports"}`，由扩展在 `node_pack` 注册时提供 `ports()` 回调。扩展侧拿到后，`fields` 从 `serial_port` 改成这个通用形态即可。

**5) 卡片高度** — 主线单方面改，扩展侧零成本。

**6) 离线校验器**
终态：校验器只负责"这个 prop 看起来是引用（`@` 前缀），但没有解析器能解析它" → `unresolved_ref`；`@alias` 的解析与提示由扩展注册的解析器给出。
注意这条**改在工具仓**，需与 `Utils/ExtDev/NodeEditor` 的发布节奏对齐。

**7) 示例工程归属 —— 需要你裁决**
`SerialPulse` / `ParallelPulse` 明显属于设备示例（README 里写着"唯一的设备节点"），应迁。
`MI` / `RestingState` 更像"实验范式演示"：如果它们的价值是"展示范式结构"而非"展示发字节"，则应留在主线，把设备节点抽象成最小 send 节点；如果它们的价值是"端到端跑通设备"，则一起迁。**请按你自己的用户认知判断，不要按名字判断。**

**8) 测试归属**
短期建议：主线只做"通用测试去具体化"（把 `test_node_pack.py` 里针对 SPD 的断言抽出为 fixture 扩展或参数化），SPD 专用测试暂时留原地。
理由：挪测试需要先扩 `test_map`，收益低于成本，且不违反依赖方向。

**9) 注释去具体化** — 主线单方面改，扩展侧零成本。

---

## 9. 兼容红线（重做期间必须守住）

> 这些是**你的用户**已经依赖的东西。换实现可以，换名字/换格式不行。

| # | 红线 | 依据 |
|---|---|---|
| 1 | 节点类型名 `SerialSend` / `ParallelSend` **不改名、pin 名不改** | MI-SSSEP 场景直接写死；`HANDOFF.md` §4 已定为"持久化契约" |
| 2 | props 键 `port` / `baud_rate` / `format` / `prefix` / `suffix` / `address` / `mode` / `value` 不改 | 同上 |
| 3 | `@alias` 语法（`@name`）与语义不变：未绑定 → **显式报错**，绝不静默回退默认端口 | 决策 2（HANDOFF §3）；静默发错端口比报错更糟 |
| 4 | `SerialSend.port` 默认空（不再是 `COM1`）：未配置 → 显式 error 并跳过 | 决策 3 起生效，属于用户可见变更 |
| 5 | 注册表路径 `%APPDATA%/MyGameEngine/devices.json`、格式 `{version:1, devices:{...}}`、`MGE_DEVICES_FILE` 覆盖**全部不变** | 用户机器上已有绑定数据；测试沙箱依赖 |
| 6 | 9 个 `ext.device.*` op 的**名字与参数**不变（`status / list_ports / watch / send / monitor_snapshot / write_parallel / bind_alias / autobind / bind_nodes`） | 面板按钮、CLI、MCP、自动化脚本共用 |
| 7 | 面板按钮与 op **同一实现**（`_guard` → `_op_*`），不允许两条代码路径 | 决策 4 |
| 8 | 扩展**不 import 编辑器层**；场景读写只走 `ctx.graph`（`nodes/find/set_props`） | 层级边界铁律 |
| 9 | 扩展**不碰**宿主全局 imgui 状态（`create/destroy_context`、`set_ini_filename`、`io/style` 赋值） | 决策 7 |
| 10 | `ParallelSend` 的 uint8 语义（1–255，0 保留给 5ms 自动复位）不变 | 硬件行为，用户已按此设计触发器编码 |

**关于已导出成品**：`Paradigm/rst/MI-SSSEP` 这类包是**快照**（含当时的 `Application/` 副本），迁移不影响它们。唯一风险是"旧扩展代码 + 新 Core"的混搭——所以**迁移必须在一个仓库状态内原子完成**，不要跨版本半推半就。

---

## 10. 完成定义与交接信号

### 10.1 每项的 DoD（可验证）

| # | 验收方式 |
|---|---|
| 1 | `extension.disable id=device` → PIE 启动无 `spd-io` 线程；enable → PIE TX 计数正常；`--tier core` 绿 |
| 2 | 删掉/改名 `Core/DeviceRegistry.py`（3.1a）或改名并 grep 无 SPD 方言（3.1b）后：`--tier core` 绿；离线校验未绑定别名仍给提示（3.1b）或明确降级（3.1a） |
| 3 | `graph_rules.py` 删去两行后，`graph.types owner=device` 仍返回两节点的 pin + props 文本 |
| 4 | `node_pack.py` 的 `fields` 里不再出现 `serial_port`；端口下拉仍列出 COM 口 + `@alias` |
| 5 | 全局 grep `WIDGET_TYPES` 只剩泛化谓词，无具体类型名 |
| 6 | 无扩展环境跑离线校验：**零** `device_alias_*` 相关 warning；有扩展时正常报 |
| 7 | `File ▸ Open Example` 里 pulse 示例出现在 device 分组；从 `Examples/` 删除后仍可打开 |
| 8 | 通用测试 grep 无 `SerialSend` / `ParallelSend` / `SerialParallelDevice`（除 fixture） |
| 9 | `Application/`（除扩展目录）grep 上述关键词仅剩 §7 合规项 |

### 10.2 可复现的验收命令

```powershell
# 1) 主线引用（移出完成的判定 = 只剩 §7 合规项）
Get-ChildItem Application -Recurse -File -Include *.py,*.json |
  Where-Object { $_.FullName -notlike '*\Functions\SerialParallelDevice\*' -and
                 $_.FullName -notlike '*\__pycache__\*' } |
  Select-String -Pattern 'SerialParallelDevice|SerialSend|ParallelSend|DeviceRegistry'

# 2) 主线测试
Get-ChildItem Test -Recurse -File -Filter *.py |
  Where-Object { $_.FullName -notlike '*\dist\*' -and $_.FullName -notlike '*_runs\*' -and
                 $_.FullName -notlike '*\TestProject\*' -and $_.FullName -notlike '*_gtec_archive_20261016*' } |
  Select-String -Pattern 'SerialParallelDevice|SerialSend|ParallelSend|DeviceRegistry'

# 3) 主线示例
Get-ChildItem Examples -Recurse -File -Filter *.scene |
  Select-String -Pattern '"node_type":\s*"(SerialSend|ParallelSend)"'

# 4) 回归
.venv-py314t\Scripts\python.exe Utils/Dev/test_runner.py --tier core
.venv-py314t\Scripts\python.exe C:\WorkSpace\FLY\FlyVibing-User-And-Developer-Utils\packages\extension-kit\src\flyvibing_extension_kit\review_extension.py Application/Functions/SerialParallelDevice
```

### 10.3 交接信号

做完 §8.1 中标为 P0 / P1 的项（P2 / P3 可分批）后，任一方式通知主线即可：

1. 在本文 §12 回执表追加一行（最推荐，留痕）；
2. 或在 `HANDOFF.md` 顶部状态块加一行 `> **主线解耦完成（日期）**`。

**没收到回执，主线不动这些代码**——这是本次的约定，避免两边同时改同一批文件。

> **回执已发出（2026-11-10）**: 见 `Doc/REPLY_TO_MAINLINE_2026-11-10.md`
> （扩展侧裁决 / 已完成项 / 请主线先做的 8 步顺序 / 6 个待答复问题）。
> 下方 §12 表格是摘要；**以回信正文为准**。

---

## 11. 主线收到信号后的动作（预告，不含代码）

按本文顺序执行，每步独立可回滚：

1. 删 P0 的 4 处裸 import + `_RUNTIME_CHAIN` / `SPAWN_SITES` 条目（P0-1..P0-6）。
2. 按 §8.1-2 的裁决执行 `DeviceRegistry` 处理。
3. 泛化 `serial_port` → `choices_source`；`WIDGET_TYPES` → 谓词。
4. 校验器改为可注册 checker（工具仓，同步发布）。
5. `graph_rules.py` 去表格化。
6. 迁移示例工程（按 §8.2-6 裁决）。
7. 通用测试去具体化。
8. 更新 `Doc/Dev/README.md`、`Doc/Dev/print_inventory.md`、`Utils/Dev/test_map.py` 清单并重生成 `test_nodes.*`。

每步完成后重跑 §10.2 的四条命令。

---

## 12. 回执（扩展侧填写）

| # | 条目 | 状态 | 日期 | 签名 | 证据（命令输出/截图/commit） |
|---|---|---|---|---|---|
| 1 | 生命周期钩子迁移 | ☑ 完成（**方式变了**：主线用接缝 `OptionalExtensions` 调包级函数；钩子保留为死代码） | 2026-11-14 | 主线 + 扩展侧 | `Core/Extension/OptionalExtensions.py`；`test_runtime_optional_extensions`；扩展缺席的产物不再 `ModuleNotFoundError` |
| 2 | 端点台账（3.1a / 3.1b） | ☑ **完成（3.1a）** — 核心 `Core/DeviceRegistry.py` 已删除，实现唯一在本扩展 | 2026-11-14 | 主线 + 扩展侧（v0.7.0 认领） | `device_registry.py` 自注册 + `extension.json.device_aliases`；`A.status()` → `available=True provider=device`；`test_extension_coupling_inventory` 13/13 |
| 3 | 节点语义文档 | ☑ 扩展侧完成（主线删表仍待办） | 2026-11-10 | 扩展侧 | `node_pack.py` 两段 `props_text`（编码/范围/framing/复位） |
| 4 | 端口控件改 `choices_source` | ☐ 未开始（等主线 pack 扩展点） | | | 现仍用 `kind="serial_port"` |
| 6 | 校验器 `@alias` 贡献点 | ☑ 完成（**不需要贡献点**：校验器改读 `Application.Core.DeviceAliases`） | 2026-11-14 | 主线 | 无扩展环境零 `device_alias_check_unavailable`；有扩展时正常报未绑定 |
| 7 | 示例工程迁移 | ☐ 未开始（计划 Batch B） | | | 见 `Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md` §5 |
| — | 兼容红线 §9 自查（10/10） | ☑ 完成 | 2026-11-10（2026-11-14 复测） | 扩展侧 | 计划文档 §4 逐条对照；`devices.json` 未迁移 |

**扩展侧备注**（裁决意见、异见、阻塞项）：

```text
扩展侧备注（裁决意见、异见、阻塞项）：

```text
【2026-11-14 收尾】主线已完成迁移（逻辑互 + 删 DeviceRegistry + 能力凭据 + 声明发现）。
扩展侧认领 v0.7.0：版本/CHANGELOG/本表已更新；并加了一层跨版本保护（旧引擎无
DeviceAliases 时跳过自注册，不 ImportError）。回信：Doc/REPLY_TO_MAINLINE_2026-11-14.md。

裁决: 端点台账选 3.1a（严格搬走），落地为“自持实现 + 过渡委托”：
- 新模块 Application/Functions/SerialParallelDevice/device_registry.py；
  核心模块仍存在时公开函数整体委托，backend()=="core"；核心删除后自动接管（"extension"）。
- 路径/格式/环境变量不变（AppIdentity.data_dir("devices.json") / *_DEVICES_FILE）。
- 过渡期只有同一模块对象，不存在两份缓存 → 编辑器端口下拉 / 离线校验 / 既有测试不受影响。

P0 提醒: 导出模式 PlayerBootstrap 目前不加载扩展对象，lifecycle 钩子只能覆盖 PIE；
若成品也要走钩子，主线需先定运行期入口（manifest 或扩展加载），否则 P0-2/P0-3 保留直接调用。

节点语义: props_text 已补齐（SerialSend: port/baud/format/prefix/suffix/未绑定报错；
ParallelSend: mode/address/value 1-255/自动复位），可删 graph_rules.py 两行与 4 行说明。

示例: SerialPulse / ParallelPulse 建议迁到本扩展 Examples/（宿主已自动登记，测试覆盖）；
MI / RestingState 建议留在主线（展示范式结构，不是设备示例）。

审计补漏: `Editor/UI/panels/node_editor/visible_pins.py:132` 的 `@rule("ParallelSend")`
是**实际行为**（Manual 模式隐藏 `Value` 引脚），不是 P3 文档示例；删核心规则前，
主线需先给 node_pack 增加声明式 `pin_visibility`（详见计划文档 §3-7）。

测试: 按用户 2026-11-10 指示，本轮只跑相关测试，不跑全量。
明细: Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md
```

---

## 附录 A — 主线 `Application/` 引用清单（14 文件 / 28 行）

| 文件 | 行数 | 性质 |
|---|---|---|
| `Core/NodeGraph/graph_rules.py` | 7 | P1-2 节点表与语义 |
| `Core/DeviceRegistry.py` | 3 | P1-1 整个模块 |
| `Runtime/GameRuntime.py` | 3 | P0-1/2/3 |
| `Editor/UI/panels/node_editor/visible_pins.py` | 2 | P3 docstring |
| `Core/NodeGraph/node_packs.py` | 2 | P3 docstring 示例 |
| `Editor/UI/panels/node_editor/widgets/core.py` | 2 | P2-1 内部 import + 说明 |
| `Core/NodeGraph/node_types/io.py` | 2 | P3 迁移记录 |
| `Core/NodeGraph/node_types/__init__.py` | 1 | P3 |
| `Functions/official_extensions.json` | 1 | §7 合规 |
| `Runtime/PlayerBootstrap.py` | 1 | P0-4 |
| `Editor/UI/panels/node_editor/group_layout.py` | 1 | P2-2 |
| `Editor/UI/panels/node_editor/widgets/flow_io.py` | 1 | P3 |
| `Core/NodeGraph/evaluator_engine.py` | 1 | P3 |
| `Core/NodeGraph/evaluators/io.py` | 1 | P3 |

> 另有 `.gitignore`（1 行）属 §7 合规项，未计入。

## 附录 B — 主线测试层引用清单（15 文件 / 98 行命中）

| 文件 | 命中行 | 分类 |
|---|---|---|
| `Test/Application/Functions/test_device_alias.py` | 28 | P3 专用（282 行） |
| `Test/Application/NodeGraph/test_node_pack.py` | 24 | P3 通用测试硬编码 |
| `Test/Application/Editor/test_export_extension_scope.py` | 9 | P3 通用测试硬编码 |
| `Test/Application/Functions/test_serial_parallel_device.py` | 9 | P3 专用（432 行） |
| `Test/Application/Functions/test_spd_monitor.py` | 5 | P3 专用（100 行） |
| `Test/Application/Editor/test_pulse_examples.py` | 4 | P3（示例迁移后随之变） |
| `Test/Application/Editor/test_editor_mcp_package.py` | 4 | P3 通用测试硬编码 |
| `Test/Application/Functions/test_device_autobind.py` | 3 | P3 专用（157 行） |
| `Test/Application/Editor/test_imgui_input_flags.py` | 3 | P3 通用测试硬编码 |
| `Test/Application/Extensions/test_extension_review.py` | 3 | P3 通用测试硬编码 |
| `Test/Application/Core/test_extension_python.py` | 2 | P3 通用测试硬编码 |
| `Test/Device/com3_listener.py` | 1 | P3 专用（59 行） |
| `Test/Application/Core/test_thread_boundary.py` | 1 | **P0-6** |
| `Test/Application/NodeGraph/test_mi_groups.py` | 1 | P3 |
| `Test/Application/Core/test_node_graph_boundary.py` | 1 | **P0-5** |

## 附录 C — 同根因但不在本次范围

同样的"引擎缺少扩展挂钩契约 → 写进主线 → 加 try/except 装死"在另外两个扩展上也存在。**修 SPD 不会顺带治好它们**，单独立单：

| 位置 | 内容 |
|---|---|
| `Core/NodeGraph/validation/dry_run.py:173` | Core **反向 import** `Application.Functions.VirtualDevice`（`destroy_pool/kill_device/list_pools/list_sessions`） |
| `Core/NodeGraph/validation/dry_run.py:189` | Core 反向 import `Application.Functions.BCIAlgorithm.clear_matching` |
| `Editor/Services/LiveCommandServer.py:400` | `device.save` op 直接 import `VirtualDevice.save_record` |
| `Editor/UI/panels/node_editor/widgets/epoch.py:61` | 直接 import `BCIAlgorithm.epoch_stats` |
| `Runtime/GameRuntime.py:126/229`、`PlayerBootstrap.py:430` | `VirtualDevice.close_all` + try/except |
| `Runtime/GameRuntime.py:133/238`、`PlayerBootstrap.py:438` | `BCIAlgorithm.reset_all` + try/except |

建议：§8.1-1 的 lifecycle 钩子设计时**一并覆盖**这三类需求（启动清理、停止清理、只读统计 op），避免下一轮重复。

## 附录 D — 本次审计的未验证项

| # | 未验证 | 影响 |
|---|---|---|
| D1 | `NodePackRegistry` 的 `props_text` 是否被 `graph_rules` 消费 | 决定 P1-2 是"补消费点"还是"删表" |
| D2 | `builtin` + `always_on` 扩展的 `Examples/` 是否被 `UIManager._example_dirs()` 收录 | P3-2 动工前提 |
| D3 | `Utils/Dev/test_map.py` 是否有扩展内测试目录的扩展位 | P3-1 长期方案 |
| D4 | `Utils/Dev/Installer/build` 副本与 `Test/TestProject/**/dist` 的刷新流程 | 迁移后需重导的清单 |

> 以上四项不影响本文结论，只影响 §11 的执行顺序细节。
