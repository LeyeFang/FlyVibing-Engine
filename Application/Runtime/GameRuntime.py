"""
GameRuntime — 游戏运行时（Engine 子类）。

两种启动模式:
  start() — 非阻塞 (PIE)
             逻辑跑在独立线程，编辑器控制生命周期。
  run()   — 阻塞 (导出/独立运行)
             逻辑跑在主线程。

生命周期控制 (PIE):
  Editor → GameRuntime.start()
         → GameRuntime.stop()   (设置 run_state = False)
         → GameRuntime.is_running()
"""

from __future__ import annotations

from typing import Union

from Application.Core.Engine import Engine, RendererType, WindowType


class GameRuntime(Engine):
    """游戏运行时 — 可被编辑器管理（PIE）或独立运行（导出）。"""

    # ════════════════════════════════════════════════════════════
    # 工厂方法（暂为空实现）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls):
        """创建运行时窗口 — 当前使用 StubWindow 占位。"""
        from Application.Runtime.StubWindow import StubWindow
        StubWindow.Create()
        return StubWindow

    @classmethod
    def _create_renderer(cls):
        """创建运行时渲染器 — 当前使用 StubRenderer 占位。"""
        from Application.Runtime.StubRenderer import StubRenderer
        StubRenderer.Create()
        return StubRenderer

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def start(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> 'GameRuntime':
        """非阻塞启动 (PIE 模式)。

        逻辑循环跑在独立后台线程，立即返回。
        编辑器通过 stop() 或设置 run_state=False 停止 Runtime。
        """
        cls._state()['_logic_thread_enabled'] = True
        cls.init(window_type=window_type, renderer_type=renderer_type)
        print(f"[GameRuntime] Started in PIE mode (logic thread)")
        return cls

    @classmethod
    def run(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> None:
        """阻塞启动 (导出模式)。

        逻辑循环跑在调用线程，直到窗口关闭或 stop() 被调用。
        """
        cls.init(window_type=window_type, renderer_type=renderer_type)
        print(f"[GameRuntime] Started in export mode (inline)")
        super().run()

    # ════════════════════════════════════════════════════════════
    # 控制接口 (PIE)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def stop(cls) -> None:
        """请求停止 Runtime 并清理状态，允许再次 start()。"""
        cls.run_state = False
        # 等待线程退出
        cls._join_threads()
        # 清理窗口
        if cls.window is not None:
            try:
                cls.window.Therminate()
            except Exception:
                pass
        # 重置初始化标记，允许再次 start()
        cls._state()['_initialized'] = False
        cls._state()['_logic_thread_enabled'] = False
        # 清理层栈
        cls._state()['layer_stack'].clear()
        # 清除类变量引用
        cls.window = None
        cls.renderer = None
        cls.renderer_thread = None
        cls._logic_thread = None
        print(f"[GameRuntime] Stopped and cleaned up")

    @classmethod
    def is_running(cls) -> bool:
        """Runtime 是否仍在运行。"""
        if not cls.run_state:
            return False
        r = cls.renderer_thread
        l = cls._logic_thread
        return (r is not None and r.is_alive()) or (l is not None and l.is_alive())
