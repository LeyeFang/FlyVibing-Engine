"""
RuntimeDebugLayer — 游戏运行时调试层。

职责:
  - 按 **Debug ▸ Terminal 配置**（`DebugReportConfig`）上报事件
  - 勾选的事件类型打印；未勾选（高频鼠标/相机/统计等）直接放过、不 consume
  - WindowCloseEvent 只打印、不 consume，交给 Engine 尊重 consumed 做退出决策
"""

from Application.Core.Diagnostics.DebugEvents import DebugReportConfig
from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import LayerLifecycleEvent
from Application.Core.Events.WindowEvent import WindowCloseEvent


class RuntimeDebugLayer(Layer):
    """Runtime 调试层 — 事件日志（事件类型白名单由设置控制）。"""

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
        if not DebugReportConfig.should_report(event):
            return
        print(event)
        # 防止 Engine._on_event 兜底重复打印；但关闭事件必须继续向上传递，
        # 否则 Engine 无法根据 consumed 决定是否退出（ESC/弹窗策略）。
        if not isinstance(event, WindowCloseEvent):
            event.consume()

    @classmethod
    def OnRender(cls):
        pass
