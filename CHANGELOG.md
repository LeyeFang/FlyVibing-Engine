# Changelog

## Unreleased

### English

- **`TimeTrigger` is edge-triggered** — it now fires once per `current >= threshold`
  crossing instead of “threshold grew since the last fire”. With `mode=pin` and a
  per-frame growing threshold the old code fired on every frame (measured ~4.7
  downstream calls/s). Re-arm by raising the threshold above the current value or by
  resetting the timer; editing a manual threshold fires once when already crossed.
- **New graph ops** — `graph.remove_node` (cascade-removes links; batch via `nodes=[...]`)
  and `graph.unlink` (by `link` id or `from`/`to` pins). Iterative graph editing no longer
  requires `graph.export` → edit JSON → `graph.import`.
- **`console.tail` op** — `EntryPoint` tees stdout/stderr into a bounded ring buffer
  (`Application/Core/Diagnostics/LogBus.py`), so CLI/MCP agents can read engine console
  output (including device-node failures) without a terminal.
- **Validation dry-run scene** — `validation/dry_run.py` now injects a read-only
  `_DryScene` built from the scene JSON entities: `EntityGet` / `EntityGetTree` /
  render-visibility nodes resolve real names instead of logging `not found` every frame
  (the run loop is unchanged; writes are recorded/no-op).
- **Console noise** — `EntityGet` no longer prints on every evaluation (success is silent;
  dry-run records a structured `not_found` entry). Added `Utils/Dev/print_audit.py` +
  `Doc/Dev/print_inventory.md` (543 bare `print()` calls, 49 on hot paths) with a freshness
  guard so new prints show up as a reviewable diff.
- **Settings ▸ Debug ▸ Terminal** — runtime debug events now have a taxonomy
  (`Application/Core/Diagnostics/DebugEvents.py`, 17 event types with per-type keys);
  `RuntimeDebugLayer` reports only the checked types and consumes only those (window
  close still consumes). Defaults equal the previous hard-coded silence list; new
  `debug.events` op + CLI read/write the same state.
- **Pre-flight before PIE** — `NodeCanvas` records unregistered node types
  (`unknown_node_types`); `SimulationController.play()` refuses to start while any exist
  (those nodes are never evaluated, so the chain breaks silently) and `sim.play` returns
  `preflight_failed` with the type/node list. `force=true` overrides; the reason lands in
  `sim.state.last_error`. `graph.validate` already reported them as `unknown_type` errors.
- **`entity.list with_transform=true`** — returns `position / rotation_deg / scale` per
  entity instead of one `entity.get` call each.
- **`scene.switch reload=true`** — the op never writes to disk; `reload` re-reads the
  scene from its `.scene` file (use it, or `scene.load`, after editing JSON by hand).

### 简体中文

- **`TimeTrigger` 改为上升沿触发** —— 只在 `current >= threshold` 由不满足变为满足的那一帧
  触发一次，不再用“阈值比上次触发时大”的电平判断。`mode=pin` 且阈值每帧增长时旧实现会
  每帧触发（实测下游 4.7 次/秒）。重臂方式：把阈值抬到当前值以上，或重置计时器；
  manual 改阈值时若已越过则立即触发一次。
- **新增图操作** —— `graph.remove_node`（级联删连线；`nodes=[...]` 批量）与
  `graph.unlink`（按 `link` id 或 `from`/`to` 引脚）。迭代改图不再需要
  `graph.export` → 手改 JSON → `graph.import`。
- **`console.tail` op** —— `EntryPoint` 把 stdout/stderr tee 进环形缓冲
  （`Application/Core/Diagnostics/LogBus.py`），CLI/MCP 无终端也能读引擎控制台
  （含设备节点失败原因）。
- **校验干跑假场景** —— `validation/dry_run.py` 从场景 JSON 的 entities 建只读
  `_DryScene` 并注入 `ctx.scene`：`EntityGet` / `EntityGetTree` / 可见性节点能解析到
  真实实体名，不再每帧 `not found`（运行循环不变；写操作只记录/no-op）。
