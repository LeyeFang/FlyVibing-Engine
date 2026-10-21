# Virtual Device 官方扩展 — 交接书

> **接手状态（2026-10-21）**: 正式交接给下一任维护 agent / 设备域维护者。
> **当前形态**: `id = virtual`，`Application/Functions/VirtualDevice/`，可装载扩展
> （`extension.py:create_extension`，capabilities `ops + ui + device + nodes`）。
> **定位**: 虚拟信号发生器设备族 + 实时波形监视面板 + SigGen/DevicePool 节点族。

---

## 1. 边界（先划清）

- **是**: 虚拟设备后端（进程内 / VIRTUAL 服务）、会话/池/落盘、监视面板
  （watch vs record）、`ext.virtual.*` ops、SigGen + DevicePool 节点。
- **不是**: 真实硬件驱动。真实品牌走同一 `DeviceBackend` / 服务协议接入；
  本扩展只是虚拟设备参考实现。
- **兼容红线**: `SigGen` / `DevicePool` 的节点 type、props、pin 名不得改；
  `ext.virtual.*` op 名与面板动作保持单点实现。
- **核心只保留发现机制**: `NodePackRegistry` 扫描 `node_pack.py`；核心不再 import
  `evaluators/siggen.py` / `evaluators/device_pool.py`。

## 2. 资产地图

| 能力 | 位置 | 说明 |
|---|---|---|
| 扩展壳 / 面板 / ops | `extension.py` | `ext.virtual.{status,open,close,watch,record,stop,filters,display,snapshot}` |
| 波形绘制 | `virtual_scope.py` | imgui draw_list，无状态 |
| 显示 DSP | `virtual_display.py` | 滤波 / min-max 抽取 / 统计 |
| 设备门面 / 会话 | `Device.py` | 环形缓冲 / 录制 / 设备池 / 生命周期 |
| 服务协议 | `ServiceProtocol.py` / `ServiceHost.py` / `ServiceClient.py` | 品牌进程 + 协议通信 |
| 虚拟后端 | `SigGen.py` / `service.py` | 确定性正弦 + 服务入口 |
| 节点声明 | `node_pack.py` | SigGen / DevicePool 类型 + Add 菜单 |
| SigGen 求值器 | `evaluator_siggen.py` | 2026-10-21 从核心迁入 |
| DevicePool 求值器 | `evaluator_pool.py` | 2026-10-21 从核心迁入 |
| 文档 | `README.md` / `BACKEND.md` / `TODO.md` | 面板 / 后端 / 维护清单 |

## 3. 已完成的“出核心”改动（2026-10-21）

- `Core/NodeGraph/evaluators/siggen.py` → `evaluator_siggen.py`
- `Core/NodeGraph/evaluators/device_pool.py` → `evaluator_pool.py`
- `node_pack.py` 在注册节点包时导入本目录求值器，核心
  `Core/NodeGraph/__init__.py` 不再 import 设备求值器。
- 扩展 manifest 原本已含 `entry`，本次未改变 `ext.virtual.*` / 面板行为。

## 4. 仍在核心的通用耦合

| 位置 | 现状 | 建议 |
|---|---|---|
| `Core/NodeGraph/graph_constraints.py` | `pool_key` 等设备规则 | 后续扩展规则注册 API |
| `Core/NodeGraph/validation/dry_run.py` | 清理 `dryrun#` 会话 / 池 | 改扩展 shutdown hook |
| `Runtime/GameRuntime.py` / `PlayerBootstrap.py` | 可选 `VirtualDevice.close_all()` 安全网 | 改扩展生命周期 hook |
| `Editor/UI/panels/node_editor/widgets/device_siggen.py` / `device_pool.py` | 设备节点卡片控件 | 保留或改成声明式 fields |
| `Test/Application/Core/test_node_graph_boundary.py` | runtime chain 引用扩展求值器 | 已同步为扩展路径 |

## 5. 验收命令

```powershell
Set-Location C:\WorkSpace\FLY\FlyVibing-Engine
$py = ".\.venv-py314t\Scripts\python.exe"
& $py Test\Application\Functions\test_siggen_device.py       # 119/119
& $py Test\Application\Functions\test_device_pool.py         # 49/49
& $py Test\Application\Extensions\test_virtual_panel.py      # 29/29
& $py Test\Application\NodeGraph\test_node_pack.py           # 17/17
& $py Utils\Dev\test_runner.py --tier core                    # 全量
```

实机：

```powershell
.\startup.bat
$cli = ".\.venv-py314t\Scripts\engine-editor-cli.exe"
& $cli call extension.enable id=virtual
& $cli call ext.virtual.status
& $cli call ext.virtual.open mode=sim
& $cli call ext.virtual.watch
& $cli call ext.virtual.snapshot
& $cli call ext.virtual.close save=false
& $cli call extension.disable id=virtual
```

## 6. 下一步

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | 把 `VirtualDevice.close_all()` 安全网改成扩展生命周期 hook | 核心不再知道具体设备扩展 |
| P1 | 面板成熟度：定时发送 / 快捷指令 / 事件过滤 / CSV 导出 | 见 `TODO.md` |
| P1 | 真实硬件回环验收（用户插设备） | 证据落 `Test/_runs/` |
| P2 | 声明式 widget fields 替代专用面板控件 | 去掉 Editor 对设备类型的硬编码 |
| P2 | 多会话 / 多设备池面板评估 | 与节点侧设备池保持一致 |
| P3 | 物理挪到独立社区扩展仓库 | 引擎只保留发现路径 |

## 7. DoD

1. 节点 type / props / pin / `ext.virtual.*` op 名不变；
2. 求值器注册在本目录，不回到核心 `evaluators/`；
3. 面板动作与 op 共用 `_op_*`（动作单点）；
4. 无头测试：DSP / 会话 / watch-record / 面板生命周期 / ops；
5. `review_extension.py` 0 FAIL；core 全绿；
6. 实机 `enable → status → open/watch/snapshot → close → disable` 走一遍。
