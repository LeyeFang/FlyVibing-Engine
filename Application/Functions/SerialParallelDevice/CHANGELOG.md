# Changelog — Serial/Parallel 设备扩展（`id = device`）

> **读者**: 扩展开发者、场景/范式作者、离线与在线 agent、部署维护者。
> **版本权威**: `extension.json` 的 `version`（本文按发布批次记录）。
> **先看哪里**: 升级前只读两节即可 —— **§A 破坏性更改总览** 与 **§F 节点图构建指导**。
> **相关文档**: `HANDOFF.md`（交接书）· `Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md`（解耦执行单）
> · `Doc/REPLY_TO_MAINLINE_2026-11-10.md`（给主线的回执）· `Doc/USER_NOTICE_DRAFT_2026-11-10.md`（用户通知草稿）
> · 协议正文: `engine-editor-cli doc show dev/device_io_protocol`

---

## A. 破坏性更改总览（升级必读）

| 版本 | 破坏性更改 | 谁的代码会断 | 一次性动作 |
|---|---|---|---|
| **0.6.0** | `@alias` 台账迁出核心：`Application.Core.DeviceRegistry` → `Application.Functions.SerialParallelDevice.device_registry` | 任何 `from Application.Core.DeviceRegistry import ...` 的扩展/脚本 | 改 import；异常可从包级取 `from Application.Functions.SerialParallelDevice import DeviceUnresolved` |
| **0.6.0** | `encode(..., prefix=, suffix=)` 新增校验：非 `string` 格式或含 CR/LF → `ValueError` | 自行拼行、或在 `bytes` 格式上顺手传 prefix 的调用方 | prefix/suffix 只配 `format="string"`；换行由 `encode` 统一追加 |
| **0.6.0** | prefix/suffix 非空时数值按**最短十进制**格式化（`14` 而非 `14.0`） | 依赖 `14.0\n` 文本的旧断言/文档 | 空 prefix/suffix 行为不变；有 prefix 时按 `40,14` 断言 |
| **0.6.0** | 节点求值器在**发送被丢弃**时新增 `error` 日志 | 断言节点日志条数/内容的测试 | 允许 `error` 级日志；不要按"零错误"断言 |
| **0.6.0** | `props_text` 重写（节点描述正文） | 依赖 `NodeTypeDef.props_text` 精确文本的测试 / agent 提示词 | 改断言关键词，或改读 `graph.types` |
| **0.6.0** | 新增 `on_engine_start` / `on_engine_stop`；失败**不吞**（异常上抛） | 覆写同名方法的扩展；或依赖"扩展静默失败"的调用方 | 覆写时先 `super()`；需要容错请自行 try |
| **0.5.0** | `start()` / `stop()` 变为**租约**语义：`stop()` 只释放自己那个 owner 的租约 | 以为 `stop()` 一定停线程的调用方 | 要强制停 → `stop_all()` |
| **0.5.0** | `send()` / `write_parallel()` 返回 `bool`；`strict=True` 抛 `DeviceNotReady` | 忽略返回值的调用方（发送被静默丢弃） | 检查返回值，或改用 `strict=True` |
| **0.5.0** | 并口复位宽度变为**设备级全局设置**（`set_reset_delay`；面板 Pulse 同样影响节点写入） | 假设固定 5 ms 的时序设计 | 显式 `set_reset_delay(ms)`，不要假设默认值 |
| **0.1.x** | `SerialSend.port` 默认值从 `COM1` 改为**空**（决策 3） | 依赖"不填 port 就走 COM1"的旧场景 | 给节点补齐 `port`（推荐 `@alias`），否则显式 error 并跳过 |
| 未来 | `serial_port` 字段 kind → 通用 `choices_source`；核心 `@rule("ParallelSend")` / `WIDGET_TYPES` 移除；`graph_rules` 表格移除 | 依赖核心端口控件/引脚规则/`_rules` 表格的代码与 agent 提示词 | 见 §G 迁移路线 |

> **场景数据不受影响**：节点类型名、引脚名、props 键名在 0.6.0 全部未变 ——
> 现有 `.scene` / 成品包无需改动。破坏面在**代码接口**，不在**数据**。

---

