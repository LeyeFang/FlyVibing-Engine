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

    @classmethod
    def OnRender(cls) -> None:
        run_time = GetRunTime()
        # 仅在 entity 的 material 支持 'time' 参数时才设置
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            from Application.Core.Scene.BasicComponents import MeshRenderer
            mr = EditorHost.scene.GetComponent(cls.entity_id_2, MeshRenderer)
            from Application.Resource.ResourceManager import ResourceManager
            mat = ResourceManager.GetMaterial(mr.material_id)
            if mat and 'time' in mat.uniforms_data:
                EditorHost.scene.SetMaterialParams(
                    cls.entity_id_2, {'time': run_time})
        except Exception:
            pass

    @classmethod
    def OnUpdate(cls) -> None:
        pass

    @classmethod
    def OnDetach(cls) -> None:
        pass
