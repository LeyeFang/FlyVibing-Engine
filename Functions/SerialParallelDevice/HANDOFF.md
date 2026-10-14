# Serial/Parallel 官方扩展 — 交接书

> **接手对象**: 本扩展自 2026-10-12 起由**新的维护 agent** 负责（本文 = 你需要的全部上下文浓缩）。
> **上游诉求方**: 用户（实验方，MI-SSSEP 范式作者）。**送交人**: 前维护 agent。
> **十分钟上手**: §1 → §2 → §3 → §6 跑三条命令 → §5 挑第一件活。

---

## 1. 这个扩展是什么（边界，先划清）

- 身份: 官方示例扩展之一，`id = device`，目录 `Functions/SerialParallelDevice/`，入口 `extension.py:create_extension`，
  `DeviceExtension(UIExtensionBase)`，manifest `extension.json`（capabilities `["ops","nodes","ui","graph"]`，ops 前缀 `ext.device.*`）。
- 两个消费者（都要照顾好，不能只顾一边）:
  1. **实验场景里的节点** — `SerialSend` / `ParallelSend`（图里发字节，MI-SSSEP 实验在用）；
  2. **人工 + agent 的面板** — 端口枚举/试发/监视事件流/**绑定逻辑设备名**。
- 它**不是**通用串口 SDK、不是设备驱动。它只负责"把实验设计里的意图可靠地送到物理端口，并把过程显式化"。
- 它同时是**官方示范**：社区开发者会照抄这里的写法 → 这里的每个取舍都要能解释。

## 2. 资产地图（改哪里 / 谁是真权威）

| 能力 | 实现位置 | 权威文档 |
|---|---|---|
| 面板（Serial/Parallel 页 + Device names 段） | `Functions/SerialParallelDevice/extension.py` | ExtDev §7（UI 契约）/ §11（自由度标注） |
| `ext.device.*` 8 件 op | 同上 `_register_ops` | ExtDev §9（agent 生态）；`engine-editor-cli call ext.device.status` |
| 串口/并口 IO + 线程 | `Application/Functions/SerialParallelDevice/{api,state,io_thread,tasks}.py` | `Doc/Dev/device_io_protocol.md` §2–§7 |
| 端口枚举 / 事件环缓 / watch | `.../monitor.py`（`state._events` 环缓 500） | device_io §11 |
| **逻辑设备名（两级身份）** | `Application/Core/DeviceRegistry.py` + `serial_manager.resolve_port()` | **device_io §12（这一节要通读）** |
| 端口解析接线 | `api.send` / `monitor.start_watch`（入队前解析） | device_io §12 |
| 节点求值器 / 控件默认值 | `Core/NodeGraph/evaluators/io.py`、`Editor/UI/panels/node_editor/widgets/flow_io.py` | device_io §12 |
| 校验规则 13（未绑定 `@ref` 警告） | `Core/NodeGraph/validation/checks.py` | device_io §12 |
| 面板 ↔ 场景同步通道 | `Application/Editor/Extensions/ExtensionGraph.py` + `ctx.graph` | ExtDev §6（能力表） |
| 静态审查器（提交前必跑） | `FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py`（M1–M6 / C1–C11 / F2） | ExtDev §7 + §14 |
| 无头 GUI 测试入口 | `FlyVibing-User-And-Developer-Utils/packages/extension-kit/imgui_headless.py` | ExtDev §12.6 |

## 3. 已定裁决（**不要重开**，除非用户主动改主意）

| # | 裁决 | 理由（用户的原始诉求） |
|---|---|---|
| 1 | **两级设备身份**: 场景写 `@名字`（实验设计），机器注册表 `%APPDATA%/MyGameEngine/devices.json` 存物理端口 | "迁移实验换台电脑插设备，设备就找不到了" → 换机器不改实验 |
| 2 | **未绑定必须显式报错**（`DeviceUnresolved`），绝不静默回退 | 静默失败 = 实验数据作废却没人知道 |
| 3 | **`SerialSend.port` 默认值从 `COM1` 改为空**（兼容性变更）：未配置 → 显式 error 日志并跳过 | 不允许"猜一个端口就发" |
| 4 | **面板按钮与 agent op 必须同一实现**（`_guard` 模式 → 调 `_op_*`） | 动作单点：避免"面板能改、agent 不能"的漂移 |
| 5 | `device` 能力键 = **导入许可声明**，不提供 `ctx.device` | 不扩大 API 面 |
| 6 | 图访问必须走 **`ctx.graph`** 受限门面（只有 `nodes/find/set_props`），扩展**禁 import 编辑器层** | 层边界铁律；同时给社区一个"面板 → 场景"的正范例 |
| 7 | 扩展**一律不碰** 宿主全局 imgui 状态 / ini（引擎已永久禁用 ini） | 三个扩展各自写 ini 会把主应用搞崩 |
| 8 | UI 文案英文（字形安全 C7）；**agent 面/日志可中文** | 字体图集无 CJK 时中文渲染成 `?`（现已合并 CJK，但字面量规则仍保留） |

## 4. 现状与已知坑

- **已交付**: 监视面板（含 Device names 段）/ 8 ops / 设备名闭环 / 面板↔场景同步；`review_extension --all` 下本扩展 **18 pass / 0 warn / 0 fail**；core 全套 46/46 绿。
- **测试资产**: `Test/Application/Functions/test_device_alias.py`（31 checks，设备名闭环，含注册表沙箱 `MGE_DEVICES_FILE`）、
  `Test/Application/Functions/test_serial_parallel_device.py`、`Test/Application/Functions/test_spd_monitor.py`（12）、
  `Test/Application/Extensions/test_extension_manager.py`（device 冒烟段）、`test_extension_review.py`（含 C8–C11 合成用例）。
- **坑（都踩过）**:
  1. 跑测试必须用 `.venv-py314t\Scripts\python.exe` — PATH 上的 `python` 是 **3.9**，会在 NodeGraph 的 `X | None` 注解上直接 TypeError。
  2. `engine-editor-cli` 不在 PATH → 用 `.venv-py314t\Scripts\engine-editor-cli.exe`。
  3. PowerShell 5.1 传 JSON 参数给原生 exe 会**吞掉内层双引号**（`props` 变 `{port:COM3}` → `dict.update(str)` 报
     "dictionary update sequence element #0 has length 1"）→ 多参数/嵌套参数一律走 `cli batch ops.json` 文件通道。
  4. 多根工作区里 `grep` 的 includePattern 可能落到**部署副本**根（`MI-SSSEP/rst/...`）→ 用绝对路径。
  5. 画 imgui 时 `begin_child` 必须**无条件配对**（0×0 全裁剪时返回 False 也要 end）；`begin_combo/tab_item` 相反。
  6. 面板里读设备状态一律**只读快照**（渲染帧内零阻塞）；发送走非阻塞队列。
- **本机现场状态（2026-10-12 交接时点）**:
  - 注册表: `SSSEP-Stimulator -> COM3 @9600`（本机；换机器需重新绑）。
  - `Test/TestProject/MI-SSSEP` 的 `MI-SSSEP.scene` + `MI-SSSEP-Version2.scene` 已由裸 `COM3` 迁到 `@SSSEP-Stimulator`。
  - 已导出: `MI-SSSEP/Experiment/Paradigm/project/MI-SSSEP`（设计）+ `.../rst/MI-SSSEP`（成品，含 runtime）。

## 5. 下一步（按优先级；每条都写了"为什么"）

| 优先级 | 任务 | 要点 / 验收 |
|---|---|---|
| **P0** | **自动重绑（免手工）** | 绑定/迁移时把指纹写进注册表 `hint`：`usb_serial`（`serial.tools.list_ports` 的 `serial_number`）/ `vid_pid`。新机器上打开工程或启动面板时按 hint 匹配 → 命中则**自动改绑并打日志**（`[ext:device] auto-bound ...`）；匹配不到 → 保持现在的显式报错。新增 op `ext.device.autobind {name?, dry_run?}` + 面板 `Auto-detect` 按钮（同一实现）。验收: 单测（伪造端口列表）+ 实机拔插一次 |
| P1 | 面板成熟度 | 定时发送间隔 / 快捷指令组（存 `ctx.data_dir`）/ 事件过滤（只看 RX 或 TX）/ 事件导出 csv；并口侧补一个"手写值"区块 |
| P1 | 真实硬件回环验收 | 需要用户插设备配合；把证据落 `Test/_runs/`（截图 + 事件流） |
| P2 | 扩展设置页 | `ctx.settings(schema)` 落地后把面板设置（port/baud/newline/hex/p_addr）迁过去，面板只留常用项 |
| P2 | 节点族迁移 | `SerialSend/ParallelSend` → 扩展 Pack（**红线: type 名与 props 不变**），与 sigproc/BCI 同批 |
| P3 | 文案 i18n | 面板英文文案进目录（等扩展 i18n 通道就绪）；`HANDOFF` 里的裁决 8 仍适用 |
| — | 环境刷新 | delegated/deployed copies（`rst/MI-SSSEP`、EmptyGame dist、Installer）在引擎侧变更后需重导 |

## 6. 验收（照抄即可）

```powershell
# 单扩展闭环（设备名/解析/求值器/校验/ops）
.venv-py314t\Scripts\python.exe Utils/Dev/test_runner.py --only device_alias
# 全量回归（动了引擎侧任何一处都跑）
.venv-py314t\Scripts\python.exe Utils/Dev/test_runner.py --tier core
# 提交前静态审查（必须 0 fail）
.venv-py314t\Scripts\python.exe FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py Functions/SerialParallelDevice
```

```powershell
# 实机（改面板/op 后至少跑一次）
.\startup.bat
$cli = ".\.venv-py314t\Scripts\engine-editor-cli.exe"
& $cli call extension.enable id=device
& $cli call ext.device.status
& $cli batch Test\_runs\e2e_device_alias\ops.json    # graph.add + bind_nodes 闭环示例
& $cli capture editor --out Test\_runs\e2e_device_alias\panel.png
& $cli call editor.quit
```

## 7. 改动的"完成定义"（DoD，别偷工）

新 op / 新面板动作必须**同时**满足：

1. op 实现（`_op_*`）+ 面板按钮走**同一实现**（`_guard`）；
2. 单测进 `test_device_alias.py` 或新建（无头、沙箱注册表、无硬件依赖）；
3. 文档: `Doc/Dev/device_io_protocol.md`（§11/§12 对应小节）+（如涉 API 契约）`Doc/ExtDev/extension_dev_protocol.md`；
4. `Test/Application/Editor/test_action_contract.py` / `test_editor_mcp_package.py` 的**核心 op 计数**不受影响（扩展 op 是增量扫描，别改成核心）；
5. `review_extension.py` 0 fail；`--tier core` 全绿；
6. 实机至少 enable → 操作 → 截图 → quit 走一遍。
