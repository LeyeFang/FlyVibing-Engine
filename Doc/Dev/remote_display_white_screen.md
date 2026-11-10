# 记录 — 远程/无物理显示器下的 OpenGL 窗口白屏（2026-10-27）

> 类型：**环境诊断记录**（非引擎缺陷、非渲染回归）
> 触发场景：开发机物理显示器被拔掉，使用向日葵等远程软件直连开发机
> 现象：主编辑器/PIE/导出成品的窗口显示为纯白；引擎内部帧抓取和运行逻辑正常

## 1. 症状

- 导出的 `MI-SSSEP` 成品通过 `run_game.cmd` 启动后，窗口客户区为纯白。
- 主编辑器自身窗口、PIE 运行时窗口在系统截图中也为纯白。
- 引擎内部 `capture` / `pie` / `renderer` 帧内容正常（能看到深灰背景和场景内容）。
- 节点图、实体注册、相机、材质均正常；没有异常日志或 `glGetError`。
- 用户远程点击原本 PIE 窗口位置时仍能启动 PIE，说明窗口存在且可交互，只是画面没有出现在远程返回的画面中。

## 2. 环境证据

采集日期：2026-10-27

| 项目 | 结果 |
|---|---|
| GPU | NVIDIA GeForce GTX 1650 |
| 当前显示模式 | 1920×1080 |
| `Win32_DesktopMonitor` | 仅 `默认监视器`，1920×1080 |
| `Get-PnpDevice -Class Monitor` | 三个历史显示器条目，状态均为 `Unknown`（当前未连接） |
| OpenGL | NVIDIA GeForce GTX 1650/PCIe/SSE2，4.4.0 NVIDIA 595.97 |
| 远程方式 | 向日葵远程控制（窗口枚举可见）；当前为 `console` 会话，非 RDP 登录 |
| 窗口状态 | `visible=true`，`iconified=false` |

> “默认监视器 + 历史 PnP 条目 Unknown” 表明当前没有活跃的物理显示器；Windows 通过虚拟显示/远程呈现层提供 1920×1080 桌面。

## 3. 关键验证：独立 GLFW 窗口探针

新增开发机探针：`Utils/Dev/remote_display_probe.py`

它创建一个与运行时窗口相同的 OpenGL 4.4 Core 窗口，填充纯绿色后分别采集：

1. **后缓冲**读回（`back.png`）
2. `SwapBuffers` 后的**前缓冲**读回（`front.png`）
3. 通过 GDI 截取窗口所在屏幕区域（`screen.png`）

实测输出：

```json
{
  "gl": {"vendor": "NVIDIA Corporation",
         "renderer": "NVIDIA GeForce GTX 1650/PCIe/SSE2",
         "version": "4.4.0 NVIDIA 595.97"},
  "monitors": [{"name": "NVIDIA GeForce GTX 1650", "size": [1920, 1080], "refresh_hz": 200}],
  "window": {"visible": true, "iconified": false, "framebuffer": [800, 450]},
  "expected_rgba": [26, 204, 51, 255],
  "back_center": [25, 204, 51, 255],
  "front_center": [25, 204, 51, 255],
  "screen_center": [255, 255, 255, 255],
  "back_matches": true,
  "front_matches": true,
  "screen_matches": false,
  "presentation_mismatch": true
}
```

解释：

- 后缓冲和前缓冲均为目标绿色 → **OpenGL 渲染与 `SwapBuffers` 正常**。
- 窗口本身可见、未最小化。
- 屏幕截图为纯白 → **远程呈现/截屏层没有拿到 OpenGL 窗口内容**。

这排除了：

- 场景节点图 / EntitySpawn / 相机 / 材质 / 实体注册导致的白屏
- 导出成品缺失资源
- 引擎渲染管线或 GL 错误
- 窗口被最小化或隐藏

## 4. 结论

**白屏来自“无物理显示器 + 远程软件的 OpenGL 窗口呈现/截屏层”，不是引擎缺陷。**

