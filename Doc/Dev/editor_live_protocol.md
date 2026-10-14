# 编辑器实时命令总线 / MCP 热注入协议（Editor Live）

> 适用：`Application/Editor/Services/LiveCommandServer.py`（编辑器侧总线）、
> `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/**`（agent 侧 MCP 服务器 / 独立包 / 安装）、`Application/Editor/EditorLayer.py`（pump 接入点）、
> `Application/Editor/EditorModule.py`（启停接入点; 原名 EditorPlugin, 2026-10-11 更名 — extension_protocol §2）。
> 目标：让 agent 像操作 Fusion360 一样**实时操作运行中的编辑器**（热注入，非文件式）。

---

## 1. 架构与线程纪律

```mermaid
flowchart LR
    A[Agent / Copilot] -- "MCP stdio" --> B["FlyVibing-User-And-Developer-Utils/packages/editor-mcp/mcp_server.py<br/>(薄 shim → src/engine_editor_mcp, 纯 socket 客户端)"]
    B -- "NDJSON + 二进制尾帧 @ 127.0.0.1:8977" --> C["LiveCommandServer socket 线程<br/>(仅收 JSON → 入队)"]
    C -- "queue.Queue" --> D["主线程 pump<br/>EditorLayer.OnUpdate 每帧"]
    D -- "复用编辑器按钮同款 API" --> E["SimulationController / ViewportController / ..."]
    E --> D --> C --> B --> A
```

**硬约束（free-threading 无 GIL）**：
- socket 线程只做 JSON 编解码 + 入队 + 等待回执；
- **一切编辑器状态变更只在主线程 `pump()` 执行** —— 与人类点击走完全相同代码路径；
- 每帧限量（16 条）保证帧率；单条命令回执等待上限 15s。

## 2. 端点与配置

| 项 | 值 |
|---|---|
| 地址 | `127.0.0.1:<port>`（**仅回环**，外部网络不可达） |
| 端口 | 默认 `8977`；环境变量 `MGE_EDITOR_MCP_PORT` 覆盖（编辑器与 MCP 两侧都读） |
| 启动 | 编辑器加载时由 `EditorModule.on_load → LiveCommandServer.start()` 自动启动 |
| 停止 | `EditorModule.on_unload → stop()`；daemon 线程随进程退出 |
| 端口占用 | 打印 `[Live] WARNING: cannot bind ...` 并禁用（不阻塞编辑器） |
| 审计日志 | 每条命令在主线程打印 `[Live] id=<n> op=<op> → ok / ERR ...` |

## 3. 协议（NDJSON + 二进制尾帧）

一行一条 JSON；请求-响应一一对应：

```json
请求:  {"id": 1, "op": "sim.play", "args": {}}
回执:  {"id": 1, "ok": true,  "result": {"requested": true, "state": "pending_start"}}
错误:  {"id": 1, "ok": false, "error": "ValueError: unknown op: 'foo' (available: ...)"}
```

- `id`：任意值原样回传（int/str）；
- 非法 JSON → `{"id": null, "ok": false, "error": "invalid request: ..."}`；
- 主线程超时未消费 → `{"ok": false, "error": "timeout waiting for editor main thread"}`
  （默认 15s; 长任务 op 逐 op 覆盖 `_OP_PUMP_TIMEOUT_OVERRIDES`: `project.open` 120s / `project.export` 900s —
  与 agent 侧 `ops.call_timeout` 同口径，服务器上限 ≥ 客户端）;
- **二进制尾随帧（v2 — 图像通道）**：若回执行 `result.binary_bytes = N`，则该行之后紧跟 N 字节
  裸负载（RGBA8, bottom-up）——客户端必须先读行、再精确读 N 字节；其余响应仍为严格单行 NDJSON。

## 4. op 表（v2 基础 13 条 — 2026-09-28 实机验证；v3 容器表见 §4.1）

> 注：下表的“MCP 工具”列为 **full 档**工具名；lite 档统一经 `engine_call(op, args)` 调用（§5），旧工具名可直接作为 op 别名。

