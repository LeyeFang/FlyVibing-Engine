# Doc/Dev — 开发协议（Agent 优先）

> 本目录是**开发契约**文档集。主要消费者是 AI agent：读它可以替代重复的代码探索
> （省 token、省时间、省误判）。**改代码前先读对应协议；改行为/约定后必须同步更新本目录。**
>
> 写作要求：只写被代码验证过的事实；用表格/清单/精确路径；不要写"可能/大概"。

---

## 1. 文档地图（职责分离 — 与代码目录一一对应）

| 文档 | 对应代码域 | 何时必须读 |
|---|---|---|
| `ui_protocol.md` | `Application/Editor/UI/**`（Panel / Widget / 样式 / 菜单 / FileDialog） | 改编辑器 UI、加内联控件、调 Add 菜单、改删除交互 |
| `node_editor_protocol.md` | `Application/Core/NodeGraph/**`（运行时）+ `Application/Editor/UI/panels/node_editor/**`（编辑器交互）+ `Utils/NodeEditor/**` | 新增/修改节点类型、求值器、图约束、图校验、MCP 文档 |
| `device_io_protocol.md` | `Application/Functions/**`（SerialParallelDevice / EEGDevice） | 设备集成、真实/空跑双后端、线程与数据落盘 |
| `project_export_protocol.md` | `Application/Editor/ProjectManager.py` + EditorHost 场景 I/O + UI/UIManager 主菜单 + UI/FileDialog | 项目保存/另存/导出、资源路径、主菜单 File 项、迁移与打包 |
| `runtime_packaging_protocol.md` | `Application/PlayerEntry.py` + `Application/Runtime/PlayerBootstrap.py` + `Application/Core/Project/**` + `Utils/Runtime/**` + 导出游戏层 | 播放器/独立运行、Python 环境打包、wheelhouse、run_game.cmd、gtec fork 轮子策略、运行时线程纪律（§3.1） |
| `editor_live_protocol.md` | `Application/Editor/Services/LiveCommandServer.py` + `Utils/Editor/**` | 实时命令总线（agent 热注入）、实体/组件/场景/资源编辑 ops（v3 §4.1）、新增 op、容器补全跟进（§10）、MCP 注册与故障排查 |

职责边界（与代码一致，不得跨层）：
- UI 层只负责**编辑 props 和渲染**；业务逻辑在 evaluators；设备/IO 在 `Application/Functions`。
- evaluators 不得 `import imgui`；设备层不得反向依赖 Engine / Editor。
- MCP 工具（`Utils/NodeEditor`）只做构建/校验/应用图，不引入 UI 依赖。

---

## 2. 强制开发流程（Definition of Done）

任何改动按此顺序完成，缺一不可：

1. **读协议** → 确认改动落在哪个域。
2. **实现**（同域内一次改全：类型定义 / 控件 / 求值器 / 菜单 / 文档 / 测试）。
3. **Pylance 零错误**（IDE 诊断必须干净）。
4. **MCP 空跑验证**（**所有节点/图相关改动必须通过**，见 §3）。
5. **相关测试脚本通过**：`Test/` 下对应脚本（如设备层 → `Test/Application/Functions/test_gtec_device.py`）。
6. **文档同步**：本目录 + `Utils/NodeEditor/rules.md` + `graph_rules.py`（若涉及节点）。

---

## 3. MCP 空跑验证（硬性验收条件）

工具链：`Utils/NodeEditor/`（MCP servers: `mcp_server.py` 构建/应用、`mcp_server_ref.py` 参考、`mcp_server_validate.py` 校验）。

- 校验入口：`validate_graph(graph, max_frames>0)` → `node_graph_validator.dry_run_simulation()`。
  干跑将 `ctx.dry_run=True`，从 `OnGameStart` → N 帧 `OnFrameUpdate` → `OnGameStop` 全链路执行。
- **所有副作用节点必须支持 dry_run**：分支 `if ctx.dry_run: ctx.emit_log(...); return`，
  参数与真实路径一致（只记录不执行）。
- **设备类开发必须附带"空跑后端"**：无硬件、无落盘、无线程、结果确定性（同样输入 → 同样输出）。
  真实设备在干跑中**绝不**被触碰。示例见 `Application/Functions/EEGDevice/GtecStub.py`。
- 模块 import 不得拉起重依赖（matplotlib / pygds / DLL）—— 重依赖在真实路径内**懒导入**。
- 验收命令（无 UI、无硬件即可跑）：

```powershell
# 单元测试（设备层示例，48 项断言：stub 会话 + 干跑全链路 + 约束）
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_gtec_device.py
# 图工具冒烟
.venv-py314t\Scripts\python.exe Utils/NodeEditor/test_smoke.py
# 场景干跑（示例）
.venv-py314t\Scripts\python.exe -m Utils.NodeEditor.node_graph_validator Test\TestProject\MI-SSSEP\scenes\MI.scene --frames 120
```

---

## 4. 环境与运行

- 引擎 venv：`.venv-py314t`（Python 3.14 自由线程）；启动：`startup.bat`（内部 `python -Xgil=0`）。
- **自由线程注意**：不存在 GIL 保护，跨线程共享的可变结构必须加锁（见 `device_io_protocol.md`）。
- 设备层可选依赖（pygds 等）只装在引擎 venv 时才对真实采集生效；缺失时节点给出明确错误日志，**不崩溃、不伪造数据**。
- 外部参考资料（本机）：`C:\WorkSpace\FLY\GtecAPI\`（g.HIamp 测试脚本 + API 摘要 + 离线 wheel）。

---

## 5. 文档消费约定（给 agent）

- 本目录文档描述的是**约定与坑**，代码是最终事实源；发现不一致 → 以代码为准并**回写文档**。
- 新增节点 / 新设备 / 新交互前，先查对应协议中的"清单"，避免重复踩坑。
- 本文档集不得收录敏感信息（密钥、token）；运行时数据路径用示例占位。
