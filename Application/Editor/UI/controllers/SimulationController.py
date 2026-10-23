"""模拟状态机 — 统一管理 Run / Pause / Stop 状态"""
from enum import Enum, auto

from Application.Core.Engine import RendererType, WindowType
from Application.Core.Events.EngineEvent import EngineLifecycleEvent
from Application.Editor.EditorHost import EditorHost


class SimulationState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()


class SimulationController:
    """单例风格的模拟状态控制器 — 持有 GameRuntime 实例。"""

    _state: SimulationState = SimulationState.STOPPED
    _pending_start: bool = False
    # 上次 PIE 启动失败原因 (章 T M2: 显式错误态; sim.state 可查) — 成功启动时清空
    last_error: str = ""
    _pending_stop: bool = False

    # ── PIE 初始窗口偏好 (Play 下方 Settings 按钮; 持久化 Application/Editor/Config/PIE.json) ──
    _PIE_SETTINGS_PATH: str = "Application/Editor/Config/PIE.json"
    _PIE_MODES: tuple = ("windowed", "borderless", "fullscreen")
    _pie_mode: str = "windowed"
    _pie_width: int = 1280
    _pie_height: int = 720
    _pie_settings_loaded: bool = False

    @staticmethod
    def _clamp_pie_size(v, lo: int = 320, hi: int = 7680) -> int:
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return lo

    @classmethod
    def get_pie_settings(cls) -> dict:
        """PIE 窗口偏好 (懒加载 Config/PIE.json)。"""
        if not cls._pie_settings_loaded:
            cls._pie_settings_loaded = True
            try:
                import json
                with open(cls._PIE_SETTINGS_PATH, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                mode = str(data.get("mode", "windowed")).lower()
                if mode in cls._PIE_MODES:
                    cls._pie_mode = mode
                cls._pie_width = cls._clamp_pie_size(data.get("width", cls._pie_width))
                cls._pie_height = cls._clamp_pie_size(data.get("height", cls._pie_height))
            except Exception:  # noqa: BLE001 — 缺失/损坏→默认值
                pass
        return {"mode": cls._pie_mode, "width": cls._pie_width, "height": cls._pie_height}

    @classmethod
    def set_pie_settings(cls, mode: str | None = None, width=None, height=None) -> dict:
        """更新并持久化 PIE 窗口偏好; 返回最新的完整设置。"""
        cls.get_pie_settings()
        if mode is not None:
            m = str(mode).lower()
            if m in cls._PIE_MODES:
                cls._pie_mode = m
        if width is not None:
            cls._pie_width = cls._clamp_pie_size(width)
        if height is not None:
            cls._pie_height = cls._clamp_pie_size(height)
        try:
            import json, os
            os.makedirs(os.path.dirname(cls._PIE_SETTINGS_PATH) or ".", exist_ok=True)
            with open(cls._PIE_SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(cls.get_pie_settings(), fh, indent=2)
        except Exception as exc:  # noqa: BLE001
            print(f"[Simulation] PIE settings save failed: {exc}")
        return cls.get_pie_settings()

    @classmethod
    def _apply_pie_window_prefs(cls, game_type) -> None:
        """PIE 启动前: 应用窗口偏好到 RuntimeWindow (下次 Run 生效)。"""
        from Application.Runtime.RuntimeWindow import RuntimeWindow
        from Application.Core.Scene.Scene import GameType
        s = cls.get_pie_settings()
        mode = s["mode"]
        if game_type == GameType.OVERLAY and mode == "fullscreen":
            mode = "borderless"   # 独占全屏与透明 Overlay 不兼容 (glfwWindow 已警示)
            print("[Simulation] Overlay 模式不支持独占全屏 — 回退 borderless")
        RuntimeWindow.apply_start_preferences(mode, s["width"], s["height"])

    # ── 状态查询 ────────────────────────────────────────────

    @classmethod
    def is_running(cls) -> bool:
        return cls._state == SimulationState.RUNNING

    @classmethod
    def is_paused(cls) -> bool:
        return cls._state == SimulationState.PAUSED

    @classmethod
    def is_stopped(cls) -> bool:
        return cls._state == SimulationState.STOPPED

    @classmethod
    def get_state(cls) -> SimulationState:
        return cls._state

    @classmethod
    def get_state_label(cls) -> str:
        if cls._state == SimulationState.RUNNING:
            return "Running"
        elif cls._state == SimulationState.PAUSED:
            return "Paused"
        else:
            return "Stopped"

    # ── ECS → Scene 同步 ────────────────────────────────────

    @staticmethod
    def _sync_ecs_to_scene(scene, scene_mgr=None) -> None:
        """将 ECS 世界中的实体同步到 Scene.entities 注册表（PIE 模板来源）。

        白名单组件随模板进入运行时（EntitySpawn 实例化携带）:
        Transform / Camera / MeshRenderer / MediaPlayer / Light / TextDisplay。
        """
        import copy
        from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer, MediaPlayer, Light, TextDisplay
        from Application.Core.Scene.Scene import EntityData

        if scene_mgr is None:
            from Application.Core.Scene.SceneManager import SceneManager
            scene_mgr = SceneManager

        # ★ 场景环境光随模板同步 (光照帧状态来源; 协议: Doc/Dev/shader_protocol.md)
        scene.ambient_color = tuple(
            getattr(scene_mgr, 'ambient_color', (0.5, 0.5, 0.5)))
        # ★ 无灯回退开关同步 (无光源时满亮 — 避免默认变黑; shader_protocol §7.3)
        scene.lighting_fallback = bool(
            getattr(scene_mgr, 'lighting_fallback', True))

        _sys_ids = {
            scene_mgr.get_main_camera_id(),
            scene_mgr.get_main_camera_2d_id(),
        }

        scene.entities.clear()
        for eid, xform in [(e, c) for e, c in scene_mgr.GetAllEntitiesWithComponent(Transform)]:
            if eid in _sys_ids:
                continue
            name = scene_mgr.GetEntityName(eid)
            parent_id = scene_mgr.GetEntityParent(eid)  # ★ 保存层级关系到 Scene 模板
            comps = {"Transform": copy.deepcopy(xform)}
            try:
                cam = scene_mgr.GetComponent(eid, Camera)
                comps["Camera"] = copy.deepcopy(cam)
            except Exception:
                pass
            try:
                mr = scene_mgr.GetComponent(eid, MeshRenderer)
                comps["MeshRenderer"] = copy.deepcopy(mr)
            except Exception:
                pass
            try:
                mp = scene_mgr.GetComponent(eid, MediaPlayer)
                comps["MediaPlayer"] = copy.deepcopy(mp)
            except Exception:
                pass
            try:
                dl = scene_mgr.GetComponent(eid, Light)
                comps["Light"] = copy.deepcopy(dl)
            except Exception:
                pass
            try:
                td = scene_mgr.GetComponent(eid, TextDisplay)
                comps["TextDisplay"] = copy.deepcopy(td)
            except Exception:
                pass
            scene.entities[eid] = EntityData(name=name, components=comps, parent_id=parent_id)

    # ── 宿主桥接实现 (供 GameRuntime 回呼; 运行时侧无 Editor 依赖) ──

    @staticmethod
    def _sync_scene_to_runtime() -> None:
        """PIE 启动前: 从编辑器同步 game_type + 摄像机 + 渲染实体到 Runtime。

        (原 GameRuntime._sync_scene_from_editor — 解耦后归属编辑器侧,
         由 GameRuntime.set_host_bridge 在启动时回调)
        """
        import esper
        from Application.Core.Scene.BasicComponents import MeshRenderer
        from Application.Runtime.GameRuntime import GameRuntime
        from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer

        editor_scene = EditorHost.scene
        if editor_scene is None:
            return
        rt = GameRuntime.scene
        rt.game_type = editor_scene.game_type
        # ★ 同步默认摄像机 ID（Editor Init 创建的，Runtime 复用）
        rt.main_camera_id = editor_scene.main_camera_id
        rt.main_camera_2d_id = editor_scene.main_camera_2d_id
        rt.main_camera_overlay_id = editor_scene.main_camera_overlay_id
        # ★ 将摄像机实体注册到 Runtime 的 entities 追踪表
        for cam_id in (editor_scene.main_camera_id,
                       editor_scene.main_camera_2d_id,
                       editor_scene.main_camera_overlay_id):
            if cam_id is not None:
                with rt._entities_lock:
                    rt.entities[str(cam_id)] = 1
                    rt._entity_names[cam_id] = editor_scene._entity_names.get(cam_id, f"Camera_{cam_id}")
        # ★ 收集模板实体名称（EntitySpawn 用，不应被 EntityGet 找到）
        _template_names: set[str] = set()
        if RuntimeNodeLayer._scene is not None:
            for ed in RuntimeNodeLayer._scene.entities.values():
                _template_names.add(ed.name)
        # ★ 同步 MeshRenderer 实体到 Runtime（PIE 渲染需要）
        #    跳过模板实体 — 它们只是数据模板，真正的渲染实体由 EntitySpawn 创建
        mesh_count = 0
        skipped_templates = 0
        for eid, _ in esper.get_component(MeshRenderer):
            with rt._entities_lock:
                if str(eid) in rt.entities:
                    continue
                name = editor_scene._entity_names.get(eid, f"Entity_{eid}")
                if name in _template_names:
                    skipped_templates += 1
                    continue  # 模板实体：只做数据参考，不参与运行时渲染
                rt.entities[str(eid)] = 1
                rt._entity_names[eid] = name
                mesh_count += 1
        # ★ 根据 game_type 选择活跃摄像机
        rt.cam_mgr._apply(rt)
        print(f"[Simulation] Synced from editor: game_type={editor_scene.game_type.value}, "
              f"camera_id={rt.scene_camera_id}, mesh_entities={mesh_count}"
              f"{f' (skipped {skipped_templates} templates)' if skipped_templates else ''}")

    @staticmethod
    def _protected_runtime_entities() -> set[str]:
        """停止 Runtime 时保留的实体（编辑器拥有的摄像机等）。"""
        if EditorHost.scene is None:
            return set()
        return set(EditorHost.scene.entities.keys())

    # ── 状态变更 ────────────────────────────────────────────

    @classmethod
    def play(cls) -> None:
        """▶ 请求启动模拟（由渲染线程 ImGui 回调触发）。

        不直接创建 Runtime 窗口，改为设置 _pending_start 标记。
        主线程在 EditorLayer.OnUpdate() 中消费此标记，
        确保 RuntimeWindow 由主线程创建（GLFW 线程亲和性要求）。
        """
        if cls._state != SimulationState.STOPPED:
            return
        cls._pending_start = True
        cls.last_error = ""
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Play requested (pending)", engine=EditorHost
        )

    @classmethod
    def _try_consume_start(cls) -> None:
        """主线程调用: 消费 _pending_start 标记，执行实际的 PIE 启动。"""
        if not cls._pending_start:
            return
        cls._pending_start = False

        from Application.Runtime.GameRuntime import GameRuntime, RuntimeHostBridge

        # 防止重复启动
        if cls._state != SimulationState.STOPPED:
            return

        from Application.Runtime.RuntimeLayer import RuntimeLayer
        from Application.Runtime.RuntimeDebugLayer import RuntimeDebugLayer
        from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer

        # ── 注入节点图 (若有) ──
        from Application.Editor.UI.UIManager import UIManager
        ne_panel = UIManager.find("Node Editor")
        if ne_panel is not None and ne_panel._canvas is not None:
            RuntimeNodeLayer.set_canvas(ne_panel._canvas)
            GameRuntime.push_layer(RuntimeNodeLayer)
            print("[Simulation] Node graph injected for PIE")

        # ── 注入 Scene (EntitySpawn 模板来源) ──
        from Application.Core.Scene.Scene import Scene
        import copy
        editor_scene = EditorHost.get_active_scene()
        if editor_scene is not None:
            # ★ 先将 ECS 中的实体同步到 Scene.entities 注册表
            cls._sync_ecs_to_scene(editor_scene, EditorHost.scene)
            runtime_scene = copy.deepcopy(editor_scene)
            RuntimeNodeLayer.set_scene(runtime_scene)
            print(f"[Simulation] Scene injected: {runtime_scene.name} "
                  f"({len(runtime_scene.entities)} entity templates)")
        else:
            print("[Simulation] WARNING: No active scene — EntitySpawn will have no templates")

        GameRuntime.push_layer(RuntimeLayer)
        GameRuntime.push_layer(RuntimeDebugLayer)

        # ── 根据场景 GameType 设置窗口模式 ──
        # ★ 从 SceneManager 读取 game_type（与 ScenePanel 的 set_game_type 同源）
        from Application.Runtime.RuntimeWindow import RuntimeWindow
        from Application.Core.Scene.Scene import GameType
        gt = EditorHost.scene.game_type if EditorHost.scene else GameType.GAME_3D
        if gt == GameType.OVERLAY:
            RuntimeWindow._transparent = True
            RuntimeWindow._topmost = True
            RuntimeWindow._click_through = True  # OverlayInputLayer 提供命中判定
            from Application.Runtime.OverlayInputLayer import OverlayInputLayer
            GameRuntime.push_layer(OverlayInputLayer)
            print(f"[Simulation] Window mode: OVERLAY (transparent + topmost + click-through)")
        else:
            RuntimeWindow._transparent = False
            RuntimeWindow._topmost = False
            RuntimeWindow._click_through = False

        # ── 应用 PIE 窗口偏好 (Play 下方 Settings: 全屏 / 窗口化尺寸) ──
        cls._apply_pie_window_prefs(gt)

        # ── 工程背景色 → PIE 清屏色 (Overlay 保持透明; 经 RuntimeHostBridge 注入) ──
        _clear_color = None
        if gt != GameType.OVERLAY:
            try:
                from Application.Editor.ProjectManager import ProjectManager
                _bg = ProjectManager.background_color()
                _clear_color = (float(_bg[0]), float(_bg[1]), float(_bg[2]), 1.0)
            except Exception:  # noqa: BLE001 — 无工程上下文 → 用渲染器默认清屏色
                _clear_color = None

        # ── 注册运行时宿主桥接 + 上下文钩子 (运行时对 Editor 零反向依赖) ──
        RuntimeNodeLayer.set_context_hooks(on_stop_request=cls.stop)
        GameRuntime.set_host_bridge(RuntimeHostBridge(
            frame_sync=EditorHost._frame_sync,
            sync_scene_from_host=cls._sync_scene_to_runtime,
            protected_entity_ids=cls._protected_runtime_entities,
            clear_color=_clear_color,
        ))

        # ── 统一后端: PIE 使用与编辑器相同的窗口/渲染器类型 ──
        #     若 EditorHost 未初始化 (如测试环境), 回退到 GLFW + OpenGL
        try:
            # READY 屏障在 GameRuntime.start 内等待 (层挂载/内容注册完成才算启动)
            GameRuntime.start(
                window_type=EditorHost.window_type or WindowType.GLFW,
                renderer_type=EditorHost.renderer_type or RendererType.OpenGL
            )
        except Exception as e:
            # ★ 章 T M2: 显式错误态 — 不再静默"启动但没内容"
            cls.last_error = f"{type(e).__name__}: {e}"
            cls._state = SimulationState.STOPPED
            GameRuntime.clear_host_bridge()
            EngineLifecycleEvent.Pack(
                stage="exception",
                message=f"PIE start FAILED: {cls.last_error}",
                engine=EditorHost,
            )
            import traceback as _tb
            _tb.print_exc()
            print(f"[Simulation] PIE start failed — state=Stopped ({cls.last_error})")
            return
        # ★ PIE 启动完成 (层已挂载 — READY 屏障已过)
        cls._state = SimulationState.RUNNING
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Runtime started", engine=EditorHost
        )

    @classmethod
    def pause(cls) -> None:
        if cls._state == SimulationState.RUNNING:
            cls._state = SimulationState.PAUSED

    @classmethod
    def resume(cls) -> None:
        if cls._state == SimulationState.PAUSED:
            cls._state = SimulationState.RUNNING

    @classmethod
    def stop(cls) -> None:
        """■ 请求停止模拟（由渲染线程 ImGui 回调触发）。

        不直接销毁 Runtime 窗口，改为设置 _pending_stop 标记。
        主线程在 EditorLayer.OnUpdate() 中消费此标记，
        确保 glfw.destroy_window() 在创建线程执行（GLFW 线程亲和性）。
        """
        if cls._state == SimulationState.STOPPED:
            return
        cls._pending_stop = True
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Stop requested (pending)", engine=EditorHost
        )

    @classmethod
    def _try_consume_stop(cls) -> None:
        """主线程调用: 消费 _pending_stop 标记，执行实际的窗口销毁。"""
        if not cls._pending_stop:
            return
        cls._pending_stop = False

        from Application.Runtime.GameRuntime import GameRuntime
        GameRuntime.stop()
        GameRuntime.clear_host_bridge()
        cls._state = SimulationState.STOPPED
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Runtime stopped", engine=EditorHost
        )


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SIMULATION
register(NAME_SIMULATION, SimulationController)
