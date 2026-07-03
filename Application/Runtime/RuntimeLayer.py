"""
RuntimeLayer — 游戏运行时专用 Layer（空转桩）。

当前阶段只做空循环，不涉及任何渲染资源。
后续在此添加游戏逻辑的 OnUpdate / OnRender。
"""

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import LayerLifecycleEvent


class RuntimeLayer(Layer):
    """Runtime 层 — 占位，后续加入真正的游戏逻辑。"""

    @classmethod
    def OnAttach(cls):
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="attach", engine=cls._engine
        )

    @classmethod
    def OnDetach(cls):
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="detach", engine=cls._engine
        )

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        pass
