# 回信：主线解耦收尾（2026-11-14）—— 认领与答复

> **收件人**: FlyVibing Engine 主线维护者
> **发件人**: Serial/Parallel 扩展维护（`Application/Functions/SerialParallelDevice`，`id = device`）
> **日期**: 2026-11-14
> **对应来件**: `Doc/HANDOFF_2026-11-14_engine_decoupling.md`
> **关联**: `Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md`（§12 已更新）、
> `CHANGELOG.md`（0.7.0 条目）、`Doc/REPLY_TO_MAINLINE_2026-11-10.md`（上一轮）

---

## 0. 一句话

**认领完毕。** 你们代改的四处已全部接受（含不许改的语义），4 条不变量逐条复核通过，
版本升到 **0.7.0** 并写进 `CHANGELOG.md`，审计 §12 的"端点台账（3.1a）"标记为完成。
§7 的判断我们**同意现状**（别名台账的"可见性"与扩展启停解耦），理由见 §4。

另外我们**加了一层跨版本保护**（你们没要求，但 api_version 仍是 `"1"`）：
新扩展 + 旧引擎（无 `Application.Core.DeviceAliases`）时不再 ImportError，见 §3。

---

## 1. 认领清单（§3 的四处）

| 文件 | 你们改的 | 我们的处理 |
|---|---|---|
| `device_registry.py` | 删过渡委托层；新增 `names()`；末尾自注册；`DeviceUnresolved` 本地定义 | 全部保留。**没有**改回任何委托逻辑 |
| `extension.json` | 加 `device_aliases`；`description` 去掉 "transitional delegation to core" | 保留；只把 `version` 升到 `0.7.0` |
| `__init__.py` / `serial_manager.py` | "过渡期委托核心"→"自持 + 自注册" | 保留原文，未改 |
| `extension.py` | 生命周期钩子注释改为事实（引擎不调用） | 保留；同意"不要放唯一逻辑" |

`extension.py` 的 6 处 `import ...device_registry as reg` 也未动。

---

## 2. 4 条不变量复核（逐条给了命令）

### ① 导入即自注册

```powershell
.\.venv-py314t\Scripts\python.exe -Xgil=0 -c "from Application.Core import DeviceAliases as A; `
 import Application.Functions.SerialParallelDevice.device_registry as r; `
 print(A.provider() is r, A.provider_id(), r.backend())"
# True device extension
```

- `A.provider() is r` = **同一模块对象**（按包限定名导入，无第二份缓存）。
- 删掉末尾 `_Aliases.register(...)` 会静默丢能力 —— 我们已在
  `CHANGELOG.md` §0.7.0-2 与 `HANDOFF.md` 顶栏把这条写成禁令。

### ② manifest 声明

```json
"device_aliases": { "module": "device_registry", "dir": "." }
```

保留原文。审查器 `M9` 通过（`device_aliases module=device_registry dir=.`）。

### ③ `backend()` 恒 `"extension"` / `status.registry_backend`

保留。**另按你们 §2-③ 的建议补了能力视角**：

```json
"ext.device.status" → {
  "registry_backend": "extension",
  "alias_capability": { "available": true, "provider": "device",
                        "aliases": ["@SSSEP-Stimulator"],
                        "capability": "Application.Core.DeviceAliases" }
}
```

`alias_capability` 由 `device_registry.capability_status()` 产出 —— **面板层不直接
import `Application.Core`**（否则审查器 C6 会告警"超白名单"，且破坏层级边界）。

### ④ 包级 `start` / `stop` / `stop_all` / `io_owner`

语义未动，继续"存在但起不来 = 硬错误"：

| 情形 | 我们的行为 | 你们接缝的 `required` |
|---|---|---|
| 扩展缺席 | —（模块不存在） | `absent`，不抛 |
| 线程起不来（驱动/端口问题） | `start()` **抛** | `required=True` → 上抛 |
| 正常停止 | `stop(owner)` 释放租约，幂等 | `required=False` |

我们没有为了"更宽容"把 `start()` 改成吞异常，也不会改。

---

## 3. 我们额外加的一层：旧引擎兼容保护（请你们确认可接受）

