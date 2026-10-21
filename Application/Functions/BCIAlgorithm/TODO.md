# BCI Algorithm Extension — TODO（状态档案）

> 状态: **partial**（算法实现 + 节点族 + 扩展壳已交付；交接书见 `HANDOFF.md`）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`bci`; entry 已启用; ops 前缀 `ext.bci.*`）

## 0. 现状（已实现资产映射 — 迁移来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| FBCSP（CSP + LDA/SVM） | `Application/Functions/BCIAlgorithm/FBCSP.py` + `CSP.py` + `Jobs.py` | 闭式 LDA + scipy.optimize 线性 SVM; SyncJob 同步等待语义 |
| CCA（SSVEP） | `Application/Functions/BCIAlgorithm/CCA.py` | 训练无关（sin/cos 参考）; 12Hz 锁定 ρ=0.96 已验证 |
| Epoch 数据集 | `Application/Functions/BCIAlgorithm/EpochDataset.py` | (epochs, channels, samples) + 标签 + npz 存取 |
| 模型注册表 | `Application/Functions/BCIAlgorithm/ModelRegistry.py` | 训练产物管理 |
| 节点族 | `Core/NodeGraph/node_types/bci_algorithm.py` + `evaluators/bci_algorithm.py` + widgets | Init/Train/Test × FBCSP + TestCCA（五注册点已齐） |
| 协议 | `Doc/Dev/bci_algorithm_protocol.md` | 超参/同步等待/空采验证语义 |

## 1. TODO

### A. 迁移到 Extension 形态（保持兼容）
- [x] 节点 Pack 化: `node_pack.py` 注入类型/字段；**节点 type 名保持不变**
- [x] 求值器归位: `evaluator.py` / `evaluator_epoch.py` 已迁入本目录，核心不再 import
- [x] `ext.bci.status` / `ext.bci.models` / `ext.bci.datasets`（只读发现入口）
- [x] 扩展壳 `extension.py` + manifest `entry`（Extensions 菜单可启停）
- [ ] `ext.bci.train` / `test` / `model.load`（训练入口开放给 agent 渠道）
- [ ] InitFBCSP 等 widgets 的扩展命名空间（沿用 widgets 注册表, key 加前缀）

### B. 自定义算法开发生态（社区开发者主线）
- [ ] **AlgorithmBase 继承模板**: `class MyAlgorithm(AlgorithmBase)` → 自动获得
      Init/Train/Test 三节点 + 模型注册 + 干跑支持（文档 + 可复制模板文件）
- [ ] 算法注册 API: `ctx.algorithms.register(cls, name=...)`（M1.5 设计 — 与 NodePack 联动生成节点）
- [ ] 示例算法: 一个 20 行内可读的最小示例（如均值分类器）作为 test fixture + 文档样例
- [ ] 训练等待语义复用: SyncJob（阻塞同步等待）与干跑同步训练语义必须在新形态下保持
- [ ] 打包/分发: 第三方算法按 .mgext 或目录形式分发（M3）

### C. 测试生态
- [x] `test_bci_algorithm.py` 35/35；`test_node_pack` 17/17；边界 4/4
- [ ] 迁移 `test_bci_empty_data.py` 到扩展自测（test_protocol 扩展行）
- [ ] 空数据/坏数据矩阵保持（chance-level 输出断言）

## 2. 迁移注意

- **兼容红线**: 节点 type 名、props 名、引脚名不得变（存量场景/示例工程直接加载）。
- 依赖约束: 仅 scipy/numpy（不引入 sklearn — see `bci_algorithm_protocol.md`）。
- 训练/推理线程纪律: 阻塞节点只允许在反复触发链上（既有语义）; ICA 类重训练走 `ctx.jobs`（M2）。

## 3. 验收建议

- [ ] 迁移后全量回归: `test_bci_algorithm` 35 项 + `test_bci_empty_data` 11 项零回归
- [ ] 旧场景加载: 含 FBCSP/CCA 节点的 .scene 载入后图校验零 error
- [ ] 自定义算法模板: 从复制模板到测试通过 ≤ 30 分钟（面向新手的可用性验收）
