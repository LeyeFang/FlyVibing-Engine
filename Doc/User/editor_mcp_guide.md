# 编辑器 MCP 助手命令手册（User Guide）

> 适用：MyGameEngine-Python 编辑器 + VS Code / GitHub Copilot 聊天。
> 本文面向**编辑器使用者**：用自然语言指挥 AI 助手实时操作运行中的编辑器。
> （开发/协议细节见 `Doc/Dev/editor_live_protocol.md`，本文不含内部原理。）

---

## 1. 这是什么

编辑器内置了一条"AI 助手通道"（MCP）。**编辑器运行时**，VS Code 里的 Copilot 助手可以直接：

- 查询/修改场景：实体（新建、改名、移动、父子、显隐）、组件（增加、删除、读写）、节点图（加节点、连线、改属性、**干跑校验**、导入导出）、摄像机、场景（列表、切换、新建、保存、加载）、资源（列表、按名查找、材质详情）、**工程（打开 .myproj）**；
- 运行控制：启动/停止 PIE（Play In Editor）、切换 2D/3D/Overlay 场景类型；
- 截取**编辑器窗口或 PIE 运行画面**（助手能直接看到截图内容，也能存成 PNG 文件）。

你**不需要输入命令**——直接对助手说人话，它会自动调用对应命令。

---

## 2. 准备工作

1. 启动编辑器：运行 `startup.bat`（控制台出现 `[Live] Editor command server on 127.0.0.1:8977` 即就绪）；
2. **注册助手服务（仅一次 — v0.4.0 起一条命令搞定）**：

   ```powershell
   # 在你的实验项目工作区下执行（任意 IDE/平台；同时安装 Skill —— 大幅省 token）
   engine-editor-cli setup --workspace .
   ```

   - 会写入 `.vscode/mcp.json`（**lite 档**，5 个精简工具）并把 Skill 拷到 `.github/skills/engine-editor/`；
   - **安装版**：`engine-editor-cli` / `engine-editor-mcp` 是安装目录内的命令（安装时勾选 PATH 任务即可直接使用；未勾选则写绝对路径 `<安装目录>\engine-editor-cli.cmd`）。**无需任何外部 Python 环境——Python 由引擎自带运行时提供**；
   - **源码仓库（开发）**：`.venv-py314t\Scripts\python.exe Utils\User\EditorMcp\install_mcp.py`（默认 lite 档，可 `--profile full`）。

   不想用 MCP 的平台也可以只用命令行：`engine-editor-cli call sim.state`（见 §3.12）。
3. **首次注册或工具更新后**：重载一次 VS Code 窗口（或 Command Palette → `MCP: List Servers → engine-editor-live → 重启`）；
4. 打开 Copilot 聊天，直接对话。

---

## 3. 命令一览（助手执行的工具）

> 直接说人话即可；下表列出助手实际调用的命令名与参数，便于你精确指定或对照。
>
> **版本说明（v0.4.0）**：下表是 **full 档**（44 工具）的命令名；默认安装现为 **lite 档**（5 工具，schema 从 ≈17.9k 字符降到 ≈2.3k，大幅省 token）：
> 助手通过 `engine_call <op> ...` / `engine_batch` 调用同样能力，或直接终端用 `engine-editor-cli`（§3.12）。
> 想回到旧工具名行为：注册时 `--profile full`（或环境变量 `MGE_MCP_PROFILE=full`）。

### 3.1 运行控制 / 场景类型

| 命令 | 作用 | 参数 | 示例说法 |
|---|---|---|---|
| `editor_run_pie` | 启动 PIE 运行 | — | "运行一下" |
| `editor_stop_pie` | 停止 PIE | — | "停一下" |
| `editor_sim_state` | 查询运行状态 | — | "现在在运行吗？" |
| `editor_switch_2d` | 切 2D 正交俯视（等同 Scene 面板 "2D" 按钮，同时设置场景类型） | — | "切到 2D 视图" |
| `editor_set_scene_type` | 设置场景类型 | `mode`: "3d" / "2d" / "overlay" | "把场景类型设为 Overlay" |

### 3.2 摄像机

| 命令 | 作用 | 参数 |
|---|---|---|
| `editor_camera_get` | 读取场景摄像机（位置/旋转/投影/fov/ortho 等） | `role`: "3d" / "2d" / "overlay" |
| `editor_camera_set` | 修改场景摄像机（只改传入字段） | `role` + `position` / `rotation` / `projection` / `ortho_size` / `fov` |

### 3.3 节点图

| 命令 | 作用 | 说明 |
|---|---|---|
| `editor_graph_list` | 查看节点图（节点/连线/属性） | "看看节点图里有什么" |
| `editor_graph_add` | 加节点 | `node_type` + 可选 `props`；例：加 `EntitySpawn`，`props={"template": "DefaultCube"}` |
| `editor_graph_link` | 连线 | 例：`OnGameStart.exec → EntitySpawn.exec_in` |
| `editor_graph_set_props` | 改节点属性 | `node_id` + `props` |

### 3.4 截图

