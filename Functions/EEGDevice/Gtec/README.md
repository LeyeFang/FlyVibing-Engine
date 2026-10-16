# Gtec — 监视面板扩展（ext.gtec）

> 状态: **partial**（面板已交付（含观察/采集分离与阻抗视图）; 节点迁移未做 — 见 `TODO.md`）
> 规范: `Doc/ExtDev/extension_dev_protocol.md` · 设备域协议: `Doc/Dev/device_io_protocol.md` §11

类经典信号工具的实时监视面板: **自由启停 / 实时波形观察 / 软件实时滤波 / 电极阻抗 /
采集落盘**，外加 agent（CLI / MCP）控制通道 `ext.gtec.*`。面板绝不直接触碰设备 API ——
一切经设备门面（`Application.Functions.EEGDevice`）与品牌服务进程架构。

两个正交概念（2026-10-12 起明确区分）:

- **Watch（观察）** = 只流式收数据 + 实时显示波形，**不写文件**;
- **Record（采集）** = Watch 之上累积全量数据，Stop 落盘（npz/csv + json）;
- 监视中可随时升级为录制（从升级时刻起录）; Stop 时若在录制则自动保存，弃录可用 `save=false`。

## 组成

| 文件 | 职责 |
|---|---|
| `extension.json` | manifest（capabilities: ops / ui / device） |
| `extension.py` | 扩展类: 生命周期 / 会话控制 / ops / 面板布局 |
| `gtec_display.py` | 显示管线（纯 DSP）: 滤波链（谐波陷波→频带, 滑窗+预热余量; 2/4 阶）/ min-max 抽取 / 统计 / 标尺 |
| `gtec_scope.py` | 示波器绘制（imgui draw_list 包络折线 / 网格 / 悬停读数 / 质量表） |
| `TODO.md` | 状态档案与待办 |

> 品牌实现（后端 + 服务入口）位于 `Application/Functions/EEGDevice/Gtec/` —
> 本目录只放**扩展贡献**（见 `Doc/Dev/extension_protocol.md` 三层高度模型）。

## 使用

1. 编辑器 **Extensions** 菜单勾选 `Gtec Device`（或 `engine-editor-cli call extension.enable id=gtec`）。
2. 面板 `Gtec Monitor` 中选 **Mode** → `Simulated`（无硬件, 确定性合成, 不落盘）→ Open →
   **Watch**（只看波形, 不写文件）或 **Record**（采集 + 落盘; 监视中可随时升级）。
3. 真实硬件: 面板选 `Device (g.HIamp service)` → **Svc python** 填 Gtec 自有环境 python
   （如 `C:\WorkSpace\FLY\GtecAPI\.venv\Scripts\python.exe`，一次填入即持久化）→ Open 时
   自动拉起服务（动态端口，断开回收）。留空 = 连接已运行服务（`MGE_GTEC_SERVICE` 或默认
   127.0.0.1:47810）；也可手动启动: `<python> -m Application.Functions.EEGDevice.Gtec.service --port 47810`。
4. `Simulator (VIRTUAL service)` = 引擎自动拉起的虚拟信号发生器（连续合成 + Stop 真实落盘）—
   用于无硬件环境下验证完整录制链路。
5. **Impedance** 视图页（右栏）: Open 后（未在采集中）点 Measure → 逐通道阻抗表
   （good/medium/bad 着色; 被动 <7.5 / 7.5–20 / >20 kΩ, 主动 <65 / 65–200 / >200 kΩ; ch1 恒 n/a）。

模式对照:

| mode | 后端 | 数据 | Stop 落盘 |
|---|---|---|---|
| `sim` | 进程内 Gtec stub（确定性） | 合成（窗口容量封顶） | dry-run — 只算路径不写文件 |
| `device` | Gtec 服务（自动拉起* / 外部已运行, push） | 真实 g.HIamp | npz/csv + json |
| `virtual` | VIRTUAL 服务（引擎自动拉起, pump） | 合成（连续） | npz/csv + json |

\* 自动拉起 = 面板 **Svc python** 指定自有环境 python（留空则连接已运行服务）。

## agent 通道（ops, `ext.<id>.` 前缀由宿主强制）

