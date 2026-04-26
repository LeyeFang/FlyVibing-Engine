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
    def GetRenderableEntities(
        cls
    ) -> list:
        entity_id_list = []
        for entity_id, rend in esper.get_component(MeshRenderer):
            if rend.visible:
                entity_id_list.append(entity_id)
        return entity_id_list

    @classmethod
    def GetEntityTransform(
        cls,
        entity_id
    ) -> Transform:
        transform = esper.component_for_entity(entity_id, Transform)
        return transform

    @classmethod
    def GetEntityMesh(
        cls,
        entity_id: int
    ) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        mesh_id = mesh_rend.mesh_id
        return mesh_id

    @classmethod
    def GetEntityMaterial(
        cls,
        entity_id: int
    ) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material_id = mesh_rend.material_id
        return material_id


    #
    # Modified Entities Components
    #
    @classmethod
    def SetEntityTransfrom(
        cls,
        entity_id: int = None,
        position_xyz: tuple = None,
        rotation_xyz: tuple = None,
        scale_xyz: tuple = None
    ) -> None:
        if entity_id is None:
            raise ("Must specific entity ID")
        if position_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.position_x, transform.position_y, transform.position_z = position_xyz
        if rotation_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
        if scale_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.scale_x, transform.scale_y, transform.scale_z = scale_xyz

    @classmethod
    def SetMainCameraTransfrom(
        cls,
        position_xyz: tuple = None,
        rotation_xyz: tuple = None
    ) -> None:
        if position_xyz is not None:
            transform = esper.component_for_entity(cls.main_camera_id, Transform)
            transform.position_x, transform.position_y, transform.position_z = position_xyz
        if rotation_xyz is not None:
            transform = esper.component_for_entity(cls.main_camera_id, Transform)
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