引擎只负责渲染到 GL 前后缓冲；当前环境下前后缓冲内容正确，但远程软件返回的桌面图像把该窗口显示为白色。拔掉物理显示器是触发条件之一，但不是引擎渲染逻辑变化导致的回归。

## 5. 后续判断口径

遇到“窗口白屏”时先做二分：

| 内部帧抓取 / 前后缓冲 | 操作系统窗口截图 | 判断 |
|---|---|---|
| 正常 | 白色 | 远程/显示呈现层问题；不要改渲染或场景 |
| 白色 | 白色 | 真实渲染问题；继续查相机/材质/资源/GL |

推荐验证命令：

```powershell
# 独立 GLFW 窗口：应看到 front 为目标色、screen 为白色、presentation_mismatch=true
.venv-py314t\Scripts\python.exe Utils/Dev/remote_display_probe.py

# 引擎内部帧（PIE / 成品）正常即可继续运行逻辑
engine-editor-cli capture pie --out pie-view.png
```

## 6. 归档产物

- 探针：`Utils/Dev/remote_display_probe.py`（可重复运行）
- 本次结果（本地生成，通常不入库）：`Test/_runs/remote_display_probe/20261027_console2/`
  - `back.png` — Swap 前后缓冲（目标绿色）
  - `front.png` — Swap 后前缓冲（目标绿色）
  - `screen.png` — GDI 截屏（白色）
  - `result.json` — 像素对比与 GL/显示器/窗口状态
  - `engine-pie-capture.png` — 引擎内部 PIE 抓帧（正常）
  - `engine-pie-printwindow.png` — PIE 窗口系统捕获（白色）
  - `engine-editor-printwindow.png` — 编辑器窗口系统捕获（白色）

## 7. 处理决定

- **不修改引擎渲染、场景或导出逻辑**；本次白屏不作为 release blocker。
- 需要人工确认画面时：
  1. 接回物理显示器并本地运行；
  2. 或更换远程工具/开启兼容模式；
  3. 或在远程环境使用引擎内部 `capture` / 帧缓冲验证，不依赖系统桌面截图。
- 若后续在**本地物理显示器**上仍出现白屏，再按真实渲染问题排查。

---

## 8. 补充（2026-11-10）— SSH 启动成品直接崩溃：`glfw.get_video_mode` 访问违例

> 与 §1–§7 的白屏**不是同一个问题**：白屏是"画面没呈现"，这条是"**进程直接被
> 打死**"。但两者共享同一个环境前提：进程不在正常的交互式桌面显示链路上。

### 8.1 症状

用户通过 **SSH** 远程登录开发机（该机器有物理屏幕，平时用远程软件观察桌面）后
启动导出成品：

```
glfw.get_video_mode(monitor) → OSError: access violation reading 0x108
```

`0x108` 是结构体内字段偏移，典型的"指针本身已失效"特征。

### 8.2 根因

Windows 的 SSH 会话**有自己的 window station**（不是 `WinSta0\Default`）。
在这样的会话里：

| 步骤 | 结果 |
|---|---|
| `glfwInit()` | **成功**（只创建 message-only 窗口） |
| `glfwGetMonitors()` / `GetPrimaryMonitor()` | 返回**非 NULL 但已失效**的显示器句柄 |
| `glfwGetVideoMode(monitor)` | 解引用失效结构 → **访问违例，进程退出** |

也就是说：**"机器有屏幕"与"这个进程能安全查询显示器"是两件事**。

### 8.3 修复（引擎侧，2026-11-10 已落地）

原则：**任何显示查询都不允许把进程打死**。

