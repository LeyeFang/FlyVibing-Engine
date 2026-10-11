# BCI Algorithm Extension — TODO（状态档案）

> 状态: **partial**（内核算实现已交付, 尚未迁移到 extension 形态）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`bci`; 节点/ops 前缀规划 `ext.bci.*`）

## 0. 现状（已实现资产映射 — 迁移来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| FBCSP（CSP + LDA/SVM） | `Functions/BCIAlgorithm/FBCSP.py` + `CSP.py` + `Jobs.py` | 闭式 LDA + scipy.optimize 线性 SVM; SyncJob 同步等待语义 |
| CCA（SSVEP） | `Functions/BCIAlgorithm/CCA.py` | 训练无关（sin/cos 参考）; 12Hz 锁定 ρ=0.96 已验证 |
| Epoch 数据集 | `Functions/BCIAlgorithm/EpochDataset.py` | (epochs, channels, samples) + 标签 + npz 存取 |
| 模型注册表 | `Functions/BCIAlgorithm/ModelRegistry.py` | 训练产物管理 |
| 节点族 | `Core/NodeGraph/node_types/bci_algorithm.py` + `evaluators/bci_algorithm.py` + widgets | Init/Train/Test × FBCSP + TestCCA（五注册点已齐） |
| 协议 | `Doc/Dev/bci_algorithm_protocol.md` | 超参/同步等待/空采验证语义 |

## 1. TODO

### A. 迁移到 Extension 形态（保持兼容）
- [ ] 节点 Pack 化: 用 `ctx.nodes.register_pack`（M1 实装）替代 core 五注册点直注册;
      **节点 type 名保持不变**（已保存场景的图引用兼容——.scene 里带 `TrainFBCSP` 等字符串）
- [ ] 实现文件平移: `Functions/BCIAlgorithm/**` 保留为扩展私有实现; `evaluators/bci_algorithm.py`
      改为薄转发或整体迁入扩展目录（求值器注册协议不变）
- [ ] `ext.bci.*` ops: `train` / `test` / `model.list` / `model.load`（把训练入口开放给 agent 渠道）
- [ ] InitFBCSP 等 widgets 的扩展命名空间（沿用 widgets 注册表, key 加前缀）

### B. 自定义算法开发生态（社区开发者主线）
- [ ] **AlgorithmBase 继承模板**: `class MyAlgorithm(AlgorithmBase)` → 自动获得
      Init/Train/Test 三节点 + 模型注册 + 干跑支持（文档 + 可复制模板文件）
- [ ] 算法注册 API: `ctx.algorithms.register(cls, name=...)`（M1.5 设计 — 与 NodePack 联动生成节点）
- [ ] 示例算法: 一个 20 行内可读的最小示例（如均值分类器）作为 test fixture + 文档样例
- [ ] 训练等待语义复用: SyncJob（阻塞同步等待）与干跑同步训练语义必须在新形态下保持
- [ ] 打包/分发: 第三方算法按 .mgext 或目录形式分发（M3）

### C. 测试生态
- [ ] 迁移 `test_bci_algorithm.py` / `test_bci_empty_data.py` 到扩展自测（test_protocol 扩展行）
- [ ] 空数据/坏数据矩阵保持（chance-level 输出断言）

## 2. 迁移注意

- **兼容红线**: 节点 type 名、props 名、引脚名不得变（存量场景/示例工程直接加载）。
- 依赖约束: 仅 scipy/numpy（不引入 sklearn — see `bci_algorithm_protocol.md`）。
- 训练/推理线程纪律: 阻塞节点只允许在反复触发链上（既有语义）; ICA 类重训练走 `ctx.jobs`（M2）。

## 3. 验收建议

- [ ] 迁移后全量回归: `test_bci_algorithm` 35 项 + `test_bci_empty_data` 11 项零回归
- [ ] 旧场景加载: 含 FBCSP/CCA 节点的 .scene 载入后图校验零 error
- [ ] 自定义算法模板: 从复制模板到测试通过 ≤ 30 分钟（面向新手的可用性验收）
