"""
RuntimeWindow — 游戏运行时窗口，继承自 glfwWindow。

职责:
  - 创建独立的 GLFW 窗口 (OpenGL 上下文)，PIE 模式下作为独立子窗口
  - 提供 SwapBuffer / MakeContextCurrent 等 GL 操作
  - Therminate 仅销毁自身窗口，不终止 GLFW（编辑器窗口仍需 GLFW）

与 EditorWindow 的区别:
  EditorWindow — 编辑器主窗口，Therminate 会调用 glfw.terminate()
  RuntimeWindow — PIE 子窗口，Therminate 只销毁自己，保留 GLFW 给编辑器
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine

from Application.Core.Window.glfwWindow import glfwWindow
from Application.Core.Events.Event import Event

import glfw


class RuntimeWindow(glfwWindow):
    """游戏运行时窗口 — GLFW + OpenGL 上下文。

    PIE 模式下作为编辑器窗口之外的独立子窗口。
    导出模式下作为主窗口运行。
    """

    _window_title: str = "Game (PIE)"

    # ════════════════════════════════════════════════════════════
    # 窗口生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(cls) -> 'RuntimeWindow':
        """创建运行时窗口 (OpenGL 上下文)。"""
        super().Create()
        # 设置运行时专属标题
        if cls.glfw_window is not None:
            glfw.set_window_title(cls.glfw_window, cls._window_title)
        return cls

    # ════════════════════════════════════════════════════════════
    # GL 特化窗口操作
    # ════════════════════════════════════════════════════════════

    @classmethod
    def SwapBuffer(cls) -> None:
        glfw.swap_buffers(cls.glfw_window)

    @classmethod
    def MakeContextCurrent(cls) -> None:
        glfw.make_context_current(cls.glfw_window)

    # ════════════════════════════════════════════════════════════
    # OpenGL 上下文提示
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _set_window_hints(cls) -> None:
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    # ════════════════════════════════════════════════════════════
    # 点击穿透 — Overlay 模式通过 Pick 系统判定
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _is_click_through_target(cls, ndc_x: float, ndc_y: float) -> bool:
        """Overlay 模式: 光标下有渲染内容 → 捕获, 透明背景 → 穿透。"""
        try:
            from Application.Runtime.OverlayInputLayer import OverlayInputLayer
            return OverlayInputLayer.is_cursor_hit()
        except Exception:
            return True  # 保守: 全捕获

    # ════════════════════════════════════════════════════════════
    # 清理 — 仅销毁自身窗口，不调用 glfw.terminate()
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Therminate(cls):
        """销毁运行时窗口。

        仅销毁自身 GLFW 窗口，不调用 glfw.terminate() —
        编辑器窗口仍然需要 GLFW 处于初始化状态。
        """
        if cls.glfw_window is not None:
            glfw.destroy_window(cls.glfw_window)
            cls.glfw_window = None
        # 注意: 不调用 glfw.terminate()！

    # ════════════════════════════════════════════════════════════
    # 事件的空处理 (runtime 无需在窗口层消费事件)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass
