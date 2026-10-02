# 设备 IO 层开发协议（Application/Functions）

> 适用：`SerialParallelDevice`（串口/并口）、`EEGDevice`（g.tec g.HIamp）等硬件集成。
> 节点求值器如何调用设备见 `node_editor_protocol.md`；UI 控件见 `ui_protocol.md`。

---

## 1. 域地图与两种既有架构

| 模块 | 架构 | 要点 |
|---|---|---|
| `Functions/SerialParallelDevice/` | 全局单例 + I/O 线程 + 队列 | `api.py`（start/stop/send/write_parallel）、`io_thread.py`、`state.py`、`test_hooks.py`；无驱动优雅降级；5ms 自动复位 |
| `Functions/EEGDevice/` | 会话注册表 + 后端协议 + 环形缓冲 + **品牌服务进程** | `Device.py`（后端无关：配置/缓冲/会话/注册表/落盘）、`ServiceProtocol/ServiceHost/ServiceClient.py`（品牌进程通信，见 §8）、`Gtec/`（品牌目录：真实 pygds + 服务入口; 自有环境）、`VirtualDevice/`（品牌目录：虚拟信号发生器 + 服务入口; 引擎环境）、`eCon/`（品牌目录：念通科技 econEXG 预留）、`__init__.py`（门面路由） |

共同约束：
- **不得反向依赖 Engine / Editor**；被求值器（`Application/Core/NodeGraph/evaluators/*`）调用。
- 门面 API 返回 `(ok, detail)` / `(result, detail)`，**不向上抛异常**（求值器把它转为 error 日志）。
- 真实不可用（驱动缺失/设备未连）→ 明确报错 + 优雅降级，**绝不静默伪造数据**。

---

## 2. 真实 / 空跑双后端契约（本层核心，MCP 空跑依赖）

- 后端接口：`DeviceBackend`（`configure / start / stop / close / pump / info`）。
- 空跑后端（`GtecStub`）规则：
  - 不触硬件、不落盘、不起线程（`pump` 同步补齐数据）；
  - **确定性**：同一时间轴 → 同一数组（干跑可复现）；
  - 合成总量封顶为窗口容量（避免长时间干跑占内存）；
  - 通过 `on_block` 走**与真实后端相同的数据通路**（环形缓冲/全量录制逻辑一并被验证）。
- 选择方式：门面 `_make_backend` 路由 —— 干跑（`ctx.dry_run=True`）走进程内确定性后端（GtecStub / Virtual dry，无进程零副作用）；真实模式默认走**品牌服务进程**（独立进程 + 协议通信，见 §8）；逃生门 `MGE_EEG_TRANSPORT=inproc` 退回进程内真实后端。
  **真实模式绝不回退 stub**（防实验数据污染），干跑才走 stub。
- 新增设备时同步实现两套后端 + 在 `Doc/Dev/README.md` §3 的验收命令下跑通。
  **纯软件设备例外**（如 `SigGen` — 虚拟信号发生器）：单一后端 + 构造参数 `dry_run` 控制
  `is_stub`/落盘（干跑不落盘、真实落盘），同样走会话/缓冲/导出全通路。

---

## 3. 数据与落盘约定

- 单位/类型：g.HIamp 数据为 **float32、µV**（GDS 已定标）。
- **窗口缓冲**：形状 `(channels, capacity)`，`capacity = buffer_seconds × fs`（上限
  `MAX_BUFFER_SAMPLES = 4e6`/通道）；环形写入、旧数据覆盖；快照按时间序，未填区 = 0，
  有效样本数单独给出（`samples`）。
- **导出文件**：形状 `(samples, channels)`（与 GtecAPI 脚本一致，便于 np.load/MNE 复用）。
  - `npz`：keys = `data / fs / channel_names / serial / duration_s`（压缩）；
  - `csv`：首行 `sample,<ch names...>`，行 = 采样点；
  - 两种格式都附同名 `.json` 元数据（设备信息、滤波器索引、起止时间、模式 stub/device、文件清单）。
  - 文件名：`<安全化设备名>_<YYYYmmdd_HHMMSS>.<ext>`；目录来自 Init 节点 `save_dir`
    （默认 `.` = 当前目录）。
- Stop 语义：`save_scope=session` 保存 Start 以来全部数据（内存拼接，受
  `MAX_RECORD_BYTES = 2 GiB` 保护，超限仅窗口继续更新）；`save_scope=buffer` 只保存当前窗口。
- `close_all()`：Runtime 停止安全网（**不保存**，丢弃数据）；由 `GameRuntime.start/stop` 调用。

---

## 4. 线程模型与自由线程引擎（重要）