| 命令 | 作用 | 参数 |
|---|---|---|
| `editor_capture` | 抓取窗口画面（PNG + 直接展示给助手） | `target`: "editor"（编辑器窗口）/ "pie"（运行时窗口，需 PIE 运行中） |

- 图片存放：系统临时目录 `%TEMP%\engine_editor_mcp\frames\`（文件名 `frame_编辑器或pie_时间戳.png`），可用环境变量 `MGE_MCP_FRAMES_DIR` 更改位置；
- **清理规则**：助手服务每次启动时自动清空该目录（重要截图请另存到你的项目目录）。

### 3.5 实体

| 命令 | 作用 |
|---|---|
| `editor_entity_list` | 列出所有实体（可只要根实体） |
| `editor_entity_get` | 读取实体详情（组件、父子、可见性、位置/旋转/缩放 — 旋转为角度） |
| `editor_entity_add` | 新建实体（与 **+ New** 一致：有选中时会成为其子级；可指定 `parent`） |
| `editor_entity_rename` | 改名（不强制唯一；重名会给提示） |
| `editor_entity_delete` | 删除实体（连同子实体） |
| `editor_entity_transform` | 设置位置 / 旋转（角度）/ 缩放（可标量等比；可选本地坐标；`relative=true` 相对调整 — 位移加法/旋转加法/缩放乘法） |
| `editor_entity_visible` | 编辑器视口可见性（眼图标）与渲染可见性 |
| `editor_entity_reparent` | 设置父实体（`parent` 传 `"none"` 解除） |

### 3.6 选中

| 命令 | 作用 |
|---|---|
| `editor_selection_get` | 当前选中的实体 |
| `editor_selection_set` | 选中实体（默认同时显示变换 gizmo，等同视口点选） |
| `editor_selection_clear` | 取消选中 |

### 3.7 组件

| 命令 | 作用 |
|---|---|
| `editor_component_types` | 可用组件类型表（当前：Camera / MeshRenderer / Transform / Light / MediaPlayer / TextDisplay 等；旧名 DirectionalLight 自动迁移） |
| `editor_component_list` | 实体的组件列表 |
| `editor_component_add` | 添加组件（MeshRenderer 自动绑定默认 Cube 网格） |
| `editor_component_remove` | 移除组件（Transform 为实体必需，不可移除） |
| `editor_component_get` | 读取组件全部字段（MeshRenderer 还会附带网格/材质的摘要信息） |
| `editor_component_set` | 修改组件字段，例如：<br>• MeshRenderer：`{"mesh": "Cube", "material": 2, "color": [1,0,0], "visible": true, "material_name": "Cue", "shader": "Basic", "blend": "alpha", "uniform": {"uColor": [1,0.5,0,1]}, "texture": "Default"}`<br>• Transform：`{"position": [3,0,0], "rotation": [0,90,0], "scale": 2}`<br>• Camera：`{"fov": 60, "projection": "ortho"}`<br>• Light：`{"light_type": "point", "intensity": 2, "range": 8, "color_r": 1, "color_g": 0.55, "color_b": 0.2}`（`directional` 平面光 / `point` 点光；数值自动钳制到合法范围） |

### 3.8 场景

| 命令 | 作用 |
|---|---|
| `editor_scene_list` | 场景列表 + 当前场景 |
| `editor_scene_switch` | 切换场景（含保存当前、刷新视口与节点图） |
| `editor_scene_create` | 新建场景 |
| `editor_scene_save` | 保存为 `.scene`（可指定路径；省略时用最近保存路径） |
| `editor_scene_load` | 从 `.scene` 文件加载 |

### 3.9 资源

| 命令 | 作用 |
|---|---|
| `editor_resource_list` | 列出资源（mesh / shader / texture / material / prefab） |
| `editor_resource_find` | 按名查找资源（返回全部同名匹配） |
| `editor_resource_material_get` | 材质详情（shader / blend / 颜色 / 纹理槽 / uniform 键） |

### 3.10 关闭

| 命令 | 作用 |
|---|---|
| `editor_quit` | 关闭编辑器（等同点窗口 X） |

### 3.11 图校验 / 导入导出 / 工程

| 命令 | 作用 | 参数 / 说明 |
|---|---|---|
| `editor_graph_validate` | **干跑校验当前节点图**（静态检查 + 6 秒模拟运行） | 返回完整报告（错误/警告/事件日志）；需编辑器运行中 |
| `editor_graph_validate_report` | 取回最近一次校验报告 | 可指定 `task_id`；`save_path` 可落盘 .txt/.json |
| `editor_graph_validate_cancel` | 取消正在跑的校验 | — |
| `editor_graph_export` | 导出节点图 JSON 文件 | `path` 落盘位置（含规则文档） |
| `editor_graph_import` | 导入节点图 JSON 替换当前图 | 导入前自动静态检查，有错会拒绝 |
| `editor_project_open` | 打开 `.myproj` 工程 | 资源+场景全量加载，自动激活启动场景 |
| `editor_project_save` | 保存工程 | 等同 File ▸ Save Project；带 `path` = Save As（换根保存） |
| `editor_project_export` | 导出工程包 | 等同 File ▸ Export；`include_player`（默认 true）附游戏层 → 自包含成品（含 runtime）；false = 纯工程包 |

> 也可以直接在 Node Editor 面板点 **Validate** 按钮：完成后面板自动弹「Validation Report」窗口，
> 点报告里的条目能直接跳转到对应节点；支持复制摘要 / 导出 JSON。
> **注意**：图校验现在在引擎内执行 —— 需要编辑器运行中（旧版"离线校验"已停用）。

### 3.12 终端命令行 `engine-editor-cli`（省 token 推荐）

不想（或不能）通过 MCP 时，可在任意终端直接操作编辑器；对 AI agent 而言这是**零常驻上下文成本**的通道，
多步操作/批处理/脚本都推荐用它：

| 命令 | 作用 |
|---|---|
| `engine-editor-cli ops` | 列出全部 53 个核心 op（一行一个；扩展 op 经 `extension.list` 发现） |
| `engine-editor-cli help <op>` | 单 op 详情（参数 + 示例） |
| `engine-editor-cli call <op> k=v ...` | 执行一个 op（数组/对象值加引号，如 `position='[1,0,2]'`） |
| `engine-editor-cli batch ops.json` | 一次执行多个 op（JSON 数组；`-` 读 stdin） |
| `engine-editor-cli exec script.py` | 脚本模式（注入 `engine` 客户端，可过滤输出 → 省 token） |
| `engine-editor-cli validate` | 图干跑校验（默认摘要；`--detail full` / `--save` 取全量） |
| `engine-editor-cli capture pie --out f.png` | 抓帧并落盘（只回路径，不回传图像） |
| `engine-editor-cli setup [--workspace DIR]` | 安装/更新 Skill + `.vscode/mcp.json`（`--uninstall` 卸载） |

示例：`engine-editor-cli call entity.add name=Cue` → `{"id": 6, ...}`；
编辑器未运行时返回人话错误并退出码 1（不会卡住）。

---

## 4. 典型使用场景

**① 摆场景 + 看图**
> "把 DefaultCube 移到 (3, 0, 0)，选中它，然后截一张编辑器窗口的图给我看看。"

**② 新建物体**
> "新建一个叫 Target 的实体，加一个 MeshRenderer，颜色改成蓝色；挂在 DefaultCube 底下。"

**③ 运行验证**
> "切到 2D 视图，运行 PIE，截一张运行时画面。"

**④ 查资源**
> "列出所有的材质，并告诉我 DefaultCube 用的材质是什么 shader。"

**⑤ 节点图速搭**
> "加一个 EntitySpawn 节点（模板 DefaultCube），把 OnGameStart 连到它，然后运行并截图。"

**⑥ 提示指示（实验常用）**
> "新建一个 2 倍大的方块放 (0, 0, 2)，颜色改成青色，材质改名 Cue_Cyan；截图看看；
> 然后把它隐藏，再截一张对比。"
> （“往右挪 1 格”这类相对调整也可以直接说 — 等同于拖拽 gizmo。）

---

## 5. 注意事项

- **必须编辑器在运行**；否则助手会提示"编辑器未运行 — 请先启动 startup.bat"。
- 所有操作与手动点击**等价**（走同一套编辑器逻辑），你在屏幕上能实时看到变化。
- **名称不强制唯一**：按名操作时匹配第一个，助手会提示存在重名（建议用实体 ID 精确指定）。
- **改名提醒**：节点图里按名字引用的（如生成实体的模板名）会跟着名字变化。
- 运行中窗口截图（`pie`）需 PIE 处于运行状态；编辑器窗口（`editor`）随时可截。
- 通道仅监听本机（127.0.0.1），外部网络不可访问。

---

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| 助手说"编辑器未运行" | 先运行 `startup.bat`；确认编辑器控制台有 `[Live] Editor command server on 127.0.0.1:8977` |
| 聊天里找不到这些命令（助手不能用） | 重载 VS Code 窗口；或 `MCP: List Servers → engine-editor-live → 重启` |
| 助手工具名变成 `engine_call` 等（不再是 editor_*） | 正常 — v0.4.0 默认 lite 档（省 token）；`--profile full` 可回到旧 44 工具 |
| 找不到 `engine-editor-cli` 命令 | 安装时未勾选 PATH → 用绝对路径 `<安装目录>\engine-editor-cli.cmd`；源码仓用 `.venv-py314t\Scripts\engine-editor-cli.exe` |
| Skill 不生效/想更新 | 在项目目录重新跑 `engine-editor-cli setup --workspace .`，再重载窗口 |
| 截图找不到 | 查看 `<临时目录>\engine_editor_mcp\frames\`（默认 `%TEMP%`；可用环境变量 `MGE_MCP_FRAMES_DIR` 覆盖）；注意该目录会在助手服务启动时自动清空 |
| 工具报"PIE is not running" | 截图运行时窗口前先"运行一下" |
| 端口被占用 | 关闭占用进程，或在启动前的环境变量中设置 `MGE_EDITOR_MCP_PORT`（编辑器与 VS Code 两侧需一致） |
