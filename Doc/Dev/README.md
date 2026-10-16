# Doc/Dev — 开发协议（Agent 优先）

> 本目录是**开发契约**文档集。主要消费者是 AI agent：读它可以替代重复的代码探索
> （省 token、省时间、省误判）。**改代码前先读对应协议；改行为/约定后必须同步更新本目录。**
>
> 写作要求：只写被代码验证过的事实；用表格/清单/精确路径；不要写"可能/大概"。
>
> **★ Doc CLI 化（2026-10-16）**：dev 区**知识类协议** + `Doc/ExtDev/**` 正文已全部迁入
> `engine-editor-cli doc`（按节读取、省 token；`doc` 总索引 → `doc outline <topic>` 章节索引 →
> `doc show <topic>#节号` 正文）；对应 md 只留指针 stub（"面对什么问题 / 去哪获得内容"）。
> 记录/计划类（roadmap / *_plan / feedback / upstream）保留正文 md。
> 开发工具（`Utils/Dev/**`：test_runner / thread_probe / i18n_tool …）走 `doc tools` / `doc tool <名>`
> （数据源=工具文件本身，无单独文档）。方案与进度：`doc_cli_plan.md`。

---

## 0. 读者三分区（文档消费者模型 — 2026-10-11 确立）

| 读者 | 文档区 | 说明 |
|---|---|---|
| 主应用开发团队（含 agent） | **`Doc/Dev/**`（本目录）** | 引擎内部开发契约（协议/坑/守则） |
| 社区开发者（扩展/插件作者） | **`Doc/ExtDev/**`** | 扩展开发规范（自包含，不要求读本目录）；入口 `Doc/ExtDev/README.md` |
| 用户（实验/游戏使用者） | **`Doc/User/**`** | 手册级文档（编辑器 MCP 指南等） |

> 变更涉及时修对区：对外开发者的内容写 `Doc/ExtDev`，产品手册写 `Doc/User`，引擎内部写本目录。

---

## 1. 文档地图（职责分离 — 与代码目录一一对应）

