# 运行时打包 / 游戏导出开发协议（Runtime Packaging & Game Export）

> 适用：`Application/PlayerEntry.py`、`Application/Runtime/PlayerBootstrap.py`、
> `Application/Core/Project/**`（运行时工程加载）、`Utils/Runtime/**`（打包流水线）、
> `ProjectManager.export_project_bundle(include_player=True)`（Export 按钮游戏层）、
> `run_game.cmd` 启动器与 wheelhouse。
> 工程导出本体见 `project_export_protocol.md`；节点/设备见 `node_editor_protocol.md` / `device_io_protocol.md`。

---

## 1. 决策记录（2026-09-28 锁定）

| 决策 | 内容 |
|---|---|
| 运行时形态 | **双轨制**：主轨 = 导出时预装好的 Python 环境（目标机零安装、免联网）；备轨 = 随包 `wheelhouse/`（离线重建/修复材料） |
| 解释器来源 | **python-build-standalone**（即 uv 管理的那份 3.14t），整目录可搬运；不复制 `.venv`（venv 含绝对路径不可搬） |
| gtec 真机 | **随包提供**。pygds 官方无 free-threading 版本 — 由用户 fork 补 `Py_mod_gil` 标记后把 wheel 放入 `Resource/wheels/`；管线将其视为一等公民；缺失时导出**告警不失败** |
| 数据输出 | 默认包内 `output/`，`game.json` 的 `output_dir` 可配置 |
| 规模取向 | 不在乎体积（科研场景）；宁大勿缺，环境与开发版保持一致 |

---

## 2. 文件地图

| 文件 | 职责 |
|---|---|
| `Application/PlayerEntry.py` | 播放器 CLI：`<game.json\|.myproj\|.scene>` + `--dry-run` + `--frames N`（真实运行 N 帧后自动退出，冒烟用） |
| `Application/Runtime/PlayerBootstrap.py` | 编排：`prepare_offline`（解析+加载场景）→ `activate_resources`（材料+重映射）→ `dry_run`（无头校验）/ `run`（窗口→init→注入→推层→`GameRuntime.run()`）；含 `_AutoExitLayer` |
| `Application/Core/Project/RuntimeProjectLoader.py` | 运行时 .myproj 加载（编辑器零依赖，语义镜像 `ProjectManager`）；**必须在 `ResourceManager.Init` 之后调用 `load_resources`** |
| `Utils/Runtime/collect_wheels.py` | `.venv-py314t` 实况 → `requirements.export.txt`(全量) + `requirements.runtime.txt`(游戏子集) → 逐包下载 → `Resource/wheels/` → 覆盖度核对 + `CHECKSUMS.sha256` |
| `Utils/Runtime/prepare_runtime.py` | uv 3.14t 解释器 → `Resource/runtime/` 镜像 → 按**运行时子集**离线安装 → 瘦身（pdb/test/Doc）→ 冒烟 + 子集断言 |
| `ProjectManager.export_project_bundle(..., include_player=True)` | Export 按钮入口：工程包 + 游戏层（game.json/引擎副本/runtime/wheelhouse/run_game.cmd） |
| `Utils/Runtime/player.bat` | 开发机播放器启动（用 dev venv；2026-09-28 从引擎根移入） |

---

## 3. 播放器契约

- **启动顺序（run 模式）**：`prepare_offline` → 窗口标志（含 OVERLAY 透明/置顶/穿透）→
  `GameRuntime.init()` → `activate_resources` → `SceneManager.SyncFromScene` →
  `cam_mgr._apply`（按 game_type 选机位）→ `RuntimeNodeLayer.set_canvas/set_scene(copy)` +
  `set_context_hooks(on_stop_request=None)` → push layers → `GameRuntime.run()`。
- **ExitGame**：宿主无回调 → `RuntimeNodeLayer` 中立兜底（`run_state=False`），无需编辑器。
- **摄像机**：场景文件不存 Camera 实体（"相机由 prefab 管理"）；`SyncFromScene` 兜底
  `cam_mgr.create_defaults()`（依赖 `ResourceManager.Init` 已加载内置 prefab）。
- **`--dry-run`**：不建窗口；`ResourceManager.Init` → 加载器全链路 → 原始场景 JSON 走
  MCP 校验链路（`validate_static` + `dry_run_simulation`）。
- **窗口模式**：`game.json window.mode` 显式配置优先，"auto" 时由 `scene.game_type` 决定。
- **工作目录**：始终 = 包根（builtin 资源是 CWD 相对路径）；播放器不 chdir。
- **收尾**：run 返回后调 `SerialParallelDevice.stop()` + `EEGDevice.close_all()` 安全网。

### 3.1 运行时线程纪律（PIE / 播放器通用，2026-09-28 锁定）

`GameRuntime` 启动即双线程并发（free-threading 无 GIL）：

- **渲染线程** `Engine._render_loop`：`run_ready` 放行后逐个 `layer.OnAttach()` → 渲染帧；
- **逻辑线程** `Engine._logic_loop`：每帧对全部 layer 调 `OnUpdate()` —— **与 OnAttach 并发**。

因此 Layer 类初始化（classmethod 共享类状态）必须满足：

1. `OnUpdate` 会读取的字段必须有**类级默认值**（例：`RuntimeNodeLayer._frame = 0`）；
2. **"就绪标记"最后赋值** —— 把它当作 `OnUpdate` 守卫的可见性开关
   （例：`RuntimeNodeLayer._evaluator` 在 `_context` / `_frame` / `_pending_start` 全部备齐后才赋值，
   `OnUpdate` 只有越过 `_evaluator is None` 守卫才执行帧逻辑）。

