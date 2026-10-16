# Signal Process Extension — TODO（状态档案）

> 状态: **skeleton**（2026-10-11 建档; 仅 `ext.sigproc.info` ops 通道样例已实现）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md`（必读）· 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`sigproc`; ops 前缀 `ext.sigproc.*`）

## 0. 现状（已实现资产）

| 资产 | 位置 | 说明 |
|---|---|---|
| 可装载骨架 | `Application/Functions/SignalProcess/extension.py` | 生命周期 + ops 样例（增量扫描链路验证） |
| 依赖技术 | `scipy`（既有依赖）· `numpy` | 滤波/变换实现基础 |
| 参考先例 | `Application/Functions/BCIAlgorithm`（CSP / Butterworth SOS 带通）、`Application/Core/{Media,Text}` 节点族五注册点 | 复用工程模式 |

## 1. TODO（按功能域）

### a) 初始化信号处理器节点 `SignalProcessorInit`
- [ ] 配置模板: 采样率 / 通道数 / 通道名表（可选）/ 单位（µV/uV）
- [ ] **输入形状各维度含义**定义并在节点文档与 props 注明:
      `(channels, samples)`（连续流）/ `(epochs, channels, samples)`（分段）— 与 `EpochDataset` 约定对齐
- [ ] 下游动态依赖: 滤波/参考节点从 Init 上游读取配置（模板 prop 机制, 参考 `device_inventory` 模式）

### b) 滤波器 `BandpassFilter`（即时 in→out）
- [ ] 参数: 滤波器类型（IIR Butterworth / FIR）/ 阶数 / 下限截止 / 上限截止
- [ ] 实现: SOS 系数（scipy.signal, `filtfilt` 离线语义 vs `sosfilt` 流式语义分模式）
- [ ] 边界: 截止频率 Nyquist 钳制（复用 `FIELD_CLAMPS` 思路）/ 数据不足一阶时的旁路

### c) 参考 `Reference`
- [ ] 参考类型: ①指定通道参考 ②全体均值参考 ③**拉普拉斯参考**（近邻通道加权均值）
- [ ] 动态配置模板: 通道选择由上游 Init 提供（下拉 + 多选存储为 packed list, 参考 bands 机制）
- [ ] 坏道参与策略开关（参考通道是否剔除坏道）

### d) 信号变换
- [ ] 即时 FFT 节点（幅度/相位输出; 窗函数选择）
- [ ] **SDFT**（滑动 DFT）节点 — 流式逐样本更新
- [ ] CWT（小波变换; 母小波选择）
- [ ] Hilbert（解析信号 → 包络/瞬时相位）

### e) 坏道处理
- [ ] 检测策略: 方差阈值 / 相关系数法 / 幅度阈值（可组合）
- [ ] 输出: 坏道掩码（bool 数组）+ 插值修复模式（邻道均值插值）
- [ ] 供参考节点消费的 `bad_mask` 引脚类型（variant packed）

### f) ICA
- [ ] 算法: FastICA（scipy 无现成 → 自实现或引入 `sklearn` 评估后决策）; 组件选择
- [ ] 依赖约束: 阻塞性训练语义 — 必须走后台任务（`ctx.jobs`, M2 实装）不得阻塞主线程
- [ ] 输出: 去伪迹后信号 + 成分矩阵（可选 dump 到数据目录）

## 2. 迁移/落地注意

- 节点注册经 **NodePack**（五注册点翻译, `extension_dev_protocol.md` §8; M1 实装）; type 名
  以 `ext.sigproc.` 前缀, Add 菜单新增顶级页 "Signal Process"。
- 求值器文件放本目录; 干跑（dry-run）必须是确定性纯函数（无设备/文件 IO）。
- 大数据用 `variant` 引脚传 numpy（float32）; 引用既有 `RingBuffer`（流式）与快照模式。

## 3. 验收建议（每个节点落地时）

- [ ] dry-run 数值钉死测试（合成信号: 正弦+噪声; 滤波后目标频带能量占比断言）
- [ ] 与 scipy 参考实现对照（同参数下逐样本误差 < 1e-6）
- [ ] 图校验零 error（含未接线/类型不匹配负例）
- [ ] `extension.enable id=sigproc` 后 `ext.sigproc.*` 全部出现在 `extension.list`