| op | MCP 工具 | args | 语义（等价的人工操作） | 响应 |
|---|---|---|---|---|
| `sim.play` | `editor_run_pie` | — | 点 **Run**（帧末消费） | `{requested, state}` |
| `sim.stop` | `editor_stop_pie` | — | 点 **Stop**（帧末消费） | `{requested, state}` |
| `sim.state` | `editor_sim_state` | — | 只读（状态机 + PIE 线程存活） | `{state, runtime_alive}` |
| `view.set_mode` | `editor_switch_2d` / `editor_set_scene_type` | `{"mode": "2d"\|"3d"\|"overlay"}` | **Scene Type 按钮完整语义**：`set_game_type`（决定 PIE 用哪台摄像机）+ 视口切换 | `{mode, label, game_type}` |
| `view.set_grid` | — | `{"visible": bool}` | **View 菜单 Show Grid 同路径**（`Grid.set_visible`；注销/重注册 overlay，幂等，缺参数报错） | `{visible}` |
| `threads.snapshot` | — | — | **线程注册表快照**（注册/未注册漂移/停滞判定；协议 `threading_protocol.md`，工具 `Utils/Dev/thread_probe.py` 同源） | `{registered, unregistered, stale, count}` |
| `renderer.snapshot` | — | — | **渲染器状态快照**（后端 / GL 信息 / 资源计数 / 视口 / 帧统计；协议 `rendering_protocol.md`；无头时 `available=false`） | `{available, backend, gl, viewport, counts, overlays, stats}` |
| `camera.get` | `editor_camera_get` | `{"role": "3d"\|"2d"\|"overlay"}` | 读场景摄像机实体（Transform + Camera） | `{position, rotation, projection, ...}` |
| `camera.set` | `editor_camera_set` | role + 部分字段（position/rotation/projection/ortho_size/fov/...） | Inspector 改摄像机属性（仅编辑器场景） | 更新后快照 |
| `graph.list` | `editor_graph_list` | — | 节点图快照（复用 canvas API, 不经 UI） | `{nodes, links}` |
| `graph.add` | `editor_graph_add` | `{"type", "props"?, "position"?}` | Add 菜单加节点 | `{node_id, type, props}` |
| `graph.link` | `editor_graph_link` | `{"from": {node,pin}, "to": {node,pin}}` | 画布拖线 | `{link_id}` |
| `graph.set_props` | `editor_graph_set_props` | `{"node", "props"}` | 内联控件改属性 | `{node_id, props}` |
| `frame.request` | （`editor_capture` 内部） | `{"target": "editor"\|"pie"}` | 请求抓“下一渲染帧”（立即返回） | `{target, generation}` |
| `frame.fetch` | （`editor_capture` 内部） | `{"target", "generation"}` | 取帧; 就绪时行后跟二进制尾随帧 | `{ready, state, width, height, ..., binary_bytes}` |
| `editor.quit` | `editor_quit` | — | 点窗口 **X**（GLFW 正常关闭; 无窗口回退 `run_state=False`） | `{closing, via}` |

设计约定：
- **一切 op 复用编辑器现有 API**（不绕过控制器直接改状态），保证与人工操作行为一致；
- `view.set_mode` 会**写 `scene.game_type`**（与 Scene Type 按钮一致）——`2d` 时 PIE 启动选用 `DefaultCamera2D`（俯视正交）；
- 抓帧管线（`frame.*`）：主线程 pump 登记请求 → **目标引擎渲染线程**帧末 `glReadPixels`（SwapBuffer 前）
  → 单槽发布（generation 语义: ready / superseded / pending / error）→ 主线程 `fetch` 取回；
  主线程不等待、渲染线程不编码 —— PNG 编码在 MCP 进程（§5）；
- `graph.*` 直接操作 Node Editor 画布（PIE 注入的同一 canvas 实例）；
- v3 容器 ops（§4.1）与 v2 同一主线程泵机制；容器级缺口单独维护于 §10。

### 4.1 v3 — 实体 / 组件 / 选中 / 场景 / 资源（25 条, 2026-09-28 实机验证）