- **控制台噪声** —— `EntityGet` 不再每次求值都 print（成功静默；干跑只记一条结构化
  `not_found`）。新增 `Utils/Dev/print_audit.py` + `Doc/Dev/print_inventory.md`
  （543 条裸 `print()`，热路径 49 条），并用新鲜度测试保证新增 print 形成可评审的 diff。
- **Settings ▸ Debug ▸ Terminal** —— 运行期 debug 事件首次有了分类表
  （`Application/Core/Diagnostics/DebugEvents.py`，17 类事件、每类一个勾选键）；
  `RuntimeDebugLayer` 只汇报且只 consume 被勾选的类型（窗口关闭仍强制 consume）。
  默认值与旧硬编码静默表等价；新增 `debug.events` op 与 CLI 读写同一份状态。
- **PIE 启动前硬预检** —— `NodeCanvas` 记录未注册节点类型（`unknown_node_types`）；
  只要存在这类节点，`SimulationController.play()` 就**拒绝启动**（这些节点不会被求值，
  链路会静默断掉），`sim.play` 返回 `preflight_failed` + 类型/节点清单；`force=true` 可强跑，
  原因写入 `sim.state.last_error`。`graph.validate` 本来就会报 `unknown_type` error。
- **`entity.list with_transform=true`** —— 一次拿到每个实体的 `position / rotation_deg / scale`，
  不必逐个 `entity.get`。
- **`scene.switch reload=true`** —— 该 op 从不写盘；`reload` 从 `.scene` 文件重新读取
  （手改 JSON 后用它或 `scene.load`）。

## 1.0.3 — 2026-11-01

### English

- **Pin-type-aware input reading** — new `evaluators.inputs.read_pin()` is the single
  reader for data inputs: it converts by the pin's declared `data_type` (`string` → str,
  `bool`, `int`, `float`, everything else passed through) and falls back to the default
  with a one-time warning instead of raising. Fixes `EntityGet.Name` crashing on a
  string input (`float("HUD")`), plus the same class of failure on `VarSet.Name`,
  `NewTimer.Name`, and `entity_ref` / `variant` / `vec3` pins. `VarSet` / `VarGet` now
  keep `variant` values as-is instead of forcing `float()`.
- **Node-level error isolation** — `GraphEvaluator._walk_exec` catches evaluator
  exceptions per node, logs them throttled (first + every 100th), and skips only that
  branch instead of aborting the whole exec chain / frame.
- **`TimeDelay` removed** — the node only advanced when the whole exec chain re-entered
  every frame (`_exec_visited` + `_blocked`), and its `props.duration` was ignored
  (duration came only from the `Seconds` pin). Use
  `TimeTrigger(mode=manual, time=N)` on an `OnFrameUpdate` chain. Scenes that still
  contain `TimeDelay` keep the node on load and now print an explicit migration warning.

### 简体中文

- **按引脚类型读取输入** — 新增 `evaluators.inputs.read_pin()` 作为数据输入的唯一读取入口：
  按 `PinDef.data_type` 转换（`string`→str、`bool`、`int`、`float`，其余原样透传），
  数值转换失败回默认值并告警一次，不再抛异常。修复 `EntityGet.Name` 接字符串时的
  `float("HUD")` 崩溃，以及 `VarSet.Name` / `NewTimer.Name` / `entity_ref` / `variant` /
  `vec3` 引脚的同类问题；`VarSet` / `VarGet` 不再强制 `float()`，保留 `variant` 原值。
- **节点级异常隔离** — `GraphEvaluator._walk_exec` 按节点捕获求值异常，限流打印
  （首次 + 每 100 次），只跳过该分支下游，不再中断整条 exec 链 / 整帧。