坑（2026-09-28 实证）：旧序先赋 `_evaluator` 后再赋 `_frame` → PIE 启动瞬间逻辑线程
`AttributeError: type object 'RuntimeNodeLayer' has no attribute '_frame'`（线程静默死亡，无异常上抛）。
回归守卫：`Test/Application/Runtime/test_runtime_node_layer_race.py`（无头 + 可控阻塞点，确定性）。

---

## 4. 导出包结构（v1）

```
<Name>/
    run_game.cmd           # 双击入口（%~dp0 锚定; 设 PYTHONNOUSERSITE/PYTHONDONTWRITEBYTECODE/PYTHON_GIL）
    game.json              # 清单: project / startup_scene / window.mode / output_dir / engine 版本
    <Name>.myproj          # 工程（scenes/resources 全相对路径）
    scenes/ assets/        # 内容（工程导出既有契约不变）
    export_manifest.json   # 含 "game" 段: runtime/wheelhouse 统计
    Application/           # 冻结引擎副本（排除 __pycache__）
    Resource/              # 引擎内置资源（排除 wheels/ 与 runtime/）
    runtime/               # 预装 Python 环境（Resource/runtime 镜像拷贝; 缺失→告警）
    wheelhouse/            # 全部 wheel + requirements.export.txt + CHECKSUMS.sha256
    output/                # 运行期数据（默认; 不存在时播放器自建）
```

启动器关键旗标：`-Xgil=0` + `PYTHON_GIL=0`（free-threading 双保险）、
`PYTHONNOUSERSITE=1`（不读用户 site-packages, 双向不污染）、
`PYTHONDONTWRITEBYTECODE=1`（只读介质可跑）。run_game.cmd 内容保持 **ASCII only**（避免代码页问题）。

---

## 5. 打包流水线（开发机）

```
[锁变更时]  collect_wheels.py   → Resource/wheels/ (requirements.export.txt + CHECKSUMS.sha256)
[一次性]    prepare_runtime.py  → Resource/runtime/ (解释器 + 预装 site-packages + 冒烟)
[每次导出]  Export 按钮          → 游戏层拷贝（runtime/wheelhouse 原样随包）
```

- `Resource/runtime/` 已 .gitignore（大体积镜像不入库）；`Resource/wheels/` **入库**（复制版轮子, 含本地 fork）。
- wheelhouse 覆盖度核对：每条需求须有 wheel；sdist-only 会标注（安装需编译工具链）。
- requirements 包含 `pip==…` → 运行时自带 pip，支持包内离线修复
  （`runtime\python.exe -m pip install --no-index --find-links ..\wheelhouse ...`）。

### 5.1 运行时子集与镜像瘦身（2026-09-28）

导出运行时**不含编辑器专用包**，且镜像做了发行版瘦身（实证 + 静态守卫双重保证）：

| 处理 | 内容 | 依据 |
|---|---|---|
| 子集排除 | `imgui-bundle` + MCP 工具链 26 包（`collect_wheels.py` 的 `_EDITOR_ONLY`） | 包内隐藏后 dry-run + 窗口运行全绿（2026-09-28 实证）；边界测试运行时树扫描（除 Editor 与 Vulkan 外不得 import `imgui_bundle`/`mcp`） |
| 发行版瘦身 | `Lib/test`(146M) / `Doc`(63M) / 全部 `*.pdb`(266M) | 与运行无关的 CPython 发行版内容 |

- 生成链：`collect_wheels.py` 写 `requirements.runtime.txt` → `prepare_runtime.py` 按它安装 + `trim_image()` + `check_editor_only()` 断言；
- 实测（2026-09-28）：镜像 887 → **364 MiB**；整包 1.3 GB → **409 MB**（其中 runtime 324 MB；导出时剔除 `__pycache__`）+ dry-run/窗口 e2e 全绿；
- ⚠️ 导出包内**不再能运行编辑器**（imgui 不在镜像中）——`wheelhouse/` 保留**全量轮子**与 `requirements.export.txt`，需要“全量/编辑器版”环境时用 wheelhouse 重建即可。

---

## 6. 边界与守卫

- 播放器链路（`PlayerEntry` / `PlayerBootstrap` / `Core/Project`）必须能在外界
  **阻断 imgui_bundle + Application.Editor** 的情况下导入 —
  已纳入 `Test/Application/Core/test_node_graph_boundary.py` 运行时链路清单。
- `Core/Project/**` 另有独立源码扫描（`test_runtime_project_loader.py`）。
- 修改导出/播放器行为后必跑：
  `test_runtime_project_loader.py`、`test_node_graph_boundary.py`、
  `Application/PlayerEntry.py <工程> --dry-run`、`--frames 60` 冒烟。

## 7. 已知缺口 / 后续

1. gtec fork wheel 待放入 `Resource/wheels/`（就绪后重跑 collect_wheels + prepare_runtime）。
2. `fullscreen` 窗口模式尚未实现（`window.mode` 已预留）。
3. 自定义资产（mesh/texture/shader）导入不持久化（`project_export_protocol.md` §7.5）——
   用到它们的实验包会缺资源；打包前会强告警。
4. 实验数据默认写入 `output/`；数据节点仍以 CWD 为相对基准，后续接入 `game.json output_dir` 统一策略。
5. Windows Sandbox / 中文路径 / 只读介质 三场景验证（P4）。
