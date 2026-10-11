# Device (Serial/Parallel) Extension — TODO（状态档案）

> 状态: **partial + demo 交付**（监视面板 + `ext.device.*` ops 已交付 2026-10-11 → 官方示例扩展）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`device`; entry=extension.py; ops 前缀 `ext.device.*`）

## 0. 现状（已实现资产映射 — 复用来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| 设备 API | `Application/Functions/SerialParallelDevice/api.py`（+ `__init__` 门面） | 串口/并口打开/写/读; 线程 `spd-io`（已在 ThreadRegistry 注册） |
| 监视能力 | `Application/Functions/SerialParallelDevice/monitor.py`（新 2026-10-11） | 端口枚举 / RX poll（io_thread ≤50ms）/ 事件环缓 (500) / 统计 |
| 扩展本体 | `Functions/SerialParallelDevice/extension.py`（新 2026-10-11） | 监视面板（Serial/Parallel 页） + `ext.device.*` ops + 设置持久化 |
| IO 线程 | `Application/Functions/SerialParallelDevice/io_thread.py` | 委托线程（thread boundary 白名单 delegated） |
| 节点族 | `Core/NodeGraph/node_types` 设备页（Serial/Parallel Send/…） | 图驱动发送（MI-SSSEP 实验在用） |
| 协议 | `Doc/Dev/device_io_protocol.md` | 设备集成/双后端/线程纪律 |

## 1. TODO

### a) 实时监视面板（类串口/并口监视器）— ✅ 已交付（2026-10-11, `extension.py`）
- [x] 设备选取（端口枚举 + 刷新 + 手输兜底）
- [x] 配置区: 波特率（常用集 combo）; 并口地址（0x3FF8/3FF0/3FE8/378/278）
- [x] **信号可视化**: 接收字节流事件滚动显示（hex + ascii 预览）; 环形缓冲 + 锁保护快照
- [x] **发送行为配置**: 换行符（none/\n/\r\n）/ hex 输入模式 / （定时发送间隔未做）
- [x] Debug 面板: 统计（TX/RX/PX 计数、接收字节、最后错误、spd-io 线程状态）
- [ ] 发送快捷按钮组（可配置指令集取 `ctx.data_dir`）— 后续增强

### b) 发送节点（复用既有）
- [ ] 迁移 Serial/Parallel Send 节点到扩展 Pack（type 名保持不变 — MI-SSSEP 场景兼容红线）
- [x] `ext.device.*` ops: `status / list_ports / watch / send / monitor_snapshot / write_parallel`（agent 监视通道已通）

### c) 迁移形态
- [x] 面板经 `ctx.ui.register_window`（M1 已实装 — 本扩展为首个消费者）
- [ ] 节点 Pack 经 `ctx.nodes.register_pack`（M1）
- [x] 线程: 现有 `spd-io` 委托线程保持不变; 面板侧只读快照（无新增阻塞点）

## 2. 迁移注意

- **兼容红线**: 节点 type 名/props 不变（MI-SSSEP 实验工程在用 SerialSend/ParallelSend）。
- 线程纪律: 面板 UI 只读快照; 发送调用不得在渲染/主线程上阻塞等待（现有 api 已异步）。
- 干跑语义: 监视面板与发送节点的 dry-run 行为保持现状（不真开端口）。

## 3. 验收建议

- [x] 面板首启即注册（enable → 窗口出现 → disable → 窗口与 ops 同时清理; 测试 `test_extension_manager` + `test_extension_ui`）
- [ ] 真实/虚拟串口回环: 发送 "hello\n" → 收字节可见（需硬件 — 实机截图证据入库 `Test/_runs/`）
- [x] 配置持久化（`ctx.data_dir/settings.json`; 重开面板保持）
- [ ] 迁移后 MI-SSSEP 场景加载/干跑零回归（节点迁移完成后）
