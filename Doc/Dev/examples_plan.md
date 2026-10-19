# Examples 构建计划（MI / 静息态 / 节点组）

> 状态：2026-10-18 重启。本文是 Examples 构建 + 节点组构建的**进度板与执行顺序**，
> 不是已完成协议；落地后把对应行改成 ✅ 并补证据路径。
>
> 相关：`Doc/Dev/node_editor_protocol.md`（画布存档契约 / 组元数据）、
> 工具仓 `packages/node-editor/README.md`（alias / cue_n_way / set_group）、
> `Doc/Dev/graph_validation_protocol.md`（L1/L2 校验）。

---

## 1. 目标

每个 Example = **一个可运行工程场景 + 节点图 + README + 可复现验收**：

| 产物 | 要求 |
|---|---|
| 场景 | `.scene` 内有模板实体（EntitySpawn 的模板来源）与相机/光照 |
| 节点图 | 用 alias 命名关键节点；分支型逻辑优先用 `cue_n_way` 组；L1 = 0 error |
| 运行 | PIE 实测（关键帧截图）+ L2 干跑 0 error |
| 成品 | `project.export` 导出包可被 `run_game.cmd` 启动 |
| 文档 | 场景 README：范式、时间线、地址/码值表、如何改臂/参数 |

Examples 目录：`Examples/`（正式示例，可提交；`Test/TestProject/Examples/` 仅作开发备用，File 菜单两者都扫）。

---

## 2. 现状（2026-10-18）

### 2.1 节点组（基础能力）— ✅ 已完成

- `nodes[nid].alias` 持久别名；`@alias` 解析；`set_alias` / `add_node.alias`；校验重复/格式。
- `nodes[nid].description` 持久描述；GUI 节点卡展开编辑；`graph.set_description` / 离线 `set_description` 读写。
- `flyvibing_node_editor.node_groups`：`cue_n_way` 模板（Random → N×(Compare→Branch)；
  每臂单实体 `EntityGet → EntitySetRenderVisible → ParallelSend`，多实体
  `EntityGet×E → EntityPack/Merge → EntityListSetVisible → ParallelSend`），
  `cue_window`（每帧可见窗口）、`hide_group`（实体树批量显隐）、`container`（外层嵌套子组）。
- `add_group` / `set_group`：按 arm `id` 差分重展开；保留臂节点 ID 稳定；入口连线自动重挂。
- 引擎画布保留 `alias` 与 `node_groups`（修复了原来 `graph.export` / 场景保存静默丢元数据的 bug）。
- GUI：节点卡显示 `@alias`；组背景框（`@组别名 [类型]`）；工具栏 **Fit** / `graph.fit`。
- 实机：`ui.panels` / `ui.panel` 面板开关闭环；组演示场景 PIE 显示随机臂。
- 测试：`test_aliases_groups.py` 54/54 · `test_canvas_metadata.py` 18/18 ·
  `test_examples_catalog.py` 18/18 · `node_editor_smoke` 18 checks（含 description 展开）。

### 2.2 MI / SSSEP 示例 — 🟡 历史资源 + ✅ 组化示例

- 4 个历史场景：`MI` / `MI-SSSEP` / `MI-SSSEP-Version2` / `SSSEP`（TestProject + Paradigm 导出副本）。
- L1 校验 0 error（仅有 6 个遗留 `exec_out` stale pin warning）。
- PIE 已验证注视十字、并行口触发发码；工程导出/成品启动链已跑通。
- **已建组化示例**：`Examples/MI/scenes/MI.scene` — 3 臂 × 2 实体 `cue_n_way` 子组
  `@class_cue`（0–6 s）、`@task_cue`（2–6 s `cue_window`）、`@rest_cue`（6 s `hide_group`），
  外层 `container` 组 `@trial` 嵌套；关键节点带 `@alias` / `description`；0/2/6/10 s 时间线。
  2–6 s class/task 重叠测试：`Test/Application/NodeGraph/test_mi_groups.py`。

### 2.3 静息态示例 — ✅ 已建

- `Examples/RestingState/scenes/RestingState.scene`：十字注视 + 睁眼/闭眼 0/20/40 s，
  并行码 1/2；用 `EntityGetTree + EntityListSetVisible` 演示整批显隐；
  `@tt_open` / `@tt_closed` / `@tt_cycle` 等别名 + 节点描述齐备。

### 2.4 可加载演示（非正式 Example）

- `Test/_runs/ng_cue_demo/CueGroup_Demo.scene`：MI 模板实体 + `EntitySpawn×2` + `cue_n_way` 组，
  带 `@start` / `@cue_rand` 别名；L1 + L2 通过；用于 GUI 看组框。

### 2.5 Examples 工程（2026-10-18 已拆分）

- 位置：`Examples/MI/MI.myproj` 与 `Examples/RestingState/RestingState.myproj`；
  入口 **File → Open Example → MI / RestingState**。
- 场景：`MI/scenes/MI.scene`（3 臂 × 2 实体 `@class_cue` + `@task_cue` 2–6 s +
  `@rest_cue` 6 s，外层 `@trial` 容器组）、
  `RestingState/scenes/RestingState.scene`（睁眼/闭眼 0/20/40 s，`EntityGetTree + EntityListSetVisible`）。
- 可读性：关键节点带 `@alias`，绝大多数节点带 `description`（GUI 可展开编辑；agent 可读写）。
  实测 MI：77 nodes / 93 links / 4 groups（含外层 `@trial`）、描述覆盖率 80%+；
  RestingState：23 / 22 / 19 / 19。
