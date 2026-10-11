---
name: engine-editor
description: "控制正在运行的 MyGameEngine 编辑器：创建/修改场景与实体、编辑与校验节点图、运行 PIE、抓帧截图、打开工程。Use when the user asks to build or edit experiment scenes in the engine, wire/validate node graphs, run or screenshot the editor, or AI-generate an engine project. 通道: engine-editor-cli（终端首选，省 token）或 engine-editor-live MCP（lite 档: engine_help / engine_call / engine_batch / engine_validate_graph / engine_capture）。"
---

# Engine Editor 实时控制（MyGameEngine）

用 CLI 或 MCP 操作**正在运行的编辑器**（127.0.0.1:8977 回环；所有操作与人工点击等价）。

## 0. 前置检查（先做，一次）

1. 编辑器必须在运行（仓库: `startup.bat`；发行版: 安装快捷方式）。就绪标志（编辑器控制台）: `[Live] Editor command server on 127.0.0.1:8977`。
2. 若返回 `编辑器未运行（127.0.0.1:8977 无监听）` → **不要重试循环**，直接告诉用户先启动编辑器。
3. 端口自定义时两侧都设 `MGE_EDITOR_MCP_PORT`（默认 8977）。

## 1. 通道选择（token 成本排序）

| 通道 | 未使用时的常驻成本 | 何时用 |
|---|---|---|
| `engine-editor-cli`（终端） | **0** | 默认首选：多步、批处理、脚本、需要过滤输出 |
| MCP `engine_call` / `engine_batch` | ~0.7k tokens（lite 档 5 工具） | 无终端权限、或任务需要图像直回 |
| MCP 旧 `editor_*` 工具（44 个） | ~5.6k tokens（full 档） | 仅当 `MGE_MCP_PROFILE=full` 且提示词已绑定旧工具名 |
| `engine_capture`（MCP） | 同 lite | 需要**看到**画面时；否则 `engine-editor-cli capture`（只落盘） |

## 2. CLI 速查

```powershell
engine-editor-cli ops                        # op 目录（53 个核心 op; 一行一个; 扩展 op 见 extension.list）
engine-editor-cli help entity.transform      # 单 op 详情（参数 + 示例）
engine-editor-cli call entity.add name=MCP_Cue
engine-editor-cli call entity.transform id=5 position='[1,0,2]' scale=2
engine-editor-cli call component.set id=5 type=MeshRenderer fields='{"color":[0.2,0.7,1,1]}'
engine-editor-cli call component.set id=5 type=MeshRenderer fields='{"blend":"alpha","color":[0,1,0,0.5]}'   # 半透明
engine-editor-cli call component.set id=5 type=MeshRenderer fields='{"shader":"Lighting"}'                    # 受光（默认场景含 Sun）
engine-editor-cli call component.set name=X type=TextDisplay fields='{"text":"你好","size":72,"bold":true}'  # 文字（自动生成纹理; 见 text_protocol.md）
engine-editor-cli call sim.play
engine-editor-cli batch ops.json             # [{"op":...,"args":{...}}, ...]（- = stdin）
engine-editor-cli exec build_scene.py        # 脚本模式（见 §4）
engine-editor-cli validate                   # 干跑校验（默认 summary）
engine-editor-cli validate --detail full --save report.json
engine-editor-cli capture pie --out cue.png  # 抓帧（只回路径）
engine-editor-cli probe editor --points 160:120;800:450   # 像素采样（顶左坐标 → RGBA; 免图像通道）
engine-editor-cli call renderer.snapshot     # 渲染器状态（后端/GL/资源计数/帧统计）
engine-editor-cli call project.save          # 保存工程（当前路径; 带 path=Save As）
engine-editor-cli call project.export target_parent=D:/out include_player=true   # 导出成品（含 runtime; 分钟级）
```

- 值解析：先按 JSON（数字/true/false/数组/对象/带引号字符串），失败按纯字符串；`parent=none` 即字符串。
- Windows 终端里数组/对象**要加引号**（PowerShell 用单引号包 `'[1,0,2]'`）。
- 未知 op 会退出码 2 并给出相近建议；`_unknown_args` 字段提示拼错的参数名。

## 3. 常用 op（完整表: `references/ops.md`）