- 引擎以 `-Xgil=0`（Python 3.14 自由线程）运行：**没有 GIL 保护**，跨线程共享结构必须加锁。
- 现有实现：`RingBuffer` 自带锁；`RecordingSession._on_block` 会话锁 + 录制内存保护；
  `_REGISTRY` 注册表锁。
- 真实采集：worker 线程跑 `d.GetData(user_block, more)`；`stop()` 置 flag → `more` 返回 False
  → GetData 内部 StopStreaming/StopAcquisition 收尾 → join。
- 空跑：`pump(elapsed_s)` 由**图线程**同步调用（无并发）。
- 时序坑（已修复，勿回退）：`RecordingSession.start()` 必须**先** `backend.start()`
  **再** `backend.pump(elapsed_s)` —— 空跑后端在 pump 中锚定仿真起点；顺序反了会得到空数据。

---

## 5. g.tec g.HIamp 实机要点（pygds）

- 环境：引擎 venv 需装 g.tec 官方 `pygds` wheel（+ cffi/pywin32/matplotlib）；Windows 服务
  **GDS** 必须运行；设备不得被 g.Recorder / g.SCOPE 占用。参考 `C:\WorkSpace\FLY\GtecAPI\`。
- `pygds` **必须懒导入**（真实路径内），import 会连带 matplotlib/pywin32 —— 干跑机器无此依赖。
- pygds 1.24.0 bug：`GDS(DEVICE_TYPE_*)` 抛 `UnboundLocalError`，**必须传序列号字符串**。
- 采样率：256/512/600/1200/2400/4800/9600/19200/38400；`NumberOfScans` 用
  `GetSupportedSamplingRates()[rate]`；用户块 = 整数个设备块（默认 ~100ms）。
- Trigger：**固定启用**（16 条数字线合并为 1 个附加通道，"combine"）；计数器/Hold 关闭。
- 滤波器是**离散预设**（`GetNotchFilters` / `GetBandpassFilters`，按采样率分组）；
  匹配用容差查找，匹配不到 → 跳过 + 告警（不阻塞采集）。截止频率语义（0=未填、
  类型不匹配忽略）在 `Device.GtecConfig.effective_filters()` 中定义并被测试覆盖。
- 通道：`GetAvailableChannels(combine=False)` 才是硬件真实可用性（`combine=True` 会 AND
  `Acquire` 标志，直读可能"只有 16 通道"）；阻抗测量要求通道 1 接 GND，且通道采样后
  前 1s 为 DC 建立瞬态（分析时丢弃）。
- 元数据：`d.GetDeviceInformation()` 多行字符串进 JSON `<dev_info>`。

---

## 6. Runtime 集成

- `GameRuntime.start()`：清理上次残留 EEG 会话（异常退出保护）；`stop()` 末尾再次
  `close_all()`（图内 `OnGameStop` 链（含 StopGtecRecord/KillGtecDevice）已执行完，此处兜底）。
- PIE 重复运行：同名 `InitGtecDevice` 会**替换**旧会话（门面内先 kill 再注册）。
- 图内生命周期（Init→Start→Get…→Stop→Kill）与 Runtime 安全网是两层保障，缺一不可。

---

## 7. 设备池 (Device Pool)

设备池 = 设备的分组 / 生命周期 / (未来) 进程组与同步域锚点（模块级注册表, `Device.py`）。

- 门面 API：`create_pool / destroy_pool / add_to_pool / pool_of / pool_members / list_pools / reset_pools`；
  隐式 `global` 池始终存在（未入显式池的设备），不可创建/销毁。
- **排他成员制**：一个设备同一时刻只属一个池；`add_to_pool` 到新池 = 移动（日志记录）；
  `kill_device` 自动脱池；`destroy_pool` 成员回落 `global`；`close_all` 连池一并清空。
- 池作用域绑定：`resolve_session(name, pool)` —— `name` 非空按名称解析；空名 + `pool=None`
  保持旧语义（全注册表唯一会话自动绑定）；空名 + 池 → 池内唯一设备自动绑定（多设备报歧义）。
- 节点侧（IO ▸ Pool）：`CreateDevicePool ⇄ KillDevicePool` 强制配对（校验 + 编辑器级联，
  与设备族同一套规则）；`AddToDevicePool` 读 Init `device` pin 的会话键入池 —— **必须与对应
  Init 排在同一条 exec 链、紧跟其后执行**（pin 值仅一个 trigger 内有效）。
- 键规则单点定义在 `graph_constraints`（`device_session_key` / `pool_key`），
  评估器 / 校验器 / UI 下拉三处共用，禁止另写变体。
- 干跑隔离：池与会话共用 `dryrun#` 命名空间，任务结束由 `validation/dry_run.py` 一并清理。
- **品牌目录布局（2026-10-03 已落地）**：`Functions/EEGDevice/{Gtec, eCon, VirtualDevice}/` 三个品牌目录
  —— **一个品牌（一个 API）= 一个独立文件夹 + 独立环境**（Gtec/eCon 自有环境；VirtualDevice 用引擎
  环境）；品牌 = 独立进程文件应用（后端 + `service.py`，见 §8）。导出**按需包含**：项目未引用某品牌时，
  其目录（含未来成品环境）不随导出。设备池 = 进程组管理单元（池条目 `meta` 预留进程句柄/启动参数）。
  延伸规则：`Functions/` 下未来一律按**终端可安装的可选拓展**演进（仅备忘，暂不施工）。

