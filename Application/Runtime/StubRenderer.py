"""
StubRenderer — Runtime 用的占位渲染器（无真实 GPU 资源）。

在 PIE/开发阶段替代真正的渲染器，
不创建任何 OpenGL/Vulkan 上下文。
"""

from Application.Core.Renderer.Renderer import Renderer


class StubRenderer(Renderer):
    """占位渲染器 — 所有方法空实现，不分配 GPU 资源。"""

    viewport_width: int = 1
    viewport_height: int = 1
    aspect_ratio: float = 1.0

    @classmethod
    def Create(cls):
        print("[StubRenderer] Create (stub)")
        return cls

    @classmethod
    def StartFrame(cls):
        # 跳过命令队列消费 + _do_start_frame
        pass

    @classmethod
    def _do_start_frame(cls):
        pass

    @classmethod
    def EndFrame(cls):
        pass

    @classmethod
    def pick_at(cls, x: int, y: int):
        return (None, None)
