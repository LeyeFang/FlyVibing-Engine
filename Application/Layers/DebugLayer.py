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
        model_id = ResourceManager.GetDefaultModel("Square")
        entity_id = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=entity_id,
            component_instance=MeshRenderer(model_id=model_id))
        print(model_id, entity_id)

    @classmethod
    def OnEvent(
        cls,
        event
    ):
        print(event.UnPack())
