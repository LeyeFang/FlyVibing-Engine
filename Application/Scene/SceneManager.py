import esper

from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.BasicComponents import *


class SceneManager:

    app = None
    scene: dict = {}
    entities: dict = {}
    scene_camera: Camera = None
    scene_camera_id: int = None
    main_camera_id: int = None

    @classmethod
    def Init(
        cls,
        app
    ) -> None:
        cls.app = app
        cls.scene["default"] = "default"
        cls.main_camera_id = esper.create_entity(Transform(), Camera(True))
        cls.scene_camera_id = cls.main_camera_id
        cls.scene_camera = esper.component_for_entity(cls.scene_camera_id, Camera)

    @classmethod
    def CreateScene(
        cls,
        new_scene_name: str
    ) -> None:
        cls.scene[new_scene_name] = new_scene_name

    @classmethod
    def AddEntity(
        cls
    ) -> int:
        entity_id = esper.create_entity(Transform())
        cls.entities[f'{entity_id}'] = 1
        return entity_id

    @classmethod
    def AddComponentToEntity(
        cls,
        component_instance: type,
        entity_id: int
    ) -> None:
        esper.add_component(entity_id, component_instance)

    @classmethod
    def GetSceneCamera(
        cls
    ) -> tuple[Camera, Transform]:
        camera = esper.component_for_entity(cls.scene_camera_id, Camera)
        transform = esper.component_for_entity(cls.scene_camera_id, Transform)
        return camera, transform

    @classmethod
    def GetRenderableEntitiesModelShader(
        cls
    ) -> list:
        model_shader_handle = []
        for _, rend in esper.get_component(MeshRenderer):
            if rend.visible:
                model_id = rend.model_id
                shader_id = rend.shader_id
                model_shader_handle.append((model_id, shader_id))
        return model_shader_handle
