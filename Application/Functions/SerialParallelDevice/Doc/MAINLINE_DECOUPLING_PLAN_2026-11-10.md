# 主线解耦迁移计划 —— 扩展侧执行单（2026-11-10）

> **⚠ 2026-11-14 已收尾（本文已被取代）**: 主线已完成迁移（P0 接缝 + 删除
> `Core/DeviceRegistry.py` + 能力凭据 `Application.Core.DeviceAliases`），
> 本文的“过渡期委托”描述已过期。**以 `Doc/HANDOFF_2026-11-14_engine_decoupling.md`
> 与 `Doc/REPLY_TO_MAINLINE_2026-11-14.md` 为准**；本文保留作为决策记录（3.1a 的推导过程）。

> **签发**: Serial/Parallel 扩展维护 agent
> **输入**: `Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md`（主线只读审计 + 工作单）
> **对外交付**: 给主线的回信 = `Doc/REPLY_TO_MAINLINE_2026-11-10.md`（本文件是内部执行单，回信是要递出去的那份）
> **范围**: 代码改动**只落在本扩展目录**。主线文件（`Core/`、`Runtime/`、`Editor/`、`Examples/`、`Test/`）
> 与工具仓由主线/对应 owner 执行；本单只给契约、证据与回执。
> **原则**: 先做兼容、再交主权；用户可见行为变化尽量为零。

---

## 0. 结论（先看）

1. **端点台账选 3.1a（严格搬走）**，但采用"自持实现 + 过渡委托"的落地方式
   （主线建议 3.1b；按用户"把扩展内容移出主线、由扩展自己负责"的要求选 3.1a）：
   - 新模块 `device_registry.py` 是扩展的正式实现；
   - 核心 `Application/Core/DeviceRegistry.py` 仍存在时，公开函数**整体委托**给它 →
     编辑器通用端口下拉、离线校验器、既有测试看到的状态完全不变；
   - 主线删除核心文件后，本模块**自动接管**；存储路径与 JSON 格式不变，用户无迁移动作。
   - **已知代价（接受）**：离线校验器（不加载扩展）将无法在 PIE 前报"别名未绑定"，
     主线按 3.1a 同步降级；扩展在场时（面板 / `ext.device.*` / 节点求值）仍显式报错，
     不会静默回退。这符合"引擎不认识设备概念"的最终边界。
2. **节点语义文本（`props_text`）已补全**，达到可替代 `graph_rules.py` 中
   `SerialSend` / `ParallelSend` 两行与 4 行编码说明的完整度。
3. **引擎生命周期钩子已在扩展侧实现**（`on_engine_start` / `on_engine_stop`），
   但**调度点必须由主线补**；且导出模式（`PlayerBootstrap`）需要主线先决定
   "成品运行期是否加载扩展"，否则 P0-2/P0-3 不能只靠钩子解决。
4. 本轮**不动** `Examples/`、`Test/`、主线注释与工具仓校验器 —— 这些要么属于 P3，
   要么需要主线/工具仓先给通用契约（`choices_source` / checker 贡献点）。
5. 节点求值器在 I/O 线程未运行 / 驱动不可用时，改为**节点日志显式告警**
   （仍不打断图执行），配合"停用扩展 = 真的不拉起 I/O"的语义。

---

## 1. 归属盘点（迁移前 → 目标）