- **移除 `TimeDelay`** — 该节点只有整条 exec 链被逐帧重入时才推进
  （`_exec_visited` + `_blocked`），且 `props.duration` 不生效（时长只读 `Seconds` 引脚）。
  时间推进请用 `TimeTrigger(mode=manual, time=N)` 挂在 `OnFrameUpdate` 链上。
  含 `TimeDelay` 的旧场景加载时保留节点并给出显式迁移告警。

## 1.0.2 — 2026-10-31

### English

- **Distribution policies split** — game export is now user-specific and
  on-demand: only extension node packs referenced by the project scenes are
  copied, and `export:false` remains a hard opt-out. The installer uses a
  separate mainline allowlist (`Application/Functions/official_extensions.json`);
  local/third-party directories never ship, while official extensions are not
  dropped just because they opt out of game export. Both paths exclude the
  git-ignored `Application/Editor/Config/` local state.
- **Extension state location** — extension enablement and `ctx.data_dir`
  now default to `%APPDATA%/FlyVibingEngine/` (`editor_state/extensions.json`
  and `extensions_data/<id>/`) instead of the repository/install tree; existing
  `FVE_*` / legacy `MGE_*` environment overrides still work.
- **Provider signatures** — node cards show a muted provider line under the
  title (`@Official` for core and official packs, `@Community` by default for
  runtime packs, or an explicit `signature` from the pack). Examples show
  `Name @Provider`; community examples are discovered from
  `%APPDATA%/FlyVibingEngine/examples` and remain outside the mainline tree.
- **Extension graph API** — `ctx.graph` now supports owned-node discovery,
  `add_node` / `update_node` / `set_props` / `replace_props` / `remove_node`,
  link add/remove, and `request_redraw()`. Mutations bump a canvas revision
  and request an editor repaint; extension writes are limited to its own owner.
- **Device save without Stop** — `RecordingSession.save(scope, elapsed_s, pump=True, tag="")`,
  facade `save_record(...)`, graph node `SaveDeviceData` (Device ▸ Save), and
  agent op `device.save` share one implementation. Saves pump first, keep the
  session recording, and use microsecond/tag-specific unique file names.
- **Generic File IO SaveData** — new `SaveData` node (IO ▸ File) writes arrays,
  tables, dicts and JSON-compatible values to `npz`/`npy`/`csv`/`json` with an
  optional `.meta.json` sidecar (format/shape/dtype/rows/cols/samples). It is
  separate from `TextFileWrite`: `unique` naming, tag, compression, CSV header/
  delimiter/append mode and dry-run are built in; `SaveData` outputs Path,
  MetaPath, Rows, Cols, Samples, Written and Ok for downstream logic.
- **GameRuntime input** — `RuntimeInputLayer` queues keyboard/mouse events on
  the render thread and exposes immutable `RuntimeInputFrame` snapshots to the
  logic tick. New graph nodes `OnKeyPressed`, `OnKeyReleased`, `OnMouseClicked`,
  `IsKeyDown`, `IsMouseButtonDown`, `GetMousePosition`. ESC remains a safe
  window-close by default; `RuntimeInputLayer.set_escape_exit(False)` lets graph
  nodes own ESC. `Engine` now respects `WindowCloseEvent.consumed`.
  `OnMouseClicked` uses click semantics: press+release with <=6 px movement;
  right/left drag does not fire a click.
- **Node graph gesture semantics** — the canvas context menu now opens on
  right-button *release* only when the press did not move more than 6 px.
  Right-drag keeps panning the canvas and no longer opens the menu; left-drag
  remains box selection. `ui.drag`/`ui.click` accept the same button semantics,
  covered by the live `node_graph_gestures` regression.
- **Extension-contributed Examples** — an extension's bundled
  `<extension_dir>/Examples/` is registered while the extension is enabled and
  removed on disable/unload, so `File ▸ Open Example` discovers it without
  copying into the user tree. Declare `capabilities:["examples"]` to use
  `ctx.examples.register/unregister` for extra read-only roots; manifest
  `provider` / `.myproj.provider` supplies the muted signature.
