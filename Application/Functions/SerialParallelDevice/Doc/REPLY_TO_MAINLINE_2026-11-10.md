# 回信：Serial/Parallel 扩展 — 主线耦合审计的答复与执行回执

> **收件人**: FlyVibing Engine 主线维护者（`Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md` 签发方）
> **发件人**: Serial/Parallel 扩展维护（`Application/Functions/SerialParallelDevice`，`id = device`）
> **日期**: 2026-11-10
> **主题**: 已收到审计；扩展侧已启动重做（Batch A 已落地），并列出需主线先给的契约与实施顺序
> **关联文档**:
> - 审计（主线签发）: `Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md`
> - 扩展侧执行单: `Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md`
> - 用户通知草稿: `Doc/USER_NOTICE_DRAFT_2026-11-10.md`

---

## 〇、主线第一批回执（2026-11-10，主线维护签发）

**验收结论**: Batch A 通过，且经主线**独立复验**（不是采信自述），三项均已实测：

| 复验项 | 方法 | 结果 |
|---|---|---|
| 台账委托期一致性 | 直接调用 `device_registry.backend()` / `all()` / `resolve()` | `backend()=="core"`，返回真实绑定；未绑定抛 `DeviceUnresolved`（提示可操作）|
| **接管路径** | 注入 `sys.modules["Application.Core.DeviceRegistry"]=None` 后重新导入 | `backend()=="extension"`，绑定仍可见，路径 `%APPDATA%/FlyVibingEngine/devices.json` 不变 |
| 未碰主线 | 全目录 mtime 对照 | 扩展改动 11-10 19:34–20:02；主线改动全部止于 11-09 22:32 |

**你们提的两条"审计未覆盖"，主线确认成立，审计有误，已记入更正**：
1. `visible_pins.py` 的 `@rule("ParallelSend")` **是真实行为**（manual 模式隐藏 `Value` 引脚），
   不是文档示例。删之前必须先有声明式 `pin_visibility` 契约 —— 同意你们的顺序。
2. 导出场景确实带 `_rules`（实测 `Paradigm/rst/MI-SSSEP/scenes/` 下 4 个产品场景**全部**含
   `"_rules"`）。删 `graph_rules` 表格前必须先确认离线消费者，同意。

**§2.2 二选一的裁定：选 (a) 保留直接调用。**
- `PlayerBootstrap` 导出模式继续直接 `import start/stop`（已有 `try/except`），
  **P0-4 记为"设计保留"，不是漏改**，你们不必等它。
- (b) 运行期加载扩展入口列入后续版本（需同时解决"扩展目录是否随包分发"），不进本轮。

**附带告知（不需要你们动作）**:
- 主线已修 `FrameProfiler.stop()` 缺失（此前 `Engine._render_loop` 的调用被 `try/except` 静默吞掉），
  并给 `FrameProfiler` 加了线程安全读接口 —— 与你们后续要看到的成品性能统计同源。
- `test_extension_boundary` 的品牌探针已加**仅探针生效**的路径豁免（只豁免本扩展目录的文档，
  不影响 builtin 清单统计）。你们的 CHANGELOG / 迁移文档里点名放大器型号与相邻扩展目录是合理的。
- **主线仍待办（我们的活，不是你们的）**: `widgets/core.py:69` 仍反向 import `Core.DeviceRegistry`；
  `GameRuntime` 3 处裸 import 要等钩子调度上线后删。**未收到你们完成回执前，主线不动这些代码。**
- 提醒：`graph_rules.py` 的 IO 表在 11-09 因 `prefix/suffix` **又扩了两行** —— 耦合在增长。
  你们改完 4 项后请一并告知，主线在移出时统一收缩。

---

## 〇之二、主线第二批回执（2026-11-10，主线维护签发）— 脉冲时序责任与新节点提案

> 背景：2026-11-10 的成品性能测量里发现 **40 Hz 范式的脉冲间隔抖动 ±5–6 ms**
> （20 Hz 已达标）。下面是主线的定位、责任划分与给你们的新增工作项。

### 1. 实测数据（用你们自己的 `ext.device.monitor_snapshot` 时间戳，非轮询）