## B. 英文速览（English quick scan）

| Version | Breaking change | Action |
|---|---|---|
| 0.6.0 | `@alias` registry moved out of core: use `Application.Functions.SerialParallelDevice.device_registry` instead of `Application.Core.DeviceRegistry` | change imports; `DeviceUnresolved` re-exported from the package |
| 0.6.0 | `encode(..., prefix=, suffix=)` raises `ValueError` for non-`string` formats or CR/LF in affixes | use affixes with `format="string"` only |
| 0.6.0 | with affixes, values are formatted shortest (`14`, not `14.0`) | empty affixes keep legacy `str(value)` output |
| 0.6.0 | node evaluators now emit an `error` log when a send is dropped | do not assert "zero error logs" |
| 0.6.0 | `props_text` rewritten | assert keywords, or read `graph.types` |
| 0.6.0 | new `on_engine_start` / `on_engine_stop` hooks; **exceptions propagate** | call `super()` when overriding |
| 0.5.0 | `start()` / `stop()` are lease-based; `stop()` no longer force-stops | use `stop_all()` to force |
| 0.5.0 | `send()` / `write_parallel()` return `bool`; `strict=True` raises `DeviceNotReady` | check the return value |
| 0.5.0 | parallel pulse width is a global device setting | call `set_reset_delay(ms)` explicitly |
| 0.1.x | `SerialSend.port` no longer defaults to `COM1` (empty = explicit error + skip) | set `port` explicitly (prefer `@alias`) |

Scene data (node types, pin names, prop keys) is unchanged in 0.6.0 — no scene migration needed.

---

## 0.6.0 — 2026-11-10（未发布；与主线解耦同版本发布）

主题：**主线解耦 Batch A** —— 把此前由引擎主线代管的内容收回扩展，
并为「主线删除兼容代码」准备替换件。详见 `Doc/REPLY_TO_MAINLINE_2026-11-10.md`。

### 破坏性更改

1. **`@alias` 台账所有权转移**
   - 新增 `device_registry.py`，公开面与旧核心模块一一对应：
     `path / load / all / get / resolve / describe / is_ref / parse_ref / valid_name / bind / unbind / set_hint / DeviceUnresolved / _reset_for_tests`。
   - **过渡期（核心模块仍在）**：公开函数**整体委托**给 `Application.Core.DeviceRegistry`，
     因此编辑器端口下拉、离线校验器、既有测试看到的状态完全一致，`backend() == "core"`。
   - **核心模块删除后**：自动切换为本地实现，`backend() == "extension"`。**路径/格式/环境变量全部不变**
     （`AppIdentity.data_dir("devices.json")`、`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE`、
     `{"version": 1, "devices": {...}}`），用户不需要迁移任何文件。
   - 迁移动作：
     ```python
     # 旧（将在主线删除核心后 ImportError）
     from Application.Core.DeviceRegistry import resolve, DeviceUnresolved
     # 新
     from Application.Functions.SerialParallelDevice import device_registry as reg
     from Application.Functions.SerialParallelDevice import DeviceUnresolved   # 或 reg.DeviceUnresolved
     ```
   - 诊断：`ext.device.status` 新增 `registry_backend: "core" | "extension"`（唯一新增字段，op 名/参数不变）。

2. **`encode()` 的 affix 校验（守卫式，不静默）**
   ```python
   encode(value, fmt="bytes", prefix="40,")          # → ValueError: prefix/suffix apply to text lines only
   encode(value, fmt="string", prefix="40,\n")        # → ValueError: prefix must not contain CR/LF
   ```
   一次 `SerialSend` 调用 = 一行；换行符由 `encode` 统一追加，**不要**写进 prefix/suffix。

3. **数值格式化：有 affix 时用最短十进制**
   - `prefix=""` 且 `suffix=""` → 与旧版**完全一致**（`str(value)`，即 `14.0`）。
   - 任一非空 → `format_scalar()`：`14.0 → "14"`、`14.5 → "14.5"`、`0.1+0.2 → "0.3"`（6 位有效数字）。
   - 因此刺激器 v2 的 `40,14` 使用 `prefix="40,"` + `format="string"`（**不要**自己拼 `"14.0"`）。

