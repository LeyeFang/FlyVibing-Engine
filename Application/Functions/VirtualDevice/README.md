# Virtual Device — 波形监视面板扩展（ext.virtual）

> 状态: **partial**（波形监视面板已交付; 见 `TODO.md`）
> 规范: `Doc/ExtDev/extension_dev_protocol.md` · 设备域协议: `Doc/Dev/device_io_protocol.md`
> 角色: **设备族面板扩展的官方示例**（沿用社区设备监视面板的设计语言, 代码为干净重写）
> 设计参考: 归档 `Test/_gtec_archive_20261016/`（本地留档; 不随仓库分发）

类经典信号工具的实时观察面板: **自由启停 / 实时波形观察 / 软件实时滤波 / 采集落盘**，
外加 agent（CLI / MCP）控制通道 `ext.virtual.*`。面板绝不直接触碰设备 API —— 一切经设备门面
（`Application.Functions.VirtualDevice`）与会话注册表。

两个正交概念:

- **Watch（观察）** = 只流式收数据 + 实时显示波形，**不写文件**;
- **Record（采集）** = Watch 之上累积全量数据，Stop 落盘（npz/csv + json）;
- 监视中可随时升级为录制（从升级时刻起录）; Stop 时若在录制则自动保存。

## 组成

| 文件 | 职责 |
|---|---|
| `extension.json` | manifest（capabilities: ops / ui / device） |
| `extension.py` | 扩展类: 生命周期 / 会话控制 / ops / 面板布局 |
| `virtual_display.py` | 显示管线（纯 DSP）: 显示滤波链（陷波/频带, 2/4 阶因果 IIR）/ min-max 抽取 / 统计 / 标尺 / 数值预览 |
| `virtual_scope.py` | 示波器绘制（imgui draw_list 包络 / 网格 / 悬停读数 / 统计表） |
| `TODO.md` | 状态档案与待办 |

> 本目录 = 完整设备模块（单目录自包含）: 面板扩展 + 后端（`SigGen.py`）+ 服务（`service.py`）
> + 会话核心（`Device.py` / `Service*.py`）; 游戏运行时不装载扩展（ExtensionManager 仅编辑器侧）。

## 使用

1. 编辑器 **Extensions** 菜单勾选 `Virtual Device`（或 `engine-editor-cli call extension.enable id=virtual`）。
2. 面板 `Virtual Device Monitor`: 选 **Mode** → `Simulated`（无硬件, 确定性合成, 不落盘）→ **Open** →
   **Watch**（只看波形, 不写文件）或 **Record**（采集 + 落盘; 监视中可随时升级）。
3. 连续/落盘演示: Mode → `Virtual service`（引擎自动拉起 VIRTUAL 服务; 连续合成 + Stop 真正落盘）。

模式对照:

| mode | 后端 | 数据 | Stop 落盘 |
|---|---|---|---|
| `sim` | 进程内虚拟后端（确定性） | 合成（窗口容量封顶） | dry-run — 只算路径不写文件 |
| `virtual` | VIRTUAL 服务（引擎自动拉起, pump） | 合成（连续） | npz/csv + json |

## agent 通道（ops, `ext.<id>.` 前缀由宿主强制）

| op | 参数 | 说明 |
|---|---|---|
| `ext.virtual.status` | — | 会话/流式/录制/滤波器/视图状态总览 |
| `ext.virtual.open` | `mode?, channels?, sampling_rate?, frequency?, freq_step?, amplitude_uv?, noise_uv?, seed?, buffer_seconds?, save_dir?, export_format?` | 创建会话 |
| `ext.virtual.close` | `save?=true` | 录制中先落盘再关会话（释放设备/服务） |
| `ext.virtual.watch` | — | 开始观察（流式 + 显示, **不写文件**） |
| `ext.virtual.record` | — | 开始录制（显示 + 落盘）; 监视中调用 = 从此刻升级 |
| `ext.virtual.stop` | `scope?=session\|buffer, save?=true\|false` | 停止流式（录制→保存; 观察→无落盘） |
| `ext.virtual.filters` | `enabled?, notch?=off\|50\|60, filter_type?=none\|highpass\|lowpass\|bandpass, low?, high?, order?=2\|4` | 显示滤波链（实时软件滤波） |
| `ext.virtual.display` | `window_s?, amplitude_uv?(0=auto), channel_start?, channel_count?, freeze?` | 视口设置 |
| `ext.virtual.snapshot` | `points?, preview_channels?, max_channels?` | 波形统计（mean/rms/ptp）+ 数值预览（agent 验证用） |

```powershell
engine-editor-cli call ext.virtual.open mode=sim sampling_rate=512 save_dir=Test/_runs/virtual_demo
engine-editor-cli call ext.virtual.watch          # 只看波形
engine-editor-cli call ext.virtual.record         # 升级为采集
engine-editor-cli call ext.virtual.snapshot preview_channels=2
engine-editor-cli call ext.virtual.stop scope=session   # 落盘（sim 为 dry-run）
engine-editor-cli call ext.virtual.close
```

## 数据通路（与节点图同一条）

```
Watch  -> facade start_record(record=False) -> 后端（sim 进程内 / virtual 服务 pump）
Record -> facade start_record(record=True)（监视中 = 从此刻升级; 累积全量数据）
刷新(~25 Hz) -> session.get_data(elapsed)（环形缓冲时间序拷贝）
    -> SignalView: 显示滤波（因果 IIR）+ min/max 抽取 + 统计
    -> virtual_scope 绘制（点列按版本缓存）
Stop -> session.stop(save=auto) -> 录制 = 引擎侧落盘（npz/csv + 同名 json）; 观察 = 无落盘
```

## 边界（有意为之）

- 显示滤波为**因果 IIR、非零相位**（实时工具语义; 离线分析请用离线工具链）。
- 虚拟设备**无硬件滤波/阻抗语义** —— 面板不提供这些视图; 真机厂商复制本示例时,
  按需在面板加"设备专属视图页"（设计参考: 归档 `Test/_gtec_archive_20261016/` 的 Impedance 视图页）。
- `sim` 合成量封顶一个窗口容量（干跑确定性设计）; 连续演示请用 `virtual` 服务模式。
- 会话参数（channels/rate/…）在 **Open 时生效**; 流式中修改需先 Close。
- UI 文本全程 ASCII / FontAwesome（字形图集约束 — `Doc/Dev/ui_protocol.md` §12）。

## 厂商复制指南（本示例存在的意义）

1. 复制本目录 → 改 `extension.json` 的 `id` / `name` / `description`;
2. 改 `extension.py` 的类名与 `id` 属性; ops 注册名保持**裸名**（宿主自动加 `ext.<id>.` 前缀）;
3. 把"模式/会话参数"换成自家设备的门面配置; 面板骨架（transport / 设置区 / 示波器 / 统计表）原样可用;
4. 运行侧（后端 + 服务进程）放 `Application/Functions/` 下（游戏导出需要）;
5. 提交前跑审查器: `python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>`。

## 验证

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Extensions/test_virtual_panel.py   # 无头（沙箱 + ops + DSP + 绘制烟测）
.venv-py314t\Scripts\python.exe FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py Application/Functions/VirtualDevice
```
