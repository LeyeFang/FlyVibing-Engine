# Changelog

## 1.1.0 — 2026-11-10

> **发布口径**: 1.1.0 此前只有 CHANGELOG 草稿（2026-11-05 批次），从未打 tag/出安装包；
> 本次把 11-06～11-10 的增量并入同一版本，**统一按 1.1.0 发布**（tag `v1.1.0`）。
> **工具链锁定**: `FlyVibing-User-And-Developer-Utils` **0.8.0**
> （见 `Utils/Dev/Installer/toolchain.lock.json`）。
>
> **本批次重点**：
> ① **并发竞态修复**（编辑器不再随机退出 —— 这是唯一的崩溃级修复）；
> ② **成品性能统计通道**（`--stats-json`：帧时间分布 / 卡顿桶 / CPU / 内存）；
> ③ **图求值索引化**（MI-SSSEP 图求值 ×20）；
> ④ **远程 / SSH 显示安全**（原先在 SSH 里启动成品会直接访问违例）。

### 简体中文

- **并发竞态修复（P0，崩溃级）** —— `Scene.entities` 原先无锁，且被**两个线程**
  整表重建：渲染线程的 `NodeEditorPanel._ensure_default_scene()`（每帧）与主线程的
  `SimulationController._sync_ecs_to_scene()`（点 Play）。同期主线程
  `copy.deepcopy(editor_scene)` 正在迭代它 → `RuntimeError: dictionary changed size
  during iteration` 抛在 `Engine._render_loop` → **编辑器直接 exit code 1**（无对话框，
  16 实体场景点几次必崩一次）。
  修法三层：① `Scene` 新增 `_entities_lock` 保护所有原地增删；② 批量重建走
  `replace_entities()` **整表原子替换**（读方永不见半空表）；③ 自定义 `__deepcopy__`
  锁内快照 + 离线构造（RLock 本身不可深拷贝）。
  顺带说明：Python 3.14 free-threading 让 `dict.copy()` 变成**锁下原子快照**
  （实测 20000 次无一次 `k != v`），但**没有任何内置类型**能让"边迭代边被改"变安全 ——
  `MappingProxyType` 是视图不是快照，`copy.deepcopy` 内部仍是 Python 层迭代（实测首次即抛）。
  验收：连点 Play/Stop + 反复 open 14 轮零崩溃（修复前 7 个示例中途崩 3 次）；
  新守卫 `Test/Application/Core/test_scene_concurrency.py`（20 checks，含"旧写法确实会崩"对照）。
- **成品性能统计 `--stats-json`（新）** —— `PlayerEntry --stats-json P [--seconds T]
  [--stats-interval S]`：结束时写 `P`（帧时间 mean/p50/p90/p95/p99/max + 卡顿桶
  >16.7/33.3/50/100 ms + 进程 CPU/RSS/GC/线程清单 + GIL 状态）与 `P.jsonl`（每秒趋势，
  可定位"第几秒开始变慢"）。新模块 `Application/Runtime/PerfStatsLayer.py`；
  `FrameProfiler` 新增线程安全的 `snapshot_stats()` 与缺失已久的 `stop()`
  （`Engine._render_loop` 一直在调它，此前被 `try/except` 静默吞掉）。
  `--seconds` 为**墙钟**截止（原 `--frames` 在导出模式下内联逻辑循环不受 vsync 限制，
  120 帧只要 0.2 s，量不到稳态）。守卫 `test_perf_profiler.py`（20 checks，含并发 tick+snapshot）。
  实测 7 个 MI-SSSEP 成品：**460–693 fps（1.44–2.17 ms/帧）、零卡顿、~190 MB RSS**。
- **图求值索引化** —— `NodeCanvas` 新增 `pin→node` / `pin→元数据` / 输出 pin→下游 /
  输入 pin→上游 / `事件类型→入口节点` 五张缓存表，按 `revision` 失效；
  `find_pin_*` / `_downstream_nodes` / `_read_input` / `trigger` 全部改查表。
  此前每次引脚读写都要线性扫全图（`canvas.py:116` 占 cProfile 最热）。
  实测 MI-SSSEP：**3.404 → 0.171 ms/帧（×20）**，事件数与错误数逐一比对完全一致。
  守卫 `test_canvas_pin_index.py`（16 checks，用暴力扫描当 oracle）。
  新工具 `Utils/Dev/perf_graph.py`（`graph` / `live` / `cpu` 三档 + `--json` / `--baseline`
  回归门槛，含预热与 0.05 ms/帧 噪声地板）。
- **垂直同步 / 帧率上限开关** —— `MGE_VSYNC=0` 解除 vsync；新增
  `glfwWindow.ApplySwapInterval()`，在**渲染线程取到上下文之后**设置
  （`glfw.swap_interval` 不能在 `create_window` 之后立即调，会报 GLFW 65538）。
  此前 200 Hz 显示器上所有场景都恰好报 199.7 fps，渲染成本差异被完全掩盖。
- **远程 / SSH 会话显示安全（崩溃级）** —— 在非交互式桌面会话（Windows SSH 有自己的
  window station）里启动成品会 `glfw.get_video_mode(monitor)` →
  `OSError: access violation reading 0x108` 直接退出。
  修法：① 所有显示器查询改为"失败返回 None 并停用本会话后续查询"（只告警一次）；
  ② 分辨率四级回退 `MGE_WINDOW_SIZE` → Win32 `EnumDisplaySettingsW` → GLFW → 1920×1080；
  ③ 只有 `FULLSCREEN` 才触碰 monitor 句柄；④ FULLSCREEN 无可用显示器 → 自动降级
  BORDERLESS；⑤ 逃生开关 `MGE_WINDOW=windowed|borderless|fullscreen|overlay`、
  `MGE_WINDOW_SIZE=WxH`、`MGE_MONITOR=off`。
  新增诊断工具 `Utils/Dev/display_diag.py`（会话身份 / Win32 三源 / GLFW 实际路径并排输出，
  `--json` 落盘）与守卫 `test_window_display_fallback.py`（17 checks）。
  注意：SSH 会话里创建的窗口属于该会话的桌面，**不会**出现在物理屏幕/远程软件看到的桌面上。
- **工具链版本锁定** —— 新增 `Utils/Dev/Installer/toolchain.lock.json`
  （引擎 1.1.0 ↔ 工具链 0.8.0），`build_installer` 在不一致时打印 WARNING。
- **既有条目（11-05 批次）** —— shader 参数注解 `//!`、材质默认值单一来源、
  运行期 `time` 注入、材质面板注解驱动、资源引用唯一性、`dev/imgui_api` 控件目录、
  `extdev/ui_recipes` 配方、端口台账与 `instance.info/describe`、测试选测 `--affected/--changed`、
  `ctx.python` 扩展解释器协议 —— 详见下方「1.1.0 前期批次」。

