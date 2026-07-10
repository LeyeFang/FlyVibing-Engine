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
    _pending_stop: bool = False

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
            return "Not running"

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
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Play requested (pending)", engine=EditorHost
        )

    @classmethod
    def _try_consume_start(cls) -> None:
        """主线程调用: 消费 _pending_start 标记，执行实际的 PIE 启动。"""
        if not cls._pending_start:
            return
        cls._pending_start = False

        from Application.Runtime.GameRuntime import GameRuntime

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
            runtime_scene = copy.deepcopy(editor_scene)
            RuntimeNodeLayer.set_scene(runtime_scene)
            print(f"[Simulation] Scene injected: {runtime_scene.name} "
                  f"({len(runtime_scene.entities)} entity templates)")
        else:
            print("[Simulation] WARNING: No active scene — EntitySpawn will have no templates")

        GameRuntime.push_layer(RuntimeLayer)
        GameRuntime.push_layer(RuntimeDebugLayer)
        # ── 统一后端: PIE 使用与编辑器相同的窗口/渲染器类型 ──
        #     若 EditorHost 未初始化 (如测试环境), 回退到 GLFW + OpenGL
        GameRuntime.start(
            window_type=EditorHost.window_type or WindowType.GLFW,
            renderer_type=EditorHost.renderer_type or RendererType.OpenGL
        )
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
        # ★ PIE 停止后切回 EditorHost 的 ECS 世界
        from Application.Core.Scene.SceneManager import SceneManager
        SceneManager.set_thread_active("EditorHost")
        cls._state = SimulationState.STOPPED
        EngineLifecycleEvent.Pack(
            stage="simulation", message="Runtime stopped", engine=EditorHost
        )


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SIMULATION
register(NAME_SIMULATION, SimulationController)