**问题**：`api_version` 仍是 `"1"`，但 `0.7.0` 的 `device_registry.py` 顶层
`from Application.Core import DeviceAliases import ...` 只在 2026-11-14 之后的引擎存在。
用户把新扩展目录拷进旧引擎（很常见：只换扩展不换引擎）会得到：

```
ImportError: cannot import name 'DeviceAliases' from 'Application.Core'
```

而失败点是 `__init__` → `serial_manager` → `device_registry`，等于**整个 Serial/Parallel
节点族消失**（编辑器里显示 missing extension），比"别名不可用"严重得多。

**我们的处理**（只改本扩展文件）：

```python
try:                                    # 核心能力凭据（2026-11-14+）
    from Application.Core import DeviceAliases as _Aliases
    _ALIAS_CAPABILITY = "Application.Core.DeviceAliases"
except Exception:                       # 旧引擎：跳过自注册，台账本身照常工作
    _Aliases = None
    _ALIAS_CAPABILITY = ""
...
if _Aliases is not None:
    _Aliases.register("device", sys.modules[__name__])
```

已验证：把 `Application.Core.DeviceAliases` 从 `sys.modules` 摘掉后，
`bind / names / describe / unbind` 全部正常，`capability()` 返回 `""`。

> **这不会掩盖真故障**：`DeviceAliases` 只在"引擎版本旧"这一种情况下缺失；
> 若是它自身 import 出错（真 bug），仍然会走到 `except` 并静默降级 —— 但那种情况下
> 能力层坏了，本扩展也无法补救，报错只会让用户连节点都用不了。
> **请你们确认这个取舍**；若主线希望"宁可炸也不降级"，我们改回硬 import（一行）。

---

## 4. 答复 §7：别名台账**应当**与扩展启停解耦（同意现状）

我们的判断：**保持现状（`ensure()` 不查 `ExtensionManager.enabled`）**。

理由按重要性排序：

1. **台账是机器侧数据，不是扩展运行态。**
   `devices.json` 描述的是"这台机器上 `@SSSEP-Stimulator` 插在哪个 COM 口"。
   它和"本进程是否加载了 SPD 的 I/O 线程/面板"是两件事。停用扩展的语义是
   "我现在不想让它跑 I/O / 不显示面板"，不是"这台机器没插过设备"。

2. **停用后仍要能"看得见问题"。**
   场景里写着 `@SSSEP-Stimulator`。用户停用扩展往往是**排查**（怀疑是设备扩展导致崩溃）。
   此时打开场景若报一堆 `device_alias_check_unavailable`，会把真问题埋掉：
   用户看到的是"别名全没了"，而不是"我把扩展关了"。

3. **与迁移前行为一致 = 零学习成本。**
   旧 `Core.DeviceRegistry` 直接读文件，从来没有"启用状态"概念。加这条判断等于
   引入一个用户没见过的行为变化，且只在"停用"这个罕见路径上出现 —— 属于最难被理解的差异。

4. **真正需要"启用语义"的地方已经分开了。**
   `ext.device.*` op、面板窗口、`send/write_parallel` 都依赖扩展被加载/启用；
   节点求值器在 I/O 不可用时**显式写 error 日志**（0.6.0 起）。这些已经足够表达
   "扩展没在工作"。别名清单只是数据视图，不必再叠一层门禁。

**唯一需要你们注意的边界**（如果将来你们改口径）：

- `DeviceAliases.ensure()` 的惰性发现会 **import** provider 模块。若某天 provider 模块
  在导入期有副作用（开端口、起线程），那它就变成"读清单 = 启动设备"，这才是真正的问题。
  我们保证 `device_registry.py` **导入期零副作用**（只做 `register`，不 `load()` 文件、
  不开端口）—— 这条已写进 `CHANGELOG.md` 的别名能力说明里。
- 若主线将来要做"停用即隐藏"，建议用**新键**（如 `"device_aliases"` 里加
  `"respect_enabled": true`）而不是直接改默认，避免二次迁移。

---

## 5. 本轮实际改动（都在扩展目录内）

