from Application.Core.Layers.Layer import Layer
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from Application.Core.Timer.Timer import GetRunTime
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import *

from Application.Editor.EditorCamera import EditorCamera

mask_events = [
    MouseGragEvent,
    SceneCameraUpdateEvent
]


class DebugLayer(Layer):
    @classmethod
    def OnAttach(
        cls
    ):
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
            position_xyz=(-10, 0, -50),
            scale_xyz=(8, 8, 8))
        SceneManager.SetEntityTexture(
            cls.entity_id_1,
            tex_id)       # ★ 绑定棋盘格纹理
        # Entity 2 SSVEP
        cls.entity_id_2 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_2,
            component_instance=MeshRenderer(mesh_id=square_mesh_id))
        SceneManager.SetEntityTransform(
            cls.entity_id_2,
            position_xyz=(10, 0, -50),
            scale_xyz=(5, 5, 5))
        SceneManager.SetEntityShader(
            cls.entity_id_2,
            ssvep_shader_id
        )
        SceneManager.SetMaterialParams(
            cls.entity_id_2,
            {"freq": 60}
        )
        # Camera — EditorCamera 已内置默认轨道参数 (target 0,0,-50 / dist 47 / yaw π)
        # 首次 SceneCameraUpdateEvent 确保 Renderer 缓存正确的初始矩阵
        SceneCameraUpdateEvent.Pack()

    @classmethod
    def OnEvent(
        cls,
        event
    ):
        global mask_events
        if event not in mask_events:
            print(f"Time: {GetRunTime():.4f}, Event: {event}")
        pass

    @classmethod
    def OnRender(
        cls
    ):
        run_time = GetRunTime()
        SceneManager.SetMaterialParams(
            cls.entity_id_2,
            {'time': run_time})