| 改动 | 位置 |
|---|---|
| `_safe_primary_monitor()` / `_safe_video_mode()` 包装，失败返回 `None` 并**停用本会话后续查询**（只告警一次） | `Core/Window/glfwWindow.py` |
| `_get_system_resolution()` 四级回退：`MGE_WINDOW_SIZE` → Win32 `EnumDisplaySettingsW`（不经 GLFW monitor 指针）→ GLFW → 1920×1080 | 同上 |
| 只有 `FULLSCREEN` 才触碰 monitor；`WINDOWED`/`BORDERLESS` 完全跳过显示器枚举 | `_create_window()` |
| `FULLSCREEN` 拿不到可用显示器 → **自动降级 BORDERLESS**（用户仍看到满屏窗口） | `_create_window()` / `set_window_mode()` |
| `MGE_WINDOW=windowed\|borderless\|fullscreen` 覆盖窗口模式 | `_env_window_mode()` |
| `MGE_WINDOW_SIZE=1280x720` 直接指定尺寸（绕开所有探测） | `_env_size()` |
| `MGE_MONITOR=off` 完全停用显示器枚举 | `_monitors_disabled()` |

### 8.4 SSH / 远程环境推荐启动方式

```powershell
# 最稳：完全绕开显示器枚举
$env:MGE_WINDOW='windowed'; $env:MGE_WINDOW_SIZE='1280x720'; $env:MGE_MONITOR='off'
# 需要满屏又不想碰独占全屏
$env:MGE_WINDOW='borderless'; $env:MGE_WINDOW_SIZE='1920x1080'; $env:MGE_MONITOR='off'

# 先诊断会话能拿到什么（不创建窗口，安全）
.venv-py314t\Scripts\python.exe Utils/Dev/display_diag.py --json display.json
```

`display_diag.py` 会并排打印四类信息源，用于判断"当前会话到底能拿到什么"：

| 段 | 内容 | 判读 |
|---|---|---|
| `[1] 进程 / 会话` | `session_id` / `window_station` / `desktop` / `interactive_desktop` | **`interactive_desktop=False` 即 SSH 会话**，GLFW 显示器枚举不可靠 |
| `[2] Win32 EnumDisplaySettings` | 该会话桌面的分辨率/刷新率 | 正常工作时引擎就用这个值 |
| `[3] GetSystemMetrics` | 会话桌面尺寸 + 显示器数量 | 与 `[2]` 交叉验证 |
| `[4] EnumDisplayDevices` | 适配器/显示器列表（含 `attached`/`primary`）| 可看出是否只有虚拟显示器（如远程软件的 Indirect Display） |
| `[5] GLFW` | 引擎实际走的路径（**可能崩，但已用子进程隔离**）| 有 `errors` 就说明该会话不能安全查询 |

退出码：`0` = Win32 能取到分辨率（引擎可正常跑）；`3` = 只能拿到回退值。

### 8.5 仍然存在的限制（不是 bug）

- SSH 会话里创建的窗口**属于 SSH 会话的桌面**，不会出现在物理屏幕/远程软件看到的
  那个桌面上。要在"看得见的屏幕"上跑，必须：
  1. 在交互式会话里启动（本地登录后的终端 / 计划任务指向交互式会话 / 远程软件自身的命令行）；
  2. 或 SSH 只用于构建与无头校验（`--dry-run` / `--stats-json` + `perf_graph graph`）。
- 若远程软件本身是 Indirect Display（`EnumDisplayDevices` 里出现 `CDD`），
  §1–§7 的"白屏"仍可能发生 —— 那是呈现层问题，与本节的崩溃不同。

### 8.6 验收证据

| 检查 | 结果 |
|---|---|
| `Test/Application/Core/test_window_display_fallback.py` | **17/17**（含"模拟 `get_video_mode` 抛 0x108"→ 返回 `None`、只告警一次、后续短路）|
| `MGE_MONITOR=off MGE_WINDOW=fullscreen MGE_WINDOW_SIZE=1024x600` 实跑成品 | 打印 `FULLSCREEN degraded to BORDERLESS` → `mode=borderless` → `exit 0` |
| `MGE_MONITOR=off MGE_WINDOW=windowed MGE_WINDOW_SIZE=1280x720` 实跑成品 | `resolution from MGE_WINDOW_SIZE: 1280x720` → `exit 0` |
| `Utils/Dev/display_diag.py`（本地 200 Hz + CDD 虚拟显示器） | 四源一致，`interactive_desktop=True`，GLFW 正常 |