- **shader 参数注解 `//!`** —— 参数的控件形态 / 范围 / 单位 / 默认值 / 归属写回 GLSL 声明旁
  （`//! ui: float | label=mat.freq | group=Stimulus | range=1..60 | unit=Hz | default=10`），
  面板、默认值、校验、文档全部从这一处派生；无注解的 shader 完全降级为旧行为。
  `Basic`/`Lighting`/`SSVEP` 已全部注解。
- **默认值单一来源** —— 删掉 `ResourceManager` 里硬编码的 `uShininess = 32.0`，
  `Material.__init__` / `set_new_shader` 统一走 `UniformSpec.build_default_uniforms()`。
- **`time` 运行期注入** —— 声明 `//! owner=runtime` 的 uniform 由渲染器每帧写入引擎 elapsed 秒，
  不进材质、不可编辑。SSVEP 方块此前因 `time` 恒为 0 而**一直是静态的**（默认相位下恒黑），
  现在真正按 `sin(2π·freq·time + phase)` 闪烁；GL 探针实测 10 Hz 下 t=0 黑 / 0.025s 白 /
  0.075s 黑 / 0.125s 白。
- **材质面板改为注解驱动** —— 分组折叠（Surface / Specular / Stimulus）、带单位、已改标记、
  单参数与整组复位、共享/内置材质提示；`time` 灰显标注「引擎驱动」。
- **资源引用唯一性（`.mat`）** —— 新增 `shader_ref` 与 `texture_refs`（`builtin://名称` 或绝对路径），
  加载时优先按 ref 解析、解析不到才回退保存时的会话内 id。修复跨会话把 SSVEP 材质绑到
  Lighting、或纹理槽指向别人家纹理的隐患。
- **修复** —— 材质面板的「注解路径」与「旧通用列表」两条渲染路径同时生效，每个参数被画两遍；
  现在只有拿不到 spec 时才走旧路径。
- 新增 `Test/Application/Core/test_uniform_schema.py`（50 checks：注解解析、默认值、复位、
  shader/纹理引用、材质隔离、运行期注入）。
- **面板控件目录 `dev/imgui_api`（生成物）** —— `Utils/Dev/imgui_docgen.py` 从已安装
  `imgui_bundle` 的运行时签名生成，按用途分 16 组收 143 个在用接口（文本/按钮/输入/布局/容器/
  表格/弹窗/交互状态/禁用/拖放/样式/输入/窗口/宿主侧禁止），附录收录其余 230 个函数 + 146 个枚举/类型；flag 速查的值
  也在生成时读取，升级依赖不会静默过时。`engine-editor-cli doc show dev/imgui_api#表格` 按节取。
- **扩展面板配方 `extdev/ui_recipes`** —— 9 个可复制片段：参数行、设置持久化、表格、日志
  （跟随/暂停）、实时波形、确认弹窗、禁用原因、后台线程队列、无头自测。
- **守卫** `Test/Application/Editor/test_imgui_api_doc.py`：产物新鲜 + 分组名真实 +
  **引擎里用到的每个 imgui 函数都被归类** + CLI 可寻址（12 checks）。
- **实测坑入库**：`from imgui_bundle.imgui import ImVec2 / TableFlags_` 会 `ImportError`，
  统一 `from imgui_bundle import imgui` + `imgui.TableFlags_.xxx`，`ImVec2/ImVec4` 从顶层拿。
- **端口台账（谁占了端口 / 目的 / 涉及内容）** —— 每个编辑器实例启动时在
  `<tmp>/engine_editor_mcp/ports/<port>.json` 登记 `purpose / owner / project / touches / notes`，
  退出时删除；`engine-editor-cli ports` 一眼看到占用者，`launch --purpose ...` 在进程启动前先预占
  （并发 agent 不会抢同一个空闲端口），引擎就绪后改写为 `ready` 并补上工程/场景。新增
  `instance.info` / `instance.describe` 两个 op（78 个核心 op）。
- **启动参数** `--purpose / --owner / --tag / --touch / --note`（实例自述，不进 Settings）。
- 新增 `Test/Application/Editor/test_port_ledger.py`（33 checks：引擎↔工具仓同格式往返、
  `starting` 预登记继承、陈旧条目清理、扫描状态机、`choose_port` 避让、两个 op、启动参数解析）。
- **测试选测（`--affected` / `--changed`）修好并装回入口** —— 改哪跑哪，不再每次全量 `--tier core`。
  修复: 改测试/场景文件时选中它自己；`?? dir/` 未跟踪目录展开；默认跳过 `manual`/`live`
  （交互式 / 需要运行中的编辑器）；`--changed` 只命中文档改动 → 0 tests 退出 0，
  显式 `--affected` 路径错 → 退出 2；选中比例 >50% 时提示工作区改动累积。
  规则同时写进 `test_runner --help` 与 `Doc/Dev/test_protocol.md`「默认入口」。
  新守卫 `Test/Application/Core/test_test_runner_selection.py`（13 checks）。
- **既存缺陷记录** —— heavy 档 `test_material_cycle_stress` 的 `shift` 场景（引擎中途新增内置材质）
  在干净 HEAD 上同样失败（`bindFail=4`），`--tier core` 不含 heavy 所以长期未暴露；待单独定位。
- **扩展解释器协议 `ctx.python`** —— manifest 可声明 `{"python": {"mode": "engine|venv|path",
  "path": "%EXT_DATA%/venv", "requirements": "...", "probe": [...]}}`；宿主统一解析
  （`FVE_EXT_PYTHON_<ID>` → manifest → 引擎解释器）、子进程 `import` 自检、`spawn` 托管与卸载回收，
  `explain()` 给出「为什么选了这个解释器」。扩展不再需要把依赖装进引擎 venv 或写死
  `...\venv\Scripts\python.exe`。官方示例 `SerialParallelDevice` 已声明
  `{"mode": "engine", "probe": ["serial"]}` 并在 `ext.device.status` 回传解析结果；
  `extension.list` 每个扩展多一个 `python` 块。
- **踩坑入库** —— 引擎以 `PYTHON_GIL=0` 启动，原样继承给外部 GIL 构建的解释器会让子进程在初始化阶段
  Fatal（"Disabling the GIL is not supported by this build"），`import` 自检永远失败；`ctx.python.env()`
  只在子进程就是引擎解释器时保留该变量。
- **`extension.python` op** —— 运行期读/写扩展解释器（`path=` 覆盖立即生效、空串清除），
  覆盖持久化到 `editor_state/extensions.json`（v2）；核心 op 78 → **79**。