4. **节点求值器不再"只打印"丢弃**
   `send()` / `write_parallel()` 返回 `False`（I/O 线程未运行 / 并口驱动不可用）时，
   除 console 打印外**同时写节点 `error` 日志**。仍然不抛异常、不打断图执行
   （保持 `strict=False` 契约，只是不再静默）。

5. **`props_text` 重写**
   `SerialSend` / `ParallelSend` 的节点描述文本改为完整的语义正文（端口/编码/取值范围/复位），
   目的是承接主线 `graph_rules.py` 里即将删除的表格。依赖精确文本比对的测试请改断言关键词。

6. **新增生命周期钩子（失败不吞）**
   ```python
   def on_engine_start(self, mode: str = "pie") -> None:  # 获取 runtime 租约
   def on_engine_stop(self) -> None:                     # 释放 runtime 租约
   ```
   契约：宿主只对**已加载（已启用）**的扩展调用；未启用 → 不调用 → 不会拉起 `spd-io`。
   租约模型下与主线现有直接调用**叠加不会重复开线程**。
   > 与其他扩展的冲突面：若某扩展也定义了同名方法，需先 `super().on_engine_start(mode)`；
   > 本扩展的实现**不做 try/except**（设备 I/O 起不来时继续跑实验 = 静默丢刺激）。
   > 导出模式（`PlayerBootstrap`）目前不加载扩展对象，仍由主线直接调用，本钩子只覆盖 PIE。

### 新增

- `device_registry.py`：扩展自持的机器侧端点台账（含过渡委托与 `backend()` 诊断）。
- `protocol.format_scalar()`：最短十进制文本（串口行协议）。
- `encode()` 的 `prefix` / `suffix` 关键字参数（仅 `string`）。
- 包级导出 `DeviceUnresolved`；`__init__` 文档补 `device_registry` 子模块。

### 内部 / 文档

- `extension.py` 6 处 `import Application.Core.DeviceRegistry` 全部改为扩展内模块（入口不再直接依赖核心台账）。
- `node_pack.py` 两段 `props_text`；求值器增加丢弃告警分支。
- `extension.json` / `extension.py` 版本 `0.5.0 → 0.6.0`；manifest 描述补充台账自持。
- 新增 `Doc/REPLY_TO_MAINLINE_2026-11-10.md`、`Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md`、
  `Doc/USER_NOTICE_DRAFT_2026-11-10.md`、本文件。

---

## 0.5.0 — 2026-10-30

主题：**并口面板修复 + I/O 线程租约 + 脉冲宽度可配**。

### 破坏性更改

1. **`start()` / `stop()` 变为租约语义（单线程 + 多租约）**
   ```python
   start("runtime")   # GameRuntime / 成品
   start("editor")    # 面板 / ops（默认值）
   stop("editor")     # 只释放 editor 租约；runtime 仍在 → 线程继续
   stop_all()         # 强制释放全部租约并关端口
   ```
   - 只有**没有任何租约**时才真正停线程、清队列、关串口。
   - `io_owner()` 返回 `"runtime" | "editor" | "none"`（仅诊断）。
   - **不要**给编辑器单开第二条线程：驱动句柄 / 串口对象 / 复位调度都只有一份。

2. **`send()` / `write_parallel()` 返回 `bool`，并新增 `strict`**
   - 默认 `strict=False`：未就绪 → 打印 + 返回 `False`（节点求值器路径，不打断图）。
   - `strict=True`：抛 `DeviceNotReady`（面板 / op 路径，禁止静默丢弃）。

3. **并口复位宽度是设备级全局设置**
   `set_reset_delay(ms)`（clamp 到 1–1000 ms，默认 5）/ `reset_delay_ms()`。
   面板 `Pulse` 下拉（1 / 5 / 10 / 25 / 50 ms）改的是**同一个全局值**，节点写入同样受影响。

### 修复（用户可见）

- **面板写并口不发字节**：旧面板 Write 不取租约 → `write_parallel` 见 `_running=False` 只打印就丢。现面板写/发前 `start("editor")` 且 `strict=True`。
- **面板默认格式必须是 `byte`**：`"bytes"` = float32 LE 4 字节，写 `1.0` 落到 base 的是 `0x00`
  （设备看不见），且 `+2/+3` 在标准 LPT 上是控制/状态寄存器。节点求值器一直用 `"byte"` ——
  这就是"图能跑、面板不能"的真因。旧 settings（schema 1）自动迁移。