---

## 8. 品牌服务进程（独立进程 + 协议通信）

品牌目录 = 独立进程文件应用：后端实现 + `service.py` 入口 +（未来）随目录携带的环境。
引擎与品牌之间只经一条协议通信，节点图侧零改动。

| 组件 | 位置 | 职责 |
|---|---|---|
| `ServiceProtocol.py` | 共享 | 帧格式 `[4B 大端长度][pickle(protocol=4)]`；3.9+ 兼容（服务可能跑在低版本环境） |
| `ServiceHost.py` | 服务侧 | 命令循环 hello/init/start/pump/stop/kill/info/shutdown；push 模式采集线程加锁写 socket |
| `ServiceClient.py` | 引擎侧 | `ServiceBackend`（DeviceBackend 实现）；pump/push 双模式；rid 路由 + 单读者线程 |

- **数据模式**：`pump`（合成后端——块随响应同步返回，与进程内逐位一致，确定性来源）；
  `push`（真实硬件——start 后采集线程持续推送，引擎接收线程写会话环形缓冲）。
- **保存仍在引擎侧**：服务只提供数据；npz/csv/元数据落盘逻辑与进程内完全一致。
- **生命周期**：VirtualDevice 引擎自动拉起（`sys.executable`，引擎环境，动态端口，日志在系统 temp）；
  Gtec 外部启动（自有环境；`MGE_GTEC_SERVICE=host:port`，默认 127.0.0.1:47810）；
  客户端断开 → 服务退出（引擎崩溃自动清理）；`kill/close` 发 shutdown 并回收子进程。
- **连通失败诊断**：报错含启动提示 + 服务日志尾部（自动拉起场景）。
- 验证：`Test/Application/Functions/test_eeg_service.py`（往返/确定性/端到端保存/逃生门/进程清理 +
  Gtec 3.9 跨版本握手——不触硬件）。
- 待办：Gtec 实机联调（自有环境启动服务 + 硬件会话）、PIE E2E 复跑、品牌目录随环境打包（规划见 §7）。

---

## 9. 测试

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_gtec_device.py        # 设备层 + 干跑 + 约束 (48 checks)
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_siggen_device.py      # 虚拟信号发生器 (配置/会话/落盘/干跑/配对)
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_serial_parallel_device.py
```

- 干跑用例必须断言：静态校验零错误、`events_by_type` 覆盖全链路节点、干跑后注册表为空。
- 测试模式遵循 `Test/_path_setup.py` 引导；参考 SPD 测试的 `check()` 累加式写法。

---

## 10. 已知坑（实战教训）

1. 空跑 pump 时序（§4）—— 顺序错误的症状是"数据全 0 / valid=0"。
2. 真实模式不得伪造数据（§2）—— 采集失败要显式报错，宁缺毋假。
3. 内存保护：缓冲区（`MAX_BUFFER_SAMPLES`）与全量录制（`MAX_RECORD_BYTES`）都有上限，
   超限行为已定义（截断 / 仅窗口更新），新增设备沿用同一策略。
4. 自由线程下忘加锁 → 概率性数据错乱，且很难复现；所有跨线程结构一律加锁。
5. 设备释放要幂等：`close_all` / `kill` 允许重复调用（异常保护包裹）。
6. 不要在 import 期做设备探测（`probe_environment` 只做只读探测且吞异常，供日志用）。
7. 服务命令顺序：`shutdown` 必须在任意状态可用（未 init 也允许）——否则 init 失败的收尾路径卡死；
   `kill` 无会话时宽容返回（幂等）。服务进程客户端断开即退出（不驻留）。
8. 控制台编码：GBK 环境**管道输出**（如 `| Select-Object`）遇非 GBK 字符（`↔` 等）会 UnicodeEncodeError
   —— 测试脚本打印只用 GBK 覆盖的符号（`──` `×` `→` 可用，箭头互指用 `<->`）。