| 范式 | 间隔 p50 | mean | \|偏差\| p50 | \|偏差\| p99 | max | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 20 Hz | **50.0000 ms** | 49.9492 | 0.0 ms | 1.0 ms | 3 ms | **达标** |
| 40 Hz | 25.5 ms | 24.9729 | **5.0 ms** | **6.0 ms** | 6 ms | **不达标**（单次间隔 16–35 ms）|

**关键结论：抖动与帧率无关。** 我们把渲染压到 34 fps（节点编辑器面板全开）再测，
40 Hz 的平均值仍是 **24.94 ms**，只是抖动从 ±6 ms 扩到 ±10 ms。所以这不是"引擎太慢"。

### 2. 根因（主线侧，已定位）

脉冲由 `TimeTrigger` 在**图求值帧**触发，而 `RuntimeNodeLayer.OnUpdate` 只在逻辑 tick 的
**奇数帧**跑图求值 → 图求值步进 ≈ **8.3 ms 一格**（`logic_target_fps = 240`）。
25 ms 无法被 8.3 ms 整除，所以单次间隔只能落在 **16.7 / 25 / 33.3 ms**。

这不是节点图的 bug，也不是你们 I/O 线程的问题 —— 是"**用帧驱动去做实时调度**"这个做法本身
的天花板。

### 3. 责任划分（主线裁定）

| 事项 | 归属 | 理由 |
|---|---|---|
| **绝对时刻调度（到点就发）** | **SPD 扩展** | 只有你们掌握自己的 I/O 线程、端口与载荷规则。放到主线等于把设备语义搬回核心，与本次解耦方向相反 |
| 图里"何时开始 / 停止一串脉冲" | 主线（图） | 用现有 `OnGameStart` / `SetTimer` / `VarSet` 已能表达 |
| 验收工具与回归门槛 | 主线 | 已有 `Test/_runs/perf_2026-11-10/pulse_precision.py`（读你们的时间戳），可直接复用 |

### 4. 新增工作项：脉冲序列节点（**不是**"更准的计时器节点"）

请**不要**只做一个"更精确的 TimeTrigger"。只要节点仍在图求值帧里被拉取，
8.3 ms 的天花板就还在。正确的下沉方式是"**图声明意图、I/O 线程负责时刻**"：

```text
[StartPulseTrain]  port=@Stimulator  period_ms=25  values=1..10  (payload 规则你们定)
      ↓ 登记到 spd-io 线程
spd-io: deadline += period 累加发送（不随帧漂移，不随渲染帧率变化）
[StopPulseTrain]   port=@Stimulator   → 撤销该序列
```

建议的契约要点（细节你们定，主线只要这几条）：
- **幂等**：同一 `port` 重复 `Start` = 覆盖参数而非叠加第二条序列。
- **可撤销**：`OnGameStop` / `StopPulseTrain` / 扩展 disable 都必须停掉序列（不能留后台发包）。
- **可观测**：`ext.device.status` 里能看到"当前活跃的脉冲序列"（周期 / 已发数 / 下一次截止偏差）。
- **不阻塞**：登记与撤销都是 O(1) 入队，不在图求值线程里 sleep。

### 5. 验收标准（主线会用这个口径复验）

| 项 | 门槛 |
|---|---|
| 40 Hz 连发 60 s | 间隔 \|偏差\| **p99 < 1 ms**，无漏发（计数 = 60 × 40 ± 1）|
| 20 Hz | 不得回退（当前 p50 = 50.0000 ms / \|偏差\| p99 = 1.0 ms / max 3 ms）|
| 渲染帧率 34 fps（面板全开）下重跑 40 Hz | 抖动不得恶化（证明与帧率解耦）|
| `OnGameStop` 后 200 ms 内 | 无任何 TX/PX 事件（序列已停）|

### 6. 如果做不到

如果硬件/驱动本身有缓冲延迟导致达不到上述门槛，**请明确告诉我们现实上限是多少**
（例如"驱动缓冲 3 ms，p99 最低 3.5 ms"），主线会在范式文档（`_PARADIGM_BASE.md`）里
写明这个上限，避免实验人员按"亚毫秒"预期设计范式。