> GUI 状态联动（面板/轮廓/gizmo/树 reveal/选中清理）的完整契约与守卫测试见
> `ui_protocol.md` §10（每个 op 的 UI 同路径入口 + 联动维度）。

实体寻址: `{"id": N}` 或 `{"name": "..."}`（二选一; 名称不唯一时返回首个 + `duplicate_ids` 警告）。

| op | MCP 工具 | 语义（等价的人工操作） |
|---|---|---|
| `entity.list` | `editor_entity_list` | Entities 列表（`roots_only` 可仅根实体） |
| `entity.get` | `editor_entity_get` | 读取实体快照（组件/层级/可见性/transform — 角度制） |
| `entity.add` | `editor_entity_add` | 点 **+ New**（有选中时成为其子级; `parent` 可显式指定/解除; 自动选中新实体） |
| `entity.rename` | `editor_entity_rename` | Inspector 名称框（不强制唯一; 返回重名警告） |
| `entity.delete` | `editor_entity_delete` | 点 **Delete**（含子实体; 选中实体已不存在（自身/祖先被删）→ 轮廓/gizmo 级联清理） |
| `entity.transform` | `editor_entity_transform` | Inspector Transform（编辑器坐标/角度; `local` 本地; `relative` 相对调整=位移加法/旋转加法/缩放乘法; scale 可标量等比） |
| `entity.visible` | `editor_entity_visible` | 眼图标（editor）+ MeshRenderer.visible（render） |
| `entity.reparent` | `editor_entity_reparent` | 树拖拽建立父子（`"none"` 解除） |
| `selection.get/set/clear` | `editor_selection_*` | 点击选中 / 清空（`set` 默认带 gizmo — 等同视口点选; 树自动展开到选中项 reveal） |
| `component.types` | `editor_component_types` | 组件注册表（当前: Camera / MeshRenderer / Transform / Light / MediaPlayer / TextDisplay 等；旧名 DirectionalLight 自动迁移） |
| `component.list` | `editor_component_list` | 实体组件名列表 |
| `component.add` | `editor_component_add` | Inspector Add Component（MeshRenderer 自动绑 Cube 网格） |
| `component.remove` | `editor_component_remove` | Inspector 移除组件（Transform 不可移除; MeshRenderer 同步注销 GPU） |
| `component.get` | `editor_component_get` | 组件字段快照（通用序列化; MeshRenderer 附带 mesh/material 语义摘要） |
| `component.set` | `editor_component_set` | 部分字段更新 — Transform 支持 relative/标量缩放; MeshRenderer 支持 color/mesh/material/material_name/shader/**blend**/uniform/texture 系列; 其余字段直写（数值范围钳制 = `ComponentRegistry.FIELD_CLAMPS` 单一权威，Inspector/脚本/MCP 同口径） |
| `scene.list` | `editor_scene_list` | 场景列表 + 活跃场景 |
| `scene.switch` | `editor_scene_switch` | Scene 下拉切换（保存当前/加载/视口/节点图同步全流程 + 选中清理） |
| `scene.create` | `editor_scene_create` | 点 **+** 新建场景（新场景成为活跃 + 选中清理） |
| `scene.save` | `editor_scene_save` | 点 **💾**（省略 path 用最近路径; 联动 startup_scene） |
| `scene.load` | `editor_scene_load` | 点 **📂** 加载 .scene（全链同步 + 选中清理） |
| `resource.list` | `editor_resource_list` | 资源列表（mesh/shader/texture/material/prefab） |
| `resource.find` | `editor_resource_find` | 按名查找（线性扫描; 返回全部匹配） |
| `resource.material.get` | `editor_resource_material_get` | 材质详情（shader/颜色/纹理槽/uniform 键） |

### 4.2 v4 — 图校验 / 图导入导出 / 工程 / 扩展（12 条; 2026-10-02 起源, 扩展体系 2026-10-11 追加）

图校验已内化为**引擎服务**（`Application/Core/NodeGraph/validation/`, 协议详见 `graph_validation_protocol.md`）——
UI / MCP / 程序三入口共用同一服务实例；离线 `validate_graph` 已弃用退场。