- **审查器 M7 / C12**（工具仓 `extension-kit`）—— manifest `python` 结构校验；
  写死绝对解释器路径或 `Popen(sys.executable)` 直接 FAIL（引导改用 `ctx.python.spawn`）。
- 新增 `Test/Application/Core/test_extension_python.py`（29 checks：归一化 / 优先级 / venv 解析 /
  变量展开 / env / probe / spawn 回收 / 覆盖落盘 / 官方示例声明）。
- **仓库清理** —— 删除根目录 `output.txt`（0B 重定向残留）与
  `Application/Core/NodeGraph/evaluators/_entity_v1_legacy.py.bak`（旧文件备份）；
  `.gitignore` 补 `*.bak` / `*.orig` / `*.rej` 与根目录 `/*.txt` `/*.log` `/*.tmp` `/*_recordings/`。
- **扩展激活策略与入口分工（行为变更）** —— 内置由 allowlist 定义（**不是**「在 Functions 里」），
  面板决定菜单：
  - **内置 = `official_extensions.json` allowlist**（与 `.gitignore` 白名单 `!Application/Functions/<Dir>/`
    互为镜像）→ `scope=builtin` → **恒激活**（`always_on`，不可停用；`FVE_EXTENSIONS_BUNDLED=off`
    为安全模式）。
  - **同在 `Application/Functions` 但不在 allowlist 的本地/社区夹具**（Gtec、mi-sssep）→
    `scope=local` → 与用户目录一样 **opt-in**，可在设置页启停。修正了上一版把这类夹具
    误判为内置、锁成不可停用的问题（判定统一到 `ExtensionManager.scope_of()`）。
  - 用户目录 `%APPDATA%/FlyVibingEngine/extensions` → `scope=user`，opt-in；
  - **主菜单栏 Extensions 只列有 UI 面板的扩展**（`has_ui`：声明 `capabilities: ["ui"]`
    或确实注册了面板），点它 = 把面板叫回来；无面板的后台扩展（ops/nodes/examples/device）
    不再占据菜单；
  - **管理面收敛到 Settings ▸ Extensions 新页**（`order=20`）：全部扩展（含无面板/broken/planned）、
    启停、诊断（scope / has_ui / 目录 / capabilities / 解释器 / 示例根目录 / 已注册 op / 错误原因）
    + Rescan；菜单底部保留「Extension Settings…」直达。
  - **`File ▸ Open Example` 不再静默空着** —— 已安装但未启用的扩展若带 `Examples/`，
    菜单底部给灰字 `"<扩展> — N 个示例（扩展未启用）"` 并附一键启用项（这条直接治
    「我写了示例却没注入成功」的误判）。
  - `extension.list` 每项 `scope` 取 `builtin` / `local` / `user`，另有 `always_on` / `has_ui`，
    agent 可据此判断「该去哪儿找它」；`extension.disable` 只对 builtin 报错。
- 新增 `Test/Application/Extensions/test_extension_activation.py`（内置恒激活 / 安全模式 /
  非内置 opt-in / 停用拒绝 / `has_ui` 两类判据 / 状态文件不被内置污染）。
- 新增 `Test/Application/Extensions/test_extension_builtin_scope.py`（allowlist 与 .gitignore
  白名单必须互为镜像 + 指向真实 manifest / `scope_of` 三态 / Gtec、mi-sssep 必须判为 `local` /
  `to_dict` 契约）。
- `Test/Application/Editor/test_editor_settings.py` 更新为内置四页
  （`common / export / extensions / debug`）。
- **文档 CLI 支持三层寻址** —— `doclib` 现在同时按 `##` 与 `###` 切节：`doc outline` 输出
  带编号的小节目录；`doc show <topic>#3.3` / `#11.1` 只拉那一小节（`#3` 仍是整章、正文含小节，
  旧用法不变）；小节无自带编号时自动补 `<父号>.<序号>`，保证长协议文档每一节都可寻址。
  `doc search` 的命中标签精确到小节（`dev/shader_protocol#6.1`），可直接拿去 `doc show`。
  此前只切 `##`，`#11.1 ctx.python` 这类小节取不到 → agent 只能整章加载（约 700 行），
  与「先索引后内容」的省上下文目标相悖。

### English

- **Concurrency race fixed (P0, crash class)** — `Scene.entities` had no lock and was rebuilt
  wholesale by **two threads**: the render thread's `NodeEditorPanel._ensure_default_scene()`
  (every frame) and the main thread's `SimulationController._sync_ecs_to_scene()` (on Play).
  Meanwhile the main thread's `copy.deepcopy(editor_scene)` was iterating it →
  `RuntimeError: dictionary changed size during iteration` raised inside `Engine._render_loop` →
  **the editor exited with code 1** (no dialog; with a 16-entity scene it crashed within a few
  Play clicks). Fixed in three layers: (1) `Scene` gained `_entities_lock` guarding all in-place
  mutations; (2) bulk rebuilds go through `replace_entities()`, an **atomic whole-table swap**
  so readers never see a half-empty table; (3) a custom `__deepcopy__` snapshots under the lock
  and constructs offline (an `RLock` is not deep-copyable anyway).
  Note on the stdlib: Python 3.14 free-threading makes `dict.copy()` a **lock-protected atomic
  snapshot** (20 000 measured copies, never an inconsistent `k != v`), but **no built-in type**
  makes "iterate while another thread mutates" safe — `MappingProxyType` is a view, not a
  snapshot, and `copy.deepcopy` still iterates in Python (it raised on the very first attempt).
  Verified: 14 rounds of Play/Stop + repeated project loads with zero crashes (previously 3
  crashes across 7 examples); guard `test_scene_concurrency.py` (20 checks, including a control
  case proving the old pattern still crashes).
- **Product performance stats (`--stats-json`, new)** — `PlayerEntry --stats-json P
  [--seconds T] [--stats-interval S]` writes `P` (frame time mean/p50/p90/p95/p99/max, stall
  buckets >16.7/33.3/50/100 ms, process CPU/RSS/GC/thread inventory/GIL state) plus `P.jsonl`
  (per-second trend, so you can see *when* it degrades). New `Application/Runtime/PerfStatsLayer.py`;
  `FrameProfiler` gained a thread-safe `snapshot_stats()` and the long-missing `stop()`
  (`Engine._render_loop` was already calling it, silently swallowed by `try/except`).
  `--seconds` is a **wall-clock** deadline (the old `--frames` ran the inline logic loop
  uncapped by vsync — 120 frames took 0.2 s and measured nothing steady-state).
  Guard `test_perf_profiler.py` (20 checks, including concurrent tick + snapshot).
  Measured on all 7 MI-SSSEP products: **460–693 fps (1.44–2.17 ms/frame), zero stalls, ~190 MB RSS**.
