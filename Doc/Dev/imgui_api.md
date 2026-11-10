# imgui 控件目录（面板开发速查）

> 本页是 CLI 文档指针 stub；正文**由生成器产出**，唯一来源在工具仓：
> `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/imgui_api.md`。
>
> 生成器：`Utils/Dev/imgui_docgen.py`（签名取自已安装的 `imgui_bundle` 运行时，
> 分组表在本文件里策展；升级依赖后重新生成即可看到差异）。

阅读：

```powershell
engine-editor-cli doc outline dev/imgui_api            # 18 节：flag 速查 / 文本 / 按钮 / 输入 / 布局 /
                                                       # 容器 / 表格 / 弹窗 / 交互状态 / 禁用态 / 拖放 /
                                                       # 样式 / 输入 / 窗口 / 宿主侧禁止 / 附录 / 维护
engine-editor-cli doc show dev/imgui_api#表格           # 单节正文（按序号或标题片段）
engine-editor-cli doc search begin_table               # 跨主题检索
```

为什么是「按用途归类」而不是照 ImGui 文档搬：

- ImGui 官方文档按 C++ 概念 + 字母组织，查得到函数但不知道**该用哪个**；
- 本页主体只收**引擎里真正在用**的接口（归类 143 个、其中 130 个仓库已有调用，合计 1800+ 处），
  附录收录其余 230 个函数 + 146 个枚举/类型；
- 每条都带我们的约定：`##` id 作用域、返回值是 tuple、`begin/end` 与 `push/pop` 必须配对、
  颜色两套类型（`ImVec4` vs u32）、以及「扩展禁用」的宿主侧接口。

维护（三件事都在这）：

| 事 | 命令 / 位置 |
|---|---|
| 重新生成 | `python Utils/Dev/imgui_docgen.py` |
| 只校验 | `python Utils/Dev/imgui_docgen.py --check` |
| 覆盖率统计 | `python Utils/Dev/imgui_docgen.py --stats`（未归类 / 不存在 / 重复） |
| 守卫测试 | `Test/Application/Editor/test_imgui_api_doc.py`：产物新鲜 + 分组名真实 + **引擎用到的都被归类** + CLI 可寻址 |

配套阅读：`Doc/ExtDev/ui_development.md`（面板怎么挂到编辑器）、
`Doc/Dev/ui_protocol.md`（引擎内部 UI 层协议：线程 / 绘制 pass / 主题）。
