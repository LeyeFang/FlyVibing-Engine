# Gtec Device Extension — TODO（状态档案）

> 状态: **partial**（监视面板已交付（观察/采集分离、实时滤波、阻抗、录制）; 节点迁移未做）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`gtec`; 已含 entry — 可装载; ops 前缀 `ext.gtec.*`）
> 2026-10-15 补丁 (v0.3.1): 服务自动拉起 + 快速失败 + 探针 / 真机 TRIG 列修复 / 阻抗 256→会话通道裁剪

## 0. 现状（已实现资产映射 — 复用来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| **监视面板（本扩展）** | `Functions/EEGDevice/Gtec/{extension, gtec_display, gtec_scope}.py` | 实时波形 / 显示滤波 / 录制（2026-10-12 交付） |
| 品牌后端 | `Application/Functions/EEGDevice/Gtec/`（backend/service/README） | **独立进程 + 自有 env**（gtec api 特性约束）; `[4B BE len][pickle proto=4]` 协议 |
| 服务客户端 | `Application/Functions/EEGDevice/ServiceClient.py` + `ServiceHost.py` | 中介线程: 连接/泵/断线重连; `eeg-gtec-service` 已在 ThreadRegistry |
| 空跑后端 | GtecStub（dry_run 路径） | 无头确定性测试 |
| 节点族 | 设备页 Init/Start/Stop/Kill/GetGtecData + 设备池 | MI-SSSEP 实验在用（兼容红线） |
| 数据链 | `RingBuffer`（锁定快照） | 采集→节点/面板消费模式 |
| 协议 | `Doc/Dev/device_io_protocol.md` §品牌/§服务 + §11 监视面板 | 品牌文件夹与进程纪律 |

## 1. TODO

### a) EEG 监视面板 — `ext.gtec.*`（✅ 2026-10-12 交付）
- [x] 窗口: `ctx.ui.register_window("Gtec Monitor", ..., close_policy="disable")` — 面板即扩展本体（X 关闭 = 停用闭环）
- [x] **信号视图**: 多通道实时波形（堆叠/包络 min-max 抽取/悬停读数/滚轮缩放）+ 每通道质量指标表（RMS/峰峰值/活跃度条）
- [x] 连接控制: Open / Start / Stop(save) / Close device（模式 sim | device | virtual）
- [x] 设备信息区: backend info（服务返回 serial / device_information）
- [x] **实时显示滤波**: notch / highpass / lowpass / bandpass（软件链, 滑窗+预热余量, 随时可改）
- [x] **采集落盘**: Stop(save) → npz/csv + json 元数据（session/buffer scope; sim 模式为 dry-run 不落盘）
- [x] **观察 vs 采集分离**: Watch（流式显示不落盘）· Record（显示+落盘; 监视中可升级）· `stop save=false` 弃录（2026-10-12）
- [x] **显示滤波选项 v2**: 谐波陷波（50+100 / 60+120）· 频带预设（broadband/delta/theta/alpha/beta/gamma/hp/lp）· IIR 阶数 2/4（2026-10-12）
- [x] `ext.gtec.*` ops 12 件套: status / open / close / watch / record / start(=record) / stop / filters / display / impedance / service(探针) / snapshot
- [x] **服务自动拉起**（`service_python` / `MGE_GTEC_PYTHON` → 动态端口 + 断开回收）+ 快速失败（~3s）+ 自解释报错（连接失败 vs init 失败两阶段区分）（2026-10-15）
- [x] **真机 TRIG 列**（65 列数据块）: 显示裁剪 / 录制保留 + `channels_saved`/`channel_names` 元数据（2026-10-15）
- [x] **阻抗浏览器**: 逐通道阻抗表（kΩ + good/medium/bad 着色; 门面 measure_impedance → pygds `GetImpedanceEx`，服务协议新增 `impedance` 命令; sim/virtual = 确定性合成演示值; 采集中拒绝）（2026-10-12）
  - [x] 实机链路验证（2026-10-15: 自动拉起→采集→TRIG→阻抗→释放 inuse=False; 256 值裁剪 + 哨兵→n/a）
  - [ ] 电极帽质量数据（需电极帽: 阈值分类校验 / TMS box 校正 / 重复测量稳定性）

### b) 进程架构纪律（✅ 本批保持）
- [x] 面板绝不直接触碰 gtec api: 一律经设备门面/ServiceClient（服务进程）— UI 零直接依赖
- [x] 断线/服务崩溃遏制: Open 失败显式报错 + 面板错误行展示（含服务启动指引）; 不下静默回退
- [x] 服务未启动场景快速失败（~3s, 不再等 20s 超时）+ 报错自解释（自动拉起命令 / A-B 分支指引）（2026-10-15）
- [x] 采集/显示隔离: 刷新节流（25 Hz）+ 环形缓冲只读拷贝; 显示滤波/抽取在引擎侧（毫秒级）
- [ ] 采集中 UI 帧率保护（长窗口大通道时的绘制预算）— 观测: 64ch/512Hz/4s 窗口下正常; 如需再降抽取列数

### c) 节点迁移
- [ ] Init/Start/Stop/Kill/GetGtecData + 设备池节点迁入扩展 Pack（type 名不变 — MI-SSSEP 红线）
- [ ] widgets 迁入扩展命名空间（`_device_name_field` 复用 device_common 模式）

## 2. 迁移注意

- **兼容红线**: 节点类型名/props/引脚不变; `dryrun#` 命名空间与确定性干跑保持。
- 服务协议版本: `hello` 握手保持向后兼容（Gtec env 是 3.9 — pickle proto=4 约束）。
- 面板依赖 gtec 实机时仅用于开发机验证; CI/无头一律走 stub。

## 3. 验收

- [x] sim 后端: 面板显示合成信号（确定性; `Test/Application/Extensions/test_gtec_extension.py` 91 checks 数值断言）
- [x] virtual 后端: 录制真实落盘（npz 形状/采样率/幅值断言 — 同一测试）
- [x] watch/record: 监视不累积录制（session scope = 0 样本）/ 监视中升级录制 / 弃录（同一测试）
- [x] 阻抗（无头）: sim 合成确定性 + 分类阈值边界 + 采集中拒绝 + virtual 路径（同一测试 + 服务协议闭环 `test_eeg_service.py`）
- [x] 实机 e2e: 引擎中 enable → 观察/采集 → 滤波 → 阻抗 → 截图（`Test/Application/Extensions/e2e_gtec_monitor_check.py` 47 checks; 2026-10-15 含真实 g.HIamp 全段）
- [ ] 实机（开发机）: g.HIamp 硬件 20 分钟连续采集不掉帧（短会话已验: 观察 1.5s + 录制 2.1s + 落盘; 长时浸泡待做）
- [ ] 服务进程 kill 后面板下次操作受控报错（现为显式 detail + 错误行; 重连策略未做）
- [ ] 迁移后 MI-SSSEP 场景加载/干跑零回归（节点迁移时执行）
