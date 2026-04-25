import esper

from Application.Application import Application
from 


app = Application.GetApplication()


class SceneManager:

    scene = []
    entities: dict = {}

    @classmethod
    def Init():
        pass

    @classmethod
    def CreateScene():
        pass

    @classmethod
    def AddObject(
    ):
        esper.create_entity()

    def RemoveObject():
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
