# VirtualDevice — 虚拟信号发生器品牌目录（进程化数据源）

## 角色

作为设备模块的后端与服务（单目录自包含模块的组成之一），身份特殊：**它是进程通信机制的验证平台** ——
用与外部品牌服务完全相同的协议与服务形态运行，验证“品牌 = 独立进程 + 数据通信”的整套设计，
且不依赖任何硬件。

## 组成

| 文件 | 职责 |
|---|---|
| `SigGen.py` | `SigGenConfig` + `VirtualSigGenBackend`（确定性正弦源; dry/live 双模式） |
| `service.py` | 服务进程入口（`pump` 模式; 引擎自动拉起） |

## 环境（与另外两者不同：**直接用引擎本体环境**）

- 无额外依赖 → 引擎可以用 `sys.executable` 直接拉起服务进程（冷启动 ≈ 1s）；
- 这也意味着导出/安装后无需为它携带任何环境。

## 数据模式

**pump**：块由 `pump(elapsed)` 命令同步生成并随响应返回 —— 与进程内调用序列完全一致，
因此**同一时间轴的合成数据逐位相同**（干跑/实采算法验证的确定性来源）。

## 与节点图的关系

节点图侧无需任何特殊处理：门面（`VirtualDevice._make_backend`）在真实模式默认路由到本服务；
干跑（`dry_run=True`）仍走进程内合成（无进程、零副作用）。

## 触发链路（附加通道）

真实硬件数据块可带一列**触发合成列**（16 线合并 → 1 列; 布局 `(n, channels+1)`）:

- **显示 / 节点**: 只消费 EEG 主通道（`RecordingSession._on_block` 裁列后进环形缓冲）;
- **录制**: 原始块全列落盘（`channel_names` 末列名 = `TRIG`）;
- **事件通路**: `RecordingSession.get_trigger_events(start=0)`（门面同名包装）—— 附加列沿变检出
  `[{sample, t_s, code}]`（增量游标、上限 10 万条、线程安全）; 落盘元数据含 `trigger_events` /
  `trigger_events_count`; `trigger_events_for_scope(scope)` 按 session/buffer 段截取;
- **合成触发源**（无硬件回归）: `SigGenConfig.trigger_every_s > 0` 时合成器追加同布局触发列
  （每 T 秒一个 10ms 脉冲、码值 1..4 循环; 由绝对样本号计算 → 确定性, 与块边界无关）。

## 服务自动拉起（外部品牌）

`ServiceBackend.connect_brand(python_exe, module)`: 给出 (配置 `service_python` / env
`MGE_EEG_SERVICE_PYTHON`) 的 python **且** (配置 `service_module` / env
`MGE_EEG_SERVICE_MODULE`) 的品牌服务模块 → 引擎自动拉起品牌服务
（自有环境, 动态端口, 断开回收子进程）; 只给其一 → 连接已运行服务 / 默认端点（与既有行为一致）。
显式 `MGE_EEG_SERVICE=host:port` 时始终按它连接（不自动拉起）。