| op | 用途 |
|---|---|
| `sim.play` / `sim.stop` / `sim.state` | PIE 启停与状态 |
| `view.set_mode` | 场景类型 3d/2d/overlay（影响 PIE 摄像机） |
| `view.set_grid` | 显示/隐藏视口网格（View 菜单 Show Grid 同路径; visible=true/false） |
| `threads.snapshot` | 线程注册表快照（配合 `Utils/Dev/thread_probe.py` 探针; 见 threading_protocol.md） |
| `renderer.snapshot` | 渲染器状态快照（GL 信息/资源计数/视口/帧统计; 无头时 available=false） |
| `entity.add` / `entity.list` / `entity.get` | 实体新建/列举/详情（id/name 寻址） |
| `entity.transform` | 位置/旋转(角度)/缩放；`relative=true` 相对调整；`scale` 可标量 |
| `entity.visible` / `entity.delete` / `entity.rename` / `entity.reparent` | 显隐/删除/改名/父子 |
| `selection.set` | 选中（截图前常用来打高亮/显示 gizmo） |
| `component.add` / `component.set` / `component.get` | MeshRenderer: `mesh/material/material_name/color/shader/**blend**/uniform/texture/visible`；`blend`=`"opaque"|"alpha"`（透明由渲染器排序处理）；`shader` 切到 `Lighting` 可受方向光/环境光影响（切 shader 会重置材质 uniform — 先切后设参）；`TextDisplay`: `text/font/size/bold/italic/color/bg_color/align/...`（自动光栅化纹理; PIE 用 SetText 节点驱动） |
| `scene.list` / `scene.switch` / `scene.save` / `scene.load` | 场景管理 |
| `graph.list` / `graph.add` / `graph.link` / `graph.set_props` | 节点图编辑（等价画布操作） |
| `graph.validate.start`(→`state`/`report`) | 图干跑校验（静态+模拟; 见 §5） |
| `graph.export` / `graph.import` | 图落盘/回灌（**export 一定带 `path`**，见 §5） |
| `project.open` / `project.save` / `project.export` | 工程：打开 `.myproj` / 保存（带 `path`=Save As）/ 导出（`target_parent` 必填; `include_player` 默认 true=自包含成品） |
| `extension.list` / `extension.enable` / `extension.disable` | 扩展体系：发现（含 `ext.<id>.*` 扩展 op 清单）/ 启停；扩展 op 直接调（`ext.*` 透传, 如 `ext.sigproc.info`） |
| `camera.get` / `camera.set` | 场景摄像机读写 |
| `resource.list` / `resource.find` / `resource.material.get` | 资源与材质查询 |

## 4. 脚本模式（多步操作首选）

`engine-editor-cli exec script.py` 注入全局 `engine` 客户端（失败会 raise）:

```python
names = ["Cross", "L_Cue", "R_Cue"]
pos = {"Cross": [0, 0, 0], "L_Cue": [-2, 0, 0], "R_Cue": [2, 0, 0]}
ids = {}
for n in names:
    r = engine.ok("entity.add", name=n)
    ids[n] = r["entity_id"]
    engine.ok("component.add", id=r["id"], type="MeshRenderer")
    engine.ok("component.set", id=r["id"], type="MeshRenderer", fields={"color": [0.2, 0.7, 1, 1]})
    engine.ok("entity.transform", id=r["id"], position=pos[n], scale=2)
print("created:", ids)   # 只打印需要的信息 → 其余不进入上下文
```

- `engine.ok(op, **args)` 失败 raise；`engine.try_send(...)` 失败返回 `{"error"}`；`engine.capture("pie")` → PNG 路径；`engine.batch([(op, args), ...])`。
- **在脚本里做过滤/汇总**（这是省 token 的关键）：不要 `print(engine.ok("graph.list"))` 全量 JSON。

## 5. Token 纪律（重要）

- 节点图别整图回传：`graph.export` 传 `path` 落盘（CLI/MCP lite 自动 `inline=false`，只回 counts+saved_path）；要看结构时读文件或分片查。
- 校验默认 summary；排错时才 `--detail full` 或 `save_path` 落盘后局部读。
- 多步操作用 `engine_batch` 或 `exec` 脚本一次完成，禁止 10+ 次单 op 往返。
- 抓帧默认 CLI（只回路径）；**需要你看画面**时才用 MCP `engine_capture`（图像直回）。
- 全量 op 参考（含每个参数）在 `references/ops.md` — 只在确实需要时读。

## 6. 常见工作流

见 `references/workflows.md`：提示场景搭建 / 实体+组件批量创建 / 节点图搭建与校验 / 工程打开与场景切换 / PIE 运行截图对比 / 干跑语义注意事项。

## 7. 故障排查

| 现象 | 处理 |
|---|---|
| 编辑器未运行（无监听） | 先启动编辑器，不要重试 |
| 名称重复警告 | 按名取首个匹配；改用 `id` 精确指定 |
| `capture pie` 报 PIE is not running | 先 `sim.play`，等 `sim.state` = Running |
| 端口占用 | 双侧设 `MGE_EDITOR_MCP_PORT` 或关掉占用进程 |
| 工具/命令缺失 | 重载 IDE 窗口；或 `engine-editor-cli setup` 重新安装 skill + mcp.json |
| 超时 | 看编辑器控制台 `[Live] id=...` 审计行（主线程可能被 modal 卡住） |