- **Extension docs** — UI, node-pack, and Example development guides moved to
  the `FlyVibing-User-And-Developer-Utils` repository as the single source.

Compatibility: Windows 10/11 x64; Python 3.14 free-threaded runtime;
`engine-editor-mcp` 0.6.x / `flyvibing-node-editor` 0.1.x /
`flyvibing-extension-kit` 0.1.x.

### 简体中文

- **发行策略拆分** — 游戏导出改为用户态按需：只带当前工程场景引用的扩展
  节点包，`export:false` 仍是硬 opt-out；安装包走独立的 mainline
  allowlist（`Application/Functions/official_extensions.json`）——本地/第三方
  目录不进包，但官方扩展不会因为“对游戏导出关闭”而被错杀。两条路径都排除
  git-ignored 的 `Application/Editor/Config/` 本地状态。
- **扩展状态目录** — 扩展启用状态与 `ctx.data_dir` 默认迁到
  `%APPDATA%/FlyVibingEngine/`（`editor_state/extensions.json` 与
  `extensions_data/<id>/`），不再写仓库/安装目录；`FVE_*` 与旧 `MGE_*`
  环境变量覆盖仍有效。
- **提供者签名** — 节点卡标题下恢复灰色签名行：核心节点/官方扩展为
  `@Official`，运行期扩展默认 `@Community`，也可由 pack 显式写 `signature`。
  Example 菜单显示 `名称 @提供者`；社区示例从
  `%APPDATA%/FlyVibingEngine/examples` 读取，不进入主线 `Examples/`。
- **扩展图 API** — `ctx.graph` 支持检索自己的节点、`add_node` /
  `update_node` / `set_props` / `replace_props` / `remove_node`、连线增删与
  `request_redraw()`。变更会递增 canvas revision 并请求编辑器重绘；扩展写入
  默认限制在自身 owner。
- **设备不停采保存** — `RecordingSession.save(scope, elapsed_s, pump=True, tag="")`、
  门面 `save_record(...)`、图节点 `SaveDeviceData`（Device ▸ Save）与 agent op
  `device.save` 共用同一实现；保存前 pump、不改变录制状态，文件名含微秒/标签，
  同一秒连续保存不会覆盖。
- **通用 File IO 数据保存** — 新节点 `SaveData`（IO ▸ File）把数组/表格/
  dict/JSON 值落盘为 `npz`/`npy`/`csv`/`json`，可选 `.meta.json` 侧车
  （格式/形状/dtype/行列/样本数）。与 `TextFileWrite` 职责分离：支持唯一命名、
  tag、压缩、CSV 表头/分隔符/追加和 dry-run；输出 Path/MetaPath/Rows/Cols/
  Samples/Written/Ok 供下游逻辑使用。
- **GameRuntime 输入** — `RuntimeInputLayer` 在渲染线程排队键鼠事件，逻辑帧
  提供不可变 `RuntimeInputFrame` 快照。新增图节点 `OnKeyPressed`、
  `OnKeyReleased`、`OnMouseClicked`、`IsKeyDown`、`IsMouseButtonDown`、
  `GetMousePosition`。ESC 默认仍安全关闭窗口；
  `RuntimeInputLayer.set_escape_exit(False)` 后由节点接管 ESC。`Engine` 现在
  尊重 `WindowCloseEvent.consumed`。`OnMouseClicked` 采用点击语义：按下后
  原地释放（位移 <=6px）才触发，左右键拖拽都不会误触发。
- **节点图手势语义** — 画布右键菜单改为右键**释放**时、且按下后位移不超过
  6px 才打开；右键拖拽继续平移画布且不弹菜单，左键拖拽仍为框选。
  `ui.drag`/`ui.click` 使用同一套按键语义，并由 live
  `node_graph_gestures` 回归覆盖。