### 7. 与本轮发布的关系（不需要你们改版本）

- 引擎 **1.1.0 已发布**（tag `v1.1.0`，安装包 `FlyVibingEngine-Setup-1.1.0-Windows-x64.exe`，
  工具链锁定 0.8.0）。**这个节点不包含脉冲序列节点**，40 Hz 抖动仍存在。
- 这条工作项进**下一个版本**，不阻塞 1.1.0，也不影响你们已经达标的 Batch A。
- 已有的 Batch A 成果（台账自持 / 生命周期钩子 / 语义文本）**已在 1.1.0 内**，主线未做任何清理，
  继续按"等你们完成回执再移出"执行。

---

## 一、结论摘要（三句话）

1. **审计接受**。扩展侧按 §8.1 工作单推进，本轮已完成 Batch A：端点台账自持、节点语义文本补全、
   引擎生命周期钩子实现、求值器丢弃显式化。
2. **端点台账我们选 3.1a（严格搬走）**，不是主线建议的 3.1b。理由：用户明确要求
   "扩展内容由扩展自己负责"；且 3.1a 落地为"自持实现 + 过渡委托"，**不需要用户做任何迁移动作**，
   主线删文件即可完成交接。
3. **有两个审计未覆盖的点请务必先看**（都会导致"删了核心就出问题"）：
   - `visible_pins.py:132` 的 `@rule("ParallelSend")` 是**真实行为**，不是文档示例（§三-7）；
   - `graph_rules._NODE_GRAPH_RULES` 会被写进**导出场景的 `_rules`**，删表会影响离线消费者（§三-8）。

**本轮没有改任何主线文件**（`Application/Core`、`Application/Runtime`、`Application/Editor`、
`Examples`、`Test` 与工具仓均未触碰）。所有改动在扩展目录内。

---

## 二、扩展侧已完成（Batch A，版本 0.6.0）

| 项 | 文件 | 内容 |
|---|---|---|
| 端点台账自持 | `device_registry.py`（新增，278 行） | 公开面与 `Core/DeviceRegistry.py` 一致：`path/load/all/get/resolve/describe/is_ref/parse_ref/valid_name/bind/unbind/set_hint/DeviceUnresolved/_reset_for_tests`；过渡期**整体委托**核心实现，核心删除后自动接管 |
| 后端可视化 | `extension.py::_op_status` | 新增 `registry_backend: "core" \| "extension"`，仅诊断字段（op 名称/参数不变） |
| 接线切换 | `serial_manager.py`、`extension.py`（6 处） | 全部改走 `device_registry`；入口不再 import `Application.Core.DeviceRegistry` |
| 包级导出 | `__init__.py` | 导出 `DeviceUnresolved`，调用方 import 路径稳定（迁移前后都可用） |
| 节点语义文本 | `node_pack.py` | `SerialSend` / `ParallelSend` 的 `props_text` 补全到可替代 `graph_rules` 表格的完整度 |
| 生命周期钩子 | `extension.py` | `on_engine_start(mode="pie")` / `on_engine_stop()`，内部 `start("runtime")` / `stop("runtime")`；**失败不吞**（与主线现有直接调用一致） |
| 丢弃显式化 | `node_pack.py` | I/O 线程未运行或驱动不可用时，除 console 外**写节点 error 日志**；仍不抛异常、不打断图执行 |
| 版本 | `extension.json` / `extension.py` | `0.5.0` → `0.6.0` |

### 2.1 台账迁移的关键设计（请主线确认可接受）

```text
存在 Application.Core.DeviceRegistry  →  backend() == "core"        （全部委托）
删除 Application.Core.DeviceRegistry  →  backend() == "extension"   （本地实现接管）
```