- **Node-graph evaluation indexed** — `NodeCanvas` now caches pin→node, pin→metadata,
  output-pin→downstream, input-pin→source and event-type→entry-nodes, invalidated by `revision`;
  `find_pin_*`, `_downstream_nodes`, `_read_input` and `trigger` all look up instead of scanning.
  Previously *every* pin read/write linearly scanned the whole graph (`canvas.py:116` was the
  hottest frame in cProfile). Measured: **3.404 → 0.171 ms/frame (×20)** with identical event and
  error sequences. Guard `test_canvas_pin_index.py` (16 checks against a brute-force oracle).
  New tool `Utils/Dev/perf_graph.py` (`graph` / `live` / `cpu` tiers plus `--json` /
  `--baseline` regression gate, with warm-up and a 0.05 ms/frame noise floor).
- **VSync / frame-rate cap switch** — `MGE_VSYNC=0` uncaps; new
  `glfwWindow.ApplySwapInterval()` applies it **after the render thread owns the context**
  (`glfw.swap_interval` cannot be set right after `create_window` — GLFW error 65538).
  On a 200 Hz display every scenario used to report exactly 199.7 fps, hiding all rendering-cost
  differences.
- **Remote / SSH display safety (crash class)** — starting a product inside a non-interactive
  desktop session (Windows SSH has its own window station) hit
  `glfw.get_video_mode(monitor)` → `OSError: access violation reading 0x108` and exited.
  Fixed: (1) every monitor query now returns `None` on failure and disables further queries for
  the session (warn once); (2) resolution falls back `MGE_WINDOW_SIZE` → Win32
  `EnumDisplaySettingsW` → GLFW → 1920×1080; (3) only `FULLSCREEN` touches monitor handles;
  (4) `FULLSCREEN` without a usable monitor degrades to `BORDERLESS`; (5) escape hatches
  `MGE_WINDOW=windowed|borderless|fullscreen|overlay`, `MGE_WINDOW_SIZE=WxH`, `MGE_MONITOR=off`.
  New diagnostics `Utils/Dev/display_diag.py` (session identity + three Win32 sources + the GLFW
  path, `--json`) and guard `test_window_display_fallback.py` (17 checks).
  Caveat: a window created inside an SSH session belongs to that session's desktop and will
  **not** appear on the physical / remotely-viewed desktop.
- **Toolchain version lock** — new `Utils/Dev/Installer/toolchain.lock.json`
  (engine 1.1.0 ↔ toolchain 0.8.0); `build_installer` warns on mismatch.
- **Earlier items (2026-11-05 batch)** — shader `//!` annotations, single source of defaults,
  runtime `time` injection, annotation-driven material panel, resource reference stability,
  `dev/imgui_api` widget catalogue, `extdev/ui_recipes`, port ledger + `instance.info/describe`,
  test selection `--affected/--changed`, `ctx.python` extension interpreter protocol — see
  the “1.1.0 pre-release batch” section below.

- **Shader parameter annotations (`//!`)** — control kind, range, unit, default and ownership now
  live next to the GLSL declaration; the inspector, defaults, validation and docs all derive from
  that single place. Shaders without annotations degrade to the previous behaviour exactly.
  `Basic` / `Lighting` / `SSVEP` are annotated.
- **Single source of defaults** — removed the hard-coded `uShininess = 32.0` from `ResourceManager`;
  `Material` builds its parameter table from the specs.
- **`time` runtime injection** — uniforms marked `//! owner=runtime` are written by the renderer
  every frame (engine elapsed seconds), never stored in a material and never editable. The SSVEP
  square used to be **static** (`time` was always 0, hence black at the default phase); it now
  actually flickers at `sin(2π·freq·time + phase)` — GL probe: black at t=0, white at 0.025 s,
  black at 0.075 s, white at 0.125 s (10 Hz).
- **Material inspector driven by annotations** — grouped sections (Surface / Specular / Stimulus),
  units, "modified" markers, per-parameter and reset-all buttons, shared/builtin material warning;
  `time` is greyed out as engine-driven.
- **Resource reference uniqueness (`.mat`)** — `shader_ref` and `texture_refs`
  (`builtin://Name` or absolute path) are written next to the session ids; loading resolves by
  reference first and only falls back to the saved id. Fixes cross-session shader/texture mix-ups.
- **Fix** — the annotation path and the legacy uniform list were both drawing, duplicating every
  parameter; the legacy path now only runs when a shader yields no specs.
- Added `Test/Application/Core/test_uniform_schema.py` (50 checks).
- **Panel control catalog `dev/imgui_api` (generated)** — `Utils/Dev/imgui_docgen.py` reads
  signatures from the installed `imgui_bundle` at runtime and groups 143 controls the engine
  actually uses into 16 purpose sections (text / buttons / inputs / layout / containers / tables /
  popups / interaction state / disabled / drag-drop / style / raw input / windows / host-only),
  with an A–Z appendix for the remaining 230 functions plus 146 enums/structs. Flag cheat-sheets are generated from live values, so
  dependency bumps surface as reviewable diffs. Read per section via
  `engine-editor-cli doc show dev/imgui_api#表格`.
- **Extension panel recipes `extdev/ui_recipes`** — 9 copy-paste snippets: parameter row, settings
  persistence, tables, log view, live waveform, confirm modal, disabled-with-reason, worker queue,
  headless self-test.
- **Guard** `Test/Application/Editor/test_imgui_api_doc.py`: artifact freshness + real group names +
  **every imgui function used in the repo is classified** + CLI addressing (12 checks).
- **Recorded pitfall**: `from imgui_bundle.imgui import ImVec2 / TableFlags_` raises `ImportError`;
  use `from imgui_bundle import imgui` + `imgui.TableFlags_.xxx` and import `ImVec2/ImVec4` from
  the top-level package.
- **Port ledger (who holds the port, why, and what it may touch)** — every editor instance writes
  `<tmp>/engine_editor_mcp/ports/<port>.json` at start (`purpose / owner / project / touches / notes`)
  and removes it on exit. `engine-editor-cli ports` shows the holders; `launch --purpose ...` reserves
  the port before the process starts, so concurrent agents no longer race for the same free port; the
  engine rewrites the entry as `ready` with project/scene once it is up. New ops `instance.info` /
  `instance.describe` (78 core ops).
- **Startup flags** `--purpose / --owner / --tag / --touch / --note` (instance self-description, not
  Settings).
