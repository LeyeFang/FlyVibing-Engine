from Application.Layers.Layer import Layer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import MeshRenderer
from Application.Timer.Timer import GetRunTime


class DebugLayer(Layer):
    @classmethod
    def OnAttach(
        cls,
        app
    ):
        mesh_id = ResourceManager.GetDefaultModel("Square")
        cls.entity_id_1 = SceneManager.AddEntity()
        cls.entity_id_2 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_1,
            component_instance=MeshRenderer(mesh_id=mesh_id))
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_2,
            component_instance=MeshRenderer(mesh_id=mesh_id))
        SceneManager.SetEntityTransfrom(
            cls.entity_id_1,
            position_xyz=(-10, 0, -50),
            scale_xyz=(5, 5, 5))
        SceneManager.SetEntityTransfrom(
            cls.entity_id_2,
            position_xyz=(10, 0, -50),
            scale_xyz=(5, 5, 5))
        SceneManager.SetMainCameraTransfrom(
            position_xyz=(0, 0, 0))

    @classmethod
    def OnEvent(
        cls,
        event
    ):
        print(f"Time: {GetRunTime():.4f}, Event: {event}")

    @classmethod
    def OnUpdate(
        cls
    ):
        run_time = GetRunTime()
        SceneManager.SetEntityMeshRenderer(cls.entity_id_2, visible=True)