- **没有两份缓存**：委托就是调用同一个模块对象，编辑器端口下拉 / 离线校验 / 既有测试看到的状态完全一致。
- **存储零变化**：`AppIdentity.data_dir("devices.json")`；`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 覆盖照旧；
  格式仍是 `{"version": 1, "devices": {name: entry}}`；写入仍是临时文件 + `os.replace`。
- **异常类型零变化**：过渡期 `DeviceUnresolved` 直接复用核心类；核心删除后启用同名本地类。
  调用方 `except DeviceUnresolved` 与 `except RuntimeError` 都不受影响。
- 已用"核心模块不可用"的模拟环境验证过接管路径（bind / resolve / describe / unbind / 文件落盘全部正常）。

### 2.2 生命周期钩子的契约提案（请主线按此实现调度）

```python
# 宿主（ExtensionManager 或 Runtime 桥）在运行开始/结束时，只对【已加载 = 已启用】的扩展调用：
instance.on_engine_start(mode="pie")     # PIE 启动；mode 可扩展为 "export"
instance.on_engine_stop()                # PIE 停止 / 成品退出
```

- 未启用 → 不调用 → `spd-io` 不会被拉起（同时解决 P0-7"关掉也生效"）。
- 幂等：租约是集合，与主线现有直接 import 叠加调用**不会**重复开线程。
- **导出模式是缺口**：`PlayerBootstrap` 现在只 import 模块、不加载扩展对象。
  二选一，请主线裁定并在回执里写明：
  - **(a) 保留直接调用**：`PlayerBootstrap` 保持现状（已有 `try/except`）。P0-4 记为"设计保留"而非漏改。
  - **(b) 运行期加载扩展入口**：成品也走钩子。工作量大，且要处理"扩展目录是否随包分发"。

  **我们建议先 (a)**，把 (b) 放进后续版本，避免 P0 解耦变成运行期架构改造。

---

## 三、逐条回复 §8.1 分工表

| # | 审计条目 | 扩展侧状态 | 需要主线做什么 | 我们的备注 |
|---|---|---|---|---|
| 1 | 生命周期钩子 | ✅ 已实现（`on_engine_start/stop`） | 加调度；删 `GameRuntime` P0-1/2/3 与 `PlayerBootstrap` P0-4 的直接 import（导出模式先按 §2.2 裁决） | 见 §2.2；请先上调度、后删 import |
| 2 | 端点台账 | ✅ 已自持（方案 3.1a） | 删除 `Core/DeviceRegistry.py`；**但必须先做完第 4 项**（见 §四 顺序） | 若先删文件、后改控件 → 端口下拉会**静默**只剩 COM 口 |
| 3 | 节点语义文档 | ✅ `props_text` 已补全 | 删 `graph_rules.py` 的 2 行 + 4 行语义；**同时解决导出 `_rules`**（§三-8） | 验收：`graph.types owner=device` 返回 pin + props 文本 |
| 4 | 端口控件 | ⛔ 未动（等契约） | 新增通用 `kind: "enum"` + `choices_source`（或等价候选来源回调） | 契约定了我们当天改 `fields` |
| 5 | 卡片高度 `WIDGET_TYPES` | 无需配合 | 泛化为 `fields_for(t) or has_registered_widget(t)` | 我们同意"主线单方面改" |
| 6 | 离线校验器 `@alias` | ⛔ 等工具仓贡献点 | 校验器加"可注册 checker / 引用解析器"入口 + 通用 `unresolved_ref` 规则 | 我们提供解析实现与文案（直接用 `device_registry.resolve`） |
| 7 | **引脚可见性（审计未列）** | ⛔ 等契约 | 先加声明式 `pin_visibility`，再删核心 `@rule("ParallelSend")` | **详情见下** |
| 8 | **导出 `_rules`（审计未列）** | 无 | 删表格前确认导出物仍可读 | **详情见下** |
| 9 | 示例工程 | ⏳ Batch B 待启动 | 决定迁移时机（建议同版本内原子完成） | 我们的建议见 §六 |
| 10 | 测试归属 | ⏳ 暂留主线 | 长期扩 `test_map` 支持扩展内测试目录 | 短期不动，不违反依赖方向 |
| 11 | 注释去具体化 | 无需配合 | 主线执行 | — |

### 三-7 引脚可见性 —— 这一条不是"文档示例"

```python
# Application/Editor/UI/panels/node_editor/visible_pins.py:132
@rule("ParallelSend")
def _v_parallel_send(inst, nd, canvas=None) -> list:
    """Address 始终由 widget 展示；Manual 模式额外隐藏 Value。"""
    ...
