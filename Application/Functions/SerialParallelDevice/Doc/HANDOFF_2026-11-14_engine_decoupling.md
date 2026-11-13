# 交接：主线解耦完成（2026-11-14）—— 需要 SPD 补的东西

**给**：Serial/Parallel Device 扩展维护者
**来自**：引擎主线
**关联**：`Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md`（本次是它的收尾）、
`Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md`（3.1a / 3.1b 的落地）、
`application/Functions/Gtec/Doc/REPLY_TO_EXT_2026-11-14_o9.md`（O9 同类事故，外部扩展提出的）

---

## 0. 一句话

**功能现在和迁移前完全一致**（台账、下拉、校验、导出、PIE、成品都验证过），
但**实现归属变了**：台账从"核心持有 + 扩展过渡委托"变成"扩展唯一持有 + 核心按声明发现"。
所以你们要做的不是补功能，而是**确认 4 条不变量、改 3 处过期表述、补 1 条 CHANGELOG/版本号**。

主线已经代改的部分，请在你们的下一次提交里"认领"（见 §3）。

---

## 1. 这轮主线到底改了什么

| 类 | 内容 | 结果 |
|---|---|---|
| A | 引擎运行时硬 import 扩展（`GameRuntime.init/run/stop`、`PlayerBootstrap` 收尾、`dry_run` 清理、`op device.save`、`widgets/epoch.py`） | 全部改走接缝 `Application.Core.Extension.OptionalExtensions`。**扩展缺席 = 正常跳过，不再 `ModuleNotFoundError`** |
| B | `Application/Core/DeviceRegistry.py`（183 行，核心为一个扩展写的台账） | **已删除**。实现只在你们 `device_registry.py`；核心只留能力凭据 `Application.Core.DeviceAliases` |
| C | 核心/编辑器"知道扩展节点类型名" | 仍有 44 处 / 7 文件，已登记为**主线待办**（棘轮守卫），**不需要你们动** —— 见 §5 |
| D | 扩展节点语义文档写死在 `Core/NodeGraph/graph_rules.py` | 仍开，同上属主线待办 |

为什么 A 必须改：导出器按**场景实际用到的节点类型**决定带哪些扩展。一个不用
`SerialSend` / `ParallelSend` 的场景（纯采集、纯展示、纯核心）导出的成品里没有
`Application/Functions/SerialParallelDevice/`，此时任何硬 import 都是启动即崩：

```
ModuleNotFoundError: No module named 'Application.Functions.SerialParallelDevice'
[ERROR] Player exited with an unhandled exception
```

一直没暴露是因为我们所有能跑的示例都用 `ParallelSend` 打标，SPD 恰好被带上。

---

## 2. 必须保持的 4 条不变量（这是"功能完备"的全部）

### ① `device_registry.py` 导入即自注册

```python
# 文件末尾（现有代码，勿删）
_Aliases.register("device", sys.modules[__name__])
```

编辑器端口下拉、离线校验器、`SerialSend` 求值器**都读这一个 provider**。
删掉这行 → 别名能力静默消失（编辑器只显示物理端口，校验器报
`device_alias_check_unavailable`）——**不会报错，只会"数据不见了"**。

> 相对的：别让核心重新持有实现。判据是"核心有没有第二个台账缓存"——有就会出现
> "面板刚绑的别名，编辑器看不到"。所以**按包限定名导入**（
> `Application.Functions.SerialParallelDevice.device_registry`）是刻意的：
> 与你们自己的 `from Application.Functions.SerialParallelDevice import device_registry`
> 是**同一个模块对象**、同一份内存缓存。守卫已断言（§4）。

### ② manifest 声明能力（已代填，请保持）

```json
"device_aliases": { "module": "device_registry", "dir": "." }
```

核心**只读这个键**、不认识任何扩展名。它的作用是让"没人 import 扩展"的场合也能找到
台账 —— 离线校验器（`flyvibing_node_editor`）和"用户停用了 SPD"的编辑器，都要能读
`@alias` 校验。旧实现（`Core.DeviceRegistry`）直接读文件，所以一直能用；迁移后必须由
声明补上，否则这两处功能会退化。**这是本轮唯一"必须新增"的东西，已代填。**

### ③ `backend()` 恒为 `"extension"`，`status.registry_backend` 保留

过渡期结束了，`"core"` 分支永远不会出现。字段保留（诊断向后兼容），值固定。
若你们想再补一句 `"provider": "device"` 也可以：`DeviceAliases.status()` 已经能给出
`{available, provider, aliases}`，直接塞进 `ext.device.status` 更便于排查。

### ④ 包级 `start` / `stop` / `stop_all` / `io_owner` 必须存在且语义不变

接缝就是这么调你们的：

```python
call("SerialParallelDevice", "start", owner)     # required=True → 真实故障会抛
call("SerialParallelDevice", "stop", owner)      # 关闭路径：失败只告警
call("SerialParallelDevice", "stop_all")
```

语义分工（主线已锁定，别改）：**"扩展存在但起不来" = 硬错误**（I/O 起不来还继续跑实验
= 静默丢刺激）；**"扩展根本不存在" = 正常跳过**。所以请保持 `start()` 失败时抛错，
不要为了"更宽容"改成吞异常。

---

## 3. 主线已代改、请你们认领的四处

