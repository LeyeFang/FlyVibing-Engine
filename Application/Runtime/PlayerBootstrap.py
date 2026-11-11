"""
PlayerBootstrap — 播放器编排（编辑器零依赖）。

职责（无编辑器启动一个工程/场景）:
  prepare_offline()  : 读 game.json / .myproj / .scene → 工程 + 场景 + 标题/窗口模式（不依赖引擎）
  activate_resources(): ResourceManager.Init 之后加载材料/prefab + material id 重映射
  dry_run()          : 无头自检 — 加载器链路 + 静态校验 + 假时间干跑（复用 MCP 验证链路）
  run()              : 真实运行 — 窗口标志 → init → 场景注入 esper → 推层 → GameRuntime.run()

运行时对 Editor 零反向依赖；本模块只 import Application.Core / Application.Runtime。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from Application.Core.Layers.Layer import Layer

# ────────────────────────────────────────────────────────────────
# 数据模型
# ────────────────────────────────────────────────────────────────


@dataclass
class PlayerSession:
    """已解析的播放会话（尚未接触引擎/窗口）。"""

    source: str                      # 用户传入的路径（game.json / .myproj / .scene）
    source_kind: str                 # "game" | "project" | "scene"
    project: object | None = None    # RuntimeProject | None
    scene: object | None = None      # Scene（已加载, 可能未重映射）
    scene_path: str = ""             # 启动场景绝对路径
    title: str = "Game"
    window_mode: str = "auto"        # auto | windowed | borderless | fullscreen | overlay
    window_width: int = 1280         # 仅 windowed 生效 (overlay 固定无边框全屏)
    window_height: int = 720
    output_dir: str = ""             # 数据输出目录（默认 <包根>/output）
    root: str = ""                   # bundle 根（= game.json 所在目录; 无则 CWD）
    background_color: 'tuple[float, float, float, float] | None' = None
    warnings: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────
# 解析（不依赖引擎初始化）
# ────────────────────────────────────────────────────────────────


def prepare_offline(source: str) -> PlayerSession:
    """解析输入路径 → PlayerSession（加载工程元数据与场景数据, 不加载资源）。"""
    abs_source = os.path.abspath(source)
    if not os.path.isfile(abs_source):
        raise FileNotFoundError(f"入口不存在: {abs_source}")

    _install_declared_node_packs()

    ext = os.path.splitext(abs_source)[1].lower()
    if ext == ".json":
        return _prepare_from_game_json(abs_source)
    if ext == ".myproj":
        return _prepare_from_project(abs_source, root=os.path.dirname(abs_source))
    if ext == ".scene":
        return _prepare_from_scene(abs_source, root=os.path.dirname(abs_source))
    raise ValueError(f"不支持的入口类型: {source}（期望 game.json / .myproj / .scene）")


def _install_declared_node_packs() -> None:
    """成品内按 `extension.json` 的 `nodes` 声明注册节点包（**必须先于场景加载**）。

    为什么成品需要这一步: 成品里没有扩展管理器 —— `NodeGraph/__init__` 只调
    `discover_builtin()`（扫 `**/node_pack.py`）。走 `ctx.nodes.register_pack()`
    运行时注册的扩展**没有** `node_pack.py`，于是目录虽然被导出器复制进产物，
    节点类型却永远不会注册 → 节点 unknown → 采集怡终不执行。

    PIE / 编辑器不受影响（那里由 `extension.enable` 负责）。
    """
    try:
        from Application.Core.NodeGraph.node_packs import NodePackRegistry

        pack_infos = NodePackRegistry.load_declared_packs()
        for info in pack_infos:
            print(f"[Player] extension nodes: {info['pack']} "
                  f"({len(info['types'])} type(s))")
    except Exception as e:  # noqa: BLE001 — 扩展加载失败不得阻断启动
        print(f"[Player] WARNING: declared node packs failed: {type(e).__name__}: {e}")


def _prepare_from_game_json(path: str) -> PlayerSession:
    root = os.path.dirname(path)
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"game.json 格式错误: {path}")

    _win = cfg.get("window") or {}
    if not isinstance(_win, dict):
        _win = {}

    def _dim(key: str, default: int) -> int:
        try:
            return max(320, min(7680, int(_win.get(key, default))))
        except (TypeError, ValueError):
            return default

    s = PlayerSession(
        source=path,
        source_kind="game",
        root=root,
        title=cfg.get("title") or os.path.splitext(os.path.basename(root))[0],
        window_mode=_win.get("mode", "auto"),
        window_width=_dim("width", 1280),
        window_height=_dim("height", 720),
        output_dir=cfg.get("output_dir") or "output",
    )

    # 工程引用优先; 否则支持仅 startup_scene 的最小清单
    project_rel = cfg.get("project")
    if project_rel:
        proj_path = project_rel if os.path.isabs(project_rel) else os.path.join(root, project_rel)
        _attach_project(s, proj_path, scene_override=cfg.get("startup_scene"))
    elif cfg.get("startup_scene"):
        scene_rel = cfg["startup_scene"]
        scene_path = scene_rel if os.path.isabs(scene_rel) else os.path.join(root, scene_rel)
        _attach_scene(s, scene_path)
    else:
        raise ValueError(f"game.json 必须提供 'project' 或 'startup_scene': {path}")

    if not os.path.isabs(s.output_dir):
        s.output_dir = os.path.join(root, s.output_dir)
    return s


def _prepare_from_project(path: str, root: str) -> PlayerSession:
    s = PlayerSession(source=path, source_kind="project", root=root)
    s.title = os.path.splitext(os.path.basename(path))[0]
    s.output_dir = os.path.join(root, "output")
    _attach_project(s, path)
    return s


def _prepare_from_scene(path: str, root: str) -> PlayerSession:
    s = PlayerSession(source=path, source_kind="scene", root=root)
    s.title = os.path.splitext(os.path.basename(path))[0]
    s.output_dir = os.path.join(root, "output")
    _attach_scene(s, path)
    return s


def _attach_project(s: PlayerSession, project_path: str, scene_override: str | None = None) -> None:
    """加载 .myproj + 启动场景（不加载资源; 场景重映射延迟到 activate_resources）。"""
    from Application.Core.Project import RuntimeProjectLoader

    project = RuntimeProjectLoader.load_project(project_path)
    s.project = project
    # 背景色（工程文件里的测试性配置）→ 会话携带; run() 时经 SetClearColorCommand 注入
    try:
        _bg = (getattr(project, "data", None) or {}).get("background_color") or (0.2, 0.2, 0.2)
        s.background_color = (float(_bg[0]), float(_bg[1]), float(_bg[2]), 1.0)
    except Exception:  # noqa: BLE001 — 坏值不影响加载
        s.background_color = None
    rel = scene_override or project.startup_scene
    if not rel:
        raise ValueError(f"工程没有可用场景: {project_path}")
    scene_path = RuntimeProjectLoader.resolve_path(project, rel)
    if not scene_path or not os.path.isfile(scene_path):
        raise FileNotFoundError(f"启动场景不存在: {rel} (解析为 {scene_path})")
    # 场景 `_file_path` 记录; 资源重映射在 activate_resources 中执行
    scene = RuntimeProjectLoader.load_scene(project, scene_path)
    s.scene = scene
    s.scene_path = scene_path


def _attach_scene(s: PlayerSession, scene_path: str) -> None:
    """无工程场景直载（无材料重映射）。"""
    from Application.Core.Scene.Scene import Scene
    from Application.Core.NodeGraph import canvas as _canvas_module  # noqa: F401

    if not os.path.isfile(scene_path):
        raise FileNotFoundError(f"场景不存在: {scene_path}")
    s.scene = Scene.load_from_file(scene_path)
    s.scene_path = scene_path


def activate_resources(session: PlayerSession) -> None:
    """加载工程资源并重映射场景引用（必须在 ResourceManager.Init 之后调用）。"""
    if session.project is None or session.scene is None:
        return
    from Application.Core.Project import RuntimeProjectLoader

    RuntimeProjectLoader.load_resources(session.project)
    n = RuntimeProjectLoader.remap_scene_materials(session.scene, session.project.id_map)
    if n:
        print(f"[Player] Material refs remapped: {n}")


def resolve_window_mode(session: PlayerSession) -> str:
    """窗口模式：显式配置优先, auto → 由场景 game_type 决定。"""
    mode = (session.window_mode or "auto").lower()
    if mode != "auto":
        return mode
    try:
        from Application.Core.Scene.Scene import GameType

        if session.scene is not None and session.scene.game_type == GameType.OVERLAY:
            return "overlay"
    except Exception:
        pass
    return "windowed"


# ────────────────────────────────────────────────────────────────
# 干跑（无头）— 复用 MCP 验证链路
# ────────────────────────────────────────────────────────────────


def dry_run(source: str, frames: int = 0, verbose: bool = False,
            dt: float = 0.0) -> int:
    """无头自检: 工程/场景加载 + 静态校验 (+ 可选假时间干跑)。

    Args:
        frames: fake-time 模拟帧数（0 = 跳过 L2 干跑）。
        dt:     每帧 fake-time 步长（秒; 0 = 引擎默认 1/60）。

    Returns:
        退出码（0=通过）
    """
    print("=" * 60)
    print(f"[Player] DRY-RUN: {source}")
    print("=" * 60)

    # ── 引擎资源基准（内置资源; 复现编辑器/运行时一致的 material id）──
    from Application.Core.Engine import Engine
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(Engine)

    # ── 1. 工程 + 场景 + 资源（完整加载器链路）──
    session = prepare_offline(source)
    activate_resources(session)

    print(f"[Player] source kind : {session.source_kind}")
    print(f"[Player] title       : {session.title}")
    print(f"[Player] startup     : {session.scene_path}")
    print(f"[Player] window mode : {resolve_window_mode(session)}")
    print(f"[Player] output dir  : {session.output_dir}")

    failures = 0
    if session.project is not None:
        for w in session.project.warnings:
            print(f"[Player] WARNING: {w}")

    scene = session.scene
    if scene is None:
        print("[Player] ERROR: scene not loaded")
        return 1
    has_graph = scene.node_graph is not None
    print(f"[Player] entities    : {len(scene.entities)}")
    print(f"[Player] node_graph  : {'present' if has_graph else 'NONE'}")

    # ── 2. 原始场景 JSON → 静态校验 + 干跑（引擎内校验服务 — 单一事实源）──
    with open(session.scene_path, "r", encoding="utf-8") as fh:
        scene_json = json.load(fh)

    from Application.Core.NodeGraph.validation import (
        ValidationBackendUnavailable,
        run_validation,
        static_check_graph,
    )

    try:
        static_entries = static_check_graph(scene_json)
    except ValidationBackendUnavailable as exc:
        print("[Player] ERROR: validation backend unavailable")
        for line in str(exc).splitlines():
            print(f"  {line}")
        print(f"  (scene: {session.scene_path})")
        return 1
    static_errors = [e for e in static_entries if e["level"] == "error"]
    static_warnings = [e for e in static_entries if e["level"] == "warning"]
    if static_errors:
        failures += len(static_errors)
        print(f"[Player] Static validation: {len(static_errors)} error(s)")
        for e in static_errors:
            print(f"  x {e['message']}")
    else:
        print("[Player] Static validation: PASSED")
    if static_warnings:
        print(f"[Player] Static validation: {len(static_warnings)} warning(s)")
        for e in static_warnings:
            print(f"  ! {e['message']}")

    if frames > 0:
        options = {"frames": frames, "verbose": verbose}
        if dt and dt > 0:
            options["dt"] = dt
        report = run_validation(scene_json, options)
        errors = report["runtime"]["errors"]
        if report["static"]["errors"]:
            print("[Player] Dry-run: skipped (static errors)")
        elif errors:
            failures += len(errors)
            print(f"[Player] Dry-run: {len(errors)} error(s)")
            for e in errors:
                print(f"  x {e}")
        else:
            rt = report["runtime"]
            print(
                f"[Player] Dry-run: {rt['frames_simulated']} frames "
                f"({report['options']['dt']} s/frame), "
                f"{rt['total_events']} side-effect events"
            )

    print("=" * 60)
    if failures == 0:
        print("[Player] DRY-RUN PASSED")
        return 0
    print(f"[Player] DRY-RUN FAILED ({failures} issue(s))")
    return 1


# ────────────────────────────────────────────────────────────────
# 真实运行（阻塞）
# ────────────────────────────────────────────────────────────────


# 缺扩展节点的运行状态（供宿主/日志查询；不是错误，是"降级"事实）
_MISSING_NODE_TYPES: dict[str, list[int]] = {}


def _report_missing_node_types(canvas) -> dict[str, list[int]]:
    """缺扩展时必须**显式降级**，不能静默 no-op（2026-11-11）。

    为什么需要: `NodeCanvas.from_dict` 对未注册类型是"保留节点但不求值"，
    窗口模式又不跑静态校验 —— 结果是成品**能启动、能渲染、时间轴在走，
    但采集/训练类节点永不执行**（用户收回来的数据是空的，且看不出问题）。

    PIE 预检与 `--dry-run` 会硬拦；窗口模式选择**降级 + 大声告知**：
    展示型产物应能跑，但使用者必须知道"这次结果不完整"。
    """
    unknown = dict(getattr(canvas, "unknown_node_types", None) or {})
    # 先按**当前**注册表重算（扩展可能在场景加载后才被启用/发现）
    refresh = getattr(canvas, "refresh_unknown_types", None)
    if callable(refresh):
        try:
            unknown = dict(refresh() or {})
        except Exception:  # noqa: BLE001 — 诊断失败不得影响启动
            pass
    _MISSING_NODE_TYPES.clear()
    _MISSING_NODE_TYPES.update(unknown)
    if not unknown:
        return unknown

    total = sum(len(ids) for ids in unknown.values())
    names = ", ".join(f"{t} x{len(ids)}" for t, ids in sorted(unknown.items()))
    print("=" * 60)
    print(f"[Player] WARNING: {total} node(s) from {len(unknown)} missing "
          f"extension type(s) are NOT evaluated — THIS RUN IS DEGRADED")
    print(f"[Player]          {names}")
    print("[Player]          enable the owning extension and re-export, or use "
          "--dry-run to see the full static report")
    print("=" * 60)
    return unknown


class _AutoExitLayer(Layer):
    """--frames N / --seconds T 支撑层: 到达任一限制后请求退出（冒烟/CI 用）。

    ★ 两种计数不是一回事:
      `OnUpdate` 在**逻辑循环**里跑，导出模式下内联循环不受 vsync 限制，
      120 次迭代可能只花 0.2 s —— 用帧数当“运行时间”会量不到稳态。
      所以性能统计请用 `--seconds`（墙钟截止）。
    """

    _count = 0
    _max_frames = 0
    _deadline = 0.0

    @classmethod
    def configure(cls, max_frames: int = 0, max_seconds: float = 0.0) -> None:
        cls._count = 0
        cls._max_frames = int(max_frames or 0)
        cls._deadline = (time.perf_counter() + float(max_seconds or 0.0)
                         if max_seconds and max_seconds > 0 else 0.0)

    @classmethod
    def OnAttach(cls):
        pass

    @classmethod
    def OnDetach(cls):
        pass

    @classmethod
    def OnUpdate(cls):
        cls._count += 1
        reached = bool(cls._max_frames and cls._count >= cls._max_frames)
        why = f"--frames {cls._max_frames}"
        if not reached and cls._deadline and time.perf_counter() >= cls._deadline:
            reached = True
            why = "--seconds limit"
        if reached:
            from Application.Runtime.GameRuntime import GameRuntime

            print(f"[Player] {why} reached — exiting")
            GameRuntime.run_state = False

    @classmethod
    def OnEvent(cls, event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        pass


def run(source: str, max_frames: int = 0, max_seconds: float = 0.0,
        stats_json: str | None = None, stats_interval: float = 1.0) -> int:
    """真实运行会话（阻塞直到窗口关闭 / ExitGame / --frames / --seconds 触发）。

    max_seconds: 墙钟时长上限（毫秒级精度到逻辑循环）—— 性能统计用这个，
                 不要用 max_frames（内联逻辑循环不受 vsync 限制）。
    stats_json:  非空时挂载 `PerfStatsLayer`，结束时把帧时间分布 / 卡顿 / CPU /
                 内存写成 JSON（同时写 `<path>.jsonl` 采样趋势）。
    """
    session = prepare_offline(source)
    mode = resolve_window_mode(session)

    # ── 窗口标志（必须在 init 创建窗口前设置）──
    from Application.Runtime.RuntimeWindow import RuntimeWindow

    RuntimeWindow._window_title = session.title
    overlay = mode == "overlay"
    RuntimeWindow._transparent = overlay
    RuntimeWindow._topmost = overlay
    RuntimeWindow._click_through = overlay

    # ── 窗口模式（与 PIE 同语义: overlay → 固定无边框全屏, 标题栏隐藏）──
    RuntimeWindow.apply_start_preferences(
        mode, session.window_width, session.window_height, overlay=overlay)

    # ── 引擎初始化（创建窗口 + 渲染线程; 之后各自属性才可用）──
    from Application.Runtime.GameRuntime import GameRuntime

    GameRuntime.init()

    # ── 工程背景色 → 渲染器清屏色（overlay 保持透明; 命令首帧前消费）──
    if session.background_color is not None and not overlay:
        _rend = GameRuntime.get_renderer()
        if _rend is not None:
            from Application.Core.Renderer.RenderCommand import SetClearColorCommand
            _rend.enqueue(SetClearColorCommand(*session.background_color))

    # ── 资源 + 场景注入（顺序: init 之后 → renderer 可用）──
    activate_resources(session)
    scene = session.scene
    GameRuntime.scene.SyncFromScene(scene, clear_existing=True)
    # ★ 按 game_type 选择活跃摄像机（与 PIE 宿主同步一致）
    GameRuntime.scene.cam_mgr._apply(GameRuntime.scene)

    # ── 节点图层 + 基础层 ──
    layers = []
    if scene.node_graph is not None:
        from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer

        RuntimeNodeLayer.set_canvas(scene.node_graph)
        RuntimeNodeLayer.set_scene(scene.copy())   # 模板副本, 与 PIE 语义一致
        RuntimeNodeLayer.set_context_hooks(on_stop_request=None)  # 中立兜底退出
        layers.append(RuntimeNodeLayer)
        _report_missing_node_types(scene.node_graph)
    else:
        print("[Player] WARNING: startup scene has no node_graph — running visuals only")

    from Application.Runtime.RuntimeLayer import RuntimeLayer

    layers.append(RuntimeLayer)
    if overlay:
        from Application.Runtime.OverlayInputLayer import OverlayInputLayer

        layers.append(OverlayInputLayer)
    if max_frames > 0 or max_seconds > 0:
        _AutoExitLayer.configure(max_frames=max_frames, max_seconds=max_seconds)
        layers.append(_AutoExitLayer)

    # ── 成品性能统计（--stats-json）──
    #   必须在 GameRuntime.init() 之后 push（帧计时器已启动），且要在 run() 前
    if stats_json:
        from Application.Runtime.PerfStatsLayer import PerfStatsLayer

        PerfStatsLayer.configure(stats_json, stats_interval, engine=GameRuntime)
        layers.append(PerfStatsLayer)
        # ★ 分相默认跟随 `MGE_PROFILE`；但用户既然要 stats-json，就说明他在
        #   诊断性能 —— 整帧数字回答不了"时间花在哪"，所以这里直接打开分相。
        try:
            GameRuntime._get_profiler().phases.set_enabled(True)
        except Exception:      # noqa: BLE001 — 统计不得阻断启动
            pass
        print(f"[Player] perf stats → {stats_json} (phase profiling on)")

    # ★ 输入层最后 push（栈顶）— 与 PIE 顺序一致。
    from Application.Runtime.RuntimeInputLayer import RuntimeInputLayer

    layers.append(RuntimeInputLayer)

    # ── 运行时 UI（ESC → 退出确认；成品默认英文，game.json 后续可覆盖）──
    from Application.Runtime.RuntimeUILayer import RuntimeUILayer

    RuntimeUILayer.configure()
    layers.append(RuntimeUILayer)

    for layer in layers:
        GameRuntime.push_layer(layer)

    # ── 数据输出目录（创建但本阶段不改变 CWD — builtin 资源依赖工作目录）──
    try:
        os.makedirs(session.output_dir, exist_ok=True)
    except OSError as e:
        print(f"[Player] WARNING: cannot create output dir: {e}")

    # ── 阻塞运行 ──
    print(f"[Player] Starting '{session.title}' ({mode}) — {os.path.basename(session.scene_path)}")
    GameRuntime.run()
    print("[Player] Session ended")

    # ── 收尾: 设备 I/O 线程 + EEG 会话安全网（与 GameRuntime.stop 语义一致）──
    try:
        # 成品退出 = 进程结束: 释放全部租约（编辑器面板/调试残留一起清）
        from Application.Functions.SerialParallelDevice import stop_all as spd_stop_all

        spd_stop_all()
    except Exception:
        pass
    try:
        from Application.Functions.VirtualDevice import close_all

        _closed = close_all()
        if _closed:
            print(f"[Player] device safety: closed {_closed} leftover session(s)")
    except Exception:
        pass
    try:
        from Application.Functions.BCIAlgorithm import reset_all as epoch_reset

        epoch_reset()
    except Exception:
        pass
    return 0
