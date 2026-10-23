# 测试节点图与 UI 展开图 — 待办与上下文（2026-10-21）

> 目标：把“测试覆盖认知”和“UI 控件归属”变成可查询、可校验、可增量维护的开发资产。
> 本文是跨会话的**任务上下文**；实现进度以下方复选框和 `git status` 为准。
> 当前仓库：`C:\WorkSpace\FLY\FlyVibing-Engine`（Python 3.14 free-threaded，`.venv-py314t`）。
> 关联协议：`Doc/Dev/test_protocol.md`、`Doc/Dev/ui_protocol.md`。

## 0. 已确认的设计决定

1. **一个测试文件 = 一个 test node**（与现有一文件一子进程的 runner 一致）。
2. **测试节点之间不建立执行顺序依赖**；边只表达静态关系：
   - `covers`：被覆盖的模块/符号/行为
   - `requires`：运行前置（fake engine、project fixture、GL、device、editor process）
   - `exercises`：关联的 UI state/control/action
   - `visualizes`：关联的 UI scenario / screenshot
3. **机器可读唯一事实源**：`Doc/Dev/test_nodes.json`（零第三方依赖；当前 venv 无 PyYAML）。
   - `Doc/Dev/test_nodes.md` 由 CLI 生成，作为人读速查表，不手工维护。
   - 地图放在 `Doc/Dev`；`Test/` 采用**局部白名单**：跟踪测试源码、Helpers/Resources/Device、`TestProject` 工程源和 `Test/README.md`；忽略 `_runs/`、`dist/`、`output/`、`runtime/`、`seed/`、缓存、截图和日志。
   - `Doc/Dev/ui_map.json` / `ui_map.md` 作为 UI 展开图事实源与生成速查表（Phase 3 首版已落地）。
4. **执行档位 `tier` 与行为层级 `kind` 分离**：
   - `tier`: `core` / `gui` / `heavy` / `live` / `manual`
   - `kind`: `unit` / `contract` / `integration` / `ui-behavior` / `ui-visual` / `e2e` / `stress` / `manual`
5. **不把“源码文件 import 比例”当覆盖率**；它只用于发现盲区。真正的覆盖证据来自 test node 的 `covers` 和行为断言。
6. UI 图采用 **state machine + control tree**：
   - `state`：`project.loaded`、`scene.loaded`、`pie.running`、`panel.node_editor.visible`、`dialog.open`
   - `transition`：菜单项、按钮、右键菜单、快捷键、MCP op
   - `control`：树节点、输入框、下拉、按钮、弹层
   - 每个 control 记录 `owner` / `visible_when` / `actions` / `tests` / `scenario` / `source`
   - `test_action_contract` 继续是 op ↔ UI 入口的契约权威；UI map 只引用 action id，不另造一套 op 表。

## 1. 当前盘点（2026-10-21 只读基线）

 - `Test/Application`：**71 个 `test_*.py`**（61 个原有测试 + `test_test_map` + 6 个 P0 测试 + `test_ui_map` + `test_group_layout` + `test_group_ops`）
 - `core`: 68
  - `manual`: 2（`test_live_ui`、`test_node_runtime`）
  - `heavy`: 1（`test_material_cycle_stress`）
- `Test/Application/Editor/scenarios/`：7 个 UI 场景（`panels_smoke`、`menu_smoke`、`node_editor_smoke`、`node_editor_clip_smoke`、`node_editor_find`、`node_groups_smoke`、`node_group_actions`）；已由 runner 自动发现，归入 `tier: gui`。
- 厂家 SDK 扩展的 `Test/`：自有测试不在 `Test/Application/**`，当前不进入标准 runner。
精确 AST import 统计：`Application` 下约 280 个 `.py`，测试直接 import 68 个（**仅作盲区线索， 不是覆盖百分比**）。
- 主要缺口：
- `Core/Scene`：`SceneManager`、`EntityManager`、`PrefabManager` 已有专门测试；`SceneSync`/`TransformAccessor` 目前由 SceneManager 集成测试间接覆盖，`CameraManager` 的主相机选择仍建议补独立用例。
  - `Application/Resource`：`ResourceManager` 无专门测试；Mesh/Texture/Shader 导入、默认资源、删除、路径缺少契约测试。
  - `Core/FileSystem`：`VFS` / `PathUtils` 无直接测试。
  - `Core/Input`：`InputPipeline` / `InputBackend` 无直接测试。
  - `Core/Camera`、`Core/Stats`、`Core/Timer`：无直接测试。
  - `Editor`：`UIManager`、`MenuBarPanel`、`ResourcePanel`、`FileDialog` 等面板/对话框缺少行为测试；UI 场景未入 runner。
  - `NodeGraph`：部分 evaluator、`graph_rules` / `graph_constraints` 边界缺少直接测试。
  - 厂家 SDK 扩展：硬件/后端测试需明确 `live/manual`，纯逻辑测试应迁入标准 tree 或显式发现。
  - Renderer：OpenGL 有像素/命令测试；Vulkan/ZenGL 为 WIP，先明确“不承诺覆盖”，不要伪覆盖。