| op | MCP 工具 | 语义 |
|---|---|---|
| `graph.validate.start` | `editor_graph_validate`（阻塞编排: start→poll→report） | 启动干跑校验; `source`: `"canvas"`(默认)/`"graph"`; `frames`(默认360)/`seed`(默认0) |
| `graph.validate.state` | （编排内部） | 任务状态 `{task_id, state, phase, progress}` |
| `graph.validate.report` | `editor_graph_validate_report` | 取回报告（`task_id` 省略=最新; `save_path` 落盘 .json/.txt） |
| `graph.validate.cancel` | `editor_graph_validate_cancel` | 取消运行中的任务（帧间生效） |
| `graph.export` | `editor_graph_export` | 导出画布 JSON（含 `_rules`; `path` 落盘） |
| `graph.import` | `editor_graph_import` | 导入 JSON 替换画布（`validate_first` 默认拒绝静态 error） |
| `project.open` | `editor_project_open` | 打开 .myproj（资源+场景全加载, 启动场景激活） |
| `project.save` | `editor_project_save` | 保存工程（File ▸ Save Project；`path` 省略=当前路径, 提供=Save As 换根） |
| `project.export` | `editor_project_export` | 导出工程包（File ▸ Export；`include_player` 默认 true=附游戏层成品含 runtime；false=纯工程包；目标目录须为空或旧导出，`output/` 实验数据保留） |
| `extension.list` | `editor_extension_list` | 扩展列表+状态+贡献 ops（扩展 op `ext.<id>.*` 增量扫描的发现入口；等价 Extensions 菜单） |
| `extension.enable` | `editor_extension_enable` | 启用扩展（加载 on_load/on_enable；等同菜单勾选；持久化到 `Config/extensions.json`） |
| `extension.disable` | `editor_extension_disable` | 停用扩展（on_disable/on_unload + 注销其全部 ext.<id>.* ops） |
| `settings.get` | — | 读取编辑器设置（`key` 省略=全量；UI 同路径 = Settings 面板 Common 页，协议 `ui_protocol.md` §13） |
| `settings.set` | — | 写入编辑器设置（校验+钳制 → 落盘 → **下一渲染帧生效**；脏值返回定格后的实际值） |

UI 入口：Node Editor 工具栏 **Validate** 按钮（静态 / 360 帧 / 600 帧；完成后自动弹报告窗口,
条目点击跳转节点; Copy / Export .json）。UI 与 MCP 任务互见（同一服务实例）。

## 5. agent 通道（MCP / CLI / Skill — v0.4.0 混合形态）

- **发布形态（独立分发; 收纳于 `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/`）**：源码唯一维护于 `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/src/engine_editor_mcp/`
  （console scripts `engine-editor-mcp` + `engine-editor-cli`）；`FlyVibing-User-And-Developer-Utils/packages/editor-mcp/mcp_server.py` 为薄 shim（dev/E2E 入口, 同一源码）。
  **纯 socket 客户端，不 import Application**（测试守卫已扩展到包源码）；
  三方工作区：`pip install` wheel（零依赖构建: `python FlyVibing-User-And-Developer-Utils/packages/editor-mcp/build_wheel.py`）→
  `engine-editor-cli setup --workspace <项目>`（拷贝 Skill + 合并 mcp.json, 默认 lite 档）；详见 `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/README.md`。
- **op 注册表（单一事实源）**：`src/engine_editor_mcp/ops.py`（55 ops: 摘要/参数/分类/旧工具别名; 每 op 含 call_timeout）。
  **扩展 op**（`ext.<id>.*`）为运行期增量注册，不入本静态表 — 发现用 `extension.list`, 调用直接透传
  （见 `Doc/ExtDev/extension_dev_protocol.md` §9）。
  驱动：CLI 命令与帮助、lite MCP 的 engine_help/engine_call、`docgen` 生成 `references/ops.md`；
  完整性由 `Test/Application/Editor/test_editor_mcp_package.py` 对照 `_register_ops` 守卫（新增 op 必须同步）。