| op | 参数 | 说明 |
|---|---|---|
| `ext.gtec.status` | — | 会话/录制/滤波器/阻抗/落盘/后端信息总览 |
| `ext.gtec.open` | `mode?, sampling_rate?, buffer_seconds?, save_dir?, export_format?, serial?, template?, notch?, filter_type?, low_cut?, high_cut?, sim_*` | 创建会话 |
| `ext.gtec.close` | `save?=true` | 录制中先落盘再关会话（释放设备/服务） |
| `ext.gtec.watch` | — | 开始观察（流式 + 显示, **不写文件**） |
| `ext.gtec.record` | — | 开始录制（显示 + 落盘）; 监视中调用 = 从此刻升级 |
| `ext.gtec.start` | — | `record` 的兼容别名 |
| `ext.gtec.stop` | `scope?=session\|buffer, save?=true\|false（默认 auto）` | 停止流式采集（录制→保存; 观察→无落盘; save=false=弃录） |
| `ext.gtec.filters` | `enabled?, preset?, order?=2\|4, notch?=off\|50\|60\|50+100\|60+120, band_type?, low?, high?` | 显示滤波链（实时软件滤波） |
| `ext.gtec.display` | `window_s?, amplitude_uv?(0=auto), channel_start?, channel_count?, freeze?` | 视口设置 |
| `ext.gtec.impedance` | `measure?=true, electrode_type?=passive\|active, tms_box?=false` | 电极阻抗测量（kΩ + 分类; 设备需 Open 且空闲） |
| `ext.gtec.service` | `probe?=true` | 服务连通探针（endpoint/reachable/hint; 排障用, 不开会话） |
| `ext.gtec.snapshot` | `preview?=true, preview_channels?=3, points?=128, max_channels?=16` | 波形统计（mean/rms/ptp）+ 数值预览（agent 验证用） |

```powershell
engine-editor-cli call ext.gtec.open mode=sim sampling_rate=512 save_dir=Test/_runs/gtec_demo
engine-editor-cli call ext.gtec.watch                 # 只看波形
engine-editor-cli call ext.gtec.record                # 升级为采集
engine-editor-cli call ext.gtec.snapshot max_channels=4
engine-editor-cli call ext.gtec.stop scope=session    # 落盘
engine-editor-cli call ext.gtec.impedance electrode_type=passive
```

## 故障排查（2026-10-15 实机教训）

- `cannot connect gtec service @ ...` = **服务没起**（与 g.Recorder 占用无关）:
  ① 面板 Svc python 填好自有环境 python → Open 自动拉起; ② 手动起服务; ③ `ext.gtec.service` 看 hint。
- `init failed ...` = 服务已起但对设备初始化失败 — 这时才需检查设备是否被 **g.Recorder** 等占用。
- 观察中报 session not found: PIE start/stop 会重置全部设备会话（close_all）— 重新 Open 即可。

## 数据通路（与节点图同一条）

```
Watch  → facade start_record(record=False) → 品牌服务（push 采集 / pump 合成）
Record → facade start_record(record=True)（监视中 = 从此刻升级; 累积全量数据）
刷新(~25 Hz) → session.get_data(elapsed)（环形缓冲时间序拷贝）
    → SignalView: 显示滤波（滑窗+预热余量, 无跨帧状态）+ min/max 抽取 + 统计
    → gtec_scope 绘制（点列按版本缓存）
Stop → session.stop(save=auto) → 录制 = 引擎侧落盘（npz/csv + 同名单 json）; 观察 = 无落盘
阻抗 → facade measure_impedance（设备空闲操作; sim/virtual 合成, device = pygds GetImpedanceEx）
```

## 边界（有意为之）

- 显示滤波为**因果 IIR、非零相位**（实时工具行为; 离线分析请用 `Functions/SignalProcess`）。
- 阻抗测量是**设备空闲操作**: 流式采集中拒绝（先 Stop 再 Measure）; 通道 1 恒 NaN 为硬件特例;
  sim/virtual 返回确定性合成演示值（`simulated` 标记）; TMS box 校正参数直接透传 pygds。
- `sim` 合成量封顶一个窗口容量（干跑确定性设计）; 连续演示请用 `virtual`。
- 真机数据块含**触发合成列 TRIG**（65 列）: 显示只取 EEG（行为与节点一致）; 录制 npz 保留
  TRIG 列 + `channel_names`/`channels_saved` 元数据。
- 节点族仍在核心（迁移红线保护 MI-SSSEP）; 阻抗**实机链路已验证**（2026-10-15: 256 值裁剪至
  会话通道、负值哨兵 → n/a）; 电极帽质量数据（阈值分类校验）待做。
- UI 文本全程 ASCII / FontAwesome（字形图集约束 — `Doc/Dev/ui_protocol.md` §12）。

## 验证

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Extensions/test_gtec_extension.py   # 92 checks（无头）
.venv-py314t\Scripts\python.exe FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py Functions/EEGDevice/Gtec
# 实机（需引擎运行中; 含真实 g.HIamp 段 — 无 GtecAPI 环境时自动 SKIP）:
.venv-py314t\Scripts\python.exe Test/Application/Extensions/e2e_gtec_monitor_check.py   # 47 checks
```
