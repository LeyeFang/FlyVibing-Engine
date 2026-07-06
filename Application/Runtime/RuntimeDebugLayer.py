"""
RuntimeDebugLayer — 游戏运行时调试层。

职责:
  - 打印所有非高频事件，帮助调试 Runtime 事件流
  - 屏蔽高频事件（MouseMoveEvent, MouseGragEvent 等）避免刷屏
"""

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import LayerLifecycleEvent
from Application.Core.Events.InputEvent import (
    MouseMoveEvent, MouseGragEvent, MouseButtonEvent,
)
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent


# ── 静默事件: 这些事件频率太高，不打印 ──
_SILENT_EVENTS = (
    MouseMoveEvent,
    MouseGragEvent,
    SceneCameraUpdateEvent,
)


class RuntimeDebugLayer(Layer):
    """Runtime 调试层 — 事件日志。"""

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
        if not isinstance(event, _SILENT_EVENTS):
            print(event)
            event.consume()  # 防止 Engine._on_event 兜底重复打印

    @classmethod
    def OnRender(cls):
        pass
