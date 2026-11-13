# 扩展依赖契约（`python.runtime`）

> 本页是 CLI 文档指针 stub；正文唯一来源在工具仓：
> `packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/extension_dependencies.md`。

阅读：

```powershell
engine-editor-cli doc outline extdev/extension_dependencies
engine-editor-cli doc show extdev/extension_dependencies#<节号|标题片段>
```

一句话结论（写依赖声明前先记住这四条）：

1. `python.mode/path/probe` 只描述**编辑器**用哪个解释器，**不描述成品**；
2. 成品依赖必须写进 `python.runtime`：`engine` = 装进产物运行时（节点进程内 import），
   `bundle` = 整个环境随包（只给子进程），`none` = 显式声明无三方依赖；
3. **随产物分发的扩展不写 `runtime` = 导出失败**（"没写"正是 2026-11-14 hdf5 事故的形态）;
4. 本地自查：`python Utils/Dev/check_extension_python.py --all`。

实现位置（引擎）：`Application/Core/Extension/ExtensionRuntimeDeps.py`（解析/校验单一实现）；
安装落地：`Application/Editor/Extensions/ExtensionPythonDist.py`；
成品侧 probe：`Application/Runtime/PlayerBootstrap.py`。
