# Gtec Device Extension — TODO（状态档案）

> 状态: **partial**（设备后端 + 服务进程 + 节点已实现; 监视面板未做; 尚未迁移到 extension 形态）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`gtec`; 节点/ops 前缀规划 `ext.gtec.*`）

## 0. 现状（已实现资产映射 — 复用来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| 品牌后端 | `Functions/EEGDevice/Gtec/`（backend/service/README） | **独立进程 + 自有 env**（gtec api 特性约束）; `[4B BE len][pickle proto=4]` 协议 |
| 服务客户端 | `Functions/EEGDevice/ServiceClient.py` + `ServiceHost.py` | 中介线程: 连接/泵/断线重连; `eeg-gtec-service` 已在 ThreadRegistry |
| 空跑后端 | GtecStub（dry_run 路径） | 无头确定性测试 |
| 节点族 | 设备页 Init/Start/Stop/Kill/GetGtecData + 设备池 | MI-SSSEP 实验在用（兼容红线） |
| 数据链 | `RingBuffer`（锁定快照） | 采集→节点消费模式 |
| 协议 | `Doc/Dev/device_io_protocol.md` §品牌/§服务 | 品牌文件夹与进程纪律 |

## 1. TODO

### a) EEG 监视面板（本次新增核心）— `ext.gtec.monitor`
- [ ] 窗口: `ctx.ui.register_window("gtec.monitor", "Gtec EEG 监视")`（M1 实装后接）
- [ ] **信号质量视图**: 多通道实时波形（`SignalScope` kit / implot）+ 每通道质量指标
      （方差/幅度/工频干扰粗检 — 来自环形缓冲快照, 不阻塞）
- [ ] **阻抗浏览**: 逐通道阻抗表（数值 + 色阶）; 手动刷新按钮 + 可选轮询间隔
      （低频 `ctx.threads.spawn(expect_hz≈0.5)`; 结果经队列进 UI）
- [ ] 设备信息区: 设备号 / 固件 / 采样率（服务进程 `info` 命令 — 现成）
- [ ] 连接控制: Connect / Disconnect / Start / Stop（按钮 → `ctx.tasks.post_main` 语义, M2）

### b) 进程架构纪律（Gtec 特殊性 — 保持现状 + 文档化）
- [ ] 面板绝不直接触碰 gtec api: 一律经 ServiceClient（中介线程）— UI 零阻塞
- [ ] 断线/服务崩溃遏制: 面板显示状态徽标（`connected / reconnecting / down`）,
      服务可由 `spawn_gtec` 逻辑自重启（现有机制保持）
- [ ] `ext.gtec.*` ops: `status` / `impedance.read` / `device.info`（agent 可见性, 可选）
- [ ] 采集中 UI 帧率保护: 数据快照拷贝采用「最新 N 样本」策略（环形缓冲滑动窗口）

### c) 节点迁移
- [ ] Init/Start/Stop/Kill/GetGtecData + 设备池节点迁入扩展 Pack（type 名不变 — MI-SSSEP 红线）
- [ ] widgets 迁入扩展命名空间（`_device_name_field` 复用 device_common 模式）

## 2. 迁移注意

- **兼容红线**: 节点类型名/props/引脚不变; `dryrun#` 命名空间与确定性干跑保持。
- 服务协议版本: `hello` 握手保持向后兼容（Gtec env 是 3.9 — pickle proto=4 约束）。
- 面板依赖 gtec 实机时仅用于开发机验证; CI/无头一律走 stub。

## 3. 验收建议

- [ ] stub 后端下: 面板显示合成信号 + 阻抗表固定值（确定性截图证据）
- [ ] 实机（开发机）: 20 分钟连续采集不掉帧（UI 帧率与采集互不阻塞; probe 线程年龄检查）
- [ ] 服务进程 kill 后面板 30s 内显示 down→重连状态流转
- [ ] 迁移后 MI-SSSEP 场景加载/干跑零回归