- **MCP 档位**（`--profile lite|full` > env `MGE_MCP_PROFILE` > 默认 full）：
  - `lite`（推荐; 5 工具 ≈2.3k schema 字符 — 相比 full 44 工具 ≈17.9k 字符约 -87%）:
    `engine_help`（op 目录/详情, 按需读取）、`engine_call`（单 op; 兼容旧工具名; 大载荷自动瘦身）、
    `engine_batch`（顺序多 op, 省往返）、`engine_validate_graph`（detail=summary 默认）、`engine_capture`（图像直回）；
  - `full`：v1–v4 全部 44 个 `editor_*` 工具（向后兼容, 行为不变）—— lite 工具不注册；
  - 工具集裁剪在 `server.py::apply_profile`（幂等; 内部结构不可用时 fail-open）。
- **CLI**（`engine-editor-cli`, 零常驻上下文成本 — 终端型 agent 首选）：
  `ops` / `help` / `call <op> k=v...` / `batch` / `exec <script.py>`（注入 `engine` 客户端, 脚本内过滤输出）/
  `validate`（阻塞编排, summary 默认）/ `capture`（只落盘）/ `setup`（向任意工作区装 Skill+mcp.json）。
- **Skill**（`engine-editor`, 渐进披露）：SKILL.md（通道选择/速查/纪律）+ `references/ops.md`（docgen 生成）
  + `references/workflows.md`（配方）；安装: `engine-editor-cli setup` 或仓库 `install_mcp.py`（同步到 `.github/skills/`）。
- **帧图像**（`engine_capture`）：request → 轮询 fetch → numpy 翻转（GL bottom-up → top-down，本进程）→
  Pillow 编码 PNG → ① 落盘 ② 返回 MCP 图像内容块（agent 可直接查看画面 + 说明文本含路径）；想省 token 用 CLI `capture`（只回路径）；
- 抓帧目录：`<临时目录>\engine_editor_mcp\frames\frame_{editor|pie}_{时间戳}_g{gen}.png`
  （默认 `%TEMP%`; 环境变量 `MGE_MCP_FRAMES_DIR` 可覆盖）；**清理策略：入口进程启动时清空**（import 不清空）；
- 编辑器未运行时返回人话错误：`编辑器未运行（127.0.0.1:8977 无监听）— 请先启动 startup.bat。`
- 注册（dev 仓库）：`.venv-py314t\Scripts\python.exe FlyVibing-User-And-Developer-Utils/packages/editor-mcp/install_mcp.py [--profile lite|full]` →
  写 `.vscode/mcp.json`（名称 `engine-editor-live`）+ 同步 Skill → **重载 VS Code 生效**；卸载 `--uninstall`；
- 注册（外部工作区）：`engine-editor-cli setup --workspace <dir>`；引擎侧无需任何配置。

## 6. 新增一个 op 的步骤（扩展清单）

1. `LiveCommandServer._register_ops()` 里注册 `"域.动作": cls._op_xxx`；
2. 实现 `_op_xxx(args) -> dict`（**主线程**执行；只调编辑器 API/控制器；错误直接 raise，pump 会转成受控错误）；
3. agent 侧登记（v0.4.0 起）：
   - `src/engine_editor_mcp/ops.py` 加条目（摘要/参数/分类）—— CLI、lite MCP（engine_help/engine_call）立即生效；
   - 需要旧式独立工具（full 档）再加 `@mcp.tool()` 薄包装（→ `_send("域.动作", args)`）；lite 档无需；
   - 图像类 op: handler 返回的 result 里放 `_payload`（bytes）+ `binary_bytes`
     （socket 线程会在行后追加裸负载, 不入 JSON）；
   - 跑 `python -m engine_editor_mcp.docgen` 重生成 `skills/engine-editor/references/ops.md`；
4. 测试：`Test/Application/Editor/test_live_command_server.py` 加往返断言（图像类用 `roundtrip_binary`）；
   `Test/Application/Editor/test_editor_mcp_package.py` 校验注册表与引擎一致 + ops.md 新鲜度；
5. 更新本文档 op 表（及 §5/§8/§9 如涉及）。