| 文件 | 改动 | 备注 |
|---|---|---|
| `device_registry.py` | 删除 `_legacy_module()` / `_delegate()` / `backend()=="core"` 过渡层；新增 `names()`；末尾自注册；异常类改为本地定义（不再复用核心类） | 与核心模块同时删除。公开面（`path/load/all/get/resolve/describe/is_ref/parse_ref/valid_name/bind/unbind/set_hint/DeviceUnresolved/_reset_for_tests`）**完全不变** |
| `extension.json` | 加 `device_aliases`；`description` 去掉 "transitional delegation to core" | 描述会在设置页/菜单 tooltip 显示，是用户可见文案 |
| `__init__.py` / `serial_manager.py` | 模块文档里的"过渡期委托核心"改为"自持 + 自注册" | 纯注释 |
| `extension.py` | 生命周期钩子的注释改为事实：**引擎目前不调用它们**，启动/收尾走接缝 | 纯注释（行为未变） |

`extension.py` 的 6 处 `import ...device_registry as reg` 未动（它们本来就对）。

---

## 4. 验收（复制粘贴即可）

```powershell
cd C:\WorkSpace\FLY\FlyVibing-Engine

# ① 你们的测试面（迁移后全绿）
.\.venv-py314t\Scripts\python.exe -Xgil=0 Utils\Dev\test_runner.py --only test_serial_parallel_device
.\.venv-py314t\Scripts\python.exe -Xgil=0 Utils\Dev\test_runner.py --only test_spd_monitor
.\.venv-py314t\Scripts\python.exe -Xgil=0 Utils\Dev\test_runner.py --only test_device_alias
.\.venv-py314t\Scripts\python.exe -Xgil=0 Utils\Dev\test_runner.py --only test_device_autobind

# ② 能力契约（含"发现到的 provider 与正常 import 是同一模块"）
.\.venv-py314t\Scripts\python.exe -Xgil=0 Utils\Dev\test_runner.py --only test_extension_coupling_inventory

# ③ 人工确认：不 import 扩展也能读到台账（离线校验器/未启用编辑器形态）
.\.venv-py314t\Scripts\python.exe -Xgil=0 -c "from Application.Core import DeviceAliases as A; print(A.status())"

# ④ 静态审查（M7/M8 必过）
python ..\..\..\FlyVibing-User-And-Developer-Utils\packages\extension-kit\review_extension.py .
```

当前实测：① 全绿（SPD 相关 4 个套件）、② 13/13、③ `available=True provider=device`、
④ 21 pass / 0 fail。

---

## 5. 不用你们动、但你们会听到的两件事

**① C 类余债（主线待办）**：核心/编辑器里还有 44 处"按扩展节点类型名写死"的代码。
其中**属于 SPD 的只有 3 处**：

| 位置 | 内容 |
|---|---|
| `Editor/UI/panels/node_editor/visible_pins.py` | `ParallelSend` 在 manual 模式隐藏 `Value` 引脚 |
| `Editor/UI/panels/node_editor/group_layout.py` ×2 | 自动分组时给 Serial/Parallel 节点留位置 |

其余 41 处属于设备池 / SigGen / Epoch / BCI。**还清它们需要先做"pack 扩展点"**
（`pin_visibility` / `constraints` / `widget` / `docs`），那是主线设计工作，已进待办。
等扩展点落地后，你们要做的是把上面 3 条**搬进 `node_pack.py` 的声明**，届时会给迁移样例。

**② `on_engine_start` / `on_engine_stop` 目前是死代码**：引擎不会调用（启动/收尾走
包级函数）。留着无害，但**不要把唯一逻辑放进去** —— 现在放了就不执行。将来若做
"扩展生命周期调度"，主线会先出协议再启用。

---

## 6. 请你们补的（本轮真正属于你们的活，约 15 分钟）

1. **版本号 + CHANGELOG**：`0.6.0 → 0.7.0`，条目建议：
   > `0.7.0` — `@alias` 台账实现完全归属本扩展。核心 `Application/Core/DeviceRegistry.py`
   > 已删除；新增 `Application.Core.DeviceAliases` 能力凭据 + manifest
   > `device_aliases.module` 声明（离线校验器/未启用扩展时也能读台账）。
   > **对调用方无破坏**：`ext.device.*` op 名/参数不变，`status.registry_backend` 恒为
   > `extension`；只有 `from Application.Core.DeviceRegistry import ...` 会 ImportError。
2. **`Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md` 的完成度表**：把"端点台账（3.1a）"
   从 🟡 改为 ☑（主线已删文件），并在表头注明"2026-11-14 主线完成迁移，见本文件"。
3. **`extension.json` 的 `version`**（我没动，留给你们与 CHANGELOG 一起改）。

---

## 7. 一个需要你们答复的判断

旧的 `Core.DeviceRegistry` 有个隐含性质：**只要机器上有 `devices.json`，谁都能读到**
（与扩展启停无关）。现在通过"声明发现"保留了这一点。

但反过来的问题来了：**用户停用 SPD 时，别名台账还应不应该被发现？**

- 现在：**是**（与迁移前一致；校验器/编辑器都能读）。
- 另一种口径：只在扩展启用时提供 —— 好处是"停用即彻底消失"，坏处是"停用期间打开
  场景会被报一堆 `device_alias_check_unavailable`"。

我们选了前者（保持一致），但如果你们认为该跟启用状态绑定，告诉我们，主线改成
"发现前先查 `ExtensionManager.enabled`"即可 —— 一行判断，但要统一口径。