- **面板载荷预览**：写入前显示 `-> 0x3FF8 <- 01 (1B)`，并对触发端口上的 float32 写法给出警告。

---

## 0.4.0 — 2026-10-30

- **Port 改为枚举下拉**：不再手输；当前值不在枚举里时显示 `(not found)` / `(alias)`。
- **新增独立面板 Device Manager**：发现端口 + 绑定/改绑/解绑 + 节点迁移。
- **改绑/解绑前确认**：弹窗列出引用该别名/端口的场景节点（超 8 条截断）；
  解绑后这些节点会变成 `device_alias_unresolved`（L1 warning）。
- 表单改为左置标签（与设备族面板同一视觉语言）。

> 无破坏性更改：仅新增设置项（默认值向后兼容）与面板控件；op 名称/参数未变。

---

## 0.3.0 — 2026-10-20

- **节点包自动注入**：`SerialSend` / `ParallelSend` 的类型、求值器、声明式字段
  （`fields`）全部由本目录 `node_pack.py` 提供；核心不再声明这两个节点。
  发现机制是 `NodePackRegistry` 扫描 `Application/Functions/**/node_pack.py`，
  **不依赖扩展 enable**（节点类型是图可加载性的一部分）。
- **USB 指纹 + 自动重绑**：`identity.py`（`usb_serial` > `vid_pid`；`location` 只诊断）
  + `ext.device.autobind` + 面板 `Auto-detect` + enable 时自动重绑；歧义显式拒绝。

> 无新增破坏性更改（`SerialSend.port` 默认值已在 0.1.x 改为空）。

---

## 0.2.0 — 2026-10-16

- 目录统一到 `Application/Functions/SerialParallelDevice/`（引擎 `Functions` 单树改造）；
  扩展扫描根随之调整（`Application/Functions/**`）。

---

## 0.1.x — 2026-10-11 → 2026-10-12

首个可用版本：

- 监视面板（Serial/Parallel 页、Port 枚举、发送区、事件流、TX/RX/PX 统计）+ `ext.device.*` ops 雏形。
- 非阻塞发送 API：`start` / `stop` / `send` / `write_parallel`；`spd-io` 单线程消费发送队列；
  并口写非零后自动复位。
