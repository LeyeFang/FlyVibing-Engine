# 扩展面板配方（UI Recipes）

> 本页是 CLI 文档指针 stub；正文唯一来源在工具仓：
> `packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/ui_recipes.md`。

阅读：

```powershell
engine-editor-cli doc outline extdev/ui_recipes
engine-editor-cli doc show extdev/ui_recipes#表格
```

内容包括 9 个可复制片段：

| 配方 | 解决什么 |
|---|---|
| §1 参数行 | 标签 + 滑杆 + 单位 + 复位 |
| §2 设置持久化 | 面板设置跨会话保存（只写 `ctx.data_dir`） |
| §3 表格 | 设备 / trial 列表、整行选中、双击、右键 |
| §4 日志区 | 自动跟随最新，用户上滑不打断 |
| §5 实时波形 | 环形缓冲 + `plot_lines` |
| §6 确认弹窗 | 危险操作二次确认 |
| §7 禁用与原因 | 灰按钮 + 「为什么不能点」提示 |
| §8 后台线程 → UI | 快照队列（`ctx.ui.post` 未实装） |
| §9 无头自测 | `headless_imgui` + 提交前审查器 |

控件签名与坑查 `Doc/Dev/imgui_api.md`（生成物，按用途归类）；
面板如何挂到编辑器查 `Doc/ExtDev/ui_development.md`。
