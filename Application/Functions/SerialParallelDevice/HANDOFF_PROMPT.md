# 交接提示词（复制粘贴给接手 agent）

> 用法: 把下面 `=== 提示词开始/结束 ===` 之间的内容整段粘给新 agent（新会话），
> 并把工作区设成 `MyGameEngine-Python` 仓库。改任务时只改最后一节"第一个任务"。

=== 提示词开始 ===

你现在**接手维护** MyGameEngine-Python（Python 3.14 free-threaded 游戏引擎）的一个**已上线官方扩展**：
串并口扩展 `Application/Functions/SerialParallelDevice/`（`id = device`，ops 前缀 `ext.device.*`）。

**先按顺序读完这 4 份，再动手**（不要凭猜测改）:

1. `Application/Functions/SerialParallelDevice/HANDOFF.md` — 交接书（边界 / 资产地图 / 已定裁决 / 坑 / 下一步 / 验收）**必读**
2. `Doc/Dev/device_io_protocol.md` §11 与 **§12（两级设备身份，通读）**
3. `Doc/ExtDev/extension_dev_protocol.md` §6（ctx 能力）/ §7（UI 契约）/ §9（agent op 生态）/ §14（提交检查单）
4. `Application/Functions/SerialParallelDevice/extension.py` + `Application/Core/DeviceRegistry.py`（源码即规范）

**红线（违反即返工）**:

- 面板按钮与 agent op **必须同一实现**（`_guard` → `_op_*`），不允许两条代码路径。
- 未绑定设备名 / 未配置端口 → **显式报错**，绝不静默回退、绝不给默认端口。
- 扩展**不得 import 编辑器层**；要读写当前场景节点只能走 `ctx.graph`（`nodes/find/set_props`）。
- 扩展**不得触碰**宿主全局 imgui 状态（`create/destroy_context`、`set_ini_filename`、`io/style` 赋值）。
- 无头 GUI 测试只能用 `flyvibing_extension_kit.imgui_headless.headless_imgui()`；`begin_child/end_child` 无条件配对。
- UI 文案英文；代码注释/日志可中文。

**环境要点**: 解释器用 `.venv-py314t\Scripts\python.exe`（PATH 上的 `python` 是 3.9，会崩）；
CLI 用 `.venv-py314t\Scripts\engine-editor-cli.exe`；嵌套参数走 `cli batch ops.json`（PS 5.1 会吞内层引号）。

**工作姿势**: 任何改动前后都跑 HANDOFF §6 三条命令（`--only device_alias` / `--tier core` / `review_extension.py`）；
改面板或 op 后必须在真实编辑器里走一遍（enable → 操作 → 截图 → quit）才算完成；
完成定义（DoD）见 HANDOFF §7。

**沟通偏好**: 用户要**简短直接**的答复（先给结论再给证据），中文；不要长篇复述代码；
设计上有多个选项时给 2–3 个方案 + 推荐 + 代价，让用户拍板；已定裁决在 HANDOFF §3 查，**不要重开**。

**第一个任务**: HANDOFF §5 的 **P0 — 自动重绑**：绑定时采集并写入设备指纹 `hint`（`usb_serial` / `vid_pid`），
新机器打开工程/启动面板时按指匹配自动改绑（日志 `[ext:device] auto-bound ...`），匹配不到保持显式报错；
对外新增 `ext.device.autobind {name?, dry_run?}` + 面板 `Auto-detect` 按钮（同一实现），按 DoD 交付
（单测伪造端口列表 + 实机拔插一次 + 文档 §12 补一小节）。

=== 提示词结束 ===
