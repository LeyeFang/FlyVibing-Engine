import esper

from Application.Application import Application
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.BasicComponents import *


app = Application.GetApplication()


class SceneManager:

    scene: dict = {}
    entities: dict = {}

    @classmethod
    def Init(
        cls
    ) -> None:
        cls.scene["default"] = "default"

    @classmethod
    def CreateScene(
        cls,
        new_scene_name: str
    ) -> None:
        cls.scene[new_scene_name] = new_scene_name

    @classmethod
    def AddObject(
        cls
    ) -> int:
        obj_id = esper.create_entity(Transform())
        cls.entities[f'{obj_id}'] = 1
        return obj_id

    @classmethod
    def RemoveObject(
        cls
    ):
        pass

    # Debug Interface
    @classmethod
    def AddTestObject(
        cls
    ) -> None:
        import numpy as np
        from Application.Scene.TestObj.testBlock import (
            TEST_BLOCK_VERTECIES,
            TEST_BLOCK_INDICIES,
            TEST_BLOCK_VERTEX_SHADER,
            TEST_BLOCK_FRAGMENTS_SHADER
        )

        class TestMesh:
            vertices = np.array(TEST_BLOCK_VERTECIES, np.float32)
            indices = np.array(TEST_BLOCK_INDICIES, np.uint32)

        app.renderer.CreateMesh(TestMesh, 1)
