# 设备 IO 层开发协议（Application/Functions）

> 适用：`SerialParallelDevice`（串口/并口）、`EEGDevice`（g.tec g.HIamp）等硬件集成。
> 节点求值器如何调用设备见 `node_editor_protocol.md`；UI 控件见 `ui_protocol.md`。

---

## 1. 域地图与两种既有架构

| 模块 | 架构 | 要点 |
|---|---|---|
| `Functions/SerialParallelDevice/` | 全局单例 + I/O 线程 + 队列 | `api.py`（start/stop/send/write_parallel）、`io_thread.py`、`state.py`、`test_hooks.py`；无驱动优雅降级；5ms 自动复位 |
| `Functions/EEGDevice/` | 会话注册表 + 后端协议 + 环形缓冲 | `Device.py`（后端无关：配置/缓冲/会话/落盘）、`Gtec.py`（真实 pygds）、`GtecStub.py`（空跑）、`__init__.py`（门面） |

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
- 选择方式：求值器按 `ctx.dry_run` 选择后端（`EEGDevice.init_session(..., dry_run=...)`）；
  **真实模式绝不回退 stub**（防实验数据污染），干跑才走 stub。
- 新增设备时同步实现两套后端 + 在 `Doc/Dev/README.md` §3 的验收命令下跑通。

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

## 7. 测试

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_gtec_device.py        # 设备层 + 干跑 + 约束 (48 checks)
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_serial_parallel_device.py
```

- 干跑用例必须断言：静态校验零错误、`events_by_type` 覆盖全链路节点、干跑后注册表为空。
- 测试模式遵循 `Test/_path_setup.py` 引导；参考 SPD 测试的 `check()` 累加式写法。

---

## 8. 已知坑（实战教训）

1. 空跑 pump 时序（§4）—— 顺序错误的症状是"数据全 0 / valid=0"。
2. 真实模式不得伪造数据（§2）—— 采集失败要显式报错，宁缺毋假。
3. 内存保护：缓冲区（`MAX_BUFFER_SAMPLES`）与全量录制（`MAX_RECORD_BYTES`）都有上限，
   超限行为已定义（截断 / 仅窗口更新），新增设备沿用同一策略。
4. 自由线程下忘加锁 → 概率性数据错乱，且很难复现；所有跨线程结构一律加锁。
5. 设备释放要幂等：`close_all` / `kill` 允许重复调用（异常保护包裹）。
6. 不要在 import 期做设备探测（`probe_environment` 只做只读探测且吞异常，供日志用）。
