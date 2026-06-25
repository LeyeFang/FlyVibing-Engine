"""
EditorWindow — 编辑器主窗口，继承自 glfwWindow，专用于 OpenGL (ModernGL) 后端。

职责:
  - 继承 GLFW 窗口的创建、输入回调、轮询等基础能力
  - 提供 GL 特化的窗口操作: OpenGL 上下文创建、SwapBuffer、MakeContextCurrent
  - 未来与 PreviewRuntimeWindow (Vulkan 后端) 分离，各自管理不同图形后端

与 glfwWindow 的关系:
  glfwWindow         — 纯窗口抽象 (创建、轮询、回调、销毁)，不含任何图形API特化
  EditorWindow       — OpenGL 窗口 (继承 glfwWindow + GL上下文管理)
  PreviewRuntimeWindow — Vulkan 窗口 (继承 glfwWindow + Vulkan Surface管理) [未来]
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine

from Application.Core.Window.glfwWindow import glfwWindow
from Application.Core.Events.Event import Event

import glfw


class EditorWindow(glfwWindow):
    """编辑器窗口 — 基于 GLFW + OpenGL 上下文。

    Class-level 属性:
        glfw_window : GLFW 窗口句柄 (继承自 glfwWindow)
    """

    # ════════════════════════════════════════════════════════════
    # 窗口生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls
    ) -> 'EditorWindow':
        """创建编辑器窗口 (OpenGL 上下文)。

        委托父类 glfwWindow.Create 完成 GLFW 初始化、
        窗口创建 (通过 _set_window_hints 注入 OpenGL hints) 和输入回调注册。
        """
        super().Create()
        return cls

    # ════════════════════════════════════════════════════════════
    # GL 特化窗口操作
    # ════════════════════════════════════════════════════════════

    @classmethod
    def SwapBuffer(cls) -> None:
        """交换前后缓冲区 — OpenGL 专用。

        将渲染结果呈现到窗口表面。
        Vulkan 后端不需要此操作 (由 Vulkan SwapChain 管理)。
        """
        glfw.swap_buffers(cls.glfw_window)

    @classmethod
    def MakeContextCurrent(cls) -> None:
        """绑定 OpenGL 上下文到当前线程 — OpenGL 专用。

        渲染线程启动时必须调用，确保后续 GL 调用作用于正确的上下文。
        Vulkan 后端不需要此操作。
        """
        glfw.make_context_current(cls.glfw_window)

    # ════════════════════════════════════════════════════════════
    # 内部钩子: 设置 OpenGL 上下文
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _set_window_hints(
        cls,
    ) -> None:
        """设置 OpenGL 4 核心模式上下文提示。
        在 glfw.create_window 之前由父类 _create_window 调用。
        """
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    # ════════════════════════════════════════════════════════════
    # 事件处理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        """处理编辑器窗口事件。

        当前处理:
          - RendererMeshReleaseEvent: 渲染器网格释放事件
        """
        pass