## 2. 分阶段实施

### Phase 1 — 测试节点基线与 CLI（已完成 2026-10-21）

- [x] 建立本待办文档
- [x] 创建 `Doc/Dev/test_nodes.json`（62 个测试节点；`check` 已通过）
- [x] 创建 `Utils/Dev/test_map.py`
  - [x] `init`：从 test 文件和 AST import 生成基线
  - [x] `list` / `show`：按 tier/kind/owner 查询
  - [x] `affected <path>`：源码路径 → 相关 test node
  - [x] `render`：生成 `Doc/Dev/test_nodes.md`
  - [x] `check`：完整性、路径、重复 ID、tier/kind 校验
- [x] 创建 `Test/Application/Core/test_test_map.py`，把 `check` 纳入 runner
- [x] 生成并检查 `Doc/Dev/test_nodes.md`
- [x] 验收命令：
  - `python Utils/Dev/test_map.py check`
  - `python Utils/Dev/test_map.py affected Application/Core/Scene/SceneManager.py`
  - `python Utils/Dev/test_map.py render`
  - `python Test/Application/Core/test_test_map.py`
  - `python Utils/Dev/test_runner.py --only test_test_map`

Phase 1 初始结果：`check` OK（62 nodes）；`test_runner --only test_test_map` 1/1 通过。当前已扩展到 **71 nodes**（新增 6 个 P0 测试 + UI map 守卫 + 组布局 + 组元数据操作）。

### Phase 2 — P0 模块测试（已完成）

- [x] `Test/Application/Core/Scene/test_scene_manager.py` — 52 checks（含实体注册表并发快照）
  - CRUD/命名、父子/根/级联删除、组件增删查、编辑器/渲染可见性、Transform world/local/editor、`SyncToScene` / `SyncFromScene`、环境光/光照回退/GameType。
- [x] `Test/Application/Core/Scene/test_prefab_manager.py` — 16 checks
  - 保存/加载/实例化、prefab-local parent remap、损坏 JSON、缺失文件/实体、Transform/MeshRenderer 恢复。
  - 修复：`_collect_tree` 现在先检查 `SceneManager.EntityExists`，避免对不存在实体生成幽灵 prefab。
- [x] `Test/Application/Core/Scene/test_entity_manager.py` — 13 checks
  - facade 的 add/delete/命名/父子/组件/查询/级联删除。
- [x] `Test/Application/Resource/test_resource_manager.py` — 35 checks
  - Init/默认资源/程序化纹理/材质 clone/颜色/纹理槽/删除/坏文件/未支持后缀/路径解析。
- [x] `Test/Application/Core/FileSystem/test_vfs.py` — 24 checks
  - PathUtils 纯函数、VFS init/读写 JSON/二进制、mount 优先级、list/glob、shutdown 错误路径（`PathUtils` 已并入本文件）。
- [x] `Test/Application/Core/Input/test_input_pipeline.py` — 19 checks
  - key/modifier、鼠标 press/drag/click 阈值、scroll/camera preset、detach 回调恢复。
- [x] 每个新测试 已更新 `Doc/Dev/test_nodes.json`（当前 71 nodes）。

Phase 2 结果：`scene 52/52`、`entity 13/13`、`prefab 16/16`、`resource 35/35`、`vfs 24/24`、`input 19/19`；统一 runner 均 PASS。全量 core：**68/68 passed**（2026-10-21；新增 `test_group_ops` 后 68）。

Phase 2 备注：`SceneSync` / `TransformAccessor` 已由 SceneManager/SceneSync 场景测试间接覆盖；`CameraManager` 的主相机选择仍建议后续补独立用例。

### Phase 3 — UI 展开图与 GUI 场景入 runner（首版已完成）

- [x] `Doc/Dev/ui_map.json`：Editor shell、Scene、Node Editor、Resources、Settings 五条主链（23 controls）
  - [x] state：boot / project.loaded / scene.loaded / pie.running / panel.* / dialog.*
  - [x] control：`owner` / `visible_when` / `actions` / `tests` / `scenario` / `source`
