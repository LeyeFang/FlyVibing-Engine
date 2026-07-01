"""
StubWindow — Runtime 用的占位窗口（无真实窗口）。

在 PIE/开发阶段替代真正的 RuntimeWindow，
不创建任何 GLFW 窗口或图形上下文。
"""

from Application.Core.Window.Window import Window


class StubWindow(Window):
    """占位窗口 — 所有方法空实现，不创建真实窗口。"""

    @classmethod
    def Create(cls):
        print("[StubWindow] Create (stub)")
        return cls

    @classmethod
    def Update(cls):
        pass

    @classmethod
    def GetSize(cls) -> tuple[int, int]:
        return (1, 1)

    @classmethod
    def SwapBuffer(cls):
        pass

    @classmethod
    def MakeContextCurrent(cls):
        pass

    @classmethod
    def OnEvent(cls, event):
        pass

    @classmethod
    def Therminate(cls):
        print("[StubWindow] Therminate (stub)")