| 文档 | 对应代码域 | 何时必须读 |
|---|---|---|
| `../..` → **`Utils/README.md`** | `Utils/**`（工具层布局：受众 × 分发命运） | **往 Utils/ 放任何东西前必读**：三层词表（Dev/ExtDev/User 与 Doc 三分区同名）、依赖资格（ExtDev 禁 import 编辑器内部）、导出卫生（游戏包只带 `Utils/User`） |
| `ui_protocol.md` | `Application/Editor/UI/**`（Panel / Widget / 样式 / 菜单 / FileDialog） | 改编辑器 UI、加内联控件、调 Add 菜单、改删除交互 |
| `i18n_protocol.md` | `Application/Editor/I18n.py` + `Application/Editor/Locale/**` + `Utils/Dev/i18n_tool.py` + `Doc/Dev/i18n_baseline.json` | **写任何 UI 文案 / 加菜单项 / 新增语言前必读**：角色分工、键规范与可提取性、不翻译边界表（agent 面=中文不随语言变化）、运行时回退链、**守卫三层与棘轮口径**、新增语言 Runbook（全量适配门槛）、扩展侧约定 |
| `node_editor_protocol.md` | `Application/Core/NodeGraph/**`（运行时）+ `Application/Editor/UI/panels/node_editor/**`（编辑器交互）+ `FlyVibing-User-And-Developer-Utils/packages/node-editor/**` | 新增/修改节点类型、求值器、图约束、图校验、MCP 文档 |
| `device_io_protocol.md` | `Application/Functions/**`（SerialParallelDevice / VirtualDevice） | 设备集成、真实/空跑双后端、线程与数据落盘 |
| `bci_algorithm_protocol.md` | `Application/Functions/BCIAlgorithm/**` + `node_types/evaluators {epoch,bci_algorithm}` + 对应 widgets | epoch 数据集、FBCSP/CCA 节点、打包 list 超参、训练同步语义、模型注册、空采验证 |
| `project_export_protocol.md` | `Application/Editor/ProjectManager.py` + EditorHost 场景 I/O + UI/UIManager 主菜单 + UI/FileDialog | 项目保存/另存/导出、资源路径、主菜单 File 项、迁移与打包 |
| `runtime_packaging_protocol.md` | `Application/PlayerEntry.py` + `Application/Runtime/PlayerBootstrap.py` + `Application/Core/Project/**` + `Utils/Dev/**`（打包流水线） | 播放器/独立运行、Python 环境打包、wheelhouse、run_game.cmd、运行时线程纪律（§3.1） |
| `editor_live_protocol.md` | `Application/Editor/Services/LiveCommandServer.py` + `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/**` | 实时命令总线（agent 热注入）、实体/组件/场景/资源编辑 ops（v3 §4.1）、校验/导入导出/工程 ops（v4 §4.2）、新增 op、容器补全跟进（§10）、agent 通道（MCP lite/full 档、CLI、Skill）与故障排查 |
| `graph_validation_protocol.md` | `Application/Core/NodeGraph/validation/**` + Node Editor 面板 Validate + `graph.validate.*` / `graph.export/import` ops | 改校验规则/干跑语义/报告格式、改 Validate UI 或图导入导出 |
| `test_protocol.md` | `Test/**` + `Utils/Dev/test_runner.py` + `Test/Application/Editor/ui_scenario.py` + `_ui_boot.py` | 新增/修改测试、UI 场景回放、排查测试互相干扰时必读：档位 / 沙箱 / 输出契约 / 重置清单 |
| `threading_protocol.md` | `Application/Core/ThreadRegistry.py` + 全体线程启动点 + `Utils/Dev/thread_probe.py` | **新开线程/跨线程通信/服务进程集成前必读**：三通道纪律、心跳注册四步、实时探针、检查单 |
| `media_protocol.md` | `Application/Core/Media/**` + `ShowMedia` 节点 + `MediaPlayer` 组件 + `TextureUpdateCommand` 链 | 改动态媒体（GIF/视频/音频）、媒体节点、动态纹理上传：架构决议 **v2**（编辑器=模板 / PIE 唯一由 GameRuntime 控制 / 节点建图才生效）、数据流、注册点、验收证据 |
| `rendering_protocol.md` | `Application/Core/Renderer/**` + `Resource/Shaders/**` + `Test/Application/Renderer/**` | 改渲染器/渲染命令/shader/纹理上传/overlay，或需要像素级验证时必读：后端现状（OpenGL 一等公民）、线程纪律、资源模型、**验证体系**（GL 像素探针 + 金标准）、agent 工具（`renderer.snapshot` / CLI `probe`）、**§7 渲染目标(RT)**、**§8 光照体系** |
| `shader_protocol.md` | `Resource/Shaders/**` + `Application/Resource/Material.py` + 渲染器 uniform 注入 | 新增/修改 shader、调整材质 uniform 系统、变换光照/帧级注入 uniform 前必读：顶点属性契约（STD_LAYOUT）、uniform 归属总表（矩阵/材质/**渲染器注入**）、材质默认值与「切 shader 重置」语义、光照模型与数值锁定表、新增 shader 检查单 |
| `text_protocol.md` | `Application/Core/Text/**` + `TextDisplay` 组件 + `SetText` 节点 + ScenePanel 通用组件检视 | 改文字显示/光栅化/字体/动态纹理绑定前必读：**两种形态**（有色画布 vs 浮空文字=透明底+alpha 混合）、auto 画布热更策略、合成粗体/斜体、字段表、驱动通道矩阵（编辑器预览/检查器/MCP/节点）、注册点清单与验收证据 |
| `ui_refactor_plan.md` | `Application/Editor/UI/**` 大文件（widgets.py / panel.py / ScenePanel.py） | 执行 UI 文件拆分/搬迁时读：目标结构（mixin/注册表两种拆法）+ 验证顺序 |
| `doc_cli_plan.md` | 文档交付链（Doc CLI 化）: `engine-editor-cli doc` + `doclib.py` + `docs_content/**` | 迁移文档到 CLI / 新增 CLI 文档主题时读：架构、指针 stub 纪律、守卫、批量 runbook、待决事项 |
| `extension_protocol.md` | 三层模型（EngineModule / Extension / Mod）+ `Application/Functions/**` 扩展区 + `Application/Editor/Extensions/**` | **Functions 功能模块化、扩展体系开发前必读**：Plugin 审计与改名（已执行）、三档侵入模型（T0 声明式 / T1 Hooks / T2 进程外）、依赖方向铁律、兼容与遏制机制（SDK 门面 / 命名空间 / 冲突检测 / 能力声明）、节点包与设计面板贡献点 |
| `roadmap_next.md` | 全局（线程治理 / 资源管线 / 动态媒体 三章蓝图, 待评估草案） | 开工前评估三大愿景方向、依赖取舍与里程碑顺序 |

> **社区开发者（第三方扩展作者）的外部文档已独立**：规范全文 `Doc/ExtDev/extension_dev_protocol.md`、
> 入口 `Doc/ExtDev/README.md`；开发者生态/工具链剥离规划 `ecosystem_plan.md`（本目录）。

职责边界（与代码一致，不得跨层）：
- UI 层只负责**编辑 props 和渲染**；业务逻辑在 evaluators；设备/IO 在 `Application/Functions`。
- evaluators 不得 `import imgui`；设备层不得反向依赖 Engine / Editor。
- MCP 工具（`FlyVibing-User-And-Developer-Utils/packages/node-editor`）只做构建/应用图（图校验已内化为引擎服务 — 见 `graph_validation_protocol.md`），不引入 UI 依赖。
- **开发过程临时产物（截图/演示场景/实验脚本/日志）只允许放 `Test/**` 下 — 禁止在仓库根新增目录**；产品资源入 `Resource/**`，协议文档入 `Doc/**`。

---

## 2. 强制开发流程（Definition of Done）

任何改动按此顺序完成，缺一不可：

1. **读协议** → 确认改动落在哪个域。
2. **实现**（同域内一次改全：类型定义 / 控件 / 求值器 / 菜单 / 文档 / 测试）。
3. **Pylance 零错误**（IDE 诊断必须干净）。
4. **MCP 空跑验证**（**所有节点/图相关改动必须通过**，见 §3）。
5. **相关测试脚本通过**：`Test/` 下对应脚本（如设备层 → `Test/Application/Functions/test_siggen_device.py`）。
6. **文档同步**：本目录 + `FlyVibing-User-And-Developer-Utils/packages/node-editor/rules.md` + `graph_rules.py`（若涉及节点）。

---

## 3. MCP 空跑验证（硬性验收条件）

工具链：`FlyVibing-User-And-Developer-Utils/packages/node-editor/`（MCP 4 工具 + CLI + `rules.md` 分节规则）；图校验已内化为引擎服务（见 `graph_validation_protocol.md`），agent 侧实时校验经 `FlyVibing-User-And-Developer-Utils/packages/editor-mcp`（lite `engine_validate_graph` / CLI validate / v4 `graph.validate.*`）。

- 校验入口：引擎内服务 `Application/Core/NodeGraph/validation`（MCP `engine_validate_graph` / CLI `validate` / 无头 `PlayerEntry --dry-run`）。
  干跑将 `ctx.dry_run=True`，从 `OnGameStart` → N 帧 `OnFrameUpdate` → `OnGameStop` 全链路执行。
- **所有副作用节点必须支持 dry_run**：分支 `if ctx.dry_run: ctx.emit_log(...); return`，
  参数与真实路径一致（只记录不执行）。
- **设备类开发必须附带"空跑后端"**：无硬件、无落盘、无线程、结果确定性（同样输入 → 同样输出）。
  真实设备在干跑中**绝不**被触碰。
- 模块 import 不得拉起重依赖（matplotlib / 设备 SDK / DLL）—— 重依赖在真实路径内**懒导入**。
- 验收命令（无 UI、无硬件即可跑）：

```powershell
# 单元测试（设备层示例：SigGen 会话 + 干跑全链路 + 约束）
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_siggen_device.py
# 图工具冒烟（构建器）
.venv-py314t\Scripts\python.exe FlyVibing-User-And-Developer-Utils/packages/node-editor/test_smoke.py
# NodeEditor agent 通道离线套件（MCP 分节/构建/应用 + CLI）
.venv-py314t\Scripts\python.exe Test/Application/NodeGraph/test_node_editor_mcp.py
```

---

## 4. 环境与运行

- 引擎 venv：`.venv-py314t`（Python 3.14 自由线程）；启动：`startup.bat`（内部 `python -Xgil=0`）。
- **自由线程注意**：不存在 GIL 保护，跨线程共享的可变结构必须加锁（见 `device_io_protocol.md`）。
- 设备层可选依赖（设备 SDK 等）只装在引擎 venv 时才对真实采集生效；缺失时节点给出明确错误日志，**不崩溃、不伪造数据**。

---

## 5. 文档消费约定（给 agent）

- **先索引后内容**：查协议走 `engine-editor-cli doc`（主题 + 次级标题两级索引）→ `doc outline <topic>`
  （章节 + 一行预览）→ `doc show <topic>#节`（只在确定要哪节时才拉正文）。md stub 只回答"面对什么问题 / 去哪获得"。
- 本目录文档描述的是**约定与坑**，代码是最终事实源；发现不一致 → 以代码为准并**回写文档**。
- 新增节点 / 新设备 / 新交互前，先查对应协议中的"清单"，避免重复踩坑。
- 本文档集不得收录敏感信息（密钥、token）；运行时数据路径用示例占位。