- README：`Examples/README.md` 为索引；每个工程有自己的 `README.md`（时间线/别名/改组参数）。
- PIE 实机：`Test/_runs/examples_live/{mi_cue,mi_cue_right,mi_task,mi_rest,resting_open}.png`；
  MI 组化重叠复验：`Test/_runs/mi_group_migration/{pie_t1_class,pie_t3_overlap,pie_t7_rest}.png`；
  日志确认 MI 发送 `0x3FF8 <- 0x03/0x04`、静息发送 `0x3FF8 <- 0x01`，`sim.state.last_error=""`。
- L2 干跑：MI 700 帧 / 12 events / 0 errors；Resting 700 帧 / 4 events / 0 errors
  （EntityGet 在干跑中不解析场景实体，属预期日志）。

---

## 3. 执行顺序（重启后的推进路线）

| 步骤 | 内容 | 验收 |
|---|---|---|
| P0 | 本文件 + Example 目录骨架 + README 模板 | 目录存在，模板可复制 |
| P1 | **MI-V2 组化**：把 cue 分支替换为 `cue_n_way`（arm id = left/right/top…），关键节点加 alias；保留时间线与终止逻辑 | ✅ 已完成：`@class_cue` / `@task_cue` / `@rest_cue` + 外层 `@trial`；`test_mi_groups.py` 14/14 |
| P2 | **静息态示例**：确认范式 → 建场景（十字/提示）→ 节点图（相位计时器、分段、并行码）→ PIE/导出 | 同 P1；README 含时间线与码值表 |
| P3 | Examples 工程/场景列表整理（GUI 可见）+ README 索引 | 已建 `Examples/MI` 与 `Examples/RestingState`；File → Open Example 可打开；每个工程有 README |
| P4 | 组能力增强：一臂多实体（`entities` → `EntityGetTree`/`EntityPack`/`EntityListSetVisible`）已实现；`store_var`（VarSet）待做 | 与旧手写 MI 等价；回归测试 |

---

## 4. 已知缺口（会影响 Example 设计）

1. **一臂多实体**：已实现。`cue_n_way` 的 arm 支持 `entity`（单实体兼容）或
   `entities: [names...]`（多个 `EntityGet` + `EntityPack/Merge` + `EntityListSetVisible`）。
   引擎语义：`EntitySpawn` 会递归生成模板的全部子孙，但 `EntitySetRenderVisible` /
   `EntityListSetVisible` **都不递归**；MI 的 `LeftCue` 是只有 Transform 的容器，
   真正的网格在 `arrow_body` / `arrow_head_copy` 子实体上，所以 arm 要把它们都列上。
2. **无 `store_var`**：旧 MI 每臂 `VarSet cue_val` 供后续节点读取；组模板只把码值送进 ParallelSend。
   → 仍需 arm 级 `var` 或组参数 `store_var`。
3. **无 GUI 组编辑**：目前只能用 CLI `add_group` / `set_group`；
   GUI 只读显示组框。arm 增删仍走工具通道。
4. **MI 遗留 stale pin**：6 个旧 `exec_out`（TimeTrigger/Branch），不影响运行但会让校验报警。
5. 运行中的编辑器进程需要重启才能加载新 op / 新画布字段。

---

## 5. 组化复杂度实测（MI 左右手 cue）

实测（`add_group` 展开后统计）:

| 方案 | 节点 | 连线 | 差异 |
|---|---:|---:|---|
| 旧手写 MI（N=2 臂 × E=2 实体，含 TimeTrigger / VarSet / 每实体 SetRenderVisible） | 22 | 28 | 基线 |
| `cue_n_way`（N=2 × E=2） | 19 | 23 | **−3 节点 (−13.6%) / −5 连线 (−17.9%)** |

> 旧 MI 的 N=2 用单个 `Compare/Branch` 特化（不是通用 N 路链），所以实测 22
> 低于通用公式的 25；即使按这个更省的特化基线比，新组仍少 3 节点/5 连线。

通用口径（N 臂、每臂 E 个实体，不含组外入口）:

- 新组：`nodes = 1 + 7N + NE`，`links = 8N + 2NE − 1`。
- 旧手写（每实体单独 `EntitySetRenderVisible` + 每臂 `VarSet`）：
  `nodes = 1 + 6N + 3NE`，`links = 9N + 3NE − 1`。
- 节省：`nodes = N(2E−1)`，`links = N(E+1)`。即每臂每增加一个实体，
  旧法 +3 节点/+3 连线，新法只 +1 节点/+2 连线；超过 4 个实体时每 4 个加一组
  `EntityPack` + `EntityListMerge`（E=4→5 实测 +3 节点/臂）。

新组实测规模:

| | E=1 | E=2 | E=3 | E=4 |
|---|---:|---:|---:|---:|
| N=2 | 15 / 17 | 19 / 23 | 21 / 27 | 23 / 31 |
| N=3 | 22 / 26 | 28 / 35 | 31 / 41 | 34 / 47 |
| N=4 | 29 / 35 | 37 / 47 | 41 / 55 | 45 / 63 |

结论：**节点组确实因实体列表而受益** —— 旧图根本表达不了“一臂多网格”的
原子显隐；组化后 MI 的左右手 cue 少 3 节点/5 连线，且 E 越大收益越大；
`set_group` 增删臂只改参数（N=2→3、E=2 实测 +9 节点/+12 连线，组外连线不动）。

---

## 6. 待拍板

- 静息态范式：总时长、分段（睁眼/闭眼各几段）、是否要注视十字、并行口码值表。
- Examples 最终归属：`Test/TestProject/Examples`（开发）/ `Paradigm`（用户交付）/ 产品示例目录。
- MI 系列是“保留历史图 + 另建组化版”，还是直接迁移现有 4 场景。