- **逻辑设备名（`@alias`）闭环**（2026-10-12）：`bind_alias` / `bind_nodes` + 面板别名段；
  `serial_manager.resolve_port()` 在入队前解析；未绑定 → `DeviceUnresolved`（绝不静默回退）。
  台账文件 `devices.json`（`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 覆盖）。
- **`SerialSend.port` 默认值从 `COM1` 改为空**（破坏性，决策 3）：未配置 → 显式 `error` 日志并跳过，
  绝不"猜一个端口就发"。旧场景若依赖"不填就走 COM1"，升级后会看到 error 并在日志里被跳过。

---

## C. 永不改变的兼容红线

这些是**持久化契约**，任何版本都不会改（改动等于让用户场景作废）：

| # | 契约 |
|---|---|
| 1 | 节点类型名 `SerialSend` / `ParallelSend`；引脚名 `exec_in / exec_out / Value / Address` |
| 2 | props 键 `port / baud_rate / format / prefix / suffix / address / mode / value` |
| 3 | `@name` 引用语法；未绑定 → **显式报错**，绝不静默回退默认端口 |
| 4 | 台账路径 `%APPDATA%/FlyVibingEngine/devices.json`、格式 `{version:1, devices:{...}}`、`*_DEVICES_FILE` 覆盖 |
| 5 | 9 个 `ext.device.*` op 的名称与参数（`status / list_ports / watch / send / monitor_snapshot / write_parallel / bind_alias / autobind / bind_nodes`） |
| 6 | 面板按钮与 agent op **同一实现**（`_guard` → `_op_*`） |
| 7 | `ParallelSend` 的 uint8 语义：**1–255**，`0` 保留给自动复位 |
| 8 | 扩展不 import 编辑器层；场景读写只走 `ctx.graph`；不碰宿主全局 imgui 状态 |

---

## D. 我们负责的内容（解耦后的归属）

| 能力 | 位置 | 备注 |
|---|---|---|
| 节点类型 + 求值器 + 声明式字段 | `node_pack.py` | 核心不再声明；`NodePackRegistry` 自动发现 |
| 节点语义正文 | `node_pack.py` 的 `props_text` | 主线删除 `graph_rules` 表格后，这是 `graph.types` 的正文来源 |
| `@alias` 台账 | `device_registry.py` | 过渡期委托核心；核心删除后接管 |
| USB 指纹 / 自动重绑 | `identity.py` + `extension.py::_op_autobind` | — |
| 串口 / 并口 I/O + 线程 + 租约 | `api.py` / `state.py` / `io_thread.py` / `tasks.py` | 单线程 `spd-io` |
| 复位调度 / 脉冲宽度 | `parallel_manager.py` + `api.set_reset_delay` | 设备级全局设置 |
| 端口枚举 / 事件环缓 / watch | `monitor.py` | 环缓 500 条 |
| 面板 + Device Manager + 9 ops | `extension.py` | 同一实现 |
| 引擎生命周期钩子 | `extension.py::on_engine_start/on_engine_stop` | 待主线调用（导出模式入口未定） |

**仍由主线提供（我们不改，只提需求）**：
端口下拉的通用控件 kind（`serial_port` → `choices_source`）、引脚可见性规则
（`visible_pins.py`）、卡片高度 `WIDGET_TYPES`、离线校验器的 `@alias` 检查、
`graph_rules` 表格、`Runtime` 侧的调度点。详见 `Doc/REPLY_TO_MAINLINE_2026-11-10.md` §三/§四。

---

## E. 迁移检查单（从 0.5.0 升到 0.6.0）

```powershell
# 1) 还有没有直接依赖核心台账的代码？（应为空）
Get-ChildItem Application,Test -Recurse -File -Include *.py |
  Select-String -Pattern 'Application\.Core\.DeviceRegistry'

# 2) 扩展/脚本是否检查了 send/write_parallel 的返回值？
#    （忽略返回值 = 发送被丢弃时你收不到任何信号）
Select-String -Path <你的文件> -Pattern 'spd_send|write_parallel|\.send\('

# 3) 有没有在非 string 格式上使用 prefix/suffix？（会 ValueError）
#    有没有把 "\n" 写进 prefix/suffix？（会 ValueError）
Select-String -Path <你的场景或代码> -Pattern 'prefix|suffix'

# 4) 台账后端确认（过渡期应为 core；主线删文件后应为 extension）
.\.venv-py314t\Scripts\engine-editor-cli.exe call ext.device.status
```

```python
# 推荐写法：先拿租约，再发送，并检查结果
from Application.Functions.SerialParallelDevice import (
    DeviceNotReady, DeviceUnresolved, io_owner, send, set_reset_delay,
    start, stop, write_parallel,
)

start("editor")                          # 幂等；PIE 期间会与 runtime 租约共存（交权语义）
try:
    set_reset_delay(10)                  # 10 ms 脉冲（默认 5）
    ok = send("@SSSEP-Stimulator", 115200, b"40,14\n")
    if not ok:
        ...                              # I/O 未就绪 —— 显式处理，不要静默
    write_parallel(0x3FF8, 1, "byte", strict=True)   # uint8，非零触发
finally:
    stop("editor")                       # 只释放自己的租约