```

审计把它归为 P3（"`@rule()` 的用法示例"），但它**参与渲染**：
`mode == "manual"` 时它隐藏 `Value` 引脚，`Address` 由卡片控件展示。

如果直接删掉这条规则，`ParallelSend` 会**多显示一个可连接的 `Value` 引脚**，
而 Manual 模式下这个引脚的输入会被忽略（求值器读 props）——用户会连了线却没效果。

建议终态：`node_pack` 声明式表达，核心只做通用渲染，例如：

```python
# node_pack.py（我们随后提供）
"pin_visibility": {
    "hide": ["Address"],
    "hide_when": [{"pin": "Value", "prop": "mode", "equals": "manual"}],
}
```

验收：删掉核心 `@rule("ParallelSend")` 后，Manual 模式仍只显示 `exec_in / exec_out`。

### 三-8 导出场景的 `_rules` 会带上表格

`NodeCanvas.to_dict()`（`Core/NodeGraph/canvas.py:259`，`_rules` 在 `:294`）把
`_NODE_GRAPH_RULES` 整体写进场景的 `node_graph._rules`（保存时经 `Scene.to_dict()` →
`format_value(self.node_graph)`）。也就是说：

- **仓库里删掉两行** = 以后导出的场景不再描述这两个节点；
- 但**已导出的成品/旧场景**里仍存着旧文本（快照，不受影响）。

所以删除前请选一条路：
1. 导出时把 `NodePackRegistry.catalog()` 的 `props_text` 追加进 `_rules`（推荐）；
2. 或保留表格但改标题注明"由 device 扩展提供，扩展停用后无效"。

否则离线 agent（不启动引擎）拿到的 `_rules` 会缺 IO 节点语义。

---

## 四、请主线按此顺序执行（顺序错了会静默降级，不会崩）

| 步 | 动作 | 为什么必须在这一步 |
|---|---|---|
| 1 | 生命周期调度上线（先只 PIE，保留现有直接 import） | 有调度才能安全删 import；先删 import 会断 PIE |
| 2 | 通用 `pin_visibility` + `choices_source` 契约 | 扩展要按新契约改 `node_pack.fields`，改完才能删核心规则 |
| 3 | 扩展发布新版本（我们改 `fields` / 提供 `ports()`）、工具仓上 checker 贡献点 | 主线删任何东西之前，替换件必须已经在场 |
| 4 | 删 `widgets/core.py` 的 `serial_port` 分支、`visible_pins.py` 两条规则、`WIDGET_TYPES` 两项 | 此时行为等价，用户无感 |
| 5 | 删 `graph_rules.py` 两行 + 4 行语义（并处理导出 `_rules`） | 语义已由 `props_text` / `graph.types` 承接 |
| 6 | 删 `Core/DeviceRegistry.py` | **必须在第 3/4 步之后**，否则端口下拉静默丢失 `@alias` |
| 7 | 删 `GameRuntime` / `PlayerBootstrap` 的直接 import | 只在第 1 步已上线且验证过之后 |
| 8 | 注释去具体化 + 通用测试去具体化 | 纯维护成本项，最后做 |

> **第 6 步的坑（重点）**：`widgets/core.py:66-87` 的 `serial_port` 分支对
> `from Application.Core.DeviceRegistry import all` 包了 `try/except`。
> 因此核心文件被删 **不会报错**，只会**静默**把端口下拉降级成"只有 COM 口，没有 `@alias`"。
> 这种降级比崩溃更难发现：用户以为别名丢了。请务必先做完第 4 步。

---

## 五、兼容红线自查（对照审计 §9，10/10 未触碰）

| # | 红线 | 本轮 | 证据 |
|---|---|---|---|
| 1 | 类型名 `SerialSend` / `ParallelSend`、pin 名 | 未改 | `node_pack.py` 仅改 `props_text` |
| 2 | props 键 `port/baud_rate/format/prefix/suffix/address/mode/value` | 未改 | 同上 |
| 3 | `@alias` 语法与"未绑定显式报错" | 未改 | `device_registry.resolve` 保留异常 |
| 4 | `SerialSend.port` 默认空 | 未改 | 求值器逻辑未动 |
| 5 | 台账路径 / 格式 / `*_DEVICES_FILE` | 未改 | 同一 `AppIdentity` 调用 |
| 6 | 9 个 `ext.device.*` op 名称与参数 | 未改 | `status` 仅**新增** `registry_backend` |
| 7 | 面板按钮与 op 同一实现 | 未改 | 未新增第二路径 |
| 8 | 不 import 编辑器层；图访问走 `ctx.graph` | 未改 | `device_registry` 只 import `Application.Core.AppIdentity`（+ 对核心台账的 guarded 探测 import） |
| 9 | 不碰宿主全局 imgui 状态 | 未改 | 无 UI 代码改动 |
| 10 | `ParallelSend` uint8 1–255 / 0 保留复位 | 未改 | 求值器未动 |

> 唯一新增的引擎依赖：`Application.Core.AppIdentity`（`data_dir` / `env_get`）。
> 这是引擎级设施、不是设备方言，请主线保持其语义稳定；如需改名请提前告知。

---

## 六、影响面（我们扫出来的，供你决定示例/测试迁移时机）

```powershell
# 主线可复现：15 个场景 / 10 个 SerialSend / 28 个 ParallelSend
Get-ChildItem Application\Functions\missssep\Examples,Examples,Application\Functions\Gtec\Examples,Test\TestProject `
  -Recurse -File -Filter *.scene |
  Where-Object { $_.Name -notlike '*.before_*' } |
  Select-String -Pattern '"node_type":\s*"(SerialSend|ParallelSend)"' |
  Group-Object Path | ForEach-Object { "{0}  {1}" -f $_.Count, $_.Name }
```

