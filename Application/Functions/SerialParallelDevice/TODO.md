# Device (Serial/Parallel) Extension — TODO（状态档案）

> 状态: **v0.3.0 — 监视面板 + 逻辑设备名 + NodePack 注入 + 自动重绑已交付；2026-10-20 起由现任维护 agent 接手（core 58/58 全绿）**
> **接手入口: `HANDOFF.md`（交接书）+ `HANDOFF_PROMPT.md`（启动提示词）— 新维护者先读这两份**
> **2026-10-20 节点包迁移**: `Doc/NODE_PACK_MIGRATION_2026-10-20.md`（已迁出核心；Serial 侧收尾清单）
> 开发规范: `engine-editor-cli doc show extdev/extension_dev_protocol` · 架构: `engine-editor-cli doc show dev/extension_protocol`
> 设备协议: `engine-editor-cli doc show dev/device_io_protocol`（§10 = 逻辑设备名）
> 注: `Doc/...` 下同名文件是 CLI 迁移后的入口占位页；正文权威在工具仓库 `docs_content/`
> manifest: `extension.json`（id=`device`; entry=extension.py; ops 前缀 `ext.device.*`; capabilities `ops/nodes/ui/graph`）

## 0. 现状（已实现资产映射 — 复用来源）

| 资产 | 位置 | 说明 |
|---|---|---|
| 设备 API | `Application/Functions/SerialParallelDevice/api.py`（+ `__init__` 门面） | 串口/并口打开/写/读; 线程 `spd-io`（已在 ThreadRegistry 注册） |
| 监视能力 | `Application/Functions/SerialParallelDevice/monitor.py`（新 2026-10-11） | 端口枚举 / RX poll（io_thread ≤50ms）/ 事件环缓 (500) / 统计 |
| 扩展本体 | `Application/Functions/SerialParallelDevice/extension.py`（新 2026-10-11） | 监视面板（Serial/Parallel 页） + `ext.device.*` ops + 设置持久化 |
| IO 线程 | `Application/Functions/SerialParallelDevice/io_thread.py` | 委托线程（thread boundary 白名单 delegated） |
| 节点族 | `Application/Functions/SerialParallelDevice/node_pack.py` | Serial/Parallel Send 类型+求值器+fields；`NodePackRegistry` 自动发现 |
| USB 指纹/自动重绑 | `identity.py` + `extension.py::_op_autobind` | serial > vid:pid；歧义显式拒绝 |
| 协议 | `engine-editor-cli doc show dev/device_io_protocol` | 设备集成/双后端/线程纪律（正文在工具仓库 `docs_content/`） |

## 1. TODO

### a) 实时监视面板（类串口/并口监视器）— ✅ 已交付（2026-10-11, `extension.py`）
- [x] 设备选取（端口枚举 + 刷新 + 手输兜底）
- [x] 配置区: 波特率（常用集 combo）; 并口地址（0x3FF8/3FF0/3FE8/378/278）
- [x] **信号可视化**: 接收字节流事件滚动显示（hex + ascii 预览）; 环形缓冲 + 锁保护快照
- [x] **发送行为配置**: 换行符（none/\n/\r\n）/ hex 输入模式 / （定时发送间隔未做）
- [x] Debug 面板: 统计（TX/RX/PX 计数、接收字节、最后错误、spd-io 线程状态）
- [ ] 发送快捷按钮组（可配置指令集取 `ctx.data_dir`）— 后续增强

### b) 发送节点（复用既有）
- [x] 迁移 Serial/Parallel Send 节点到扩展 Pack（type 名保持不变 — MI-SSSEP 场景兼容红线）；`node_pack.py` 自动发现注入
- [x] `ext.device.*` ops: `status / list_ports / watch / send / monitor_snapshot / write_parallel`（agent 监视通道已通）
- [x] **逻辑设备名（`@alias`）闭环（2026-10-12）**: `bind_alias` / `bind_nodes` + 面板 "Device names (@alias)" 段（Rebind / Unbind / Migrate N node(s)）+ `status` 别名视图；本机注册表 = `Application/Core/DeviceRegistry.py`（`device_io` §10）
- [x] **面板 ↔ 场景同步示范（2026-10-12）**: 经 `ctx.graph`（capabilities 含 `graph`）读/写当前图节点 props；面板按钮与 agent 同一实现（动作单点）
- [x] **自动重绑（P0）**: `identity.py` 指纹（serial > vid:pid，location 只诊断）+ `ext.device.autobind` + 面板 Auto-detect + enable 自动重绑 + 换口时面板端口跟随；单测 27/27；实机已验证“过期口 → 自动恢复”（物理拔插为可选复验）

### c) 迁移形态
- [x] 面板经 `ctx.ui.register_window`（M1 已实装 — 本扩展为首个消费者）
- [x] 节点 Pack 由 `node_pack.py` 自动发现注入（`NodePackRegistry`；无需扩展 enable）
- [x] 线程: 现有 `spd-io` 委托线程保持不变; 面板侧只读快照（无新增阻塞点）

## 2. 迁移注意

- **兼容红线**: 节点 type 名/props 不变（MI-SSSEP 实验工程在用 SerialSend/ParallelSend）。
- 线程纪律: 面板 UI 只读快照; 发送调用不得在渲染/主线程上阻塞等待（现有 api 已异步）。
- 干跑语义: 监视面板与发送节点的 dry-run 行为保持现状（不真开端口）。

## 3. 验收建议

- [x] 面板首启即注册（enable → 窗口出现 → disable → 窗口与 ops 同时清理; 测试 `test_extension_manager` + `test_extension_ui`）
- [ ] 真实/虚拟串口回环: 发送 "hello\n" → 收字节可见（需硬件 — 实机截图证据入库 `Test/_runs/`）；
      串并口三件套当前基线: alias 32/32 · serial_parallel 33/33 · monitor 14/14
- [x] 配置持久化（`ctx.data_dir/settings.json`; 重开面板保持）
- [x] 逻辑设备名闭环单测（`Test/Application/Functions/test_device_alias.py` 32/32）+ autobind 27/27 + node_pack 17/17 + scalar_math 10/10 + 审查器 18 PASS / 0 FAIL + core 58/58（2026-10-20）
- [x] 实机 e2e（`Test/_runs/e2e_device_alias/`: bind_alias → bind_nodes 迁移 → 面板截图）
- [x] MI-SSSEP 设计工程 v1/v2 场景已迁到 `@SSSEP-Stimulator` 并成功导出（project + rst 成品，0 警告）
- [x] **手工换口重绑验收（2026-10-20）**: ESP32/CH340 `COM3 -> COM14`，`bind_alias` 后 V2 PIE 在新口 TX 72 / PX 73，`watch.opened=True`、无错误；场景未改（仍 `@SSSEP-Stimulator`）。`bind_alias` 现会同步面板 `port/baud`。
- [x] 自动重绑验收（伪造端口列表单测 + 实机过期口→自动恢复；物理拔插为可选复验）
- [ ] 迁移后 MI-SSSEP 场景加载/干跑零回归（节点迁移完成后）