- [x] `Utils/Dev/test_map.py ui tree|show|affected|tests|check|render`
- [x] 扩展 `test_runner.py` 发现 `Test/Application/Editor/scenarios/*.py`，通过 `ui_scenario.py` 执行，归入 `tier: gui`
- [x] `Test/Application/Editor/test_ui_map.py` 校验 UI map 路径/符号/action/test 引用
- [x] UI 开发 DoD：已写入 `Doc/Dev/ui_protocol.md` §14；控件变更 → 更新 `ui_map.json` + action/test/scenario，并跑 `ui render/check` + `tier gui`
- [x] 生成 `Doc/Dev/ui_map.md`

Phase 3 结果：`ui check` **23 controls OK**；`ui coverage` public op **63/63**（4 个 agent-only）；`test_ui_map` **6/6**；`test_runner --tier gui` **7/7**（menu_smoke / node_editor_clip_smoke / node_editor_smoke / panels_smoke / node_editor_find / node_groups_smoke / node_group_actions）。

### Phase 4 — 流程闭环

> **暂缓（2026-10-21 用户决议）**: 团队规模小 + 测试面仍在变化，CI 协调成本高；
> 先保持本地 `test_runner --tier core`，等出现 ≥2 常态维护者 / 外部 PR / 固定发布节奏再重启。
> 产品侧记录见 `Doc/Dev/product_todo.md` §1。

- [ ] `test_map.py check` 接入 CI / 本地统一检查
- [ ] `test_runner.py --affected <path>` 或 `--node` 快捷选择
- [ ] `test_protocol.md` / `ui_protocol.md` 增加 map 查询入口与维护规则
- [ ] 技能/agent 文档加入“先查 map，再改代码”的启动步骤

## 3. 新会话恢复方式

```powershell
Set-Location C:\WorkSpace\FLY\FlyVibing-Engine
$env:PYTHONIOENCODING='utf-8'
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py check
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py list --tier core
```

如果 `Doc/Dev/test_nodes.json` 或 `Doc/Dev/test_nodes.md` 不存在，先执行 Phase 1；不要跳过 `check` 直接批量改测试。

## 4. 待决策：Test/ 与 Utils/Dev 的归属

| 方案 | 正面 | 反面 |
|---|---|---|
| 打开 `Test/` 进 git | CI/干净 clone 可复现；测试变更可 review；map 与测试同仓 | 需精细白名单，避免 `_runs/`、截图、`dist/`、本机 fixture、硬件数据、密钥进入历史；仓库体积和跨机器路径风险上升 |
| 测试迁到 `Utils/Dev` | 与开发者工具同区；便于开发工具分发/排除运行时 | 破坏 `test_runner` / `_path_setup` / 文档 / fixture 的 `Test/...` 约定；测试不是工具；仍需忽略生成物，收益低、迁移面大 |
| 保持 `Test/` 忽略，只跟踪文档与 map | 本地开发零噪音；硬件/截图不污染 | 干净 clone 无法运行测试；map 指向本地文件；无法 CI 强制回归 |

**当前已采用**：局部打开 `Test/`，只跟踪源码/小型 fixture，继续忽略 `_runs/`、截图、日志、`dist/`、设备抓包；`Utils/Dev` 仍只放工具，不放测试。

推荐：不要为了 git 跟踪把测试搬去 `Utils/Dev`。若必须分离，至少把 runner 的 `TEST_ROOT` 显式配置，并同步 `_path_setup`、`test_protocol`、技能文档，避免隐式路径漂移。

## 5. 社区扩展测试完备性（待排期）

> 用户 2026-10-21 提出；先记录，等本轮核心测试/UI 图收口后再继续。

- [ ] 盘点社区扩展开发者的测试入口：厂家 SDK 及第三方扩展的 `extension.json` / ops / UI / device 测试是否覆盖发现、启停、卸载、异常隔离。
- [ ] 把厂家 SDK 扩展的纯逻辑测试迁入或显式接入 `Test/Application/Extensions/<extension>/`；硬件相关明确 `live/manual`。
- [ ] 给扩展开发文档补“最小测试骨架”：`ctx.nodes`、`ctx.ui`、`ctx.ops`、`ctx.graph` 各自的可验证样例。
- [ ] 审查器（review_extension.py）与测试 map 的 owner/`covers` 字段对齐，避免扩展作者不知道要补哪条测试。
