# 着色器设计规范协议

> ★ 本页正文已 CLI 化（2026-10-16）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

改 Resource/Shaders/**、渲染器 uniform 注入（OpenGLEntities._inject_lighting）、材质 uniform 系统（Application/Resource/Material.py）前…

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline dev/shader_protocol                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show dev/shader_protocol#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：1 定位与三层职责 · 2 文件布局与加载 · 3 顶点属性契约（STD_LAYOUT） · 4 矩阵与坐标约定（实测锁定） · 5 uniform 契约总表 · 6 材质默认值系统与「切 shader 重置」语义 · 7 光照约定（Lighting shader） · 8 shader alpha 与混合（`Material.blend`） · 9 已知限制（有意保留） · 10 内置 shader 现状表 · 11 新增/修改 shader 检查单（DoD） · 12 交叉引用

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/shader_protocol.md`。
