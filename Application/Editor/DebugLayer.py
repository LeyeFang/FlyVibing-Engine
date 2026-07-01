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

mask_events = [
    MouseMoveEvent,
    MouseGragEvent,
    MouseButtonEvent,
    SceneCameraUpdateEvent,
]


class DebugLayer(Layer):
    """编辑器调试层 — 场景实体 + 事件日志。"""

    @classmethod
    def OnAttach(cls):
        from Application.Editor.EditorHost import EditorHost
        square_mesh_id = ResourceManager.GetDefaultMesh("Square")
        cube_mesh_id = ResourceManager.GetDefaultMesh("Cube")
        tex_id = ResourceManager.GetDefaultTexture('Checkerboard')
        ssvep_shader_id = ResourceManager.GetDefaultShader("SSVEP")
        # Entity 1 Cube
        cls.entity_id_1 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_1,
            component_instance=MeshRenderer(mesh_id=cube_mesh_id))
        SceneManager.SetEntityTransform(
            cls.entity_id_1,
            position_xyz=(-3, 0, 0),
            scale_xyz=(1, 1, 1))
        SceneManager.SetEntityTexture(
            cls.entity_id_1,
            tex_id)
        # Entity 2 SSVEP
        cls.entity_id_2 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_2,
            component_instance=MeshRenderer(mesh_id=square_mesh_id))
        SceneManager.SetEntityTransform(
            cls.entity_id_2,
            position_xyz=(3, 0, 0),
            scale_xyz=(1, 1, 1))
        SceneManager.SetEntityShader(
            cls.entity_id_2,
            ssvep_shader_id)
        SceneManager.SetMaterialParams(
            cls.entity_id_2,
            {"freq": 15})
        # 通知渲染器刷新相机矩阵
        SceneCameraUpdateEvent.Pack(engine=EditorHost)

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        if type(event) not in mask_events:
            print(event)

    @classmethod
    def OnRender(cls) -> None:
        run_time = GetRunTime()
        SceneManager.SetMaterialParams(
            cls.entity_id_2,
            {'time': run_time})

    @classmethod
    def OnUpdate(cls) -> None:
        pass