| 能力 | 现在住哪 | 目标 | 状态 |
|---|---|---|---|
| `SerialSend` / `ParallelSend` 类型 + 求值器 | 本目录 `node_pack.py` | 不变 | ✅ 2026-10-20 已迁出核心 |
| 声明式字段（port/baud/format/prefix/suffix/address/mode/value） | `node_pack.py` | 不变 | ✅ 已是扩展声明 |
| 节点语义正文（pin/props/编码/取值范围） | 核心 `graph_rules.py` 硬写 + `props_text` | `props_text` / `graph.types` | ✅ 本轮补全 `props_text`；待主线删表 |
| 端点台账（`@alias` ↔ 物理端点） | 核心 `Core/DeviceRegistry.py` | 本目录 `device_registry.py` | ✅ 本轮自持 + 过渡委托 |
| 运行期 I/O 启停 | 主线 `Runtime/GameRuntime.py` / `PlayerBootstrap.py` 裸 import | 扩展生命周期钩子 | 🟡 扩展侧已实现；待主线调度 |
| 端口选择控件 | 核心 `widgets/core.py` 的 `kind == "serial_port"` | 通用 `choices_source` | ⛔ 等主线契约 |
| 离线 `@alias` 校验 | 工具仓 `node_graph_validator.py` | 可注册 checker | ⛔ 等主线/工具仓契约 |
| 示例工程（SerialPulse / ParallelPulse） | 主线 `Examples/` | 本目录 `Examples/` | ⏳ 计划（见 §5） |
| 扩展专用测试 | 主线 `Test/` | 长期随 `test_map` 扩展 | ⏳ 暂不动（见 §5） |
| 注释中的具体类型名 | 主线 8 处 | 去具体化 | ⏳ 主线单方面执行 |

---

## 2. 本轮已落地（Batch A）

### 2.1 端点台账自持 —— `device_registry.py`（新增）

- 公开面与核心模块一致：
  `path / load / all / get / resolve / describe / is_ref / parse_ref / valid_name / bind / unbind / set_hint / DeviceUnresolved / _reset_for_tests`。
- **过渡委托**: `_legacy_module()` 探测 `Application.Core.DeviceRegistry`；
  存在则所有公开函数委托，`backend()` 返回 `"core"`；删除后返回 `"extension"`。