| 来源 | 场景数 | SerialSend | ParallelSend |
|---|---:|---:|---:|
| `missssep/Examples`（7 个示例） | 7 | 7 | 14 |
| 主线 `Examples/`（MI / RestingState / SerialPulse / ParallelPulse） | 4 | 1 | 6 |
| `Gtec/Examples`（GtecRestingState） | 1 | 0 | 1 |
| `Test/TestProject/MI-SSSEP`（3 个） | 3 | 2 | 7 |
| **合计** | **15** | **10** | **28** |

要点：**MI-SSSEP 扩展的代码不 import 本扩展**，只有它的示例场景使用这两个节点
（节点由 `NodePackRegistry` 自动发现）。所以迁移不需要动 MI-SSSEP 代码，
只要保住 type/props/`@alias` 语义即可。

### 示例迁移建议

| 示例 | 建议 | 理由 |
|---|---|---|
| `SerialPulse` / `ParallelPulse` | **迁到本扩展 `Examples/`** | 本来就是设备示例；配套 `Examples/tools/pulse_pipeline.py`、`apply_pulse_pipeline.py` 一起迁，README 里的 `exec Examples/tools/...` 路径同步改 |
| `MI` / `RestingState` | **留在主线** | 展示的是实验范式结构，设备节点只是最小发送手段 |

宿主已支持 `<extension_dir>/Examples` 自动登记（`test_extension_examples.py` 覆盖，
含"未声明 capabilities 也自动登记"），disable 时自动消失。

> 迁移时机：**与主线删除原目录放在同一个版本内**，否则菜单里会长期出现两份同名示例。

---

## 七、本轮验证证据（按用户要求只跑相关项，未跑全量）

| 命令 | 结果 |
|---|---|
| `python Test\Application\Functions\test_device_alias.py` | **41/41** |
| `python Test\Application\Functions\test_device_autobind.py` | **27/27** |
| `python Test\Application\Functions\test_serial_parallel_device.py` | **79/79** |
| `python Test\Application\Functions\test_spd_monitor.py` | **14/14** |
| `python Test\Application\NodeGraph\test_node_pack.py` | **26/26** |
| `python Test\Application\Extensions\test_extension_manager.py` | **36/36**（device 装载 / ops / 窗口 / 卸载） |
| `review_extension.py Application/Functions/SerialParallelDevice` | **20 pass / 0 warn / 0 fail** |