- Added `Test/Application/Editor/test_port_ledger.py` (33 checks: engine↔tools format round-trip,
  `starting` inheritance, stale cleanup, scan state machine, `choose_port` avoidance, both ops, flag
  parsing).
- **Test selection (`--affected` / `--changed`) fixed and re-installed at the entry point** — run only
  what your change touches instead of the full `--tier core` every time. Fixed: editing a test or
  `scenarios/*.py` selects that test itself; `?? dir/` untracked directories are expanded; `manual`/`live`
  tiers are skipped by default (interactive / needs a running editor); a `--changed` that only touches
  docs reports 0 tests with exit 0, while an explicit `--affected` path that matches nothing exits 2;
  a broad selection prints a hint about accumulated working-tree changes. The rule now lives in
  `test_runner --help` and the `Doc/Dev/test_protocol.md` entry section.
  New guard `Test/Application/Core/test_test_runner_selection.py` (13 checks).
- **Recorded pre-existing defect** — the heavy `test_material_cycle_stress` `shift` scenario (a builtin
  material added mid-run) also fails on a clean HEAD worktree (`bindFail=4`); `--tier core` never runs
  heavy tests, so it stayed invisible. To be diagnosed separately.
- **Extension interpreter protocol `ctx.python`** — manifests may declare
  `{"python": {"mode": "engine|venv|path", "path": "%EXT_DATA%/venv", "requirements": "...",
  "probe": [...]}}`; the host resolves it (`FVE_EXT_PYTHON_<ID>` → manifest → engine interpreter),
  runs subprocess `import` probes, owns spawned children (terminated on unload) and explains the
  choice via `explain()`. Extensions no longer need to install into the engine venv or hard-code
  `...\venv\Scripts\python.exe`. The official `SerialParallelDevice` sample now declares
  `{"mode": "engine", "probe": ["serial"]}` and reports the resolved interpreter from
  `ext.device.status`; `extension.list` gained a `python` block per extension.
- **Recorded pitfall** — the engine starts with `PYTHON_GIL=0`; passing that to an external GIL build
  makes the child die during startup ("Disabling the GIL is not supported by this build") so every
  probe would fail. `ctx.python.env()` keeps the variable only when the child *is* the engine
  interpreter.
- Added `Test/Application/Core/test_extension_python.py` (22 checks).
- **Repo cleanup** — removed root `output.txt` (0-byte redirect artifact) and
  `Application/Core/NodeGraph/evaluators/_entity_v1_legacy.py.bak`; `.gitignore` now covers
  `*.bak` / `*.orig` / `*.rej` and root-level `/*.txt` `/*.log` `/*.tmp` `/*_recordings/`.