## 7. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| MCP 工具报"编辑器未运行" | 编辑器没开 / 端口被环境变量改了两侧不一致 / 启动日志里有 bind 失败 |
| 工具一直超时 | 编辑器主线程被卡住（如 modal 操作）；看编辑器控制台 `[Live] id=...` 是否有输出 |
| 端口占用 | 改 `MGE_EDITOR_MCP_PORT`（两侧同时设）或关掉占用进程 |
| `.vscode/mcp.json` 不生效 | 重载 VS Code 窗口；或 Command Palette → `MCP: List Servers` 手动重启 |
| 某个 server 的工具缺失 / 启动失败 | `.vscode/mcp.json` 的 `command`/`cwd` 指向已搬迁的旧仓库路径（2026-09 实测: node-graph-editor 曾指向 `...\MI-SSSEP\Experiment\MyGameEngine-Python`，该路径已不存在）→ 用 `Test-Path` 核对后更新为当前仓库路径，再重载 VS Code |
| `editor_capture` 超时 / 一直 pending | PIE 未运行（报 `PIE is not running`）/ 渲染线程卡住；看控制台 `[Live] frame.*` 审计行与 `sim.state` |

## 8. 测试与验收

```powershell
# 无头回环测试（60 项断言: 生命周期 / 控制 / 二进制尾随帧 / v3 容器 / v4 校验·导入导出受控错误; 不需要 GUI）
.venv-py314t\Scripts\python.exe Test/Application/Editor/test_live_command_server.py
# EditorMcp 独立包离线套件（注册表 / lite schema 预算 / CLI / setup / docgen / wheel; 不需要 GUI）
.venv-py314t\Scripts\python.exe Test/Application/Editor/test_editor_mcp_package.py
# 校验服务专项（29 项: 静态规则 / 干跑 / 任务流 / 忙拒绝 / 取消; 不需要 GUI）
.venv-py314t\Scripts\python.exe Test/Application/NodeGraph/test_graph_validation.py
# 实机 E2E-v4（需 startup.bat 运行中）: 打开 MI-SSSEP 工程 → 切场景 → 画布干跑校验 → 导出/回灌
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_mcp_validate_mi_sssep.py
# 实机 E2E-v2（需 startup.bat 运行中）: graph 搭建 → 2D → PIE → 双窗口抓帧 → 停机
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_mcp_live_check.py
# 实机 E2E-v3: 实体新建/改名/移形 → 组件增改 → 选中 → 截图 → reparent → 删除
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_mcp_entities_check.py
# 实机 E2E-v3.1: Transform/MeshRenderer “提示指示”: 标量缩放/相对位移/材质改名/uniform/纹理/显隐截图
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_mcp_cue_check.py
```

实机验收基线（2026-09-28 已通过）：
1. `graph.add EntitySpawn(template=DefaultCube)` + `graph.link OnGameStart.exec → exec_in`
   → 控制台出现 `[EntitySpawn] 'DefaultCube' (eid=..., template='DefaultCube')`；