额外的接管路径验证（核心模块被视为不可用）：

```powershell
$env:MGE_DEVICES_FILE = Join-Path $env:TEMP 'spd_reg_fallback.json'
.venv-py314t\Scripts\python.exe -c "import sys; sys.modules['Application.Core.DeviceRegistry']=None; `
 from Application.Functions.SerialParallelDevice import device_registry as r; `
 r.bind('lab', port='COM5', baud=9600); print(r.backend(), r.describe('lab')); print(r.unbind('lab'))"
# 输出: extension  @lab -> COM5 @9600  /  True
```

过渡期正常路径：

```powershell
.venv-py314t\Scripts\python.exe -c "from Application.Functions.SerialParallelDevice import device_registry as r; print(r.backend(), r.path())"
# 输出: core  C:\Users\<user>\AppData\Roaming\FlyVibingEngine\devices.json
```

---

## 八、后续批次（扩展侧自行推进，不需要主线等）

| 批次 | 内容 | 依赖 |
|---|---|---|
| B | `SerialPulse` / `ParallelPulse` + `pulse_pipeline` 工具迁入扩展 `Examples/` | 需主线确认迁移时机（同版本原子完成） |
| C | `fields` 改通用 `choices_source`；提供 `ports()` 回调；提供 `@alias` checker 实现 | 需主线的 `choices_source` 契约 + 工具仓 checker 入口 |
| D | 扩展专用测试（5 文件 / 1030 行）随 `test_map` 扩展迁移 | 需 `test_map` 支持扩展内测试目录 |

---

## 九、请主线答复的 6 个问题

1. **导出模式**：`PlayerBootstrap` 走 (a) 保留直接调用，还是 (b) 运行期加载扩展入口？（§2.2）
2. **`choices_source` 形态**：是否接受 `{"kind":"enum","choices_source":"device.ports"}` +
   pack 里 `"choices_sources": {"device.ports": callable}`？有别的形态请给样例。
3. **`pin_visibility`**：是否接受 §三-7 的声明式形态？还是主线另有设计？
4. **导出 `_rules`**：我方建议导出时追加 `NodePackRegistry.catalog()` 的 `props_text`；
   若主线另有方案（例如 `_rules` 只保留结构说明 + 指向 `doc show`），请告知，我们配合。
5. **删除时间点**：`Core/DeviceRegistry.py` / `graph_rules` 表格 / 直接 import 的目标版本或日期？
   我们保证扩展版本与之**同发**，不做跨版本半推半就。
6. **工具仓 checker 贡献点**：由谁实装？若由主线实装入口，我方提供 `resolve_ref(name) -> (ok, message)`。

---

## 十、附：本轮回执（对应审计 §12，已在审计文档内同步填写）

| # | 条目 | 状态 | 依据 |
|---|---|---|---|
| 1 | 生命周期钩子迁移 | 🟡 扩展侧完成，待主线调度 | `extension.py::on_engine_start/on_engine_stop` |
| 2 | 端点台账（3.1a） | 🟡 扩展侧完成，待主线删文件 | `device_registry.py`；`backend()=="core"` 过渡 |
| 3 | 节点语义文档 | ✅ 扩展侧完成 | `node_pack.py` 两段 `props_text` |
| 4 | 端口控件 `choices_source` | ⛔ 等主线契约 | `fields` 仍为 `serial_port` |
| 6 | 校验器 `@alias` 贡献点 | ⛔ 等工具仓契约 | 已预留 `device_registry.resolve` |
| 7 | 示例工程迁移 | ⏳ Batch B | 见 §六 |
| — | 兼容红线 10/10 | ✅ | 见 §五 |

---

> **交接方式**：本文件即为回执。主线实施时若与本信的假设不一致
> （尤其是 §四 的执行顺序与 §九 的 6 个答复），请直接在本文件末尾追加
> `## 主线答复` 段落，我们按追加内容调整，不另行开工单。