- **Extension activation policy + entry-point split (behaviour change)** — built-in is defined by
  the allowlist (**not** by living under `Application/Functions`); panels decide the menu:
  - **built-in = the `official_extensions.json` allowlist** (mirrored by the `.gitignore` whitelist
    `!Application/Functions/<Dir>/`) → `scope=builtin` → **always on** (`always_on`, cannot be
    disabled; `FVE_EXTENSIONS_BUNDLED=off` is the safe mode);
  - **local/community fixtures that also live under `Application/Functions` but are not allowlisted**
    (Gtec, mi-sssep) → `scope=local` → opt-in like user extensions, toggleable in Settings. This
    corrects the previous build, which treated those fixtures as built-in and locked them on
    (classification now lives in one place: `ExtensionManager.scope_of()`);
  - extensions in `%APPDATA%/FlyVibingEngine/extensions` → `scope=user`, opt-in;
  - the **main-menu Extensions entry only lists extensions with a UI panel** (`has_ui`: declares
    `capabilities: ["ui"]` or actually registered a panel). Clicking it brings the panel back.
    Headless extensions (`ops` / `nodes` / `examples` / `device`) no longer occupy that menu;
  - **management moved to a new Settings ▸ Extensions page** (`order=20`): every extension
    (including headless / broken / planned), enable-disable, diagnostics (scope / has_ui / dir /
    capabilities / interpreter / example roots / registered ops / error) plus Rescan. The menu keeps
    an "Extension Settings…" shortcut at the bottom;
  - **`File ▸ Open Example` no longer goes silently empty** — when an installed but disabled
    extension ships `Examples/`, the menu shows a muted `"<name> - N example(s), extension
    disabled"` line plus a one-click enable entry (this is what fixes the "my examples were never
    injected" misdiagnosis);
  - `extension.list` reports `scope` as `builtin` / `local` / `user`, plus `always_on` / `has_ui`
    so an agent can tell *where* to look; `disable` only raises for built-in extensions.
- Added `Test/Application/Extensions/test_extension_activation.py` (built-in always-on / safe mode /
  non-built-in opt-in / disable refused / both `has_ui` criteria / state file not polluted).
- Added `Test/Application/Extensions/test_extension_builtin_scope.py` (allowlist and `.gitignore`
  whitelist must mirror each other and point at real manifests / `scope_of` three states /
  Gtec & mi-sssep must classify as `local` / `to_dict` contract).
- `Test/Application/Editor/test_editor_settings.py` updated for the four built-in pages
  (`common / export / extensions / debug`).
- **Doc CLI now addresses `###` subsections** — `doclib` splits on both `##` and `###`:
  `doc outline` prints a numbered sub-outline; `doc show <topic>#3.3` / `#11.1` returns only that
  subsection (`#3` still returns the whole chapter including its subsections — unchanged), and
  unnumbered subsections get an auto `<parent>.<k>` address so every section of a long protocol is
  reachable. `doc search` labels hits with the subsection (`dev/shader_protocol#6.1`) so they can be
  fed straight back into `doc show`. Previously only `##` was parsed, so sections such as
  `#11.1 ctx.python` were unreachable and agents had to load the whole ~700-line chapter —
  defeating the "index first, content second" context budget.

### 1.1.0 前期批次 — 2026-11-05

> **主要特性**：**运行期 UI 体系**（场景驱动的 UI 组件、设置控件、ESC 确认、节点图驱动）——
> 面向神经工程/神经认知实验的**被试界面**（操作提示、参数设置、流程确认）可以直接在场景里搭，
> 配合 overlay 覆盖层/穿透与热键注册表，实验范式可以脱离编辑器独立运行。
> 此外是渲染与工程稳定性修正（光照模型、材质引用、内置网格法线）、overlay 窗口与工具链一致性：
> 完整列表见下面条目。

#### English

> **Headline feature**: the **runtime UI system** (scene-driven UI components, settings controls,
> Esc confirmation, node-graph driven visibility and clicks). Experiment-facing screens — operator
> prompts, parameter settings, flow confirmation — are now built in the scene itself, and with
> overlay windows/click-through plus the hotkey registry a paradigm can run standalone.
> The rest of the release is rendering/engineering hardening (lighting model, material references,
> built-in mesh normals), overlay window behaviour and toolchain consistency — see below.

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
- **Blank frames are no longer silent** — the frame-capture slot flags a read-back that is
  entirely zero (`filter.blank`), because that means “nothing was drawn yet” (fresh context /
  window not presented / occluded), not “the picture is black”. `probe` retries and explains;
  `capture` reports the flag too.
- **Material references survive session id drift** — `MeshRenderer` gained `material_path`
  (`builtin://Name` or the material file path) written by `Scene.to_dict()`, resolved back to
  the live id on load. Material ids are session-scoped counters, so the same `.scene` used to
  render with the wrong (or default white) material whenever the id space shifted — silently.
  Unresolvable references now surface as `scene.reference_warnings` and in the new
  `project.open` → `reference_audit` (`missing_materials` / `missing_meshes`), and
  `ResourceManager.Init()` is idempotent so defaults can never be registered twice.
- **Enabling an extension fixes the open canvas** — `NodeCanvas.rehydrate_unknown()` re-resolves
  nodes that were kept as “unknown type” after `extension.enable`, so PIE no longer needs a
  scene reload; `sim.play` pre-flight now re-checks the live registry, reports `owners` plus a
  copy-pasteable `fix` list, and supports `auto_fix=true`. Disabling an extension that the open
  graph uses returns `unresolved_nodes` + a console warning.
- **Lighting rework (area vs point + classic Phong)** — the “directional” light is now a real
  **area light**: its world position is part of the shading (`uLightPos`) and surfaces behind
  the emitting plane (negative ray direction) receive no direct light. Point lights keep the
  `(1 - d/range)²` falloff. Both use classic Phong (`R·V`) with material parameters
  `uShininess` / `uSpecularStrength` / `uDiffuseStrength` / `uAmbientStrength` and
  `uSpecularModel` (0 = Phong, 1 = Blinn). The default scene light is turned so the cube is
  properly lit, and `MGE_LIGHT_DEBUG=1` dumps the collected light frame for tuning.
- **Runtime UI (M0) + ESC exit confirmation** — a screen-space UI pass (`Core/UI/layout.py` +
  `Core/Renderer/OpenGL/OpenGLUI.py`: quads + text textures, always drawn on top) and
  `Runtime/RuntimeUILayer.py`: pressing **Esc** (or the window X) in PIE/player opens an
  "Exit game?" dialog with Yes/No. The dialog is **modal** — while open, every key/mouse event
  is consumed (the node graph sees nothing) and in overlay mode the window forcibly captures
  the mouse instead of passing clicks through. `Yes` goes through
  `RuntimeNodeLayer.request_stop()` (same chain as the `ExitGame` node); `No`/`Esc` stays.
  Text is rasterized with the existing `TextSystem` (Pillow), captions come from en/zh i18n keys
  (`pie.exit.*`), and `test_runtime_ui.py` locks layout, hit-test and dialog state.
- **Runtime UI (M1): scene-driven UI components + `Examples/UIShowcase`** — UI is now data:
  `UICanvas` (reference resolution + `fit_height` / `fit_width` / **`contain`** / `stretch`),
  `UIRect` (9-grid anchor/pivot, `width/height = 0` fills the parent, `order`, `visible`),
  `UIPanel` (token colours, border, full-screen scrim, `modal`, `role`), `UILabel` and
  `UIButton` (variants `primary/secondary/danger/ghost`, `enabled`, `action`). They are plain
  `DataclassContract`s, so they serialise into `.scene`, show up in the Inspector with controlled
  enums, ride the PIE template whitelist and prefabs — and they **do not** bind `MeshRenderer`
  (world-space mesh vs screen-space rect). `Core/UI/tree.py` compiles the element tree into quads
  and hit rects (pure data, offline-testable); `Core/UI/scene.py` snapshots the ECS on the logic
  thread only, so the render thread never touches esper. Buttons dispatch `exit` / `close` /
  `show:<name>` / `hide:<name>` / `toggle:<name>`; visibility overrides are runtime-only (the scene
  is never mutated). `Esc` now prefers a scene panel with `UIPanel(role="exit_confirm")` and falls
  back to the built-in dialog, which is itself built from the same `UIElement` model — one
  layout/paint/hit implementation. Overlay click-through now captures over buttons, not just
  modals. The editor draws a live UI preview (`EditorLayer`), and `Examples/UIShowcase`
  (canvas + top bar + control panel with all button variants + detail panel + exit dialog) is
  guarded by `test_ui_tree.py` and `test_ui_showcase.py`.
- **Cube mesh winding fix** — `Resource/Meshes/Builtin/3D/Cube.obj` had its top face wound
  backwards; trimesh recomputes normals from the winding (ignoring `vn`), so the top face
  normal pointed **down** (a point light above the cube lit nothing, while a light *inside*
  lit it). The asset is rewound, `ResourceManager._auto_orient_solid()` now flips meshes that
  are entirely inside-out on load (with a console warning), and `test_builtin_mesh_normals`
  guards winding/outward-facing normal of every built-in mesh.
- **Per-scene-type PIE window settings** — the PIE window preference is no longer one global
  profile: `3D / 2D` keep “windowed (with resolution) / borderless / exclusive fullscreen”,
  while `Overlay` is **locked to borderless fullscreen** (Settings ▸ Export shows a read-only
  line instead of mode and size controls). Exclusive fullscreen cannot use a transparent
  framebuffer (transparency and click-through stop working) and windowed would keep the title
  bar and miss part of the screen. Exported games follow the same rule: `game.json`
  `window: {mode, width, height}` used to be parsed but never applied; `PlayerBootstrap.run`
  now routes it through the same `apply_start_preferences` (`mode="overlay"` or an overlay
  scene → borderless fullscreen).
- **Borderless windows now fill the screen exactly** — the old order (position/size first, then
  strip the title bar) left the client area offset by the chrome: measured
  `-8,-31 1936x1100 @1920x1080` (over-hanging top/left, an ~11 px gap bottom/right showing the
  desktop). Now `_win32_strip_chrome` runs first, then `_win32_fill_rect(0, 0, screen_w,
  screen_h)`; `Game (PIE)` is exactly `0,0 1920x1080` with `caption=False`.
- **Overlay click-through hit-tests the real cursor** — a pass-through window does not receive
  `WM_MOUSEMOVE` in transparent areas, so updating the pick sample only from the event path
  froze it: moving onto overlay content still passed clicks through (visible but not clickable).
  Every frame now pushes `glfw.get_cursor_pos` into the pick sample (framebuffer/window scale
  applied) and window-size coordinates are used for the NDC test (they differ on high DPI).
  Measured: content → `clickthrough=False` (`WindowFromPoint` = `Game (PIE)`), transparent →
  `clickthrough=True` (a real OS drag lands on the Paint window behind and draws).
- **Hotkey registry (single source of truth)** — `Application/Core/Input/Hotkeys.py` +
  `Application/Editor/HotkeyActions.py` + `Application/Editor/HotkeyDispatch.py`: one record per
  binding (id / keys / scope / action / i18n description) and **dispatch goes through the same
  record** (the registry itself stays imgui-free so exported games don't pull the UI toolkit). The new `Help ▸ Hot Keys…`
  read-only panel (`HotkeysPanel`) and the `hotkeys.list` op (optional `scope`) read the same
  `snapshot()`, so GUI and agent can never disagree. Registration fails fast on duplicate ids,
  duplicate chords inside a scope, or a `global` binding without an implementation (so menu
  placeholders like Ctrl+N/S/Z are never advertised). Migrated bindings: G/R/S/Space (from
  `EditorInputLayer` event branches → `poll()`), node-editor Delete (`fired("node_editor.delete")`
  — which also stops Delete from deleting nodes while a text field has focus). `hotkey.<id>` keys
  added in en/zh; `test_hotkeys.py` guards parsing, registration rules, i18n coverage,
  panel↔registry equality and the absence of hard-coded keys.
- **Runtime UI (M2): settings controls + UI nodes** — three new components, all built on the
  same element compiler: `UIToggle` (boolean switch), `UISlider` (`min/max/step`, value read-out,
  drag anywhere on the track, snaps to `step`) and `UISelect` (one data model `{options, index}`
  with three skins: `segmented`, `stepper`, real **`dropdown`** with an overlay list that flips
  upward near the viewport edge). Control values are **runtime state** (`RuntimeUILayer._values`,
  never written back to the `.scene`), and every interaction emits a UI event. New nodes
  `SetUIVisible` (show/hide any UI entity at runtime; `Entity` pin or `target` name prop),
  `SetUIText` (rewrites a label's text at runtime — `Text` pin wins over `props.text`; an empty
  string clears the override and the label falls back to its serialized value),
  `OnUIClick` (Event-category entry; filters by `action`/`name`, outputs action/name/value/index)
  and `GetUIValue` (reads toggle/slider/select state) let a graph drive and observe the UI.
  `Examples/UIShowcase` gained a settings panel (all three controls + all three select skins) and
  a three-link graph (hide a label on start, show it and retitle the panel on the Primary click);
  `test_ui_controls.py` covers the control math, the layer interaction, the evaluators and the full
  click → `OnUIClick` → `SetUIVisible` → `SetUIText` chain.

#### 简体中文

> **主要特性**：**运行期 UI 体系**（场景驱动的 UI 组件、交互控件、标签动态文本、ESC 模态、
> 节点图驱动）—— 面向神经工程/神经认知实验的**被试界面**可以直接在场景里搭，
> 配合 overlay 覆盖层/穿透与热键注册表，实验范式可以脱离编辑器独立运行。
> 此外是渲染与工程稳定性修正（光照模型、材质/着色器引用唯一性、内置网格法线）、
> overlay 窗口与工具链一致性：完整列表见下面条目。

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
- **全透明帧不再沉默** —— 帧末读回若整帧全 0（RGBA 全透明），抓帧信箱会标
  `blank`（这是“还没画上”，不是“画面是黑的”）；`probe` 自动重抓并解释原因，`capture` 同样透出。
- **材质引用跨会话不再漂移** —— `MeshRenderer` 新增 `material_path`（`builtin://名称` 或
  材质文件路径），保存时由 `Scene.to_dict()` 写入，加载时解析回本会话 live id。
  材质 id 是会话级自增的，以前只要 id 空间一变，同一个 `.scene` 就会错拿材质、
  渲染成默认白且不报错。解析不到的引用现在进 `scene.reference_warnings`，
  并汇总到 `project.open` 的 `reference_audit`（`missing_materials` / `missing_meshes`）；
  `ResourceManager.Init()` 改为幂等，内置材质不会被重复注册。
- **启用扩展会就地修复已打开的画布** —— `NodeCanvas.rehydrate_unknown()` 把加载时
  留在“未注册”状态的节点重新解析，PIE 不再需要重载场景；`sim.play` 预检改为查活注册表，
  并返回 `owners` 与可复制的 `fix` 列表，支持 `auto_fix=true`。停用画布上正在用的扩展时，
  回执带 `unresolved_nodes` 与控制台警告。
- **光照重做（面光源 / 点光源 + 经典冯氏）** —— 原来的“方向光”变成真正的**面光源**：
  世界位置参与计算（`uLightPos`），发光面背后的表面（射线负方向）完全没有直射光；
  点光源保留 `(1 - d/range)²` 衰减。两者都走经典冯氏（`R·V`），材质参数为
  `uShininess` / `uSpecularStrength` / `uDiffuseStrength` / `uAmbientStrength` 与
  `uSpecularModel`（0 = 冯氏 / 1 = Blinn）。默认场景光源朝向已修正，立方体现在是正常的
  受光立方体；`MGE_LIGHT_DEBUG=1` 可打印每帧收集到的光源数据。
- **运行时 UI（M0）+ ESC 退出确认** —— 新增屏幕空间 UI pass（`Core/UI/layout.py` +
  `Core/Renderer/OpenGL/OpenGLUI.py`：矩形/文本 quad，永远画在最上层）与
  `Runtime/RuntimeUILayer.py`：PIE/成品里按 **ESC**（或点窗口 X）弹出“退出游戏？”对话框
  （Yes/No）。对话框是**模态**的 —— 打开期间所有键鼠被 consume（节点图收不到），
  overlay 模式下窗口强制捕获鼠标而不是穿透。`Yes` 走 `RuntimeNodeLayer.request_stop()`
  （与 `ExitGame` 节点同一条链），`No`/ESC 留下。文本复用 `TextSystem`（Pillow）光栅化，
  文案来自 en/zh 词条（`pie.exit.*`），`test_runtime_ui.py` 锁定布局/命中/对话框状态。
- **运行时 UI（M1）：场景驱动 UI 组件 + `Examples/UIShowcase`** —— UI 变成数据：
  `UICanvas`（参考分辨率 + `fit_height` / `fit_width` / **`contain`** / `stretch`）、
  `UIRect`（9 宫格锚点/枢轴，`width/height = 0` 撑满父级，`order`、`visible`）、
  `UIPanel`（token 颜色、描边、整屏遮罩、`modal`、`role`）、`UILabel`、
  `UIButton`（`primary/secondary/danger/ghost` 变体、`enabled`、`action`）。
  它们都是普通 `DataclassContract`：随 `.scene` 读写、Inspector 通用检视（受控枚举）、
  进 PIE 模板白名单与 prefab；且**不绑 `MeshRenderer`**（世界空间网格 vs 屏幕空间矩形）。
  `Core/UI/tree.py` 把元素树编译成 quad + 命中矩形（纯数据，可离线单测）；`Core/UI/scene.py`
  只在逻辑线程拍快照，渲染线程不碰 esper。按钮动作：`exit` / `close` /
  `show:<名>` / `hide:<名>` / `toggle:<名>`，显隐是运行期覆盖（不写回场景）。ESC 现在优先打开场景里
  `UIPanel(role="exit_confirm")` 的面板，没有则退回内置对话框 —— 而内置对话框也用同一套
  `UIElement` 模型生成（只有一份布局/绘制/命中实现）。overlay 穿透判定现在也会在按钮上捕获
  （不只模态）。编辑器新增所见即所得的 UI 预览（`EditorLayer`）；`Examples/UIShowcase`
  （画布 + 顶部栏 + 全变体按钮的控制面板 + 详情浮窗 + 退出确认）由 `test_ui_tree.py` 与
  `test_ui_showcase.py` 守门。
- **运行时 UI（M2）：设置控件 + UI 节点** —— 三个新组件，全部复用同一套元素编译器：
  `UIToggle`（开关）、`UISlider`（`min/max/step`、数值回显、整条轨道可拖、按 `step` 吸附）、
  `UISelect`（一个数据模型 `{options, index}` + 三种皮肤：`segmented` / `stepper` /
  真正的 **`dropdown`** —— 弹层靠近视口底部时向上展开）。控件值是**运行期状态**
  （`RuntimeUILayer._values`，**不写回 `.scene`**），每次交互都会发一条 UI 事件。新增节点
  `SetUIVisible`（运行期显隐任意 UI 实体，`Entity` 连线或 `target` 名字属性）、
  `SetUIText`（运行期改写标签文本：`Text` 引脚优先于 `props.text`，空串=清除覆盖并回落场景值）、
  `OnUIClick`（Event 类入口，可按 `action`/`name` 过滤，输出 action/name/value/index）、
  `GetUIValue`（读开关/滑条/选择当前值）—— 节点图由此可以驱动并观察 UI。
  `Examples/UIShowcase` 增加设置面板（三种控件 + 三种选择皮肤）与三段连线的图
  （启动隐藏一个标签，点 Primary 后显示并改写面板标题）；`test_ui_controls.py` 覆盖控件数值数学、
  图层交互、求值器，以及「点击 → `OnUIClick` → `SetUIVisible` → `SetUIText`」全链路。
- **立方体网格绕序修复** —— `Resource/Meshes/Builtin/3D/Cube.obj` 的**顶面两个三角形绕序反了**；
  trimesh 会按绕序重算法线（忽略 OBJ 的 `vn`），于是顶面法线朝下 —— 点光源在立方体上方时
  顶面全黑，把光源塞进立方体内部反而亮。已修正资产；加载器新增
  `ResourceManager._auto_orient_solid()`（整体内向的网格自动翻转 + 控制台告警）；
  新增守卫 `test_builtin_mesh_normals` 校验内置网格的绕序与朝外法线。
- **Overlay 覆盖层窗口按场景类型差异化** —— PIE 窗口设置不再全局一套：`3D / 2D` 仍是
  「窗口化（可设分辨率）／无边框全屏／独占全屏」，`Overlay` **固定为无边框全屏**（Settings ▸
  Export 只显示只读说明，不给模式与尺寸控件）。理由：独占全屏不支持透明帧缓冲（透明与输入穿透
  失效），窗口化会露出标题栏且不铺满屏幕。导出成品同语义：`game.json` 的
  `window: {mode, width, height}` 以前只解析不生效，现在由 `PlayerBootstrap.run` 交给同一个
  `apply_start_preferences`（`mode="overlay"` / overlay 场景 → 无边框全屏）。
- **无边框窗口精确铺满屏幕** —— 原顺序（先定位尺寸 → 再剥标题栏）让客户区带上 chrome 偏移，
  实测 `-8,-31 1936×1100 @1920×1080`（左上溢出屏外、右下留 ~11 px 缝，能看到桌面）。
  改为**先 `_win32_strip_chrome` 再 `_win32_fill_rect(0, 0, 屏宽, 屏高)`**；`Game (PIE)` 现在
  精确 `0,0 1920×1080`、`caption=False`。
- **Overlay 点击穿透的命中源改为真实光标** —— 穿透窗口在透明处**收不到 `WM_MOUSEMOVE`**，
  原来只靠事件路径更新 pick 采样点，光标停在空白处时判定会冻结：光标移到覆盖层内容上也仍然穿透
  （画面上有东西却点不到）。现在每帧用 `glfw.get_cursor_pos` 推进 pick 采样点（按 framebuffer/
  window 比例换算像素），坐标判定统一用窗口尺寸（高 DPI 下两者不等）。实测：内容处
  `clickthrough=False`（`WindowFromPoint` = `Game (PIE)`），透明处 `clickthrough=True`
  （真实 OS 拖动落到后方「画图」窗口，可正常出墨）。
- **输入热键注册体系（单一事实源）** —— `Application/Core/Input/Hotkeys.py` +
  `Application/Editor/HotkeyActions.py` + `Application/Editor/HotkeyDispatch.py`：
  每条热键一条记录（id / 键位 / scope / 动作 / 双语说明），**派发也走这条记录**
  （注册表本身不 import imgui — 导出成品不带 UI 工具包）。新增 `Help ▸ Hot Keys…` 只读面板（`HotkeysPanel`）与 `hotkeys.list` op
  （可选 `scope`）读同一个 `snapshot()`，GUI 与 agent 不可能不一致。注册期即失败：重复 id、
  同 scope 重复和弦、`global` 没实现都会报错（菜单里没接线的 Ctrl+N/S/Z 之类永不进表）。
  已迁移：G/R/S/Space（`EditorInputLayer` 事件分支 → `poll()`）、节点编辑器 Delete
  （`fired("node_editor.delete")` — 顺手修掉“文本框里按 Delete 删节点”）；en/zh 新增
  `hotkey.<id>` 词条；`test_hotkeys.py` 守卫解析、注册约束、i18n 覆盖、面板↔注册表一致性与
  “不再有硬编码键位”。


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
