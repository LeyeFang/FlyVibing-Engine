from Application.Layers.Layer import Layer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import MeshRenderer


class DebugLayer(Layer):
    @classmethod
    def OnAttach(
        cls,
        app
    ):
        mesh_id = ResourceManager.GetDefaultModel("Square")
        entity_id = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=entity_id,
            component_instance=MeshRenderer(mesh_id=mesh_id))
        SceneManager.SetEntityTransfrom(
            entity_id,
            position_xyz=(0, 0.0, -50),
            scale_xyz=(1, 1, 1))
        SceneManager.SetMainCameraTransfrom(
            position_xyz=(0, 0, 0))
        print(mesh_id, entity_id)

    @classmethod
    def OnEvent(
        cls,
        event
    ):
        print(event.UnPack())
