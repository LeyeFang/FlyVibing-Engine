"""
RuntimeDebugLayer — 游戏运行时调试层（空桩）。

当前阶段只做空循环，后续可在此添加运行时调试输出。
"""

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event


class RuntimeDebugLayer(Layer):
    """Runtime 调试层 — 占位。"""

    @classmethod
    def OnAttach(cls):
        print("[RuntimeDebugLayer] OnAttach")

    @classmethod
    def OnDetach(cls):
        print("[RuntimeDebugLayer] OnDetach")

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        print(event)

    @classmethod
    def OnRender(cls):
        pass