| 文件 | 改动 | 类型 |
|---|---|---|
| `extension.json` | `version` → `0.7.0` | 版本 |
| `extension.py` | `version` → `0.7.0`；`_op_status` 新增 `alias_capability`（经 `reg.capability_status()`，不 import 核心） | 增量诊断字段 |
| `device_registry.py` | 能力层 import 改为防御式；新增 `capability()` / `capability_status()` | 跨版本兼容 + 诊断 |
| `CHANGELOG.md` | 新增 `0.7.0` 条目；§A/§B 总览表加 3 行；§D 归属表更新（"唯一实现"）；§E 检查单改为 0.6.0→0.7.0；§G 路线标完成状态；§H 换成 2026-11-14 复测 | 文档 |
| `Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md` | 表头加"2026-11-14 主线完成迁移"；§12 第 1/2/6 行改为 ☑ 并写真实方式 | 回执 |
| `HANDOFF.md` | 顶栏加 v0.7.0 条 | 交接 |
| `Doc/REPLY_TO_MAINLINE_2026-11-14.md` | 本文件 | 回信 |

**没有动**：`node_pack.py`、`api.py`、`state.py`、`io_thread.py`、`monitor.py`、`identity.py`、
`parallel_manager.py`、所有面板绘制代码、`Test/**`、主线任何文件。

---

## 6. 验收（按你们 §4 的命令，逐条结果）

| 命令 | 结果 |
|---|---|
| `--only test_serial_parallel_device` | PASS |
| `--only test_spd_monitor` | PASS |
| `--only test_device_alias` | PASS |
| `--only test_device_autobind` | PASS |
| `--only test_extension_coupling_inventory` | PASS（13/13） |
| `python -c "from Application.Core import DeviceAliases as A; print(A.status())"` | `{'available': True, 'provider': 'device', 'aliases': ['@SSSEP-Stimulator']}` |
| `review_extension.py .` | **22 pass / 0 warn / 0 fail**（M9 计入后 22 项） |

补充（我们自己加的）：

| 检查 | 结果 |
|---|---|
| 旧引擎模拟（`sys.modules['Application.Core.DeviceAliases']=None`） | 台账可用，`capability() == ""`，不抛 |
| provider 同一性 | `A.provider() is device_registry` → `True` |
| `ext.device.status.alias_capability` | `available=True provider=device aliases=['@SSSEP-Stimulator']` |

---

## 7. 我们了解到的剩余待办（不需要你们现在做，也不需要我们做）

| 项 | 归属 | 我们的准备 |
|---|---|---|
| `visible_pins.py` 的 `@rule("ParallelSend")`（manual 隐藏 `Value`） | 主线（pack 扩展点） | 我们会在 `pin_visibility` 契约落地后把声明搬进 `node_pack.py`；语义已写进 `CHANGELOG.md` §F3-3 |
| `group_layout.py` ×2（卡片高度预留） | 主线 | 同意用"有没有声明字段/自定义控件"的谓词替代 |
| `graph_rules.py` 的 IO 表格（含导出场景 `_rules`） | 主线 | `props_text` 已完整；删表后 `graph.types` 是权威（`CHANGELOG.md` §F1 已按此写） |
| 示例工程 `SerialPulse` / `ParallelPulse` 迁移 | 待你方定时机 | 我们可在同一版本内原子迁移（扩展 `Examples/` 自动登记已就绪） |

> 关于 `_rules`：再提醒一次（上一轮也提过）——`NodeCanvas.to_dict()` 会把
> `_NODE_GRAPH_RULES` 整体写进**已保存场景**的 `node_graph._rules`。删表格前请决定
> "导出时是否追加 `NodePackRegistry.catalog()` 的 `props_text`"，否则离线 agent
> 拿到的 `_rules` 会缺这两个节点的语义。

---

## 8. 请回一句的两个确认

1. **§3 的防御式 import**：可接受？（我们倾向保留；理由：`api_version` 仍是 `"1"`）
2. **§4 的口径**：保持"别名可见性与启停解耦"？（我们同意现状）

若你们同意，本轮即可视为 SPD 侧收尾完成；剩下的事都等主线的 pack 扩展点。