```

---

## F. 节点图构建指导（改 0.6.0 后务必看）

### F1. 先发现，再建图（权威来源）

```powershell
engine-editor-cli call graph.types owner=device      # 类型 / 引脚 / props_text / fields
engine-editor-cli call graph.add --json "@args.json"  # 建节点（不要求先连线）
```

- **不要**把 `graph_rules._NODE_GRAPH_RULES`（场景 `_rules` 字段）当权威：它随引擎版本变化，
  且主线即将删除其中的 IO 表格。权威是 `graph.types`。
- 场景里持久化的是：`node_type`、`pin_ids`、`props`。`props` 键名见 §C 红线。

### F2. `SerialSend`

| 引脚 | 方向 | 类型 | 说明 |
|---|---|---|---|
| `exec_in` | in | exec | — |
| `exec_out` | out | exec | — |
| `Value` | in | variant | 要发送的值（未连接 = 0） |

| prop | 类型 | 语义 |
|---|---|---|
| `port` | string | `COM14` 或 `@SSSEP-Stimulator`；**空 = 显式 error 并跳过** |
| `baud_rate` | int | 默认 9600（面板另记自己的默认值） |
| `format` | enum | `bytes` = float32 LE **4 字节**；`string` = UTF-8 文本行 |
| `prefix` | string | 仅 `string`；行头，如 `40,` → `40,14` |
| `suffix` | string | 仅 `string`；行尾（换行由 `encode` 统一追加） |

构建要点：

1. **一次调用 = 一行**。`prefix`/`suffix` 里写 `\n` / `\r` 会直接 `ValueError`。
2. **行协议值用最短十进制**：`prefix="40,"` + `Value=14` → `40,14\n`（不是 `40,14.0\n`）。
   没有 prefix/suffix 时保持旧行为（`14.0\n`）。
3. **`format=bytes` 是 float32 4 字节**，不是"一个字节"。设备要单字节 → 用 `ParallelSend`
   或 `format=string`。
4. **`@alias` 未绑定 → error 并跳过**（不会回退到任何默认口）。换机器后先
   `ext.device.autobind` 或面板重绑。
5. 干跑日志格式（agent 解析契约）：`port=..., baud=..., fmt=..., line='40,14\n', val=14`
   —— **`val=` 永远在最后**，解析时按 `val=` 截取。

### F3. `ParallelSend`

| 引脚 | 方向 | 类型 | 说明 |
|---|---|---|---|
| `exec_in` / `exec_out` | — | exec | — |
| `Address` | in | int | **当前始终被卡片控件隐藏**（见 F3-3） |
| `Value` | in | variant | `mode=pin` 时才显示；`manual` 下读 props |

| prop | 类型 | 语义 |
|---|---|---|
| `mode` | enum | `manual`（读 props）/ `pin`（读引脚） |
| `address` | int | `0x3FF8` LPT1 / `0x3FF0` LPT2 / `0x3FE8` LPT3 |
| `value` | int | **1–255**；自动 clamp；`0` 保留给自动复位 |

构建要点：

1. **写非零即触发**，I/O 线程会在脉冲宽度后自动写 `0` 复位（默认 5 ms，
   `set_reset_delay` / 面板 Pulse 全局可调）。**不要**自己再发一次 `0`。
2. **value 会被 clamp 到 1–255**：传 `0` 得到 `1`，传 `300` 得到 `255`。
   需要"复位"请等自动复位，或直接用 `write_parallel` 之外的路径 —— 不要指望节点发 0。
3. **`Address` 引脚始终不在画布上显示**（核心 `visible_pins.py` 的 `@rule("ParallelSend")` 把它
   恒定隐藏，地址始终由卡片控件读 `address` prop）。因此 `mode=pin` 的**实际语义**是
   「`Value` 可由上游引脚驱动，地址仍取 props」——求值器虽然会尝试读 `Address` 引脚，
   但该引脚不可连线，永远回落到 props。
   > 若将来要真支持“地址也可 pin 驱动”，需主线把引脚规则改成声明式（`pin_visibility`）后
   > 我们再放开。**在那之前不要依赖 Address 引脚。**
4. **触发端口的写入宽度**：EEG 放大器（如 g.HIamp）把并行数据线记成
   `写值 << 16`（combine bits 16..23）。所以 `value=3` 在记录里是 `0x00030000`。
   这是**预期**，不是错位。
5. `mode=manual` 下**不要**把 `Value` 连线上：该引脚被隐藏，连线不生效。
   需要按条件发不同触发码时用 `mode=pin`。

### F4. 时序与分辨率（节点图层面）

- 节点求值跟**渲染帧**走（不是独立时钟）。~100 fps 时 25 ms 周期 = 2.5 帧
  → 单拍在 2/3 帧间交替，偶发跳过格点（实测 40 Hz 下约 3.5% 丢脉冲；20 Hz 不受影响）。
  相位敏感的范式请把周期设成帧间隔的整数倍，或改由 MCU 自走时钟。
- 复位是**异步且可叠加**的：每次非零写入都会在自己的 deadline（`now + pulse`）排一个复位，
  不复用也不取消先前的。所以高密度脉冲下，**先到的复位会把后写的高电平提前拉回 0**
  ——实际脉冲宽度 = `min(自己的宽度, 距前一个 deadline 的剩余时间)`。
  需要稳定脉宽时：把脉冲宽度设得比写入间隔小，或降低写入频率。不要依赖 5 ms 默认值。

### F5. 在 `node_pack` 风格的扩展代码里

- `node_pack.py` **禁止** import Editor / imgui：导出成品运行期也会加载它。
- 求值器只做「读 props → 编码 → 入队」，**不要在求值器里做阻塞 I/O 或开端口**。
- 需要"扫描端口"这类交互，用面板/op（`ext.device.list_ports`），不要塞进节点卡片。
- 新增节点请用 `ext.device.<Name>` 前缀，避免与核心类型冲突（同 owner 冲突会抛 `NodePackError`）。

---

## G. 迁移路线（预告，不含代码）

主线接 `Doc/REPLY_TO_MAINLINE_2026-11-10.md` 后按 8 步执行，扩展侧同步提供替换件：

| 步 | 主线 | 扩展侧 | 对开发者的影响 |
|---|---|---|---|
| 1 | 生命周期调度上线（先 PIE） | 无（钩子已就位） | `extension.disable id=device` 后 PIE 不再拉起 `spd-io` |
| 2 | 通用 `pin_visibility` + `choices_source` 契约 | 改 `fields` / 提供 `ports()` 回调 | 面板端口下拉形态可能变，**场景数据不变** |
| 3 | 工具仓 checker 贡献点 | 提供 `@alias` 解析实现 | 离线校验提示改由扩展提供 |
| 4 | 删核心 `serial_port` 分支 / `@rule("ParallelSend")` / `WIDGET_TYPES` 两项 | 已切换到声明式 | 行为等价，用户无感 |
| 5 | 删 `graph_rules` IO 表格（并处理导出 `_rules`） | 无（`props_text` 已完整） | agent 必须改读 `graph.types` |
| 6 | 删 `Core/DeviceRegistry.py` | `backend()` 自动切 `"extension"` | **`from Application.Core.DeviceRegistry import ...` 将 ImportError** |
| 7 | 删 `GameRuntime` / `PlayerBootstrap` 直接 import | 无 | 导出模式按主线裁决（保留直接调用 / 加载扩展入口） |
| 8 | 注释与通用测试去具体化 | 无 | — |

> 第 6 步的隐藏坑（写给主线，也写给开发者）：`widgets/core.py` 对核心台账的 import 有
> `try/except`，先删文件**不会报错**，只会静默把端口下拉降级为"只有 COM 口、没有 `@alias`"。

---

## H. 本轮验证基线（0.6.0）

| 用例 | 结果 |
|---|---|
| `Test/Application/Functions/test_device_alias.py` | 41/41 |
| `Test/Application/Functions/test_device_autobind.py` | 27/27 |
| `Test/Application/Functions/test_serial_parallel_device.py` | 79/79 |
| `Test/Application/Functions/test_spd_monitor.py` | 14/14 |
| `Test/Application/NodeGraph/test_node_pack.py` | 26/26 |
| `Test/Application/Extensions/test_extension_manager.py` | 36/36 |
| `review_extension.py Application/Functions/SerialParallelDevice` | 20 pass / 0 warn / 0 fail |

接管路径（模拟核心台账不可用）：

```powershell
$env:MGE_DEVICES_FILE = Join-Path $env:TEMP 'spd_reg_fallback.json'
.venv-py314t\Scripts\python.exe -c "import sys; sys.modules['Application.Core.DeviceRegistry']=None; `
 from Application.Functions.SerialParallelDevice import device_registry as r; `
 r.bind('lab', port='COM5', baud=9600); print(r.backend(), r.describe('lab')); print(r.unbind('lab'))"
# extension  @lab -> COM5 @9600  /  True
```
