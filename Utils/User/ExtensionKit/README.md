# ExtensionKit — 扩展开发者工具集（SDK 雏形）

> 定位：`Doc/Dev/ecosystem_plan.md` **L0 发布物化**的组成部分 — 未来并入 SDK 包。
> 当前内容：静态审查器（无需引擎运行，零依赖）。

## review_extension.py — 静态审查器 v0

```powershell
# 审查单个/多个扩展目录
python Utils/User/ExtensionKit/review_extension.py Functions/SerialParallelDevice
# 审查仓库内全部扩展
python Utils/User/ExtensionKit/review_extension.py --all
```

检查 manifest（M1-M6）/ 代码静态（C1-C11：UIExtensionBase / on_ui_event / close_policy /
ops 前缀 / monkey-patch / import 白名单 / **imgui 文本字形安全** /
**imgui 窗口栈配对纪律**（C8 gated `begin_child` → FAIL；C9 无条件 `end_combo` → WARN；
C10 顶层创建 imgui context/窗口/GL → FAIL）/ **C11 全局 imgui 状态禁令**（`create/destroy_context`、
`set_ini_filename`、`io/style` 赋值 → FAIL））/ 文件（TODO.md）。
退出码：0 = 无 FAIL；1 = 存在 FAIL（可接 CI）。

规范依据：`Doc/ExtDev/extension_dev_protocol.md`（§4 manifest / §7 UI 完备性·文本安全·
窗口栈配对 / §12 测试 / §14 检查单）。配对纪律的崩溃机理与上游材料：
`Doc/Dev/upstream_imgui_beginchild_fullclip.md` + `Utils/Dev/repro_imgui_child_clipping.py`。

## imgui_headless.py — 无头 imgui 上下文（唯一入口）

```python
from Utils.User.ExtensionKit.imgui_headless import headless_imgui
with headless_imgui() as h:                       # 自动禁用布局持久化（不产生 imgui.ini）
    h.frames([(1280, 720), (0, 0), (1, 1), (1280, 720)], draw=my_panel_draw)
```

**为什么必须用它**：裸 `imgui.create_context()` 会在 `destroy_context()` 时把 `imgui.ini`
写进**当前工作目录**（扩展自测最常踩）；且 `set_ini_filename(None)` 会让进程**原生崩溃**
（exit `0xC0000005`）。细节与实测见 `Doc/Dev/ui_protocol.md` §2.14。
