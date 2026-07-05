"""
GameRuntime — 游戏运行时（Engine 子类）。

两种启动模式:
  start() — 非阻塞 (PIE)
             逻辑跑在独立线程，编辑器控制生命周期。
  run()   — 阻塞 (导出/独立运行)
             逻辑跑在主线程。
"""

from __future__ import annotations

from typing import Union

from Application.Core.Engine import Engine, RendererType, WindowType
from Application.Core.Events.EngineEvent import EngineLifecycleEvent
from Application.Core.Window.Window import Window
from Application.Core.Renderer.Renderer import Renderer


class GameRuntime(Engine):
    """游戏运行时 — 可被编辑器管理（PIE）或独立运行（导出）。"""

    # ════════════════════════════════════════════════════════════
    # 工厂方法
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls) -> Window:
        """创建运行时窗口 — 独立的 GLFW 子窗口 (OpenGL 上下文)。"""
        from Application.Runtime.RuntimeWindow import RuntimeWindow
        RuntimeWindow.Create()
        return RuntimeWindow

    @classmethod
    def _create_renderer(cls) -> Renderer:
        """创建运行时渲染器 — 根据 cls.renderer_type 选择后端。"""
        cls.window.MakeContextCurrent()
        renderer_cls = cls._get_renderer_class(cls.renderer_type)
        renderer = renderer_cls.Create(window=cls.window)
        return renderer

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def start(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> 'GameRuntime':
        """非阻塞启动 (PIE 模式)。"""
        cls._state()['_logic_thread_enabled'] = True
        cls.init(window_type=window_type, renderer_type=renderer_type)
        EngineLifecycleEvent.Pack(stage="start", message="Started in PIE mode", engine=cls)
        return cls

    @classmethod
    def run(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> None:
        """阻塞启动 (导出模式)。"""
        cls.init(window_type=window_type, renderer_type=renderer_type)
        EngineLifecycleEvent.Pack(stage="start", message="Started in export mode", engine=cls)
        super().run()

    # ════════════════════════════════════════════════════════════
    # 控制接口 (PIE)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def stop(cls) -> None:
        """请求停止 Runtime 并清理状态，允许再次 start()。"""
        # 必须在 run_state=False 之前派发事件 —
        # 否则渲染线程的 finally 块会先清空 layer_stack，DebugLayer 收不到事件。
        EngineLifecycleEvent.Pack(stage="stop", message="Stopped and cleaned up", engine=cls)
        cls.run_state = False
        cls._join_threads()
        if cls.window is not None:
            try:
                cls.window.Therminate()
            except Exception:
                pass
        cls._state()['_initialized'] = False
        cls._state()['_logic_thread_enabled'] = False
        cls._state()['layer_stack'].clear()
        cls.window = None
        cls.renderer = None
        cls.renderer_thread = None
        cls._logic_thread = None

    @classmethod
    def is_running(cls) -> bool:
        """Runtime 是否仍在运行。"""
        if not cls.run_state:
            return False
        r = cls.renderer_thread
        l = cls._logic_thread
        return (r is not None and r.is_alive()) or (l is not None and l.is_alive())
