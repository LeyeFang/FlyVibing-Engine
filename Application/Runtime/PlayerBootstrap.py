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
    window_mode: str = "auto"        # auto | windowed | fullscreen | overlay
    output_dir: str = ""             # 数据输出目录（默认 <包根>/output）
    root: str = ""                   # bundle 根（= game.json 所在目录; 无则 CWD）
    warnings: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────
# 解析（不依赖引擎初始化）
# ────────────────────────────────────────────────────────────────


def prepare_offline(source: str) -> PlayerSession:
    """解析输入路径 → PlayerSession（加载工程元数据与场景数据, 不加载资源）。"""
    abs_source = os.path.abspath(source)
    if not os.path.isfile(abs_source):
        raise FileNotFoundError(f"入口不存在: {abs_source}")

    ext = os.path.splitext(abs_source)[1].lower()
    if ext == ".json":
        return _prepare_from_game_json(abs_source)
    if ext == ".myproj":
        return _prepare_from_project(abs_source, root=os.path.dirname(abs_source))
    if ext == ".scene":
        return _prepare_from_scene(abs_source, root=os.path.dirname(abs_source))
    raise ValueError(f"不支持的入口类型: {source}（期望 game.json / .myproj / .scene）")


def _prepare_from_game_json(path: str) -> PlayerSession:
    root = os.path.dirname(path)
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"game.json 格式错误: {path}")

    s = PlayerSession(
        source=path,
        source_kind="game",
        root=root,
        title=cfg.get("title") or os.path.splitext(os.path.basename(root))[0],
        window_mode=(cfg.get("window") or {}).get("mode", "auto"),
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


def dry_run(source: str, frames: int = 0, verbose: bool = False) -> int:
    """无头自检: 工程/场景加载 + 静态校验 (+ 可选假时间干跑)。

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

    # ── 2. 原始场景 JSON → 静态校验 + 干跑（MCP 链路; 校验器缺失时降级）──
    try:
        import Utils.NodeEditor.node_graph_validator as validator  # 延迟导入（仅干跑需要）
    except ModuleNotFoundError:
        validator = None

    if validator is None:
        print("[Player] NOTE: node_graph_validator not available — graph validation skipped")
    else:
        with open(session.scene_path, "r", encoding="utf-8") as fh:
            scene_json = json.load(fh)

        static_errors = validator.validate_static(scene_json)
        if static_errors:
            failures += len(static_errors)
            print(f"[Player] Static validation: {len(static_errors)} error(s)")
            for e in static_errors:
                print(f"  ✗ {e}")
        else:
            print("[Player] Static validation: PASSED")

        if frames > 0:
            result = validator.dry_run_simulation(scene_json, max_frames=frames, verbose=verbose)
            errors = result.get("errors") or []
            if errors:
                failures += len(errors)
                print(f"[Player] Dry-run: {len(errors)} error(s)")
                for e in errors:
                    print(f"  ✗ {e}")
            else:
                print(
                    f"[Player] Dry-run: {result.get('frames_simulated', 0)} frames, "
                    f"{result.get('total_events', 0)} side-effect events"
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


class _AutoExitLayer(Layer):
    """--frames N 支撑层: N 次 OnUpdate 后请求退出（冒烟/CI 用）。"""

    _count = 0
    _max_frames = 0

    @classmethod
    def OnAttach(cls):
        pass

    @classmethod
    def OnDetach(cls):
        pass

    @classmethod
    def OnUpdate(cls):
        cls._count += 1
        if cls._max_frames and cls._count >= cls._max_frames:
            from Application.Runtime.GameRuntime import GameRuntime

            print(f"[Player] --frames {cls._max_frames} reached — exiting")
            GameRuntime.run_state = False

    @classmethod
    def OnEvent(cls, event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        pass


def run(source: str, max_frames: int = 0) -> int:
    """真实运行会话（阻塞直到窗口关闭 / ExitGame / --frames 触发）。"""
    session = prepare_offline(source)
    mode = resolve_window_mode(session)

    # ── 窗口标志（必须在 init 创建窗口前设置）──
    from Application.Runtime.RuntimeWindow import RuntimeWindow

    RuntimeWindow._window_title = session.title
    overlay = mode == "overlay"
    RuntimeWindow._transparent = overlay
    RuntimeWindow._topmost = overlay
    RuntimeWindow._click_through = overlay

    # ── 引擎初始化（创建窗口 + 渲染线程; 之后各自属性才可用）──
    from Application.Runtime.GameRuntime import GameRuntime

    GameRuntime.init()

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
    else:
        print("[Player] WARNING: startup scene has no node_graph — running visuals only")

    from Application.Runtime.RuntimeLayer import RuntimeLayer

    layers.append(RuntimeLayer)
    if overlay:
        from Application.Runtime.OverlayInputLayer import OverlayInputLayer

        layers.append(OverlayInputLayer)
    if max_frames > 0:
        _AutoExitLayer._max_frames = max_frames
        layers.append(_AutoExitLayer)

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
        from Application.Functions.SerialParallelDevice import stop as spd_stop

        spd_stop()
    except Exception:
        pass
    try:
        from Application.Functions.EEGDevice import close_all as gtec_close_all

        _closed = gtec_close_all()
        if _closed:
            print(f"[Player] Gtec safety: closed {_closed} leftover session(s)")
    except Exception:
        pass
    return 0
