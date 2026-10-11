"""
EditorDebugLayer — 编辑器调试层（原 Test/Helpers/DebugLayer）。

职责:
  - 创建两个调试实体（Cube + SSVEP 方片）
  - 打印非屏蔽事件（帮助调试事件流）
  - 更新 SSVEP 着色器时间参数
"""

from Application.Core.Layers.Layer import Layer
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from Application.Core.Timer.Timer import GetRunTime
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Events.StatsEvent import *
from Application.Core.Events.EngineEvent import EngineLifecycleEvent, LayerLifecycleEvent

mask_events = [
    MouseMoveEvent,
    MouseGragEvent,
    MouseButtonEvent,
    ScrollerEvent,
    SceneCameraUpdateEvent,
    PerformanceStatsEvent,
    KeyboardButtonEvent,
    ComponentModifiedEvent,
]


class DebugLayer(Layer):
    """编辑器调试层 — 场景实体 + 事件日志。"""

    @classmethod
    def OnAttach(cls):
        from Application.Editor.EditorHost import EditorHost

        # 通知渲染器刷新相机矩阵
        SceneCameraUpdateEvent.Pack(engine=EditorHost)

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        if type(event) not in mask_events:
            print(event)
            # 仅消费低频生命周期事件 (本层职责范围; 其它层不处理它们),
            # 防止 Engine._on_event 兜底重复打印; 普通事件不消费, 保证链上其它层正常接收。
            if isinstance(event, (EngineLifecycleEvent, LayerLifecycleEvent)):
                event.consume()

    @classmethod
    def OnRender(cls) -> None:
        pass

    @classmethod
    def OnUpdate(cls) -> None:
        pass

    @classmethod
    def OnDetach(cls) -> None:
        pass
