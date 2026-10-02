# BCI 算法域开发协议（Application/Functions/BCIAlgorithm）

> 适用: epoch 数据集、FBCSP / CCA 算法节点、模型注册表与训练语义。
> 节点 JSON 参考（agent 构图）: `graph_rules.py`（Epoch / Algorithm 节）;
> 设备侧见 `device_io_protocol.md`; UI 控件见 `ui_protocol.md`。

---

## 1. 文件地图

| 文件 | 职责 |
|---|---|
| `BCIAlgorithm/EpochDataset.py` | epoch 数据集注册表（append 沿 dim0; `(epochs, channels, samples)`; npz pad+lengths） |
| `BCIAlgorithm/ModelRegistry.py` | 模型注册表（spec / trained model; `dryrun#` 命名空间） |
| `BCIAlgorithm/FBCSP.py` | Filter Bank CSP + 闭式 LDA / 线性 SVM（纯 numpy/scipy; 模型 npz 落盘） |
| `BCIAlgorithm/CCA.py` | 典型相关分析（SSVEP 免训练判别） |
| `BCIAlgorithm/Jobs.py` | SyncJob — 同步等待式训练任务（线程 + 锁槽） |
| `Core/NodeGraph/node_types/{epoch,bci_algorithm}.py` | 节点类型（pins / props 文档） |
| `Core/NodeGraph/evaluators/{epoch,bci_algorithm}.py` | 求值器（键规则 / 干跑 / 训练阻塞语义） |
| 测试 | `Test/Application/Functions/test_{epoch_dataset,bci_algorithm,bci_empty_data}.py` |

## 2. 数据模型（EpochDataset — 神经工程学口径）

- 一条 epoch = 一个试次段 `(channels, samples)`; append 沿**第一维**堆叠 → `(epochs, channels, samples)`;
- 标签数值型; 首条 append 固定 channels/fs（不一致 → 错误丢弃该条）;
- `Samples` pin 裁有效段; `Samples<=0` 跳过; npz = `X(pad) + lengths + y + fs`（变长保真）;
- 节点: EpochAppend / EpochCount / EpochClear / EpochSave / EpochLoad（**无配对** — 纯内存容器）;
- 键规则: `epochs_name` 或 `epochs#<nid>` 回退; 引用节点空名 + 唯一画布源自动绑定（`graph_constraints.epoch_*`）。

## 3. 算法节点（必要超参模式 + 打包 list）

| 节点 | 必选（内联） | 动态组（+/-） | pins |
|---|---|---|---|
| InitFBCSP | n_components(1..8), classifier(LDA/SVM) | bands: `[[lo,hi],...]`（≤16; **空 = 普通 CSP**） | exec |
| TrainFBCSP | model_name, dataset_name, mode(train/load), model_path/save_path | — | exec |
| TestFBCSP | model_name | — | Data+Samples → Label+Confidence |
| TestCCA | n_harmonics(1..8) | freqs: `[f,...]`（**≥2 不限上限**） | Data+Samples+Fs → Label(idx)+Score+Freq |

- **打包 list 契约**（MCP 解包思路）: props 唯一真相 = 打包 list（`bands: [[4,8],[8,13],[13,30]]`）;
  UI 解包成行 + `[−]`/`[+]`（数量与取值边界内联守护）; 外部 MCP `graph.set_props` 整体原子替换 — **无新 op**;
- 算法语义: bands 空 → 退化普通 CSP; 训练需**恰 2 类**（CSP 定义域）;
  LDA 闭式解 / 线性 SVM（`scipy.optimize`, 零初始化 → 确定性）; **不引入 sklearn**（无 cp314t wheel）。

## 4. 训练语义（同步等待 — 核心约定）

```
首次走到 TrainFBCSP: 快照数据集 → 真实: SyncJob 线程（进度日志）/ 干跑: 同步执行
    训练期间: 节点 _blocked=True → 下游暂停（每帧被走到时上报进度）
    完成: 注册模型 → _blocked=False →【同一次 exec 遍历】继续下行（恰好一次; 之后保持 blocked）
    失败: error 日志 + 保持 blocked（不重试）
```

- **硬约束**: TrainFBCSP 必须挂**可重复触发链**（帧链/门控链）; OnGameStart-only 链会永久卡住
  （与 TimeDelay 同病, 引擎现状）;
- worker 线程绝不触碰 ctx/evaluator（只写锁保护的任务槽 — 自由线程纪律）;
- 干跑一律同步训练（确定性）; 长时间训练不进框架 → `mode=load` + `model_path`（离线流水线入口）,
  train 模式 `save_path` 导出 npz 供离线复用。

## 5. 模型注册与键规则

- `model_name` 或 `model#<nid>` 回退; Train(train) 的 spec 引用 = InitFBCSP 键; 模型注册键 = spec 键（同名对应）;
- Test 引用 TrainFBCSP 键（空名 + 唯一源自动绑定）;
- 静态校验 `bci_reference`（见 `graph_validation_protocol.md` §3）;
- 干跑: 模型/数据集同用 `dryrun#` 命名空间; 校验结束 `clear_matching` 双清;
  Runtime 安全网 `reset_all`（GameRuntime 启动+停止 / PlayerBootstrap）。

## 6. 空采验证（Stage ④, 2026-10-03 实测）

方法见 `test_bci_empty_data.py`; 结果:

| 实验 | 数据 | 结果 | 解读 |
|---|---|---|---|
| FBCSP 随机标签 | GtecStub 60 窗（64ch×256@512Hz） | train_acc=0.70 / held-out **0.65** | 训练可拟合, 留出 ≈ 随机 → **乱判** ✓ |
| CCA 纯噪声 | SigGen amplitude=0 + noise | mean ρ=**0.205** | 无节律 → 无法锁定 → 乱判 ✓ |
| CCA stub（仅报告） | GtecStub | ρ≈0.98–1.00 | stub 含工程化节律, 偏高属预期（非 rest-like） |
| 节点图端到端 | Gtec 节点链 dry-run | 45 epochs → train(acc 0.8) → test(label=2, conf=0.98) | 管线正常, 输出无意义; 干跑零残留 ✓ |

- 结论: 两种算法在**无任务信息数据**上都停在随机水平 — 管线无假学习;
- 待办: **实机休息态**数据验证（Gtec 实机联调章节: 自有环境起服务 → 录 rest → 同脚本替换数据源）。

## 7. 测试

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_epoch_dataset.py   # 28
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_bci_algorithm.py   # 35
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_bci_empty_data.py  # 11 (空采验证)
```