2. `view.set_mode 2d` → `game_type=2d`，PIE 使用 `DefaultCamera2D`（俯视正交）；
3. `capture pie` → **画面中央白色方块**（PNG 落盘 `<临时目录>\engine_editor_mcp\frames\`）；
   `capture editor` → 编辑器全 UI 画面（含 ImGui）；
4. `camera.get` 返回实体 1 实时属性；`sim.stop` → `Stopped`；`editor.quit` → 正常退出；
5. v3 容器链路：`entity.add → rename → transform → component.add(MeshRenderer, 默认 Cube) →
   component.set(color 红, 材质自动独立为 `Default_copy`) → selection.set(gizmo) → 截图可见红色实体 →
   reparent → entity.delete` 全通；`resource.find` / `resource.material.get` / `scene.list` 正常；
6. v3.1 Transform/MeshRenderer（“提示指示”链路）：标量缩放（`scale: 2.0`）✓、相对位移（+[1,0,0] 后 x=1.0）✓、
   `material_name` / `shader`(按名) / `uniform`(uColor=[1,0.5,0] 数据验证) / `texture` 替换 ✓、
   `component.get` 附带 mesh/material 摘要 ✓；提示显隐两次截图（出现 120KB / 隐藏 95KB, 视觉确认消失）。
7. v4 校验内化（2026-10-02 已通过, `e2e_mcp_validate_mi_sssep.py` 13/13）：`project.open`（Paradigm 的 MI-SSSEP 工程,
   4 场景）→ `scene.switch MI-SSSEP` → 画布 **141 nodes / 167 links** → 干跑校验 **静态 0E/0W · 运行时 0E ·
   360 帧 / 15 事件 / 82.5 ms · ok=True** → 报告落盘 `FlyVibing-User-And-Developer-Utils/packages/editor-mcp/tmp/validation_mi_sssep.txt` →
   `graph.export/import` 回灌一致。干跑语义注意: 实体查找（EntityGet）在干跑下查不到真实实体（副作用被跳过）,
   以 stdout 提示 `[EntityGet] 'x' not found` 但不计 error（图的防御写法不受影响）。

## 9. 路线（后续阶段）

- **agent 通道 v0.4.0（2026-10-05 落地）**：MCP 双档位（lite 5 工具 / full 44 工具）+ CLI
  （ops/help/call/batch/exec/validate/capture/setup）+ Skill（渐进披露）+ op 注册表/文档生成 —— 见 §5/§6。
- ~~阶段 2~~（2026-09-28 大部分落地）：`sim.stop` ✅、图编辑 ops（`graph.add/link/set_props` + `graph.list` ✅；
  `graph.remove` 未做）、`view.screenshot` ✅（`frame.request/fetch` + `editor_capture`，PNG 在 MCP 进程）；
  仍缺：`sim.pause/resume` 暴露、`graph.remove`、帧环形日志（"实时图像=调试日志"）；容器级缺口见 §10。
- **阶段 3**：事件推送（选中变化 → MCP 通知）、只读开关、多客户端。~~`validate_only` 空跑~~ ——
  2026-10-02 已落地: 校验内化为引擎服务（v4 `graph.validate.*` + UI Validate 按钮, 见 `graph_validation_protocol.md`）。

## 10. 容器补全跟进（Follow-ups — 2026-09-28 盘点）

MCP 容器接口（entity / component / scene / resource）的已知缺口与待补项；完成一项从本表划掉并在 §4.1 增行。

| # | 项 | 现状 | 需补充（含影响 op） |
|---|---|---|---|
| 1 | 场景删除 / 改名 | `_scenes` 仅 create/switch | `scene.delete/rename`（联动 startup_scene / 文件 / 内存对象） |
| 2 | 资源名称索引 | 无通用 name→id（MCP 为线性扫描）; 材质可重名 | name 索引 + 冲突策略；`GetDefaultMesh` 返回路径不完整（else 分支/无兜底） |
| 3 | 材质写操作 | 实体侧已就绪（v3.1: `component.set` 提供 color / material_name / shader / uniform / texture 系列）; 材质级 new/clone/assign/save/load 未暴露 | `resource.material.new/clone/assign/save/load/set_shader` |
| 4 | prefab 实例化 | `PrefabManager` 已有; 按名无索引 | `resource.prefab.instantiate/list`（确认 GPU 注册路径） |
| 5 | 实体复制 / 粘贴 | controller 已有 copy/paste/clipboard | `entity.copy/paste` |
| 6 | 组件注册表扩展 | 内置 3 类于 `SceneManager.Init` 注册; `ComponentRegistry.ensure_defaults()` 为死代码 | 新组件注册入口；清理死代码（SceneSync 已消费注册表） |
| 7 | 代码卫生 | `SceneManager.HasComponent/RemoveComponent` 函数体有孤立 `self` 表达式 | 清理 |
| 8 | 名称唯一性策略 | entity / 材质均不强制唯一（MCP 层返回 duplicate 警告 / 全部匹配） | 是否强制唯一/自动去重的产品决策 |
| 9 | 通用组件字段写入 | 不触发 `ComponentModifiedEvent`（仅专用路径触发） | 评估补事件（Inspector 实时刷新） |
| 10 | 多选 / 批量 | `selection.*` 仅单选 | 多选 ops（`OutlinerID` 已支持集合） |
