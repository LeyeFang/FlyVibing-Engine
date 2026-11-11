# 路径与宏（Paths & Macros）

> 本页是 CLI 文档指针 stub；正文唯一来源在工具仓：
> `packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/paths_and_macros.md`。

阅读：

```powershell
engine-editor-cli doc outline extdev/paths_and_macros
engine-editor-cli doc show extdev/paths_and_macros#<节号|标题片段>
```

一句话结论（写数据前先记住这三条）：

1. 相对路径**默认落在 `output/`**（成品 = `<成品>/output`，PIE = `<工程>/output`）；
2. 要指明"哪个根"就用宏：`<OutputRoot>` / `<ProjectRoot>` / `<GameRoot>` / `<EngineRoot>`；
3. **不要用 `os.getcwd()`**，也不要把本机绝对路径写进节点 prop（换机器就断，导出会告警）。

实现位置（引擎）：`Application/Core/FileSystem/DataPaths.py`；扩展接口：`ctx.paths`。
