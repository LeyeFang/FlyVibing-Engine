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

检查 manifest（M1-M6）/ 代码静态（C1-C6：UIExtensionBase / on_ui_event / close_policy /
ops 前缀 / monkey-patch / import 白名单）/ 文件（TODO.md）。
退出码：0 = 无 FAIL；1 = 存在 FAIL（可接 CI）。

规范依据：`Doc/ExtDev/extension_dev_protocol.md`（§4 manifest / §7 UI 完备性 / §14 检查单）。