- **异常类型统一**: 过渡期 `DeviceUnresolved` 直接复用核心类，调用方 `except` 不受影响。
- **存储不变**: `AppIdentity.data_dir("devices.json")`；`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 覆盖照旧；
  格式 `{"version": 1, "devices": {...}}`；写入仍是临时文件 + `os.replace`。
- 接线改动：
  - `serial_manager.resolve_port()` 改用 `device_registry`；
  - `extension.py` 的 6 处 `import Application.Core.DeviceRegistry as reg` 全部切换；
  - `ext.device.status` 新增 `registry_backend`（`core` / `extension`），仅诊断字段。

> **迁移期状态共享**：因为委托是"同一个模块对象"，不存在两份缓存；
> 主线删文件后扩展自动切换到本地实现，文件路径/格式不变。

### 2.2 节点语义文本补全 —— `node_pack.py`

`SerialSend.props_text` 现在包含：端口（`COMx` / `@alias`，空 = 显式报错并跳过）、
`baud_rate`、`format`（`bytes` = float32 LE 4B；`string` = UTF-8 文本行）、
`prefix/suffix`（仅 string；示例 `40,` + 14 → `40,14` + LF；拒绝 CR/LF）、未绑定别名显式报错。
`ParallelSend.props_text` 现在包含：`mode`（manual/pin）、三个 LPT 地址、
`value 1-255`（0 保留给自动复位）、非零写后按脉冲宽度自动归零（面板 Pulse，默认 5 ms）。

这两段就是 `graph_rules.py` 删除后 agent/开发者应读到的正文；`graph.types` 已直接返回 `props_text`。

### 2.3 引擎生命周期钩子 —— `extension.py`

```python
def on_engine_start(self, mode: str = "pie") -> None: ...
def on_engine_stop(self) -> None: ...
```

- 内部调用 `start("runtime")` / `stop("runtime")`（租约模型，幂等）；
- 契约提案：宿主在 PIE / 成品启动、结束时**只对已加载（已启用）的扩展**调用；
  未启用 → 不调用 → 不会拉起 `spd-io`（同时解决 P0-7 的"关掉也生效"）。
- 过渡期主线的直接 import 保留，二者并存不会重复开线程（租约是集合）。

> **导出模式注意**：`PlayerBootstrap` 目前不加载扩展对象，只 import 本模块。
> 若主线希望成品也走钩子，需要先在运行期加入"扩展入口加载"或 manifest 声明的
> runtime 入口；否则 P0-2/P0-3 仍需保留直接调用。**这一点请主线在实施 P0 时明确。**

### 2.4 节点求值器不再"只打印"丢弃

`SerialSend` / `ParallelSend` 在 `send` / `write_parallel` 返回 `False`
（I/O 线程未运行、并口驱动不可用）时，除 console 打印外**同时写节点 error 日志**
（`ctx.emit_log(..., "error", ...)`）。不抛异常、不打断图执行（保持 `strict=False` 契约），
但在"扩展停用 / 运行期入口未启动"时用户能在节点日志里看到明确原因，而不是只有终端一行。

---

## 3. 需要主线先给的东西（扩展侧无法单独完成）

| # | 主线动作 | 扩展侧随后做 | 验收 |
|---|---|---|---|
| 1 | 生命周期调度：对已加载扩展调用 `on_engine_start/on_engine_stop`；删除 `GameRuntime` / `PlayerBootstrap` 的直接 import（导出模式先定入口） | 无（钩子已实现） | `extension.disable id=device` → PIE 无 `spd-io`；enable → TX 计数正常 |
| 2 | 删除 `graph_rules.py` 的 `SerialSend/ParallelSend` 两行与 4 行语义 | 无（`props_text` 已完整） | `graph.types owner=device` 仍返回 pin + props 文本 |
| 3 | 通用 `kind: "enum"` + `choices_source`（或等价候选来源） | `node_pack.fields` 的 `serial_port` 改成通用形态 | 端口下拉仍列 COM 口 + `@alias` |
| 4 | 校验器可注册 checker / 引用解析器贡献点（工具仓） | 提供 `@alias` 解析与文案（可直接用 `device_registry.resolve`） | 无扩展环境零 `device_alias_*` warning；有扩展时正常报 |
| 5 | P2-2 `WIDGET_TYPES` 泛化、P3 注释去具体化 | 无 | 全局 grep 无具体类型名 |
| 6 | 决定 `Examples/` 与测试归属（见 §5） | 迁 pulse 示例 / 提供扩展内测试 | `File ▸ Open Example` 可见 |
| 7 | **引脚可见性规则（审计未列，本轮发现）**：`Editor/UI/panels/node_editor/visible_pins.py:132` 的 `@rule("ParallelSend")` 是**实际行为**（Manual 模式隐藏 `Value`，`Address` 由控件展示），不只是文档示例。 | 在 `node_pack` 增加声明式 `pin_visibility`（如 `hide` / `hide_when`），主线读取；否则删掉核心规则后并行节点会多出一个 `Value` 引脚 | 删掉核心 `@rule("ParallelSend")` 后，Manual 模式仍只显示 `exec_in/exec_out` |

> 附带项：工具仓 `review_extension.py` 的 C6 白名单仍列 `Application.Core.DeviceRegistry`
> （当前只在 `extension.py` 上生效，本扩展入口已不再 import 它）。
> 主线删除核心台账后该白名单项可移除；`device_registry.py` 内部的 guarded import
> 会在核心缺失时自动走本地实现，不产生 warning。
>
> 另注：`graph_rules._NODE_GRAPH_RULES` 会随 `NodeCanvas.to_dict()`（`canvas.py:294`）
> 写入场景的 `node_graph._rules`。删除两行前请确认**导出物**仍能向离线消费者描述这两个节点 ——
> 建议导出时把 `NodePackRegistry` 的 `props_text` 追加进 `_rules`，或保留指向扩展文档的指针。

---

## 4. 兼容红线自查（对照审计 §9，10/10）

| # | 红线 | 本轮是否触碰 | 证据 |
|---|---|---|---|
| 1 | `SerialSend` / `ParallelSend` 类型名、pin 名不改 | 否 | `node_pack.py` 类型/引脚未改 |
| 2 | props 键 `port/baud_rate/format/prefix/suffix/address/mode/value` 不改 | 否 | 仅改 `props_text` 文案 |
| 3 | `@alias` 语义不变；未绑定显式报错 | 否 | `device_registry.resolve` 保持异常 |
| 4 | `SerialSend.port` 默认空 | 否 | 求值器逻辑未改 |
| 5 | 台账路径/格式/环境变量不变 | 否 | 复制同一 `AppIdentity` 调用 |
| 6 | 9 个 `ext.device.*` op 名称/参数不变 | 否 | 仅 `status` 增加 `registry_backend`（增量） |
| 7 | 面板按钮与 op 同一实现 | 否 | 未新增第二路径 |
| 8 | 不 import 编辑器层；图访问走 `ctx.graph` | 否 | `device_registry` 只 import Core |
| 9 | 不碰宿主 imgui 全局状态 | 否 | 无 UI 代码改动 |
| 10 | `ParallelSend` uint8 语义（1–255，0 保留复位）不变 | 否 | 求值器未改 |

---

## 5. 后续批次（按依赖顺序）

### Batch B —— 示例工程（P3，可独立做）
- `Examples/SerialPulse`、`Examples/ParallelPulse` → 本目录 `Examples/`；
  配套 `Examples/tools/pulse_pipeline.py` / `apply_pulse_pipeline.py` 一并迁入，
  README 里的 `engine-editor-cli exec Examples/tools/...` 路径同步更新。
  宿主已支持 `<extension_dir>/Examples` 自动登记（`test_extension_examples.py` 覆盖，
  含"未声明 capabilities 也自动登记"），disable 时自动消失。
- 主线 `Examples/MI` / `Examples/RestingState` **建议留在主线**：它们展示的是"实验范式结构"，
  设备节点只是最小发送手段；移动到设备扩展会让"范式演示"跑进设备示例分组。
- 迁移时机建议：主线删除原目录的同一版本内完成，避免菜单里长期出现两份同名示例。

### Batch C —— 控件与校验（等主线/工具仓契约）
- `serial_port` → `{"kind":"enum","choices_source":"device.ports"}`；
  在扩展侧提供 `ports()` 回调（COM 口 + `@alias`）。
- `@alias` checker：扩展侧导出 `resolve_ref(name) -> (ok, message)`；
  工具仓只负责"引用无法解析"的通用规则。

### Batch D —— 测试与注释（主线主导）
- 扩展专用测试（5 个文件 / 1030 行）暂留主线；等 `test_map` 支持扩展内测试目录后再迁。
- 主线 8 处注释去具体化由主线执行，扩展侧无需配合。

---

## 6. 本轮验收（只跑相关测试，不跑全量）

```powershell
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_device_alias.py      # 41/41
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_device_autobind.py   # 27/27
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_serial_parallel_device.py  # 79/79
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_spd_monitor.py       # 14/14
.venv-py314t\Scripts\python.exe Test\Application\NodeGraph\test_node_pack.py         # 26/26
.venv-py314t\Scripts\python.exe Test\Application\Extensions\test_extension_manager.py  # 36/36（device 装载/ops/窗口/卸载）
.venv-py314t\Scripts\python.exe C:\WorkSpace\FLY\FlyVibing-User-And-Developer-Utils\packages\extension-kit\src\flyvibing_extension_kit\review_extension.py Application/Functions/SerialParallelDevice  # 20 pass / 0 warn / 0 fail
```

补充冒烟：

```powershell
.venv-py314t\Scripts\python.exe -c "from Application.Functions.SerialParallelDevice import device_registry as r; print(r.backend(), r.path())"
# 过渡期输出: core C:\Users\<user>\AppData\Roaming\FlyVibingEngine\devices.json
```

> 按用户 2026-11-10 指示：**不跑全量**（`--tier core`），只跑上表相关项。

---

## 7. 影响面（用户通知依据）

### 7.1 使用本扩展节点的工程（扫描 `Test/TestProject`、`Examples/`、`missssep/Examples`）

> MI-SSSEP 扩展**代码本身不 import 本扩展** —— 只有它的示例场景使用
> `SerialSend` / `ParallelSend`（节点由 `NodePackRegistry` 自动发现）。
> 因此迁移不需要改 MI-SSSEP 的代码，只需保证节点 type/props 与 `@alias` 语义不变。

| 来源 | 场景数 | SerialSend | ParallelSend |
|---|---:|---:|---:|
| `missssep/Examples`（7 个示例） | 7 | 7 | 14 |
| 主线 `Examples/`（MI / RestingState / SerialPulse / ParallelPulse） | 4 | 1 | 6 |
| `Gtec/Examples`（GtecRestingState） | 1 | 0 | 1 |
| `Test/TestProject`（MI-SSSEP ×3） | 3 | 2 | 7 |
| **合计** | **15** | **10** | **28** |

> 逐场景清单：MI-SSSEP 扩展 7 个示例各 `1×SerialSend + 2×ParallelSend`；
> `Examples/MI` 3P、`RestingState` 2P、`SerialPulse` 1S、`ParallelPulse` 1P；
> `GtecRestingState` 1P；`TestProject/MI-SSSEP-Version2` 1S+4P、`MI-SSSEP` 1S+1P、`MI` 2P。
> （`.scene.before_pulsefix` 备份不计入。）

### 7.2 用户可见变化预期

| 项 | 预期 |
|---|---|
| 节点类型 / pin / props 名 | **不变** —— 旧场景直接加载 |
| `@alias` 绑定数据 | **不变** —— 同一 `devices.json` |
| 9 个 `ext.device.*` op | **不变**；`status` 多一个 `registry_backend` 字段 |
| 面板 / 设备管理器 | **不变** |
| 串口行协议 | 已支持 `prefix/suffix`（2026-11-09 起）；旧场景空 prefix = 旧行为 |
| 并口语义 | 仍 uint8 1–255；0 保留自动复位；脉冲宽度默认 5 ms |
| 升级方式 | 引擎与扩展**同版本一起升级**；`Paradigm/rst/*` 成品是自包含快照，不受影响 |

### 7.3 用户通知草稿（待主线删除兼容内容时发出）

> 完整可发布草稿: `Doc/USER_NOTICE_DRAFT_2026-11-10.md`（含自查步骤与回滚说明）。
> 下面是摘要；定稿以独立草稿为准。

```text
【Serial/Parallel 设备扩展 — 迁移说明】
1. 节点类型、属性名、@设备名语法、devices.json 位置均未改变；旧场景无需改动。
2. 请确认本机 @SSSEP-Stimulator（或其他别名）仍绑定到正确 COM 口：
   engine-editor-cli call ext.device.status
   若显示 unbound / 端口变了：ext.device.autobind（或面板 Device Manager 重绑）。
3. 串口刺激协议 v2 需要行首频率（如 40,14）→ 节点 Prefix 填 "40,"；
   旧工程若未填，实发仍是 14.0 形式。
4. 并口 Trigger 仍是单字节 1–255；0 表示复位，不要手动发送 0。
5. 从 2026-11 起的引擎版本已把设备台账/节点实现收回扩展；
   请勿把旧版扩展目录与新引擎混用（成品 rst 包不受影响）。
```

---

## 8. 回执

本单对应审计 §12 的填写状态：

| # | 条目 | 状态 | 依据 |
|---|---|---|---|
| 1 | 生命周期钩子迁移 | 🟡 扩展侧完成（待主线调度） | `DeviceExtension.on_engine_start/on_engine_stop` |
| 2 | 端点台账（3.1a） | 🟡 扩展侧完成（待主线删文件） | `device_registry.py`；`backend()=="core"` 过渡 |
| 3 | 节点语义文档 | ✅ 扩展侧完成 | `node_pack.py` 两段 `props_text` |
| 4 | 端口控件 `choices_source` | ⛔ 等主线契约 | 未改 `fields` |
| 6 | 校验器 `@alias` 贡献点 | ⛔ 等工具仓契约 | 预留 `device_registry.resolve` |
| 7 | 示例工程迁移 | ⏳ 计划 Batch B | 见 §5 |
| — | 兼容红线 10/10 | ✅ | 见 §4 |
