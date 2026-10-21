# BCI Algorithm 官方扩展 — 交接书

> **接手状态（2026-10-21）**: 正式交接给下一任维护 agent / BCI 维护者。
> 本文 = 十分钟上手 + 边界 + 迁移现状 + 验收命令。
> **上游诉求方**: 用户（实验方，MI-SSSEP / SSSEP 范式）。**送交人**: 引擎侧 agent。
> **当前形态**: `id = bci`，`Application/Functions/BCIAlgorithm/`，可装载扩展
> （`extension.py:create_extension`，capabilities `ops + nodes`）。

---

## 1. 这个扩展是什么（边界先划清）

- **是**: FBCSP / CCA / Epoch 数据集的**算法实现 + 节点族 + 扩展壳**。
- **不是**: 设备采集、刺激呈现、实验编排；这些分别属于 VirtualDevice / 厂家设备 SDK 与实验工程。
- **核心引擎只保留发现机制**: `Core/NodeGraph/node_packs.py` 扫描
  `Application/Functions/**/node_pack.py`；核心不再 import FBCSP/CCA/Epoch 求值器。
- **兼容红线**: 下列内容不得改：
  - 节点 type 名：`InitFBCSP / TrainFBCSP / TestFBCSP / TestCCA / EpochAppend /
    EpochCount / EpochClear / EpochSave / EpochLoad`；
  - 节点 props / pin 名 / 语义（存量 `.scene` 直接加载）；
  - 训练同步等待语义（`SyncJob`；干跑同步路径）；
  - 依赖仅 `numpy` / `scipy`（不引入 sklearn）。

## 2. 资产地图（改哪里 / 权威在哪）

| 能力 | 实现位置 | 说明 |
|---|---|---|
| FBCSP（CSP + LDA/SVM） | `FBCSP.py` + `Jobs.py` | 闭式 LDA + scipy L-BFGS-B；模型 npz 落盘 |
| CCA（SSVEP） | `CCA.py` | 训练无关，sin/cos 参考 |
| Epoch 数据集 | `EpochDataset.py` | `(epochs, channels, samples)` + 标签 + npz |
| 模型注册表 | `ModelRegistry.py` | spec / trained model，`dryrun#` 命名空间 |
| 节点声明 / Add 菜单 | `node_pack.py` | 纯声明，type/pin/props 兼容 |
| BCI 求值器 | `evaluator.py` | 2026-10-21 从 `Core/NodeGraph/evaluators/` 迁入 |
| Epoch 求值器 | `evaluator_epoch.py` | 同上 |
| 扩展壳 / ops | `extension.py` | `ext.bci.status / models / datasets`（只读发现） |
| manifest | `extension.json` | `entry` + `capabilities` |
| 协议 | `Doc/Dev/bci_algorithm_protocol.md`（CLI 入口） | 超参 / 同步等待 / 空采语义 |
| 维护清单 | `TODO.md` | 尚未完成的算法生态项 |

## 3. 已完成的“出核心”改动（2026-10-21）

- 求值器实现文件从 `Application/Core/NodeGraph/evaluators/` 移到本目录：
  - `bci_algorithm.py` → `evaluator.py`
  - `epoch.py` → `evaluator_epoch.py`
- `node_pack.py` 通过本地文件加载器注册两个求值器，**不 import 重量级包门面**
  （避免核心启动时拉入 scipy）。
- `Core/NodeGraph/__init__.py` 不再 import 上述求值器模块。
- 新增 `extension.py`，`extension.json` 增加 `entry`，扩展现在可被
  Extensions 菜单 / `extension.enable` 装载。
- 节点包 owner 仍为 `bci`；`NodePackRegistry.unregister_owner("bci")` 可清理。

## 4. 仍在核心、但已经收敛为“通用机制”的耦合

这些不是算法实现，后续可继续抽成扩展生命周期 / 通用 API；交接时不要误以为
算法还在核心：

| 位置 | 现状 | 建议 |
|---|---|---|
| `Core/NodeGraph/graph_constraints.py` | 保存 `ALGO_INIT / ALGO_TRAIN / EPOCH_APPEND / EPOCH_LOAD / epoch_key / model_key / epoch_source_keys` | 后续做“扩展规则注册 API”，再迁入本扩展 |
| `Core/NodeGraph/validation/dry_run.py` | 清理 `dryrun#` 数据集 / 模型 | 改成扩展 shutdown hook 或通用 namespace cleanup |
| `Editor/UI/panels/node_editor/widgets/algorithm.py` / `epoch.py` | BCI/Epoch 专用卡片控件 | 可保留为编辑器侧支持；若扩展要完全独立，改为 `NodePackRegistry` 的 widget 声明 |
| `Runtime/GameRuntime.py` / `PlayerBootstrap.py` | 可选 `BCIAlgorithm.reset_all()` 安全网 | 改为扩展 `on_unload` / runtime cleanup hook |
| `graph_rules.py` / 工具仓 `rules.md` | 节点文档 | 节点迁移时保持同步 |

## 5. 十分钟上手

```powershell
Set-Location C:\WorkSpace\FLY\FlyVibing-Engine
$py = ".\.venv-py314t\Scripts\python.exe"
& $py Test\Application\Functions\test_bci_algorithm.py          # 35/35
& $py Test\Application\NodeGraph\test_node_pack.py               # 17/17
& $py Test\Application\Core\test_node_graph_boundary.py          # 4/4
& $py Test\Application\Extensions\test_extension_manager.py      # 32/32
```

实机/扩展壳验证：

```powershell
$cli = ".\.venv-py314t\Scripts\engine-editor-cli.exe"
& $cli call extension.enable id=bci
& $cli call ext.bci.status
& $cli call ext.bci.models
& $cli call ext.bci.datasets
& $cli call extension.disable id=bci
```

## 6. 下一步（按优先级）

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `ext.bci.train` / `test` / `model.list` 的 agent 通道（若需要脱离节点图训练） | op 契约 + 空数据/坏数据矩阵 |
| P1 | `AlgorithmBase` 模板 + 最小均值分类器示例 | 复制模板 → 测试通过 ≤ 30 分钟 |
| P1 | 把 `graph_constraints` 的 BCI/Epoch 规则迁到扩展规则注册 | 旧场景校验零回归 |
| P2 | 自定义算法 `.mgext` / 目录分发 | 包加载 + 版本闸门 |
| P2 | widget 声明化（去掉 Editor 对 BCI 类型的硬编码分支） | 删掉专用 widget 后仍可编辑 props |
| P3 | 物理挪到独立社区扩展仓库 | 引擎只保留 manifest 发现路径 |

## 7. 完成定义（DoD）

新增/修改 BCI 能力时必须同时满足：

1. 节点 type / props / pin 兼容（旧 `.scene` 加载不报错）；
2. 求值器注册在本目录（或扩展规则 API），不回到 `Core/NodeGraph/evaluators/`；
3. 无头测试覆盖：模型注册 / 训练 / 预测 / 干跑 / 引用校验；
4. `test_bci_algorithm.py` + `test_node_pack.py` + `test_node_graph_boundary.py` 全绿；
5. 文档同步 `Doc/Dev/bci_algorithm_protocol.md` 与工具仓 `rules.md`；
6. 实机至少 `extension.enable id=bci → ext.bci.status → disable` 走一遍。