- **扩展自带 Example** — 扩展启用时自动登记 `<extension_dir>/Examples/`，
  停用/卸载即移除；`File ▸ Open Example` 无需复制到用户目录即可发现。额外只读
  根目录声明 `capabilities:["examples"]` 后用 `ctx.examples.register/unregister`；
  签名取 manifest `provider` 或 `.myproj.provider`。
- **扩展文档** — UI、节点与 Example 开发指南迁移到
  `FlyVibing-User-And-Developer-Utils` 仓库作为唯一源。

兼容性：Windows 10/11 x64；Python 3.14 free-threaded 运行时；
`engine-editor-mcp` 0.6.x / `flyvibing-node-editor` 0.1.x /
`flyvibing-extension-kit` 0.1.x。

## 1.0.1 — 2026-10-24

### English

- **Installer fix** — all-users installs no longer fail with
  `Error creating registry key: HKEY_LOCAL_MACHINE\Environment` (code 87).
  The PATH entry is now written to the correct hive/subkey via
  `[Code]`; per-user installs still use `HKCU\Environment`.

### 简体中文

- **安装器修复** — 选择“所有用户”安装时不再报
  `Error creating registry key: HKEY_LOCAL_MACHINE\Environment`（code 87）。
  PATH 写入改由 `[Code]` 按安装模式选择正确的注册表根与子键；当前用户安装仍写
  `HKCU\Environment`。

## 1.0.0 — 2026-10-24

### English

FlyVibingEngine 1.0.0 is the first Windows release with a complete authoring,
preview, and export path.

- **Node groups** — groups can be renamed and described in-place, dragged,
  resized, nested, and populated by dragging members in or out. Each group has
  a real `GroupStart`/`GroupEnd` pair rendered as `Group entry` / `Group exit`
  ports with draggable connection dots.
- **Graph focus** — `Fit` waits until group bounds are registered, so freshly
  imported or opened graphs remain readable instead of zooming to a tiny view.
- **Examples** — `Examples/MI` and `Examples/RestingState` are refreshed with
  nested groups, group descriptions, group boxes, and entry/exit nodes.
- **Windows installer** — bundles Python 3.14 free-threaded, the offline
  wheelhouse, the editor toolchain, and the bundled examples. No Python or
  package manager is required on the target machine.
- **Toolchain** — ships `engine-editor-mcp` and `flyvibing-node-editor` for
  live editor automation and offline graph validation.

Compatibility: Windows 10/11 x64; Python 3.14 free-threaded runtime;
`engine-editor-mcp` 0.5.x / `flyvibing-node-editor` 0.1.x.

### 简体中文

FlyVibingEngine 1.0.0 是首个包含完整编辑、预览与导出链路的 Windows 版本。

- **节点组** — 支持就地重命名/描述、整体拖动、右下角缩放、嵌套，以及成员
  拖入/拖出。每个组拥有真实的 `GroupStart`/`GroupEnd` 节点，并渲染为带
  可拖拽圆点的 `Group entry` / `Group exit` 端口。
- **图视图** — `Fit` 会等待组框尺寸注册完成，新导入/打开的图不会缩成不可读
  的极小视图。
- **示例工程** — `Examples/MI` 与 `Examples/RestingState` 已重整：嵌套组、
  组描述、组框与入口/出口节点均已写入场景。
- **Windows 安装包** — 内置 Python 3.14 free-threaded、离线 wheelhouse、
  编辑器工具链和示例工程；目标机无需安装 Python 或包管理器。
- **工具链** — 随包提供 `engine-editor-mcp` 与 `flyvibing-node-editor`，
  分别用于实机编辑自动化与离线图校验。

兼容性：Windows 10/11 x64；Python 3.14 free-threaded 运行时；
`engine-editor-mcp` 0.5.x / `flyvibing-node-editor` 0.1.x。
