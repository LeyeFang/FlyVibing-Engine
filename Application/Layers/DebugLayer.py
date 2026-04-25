from Application.Layers.Layer import Layer
from Application.Scene.SceneManager import SceneManager
from Application.Scene.TestObj.testBlock import (
    TEST_BLOCK_VERTECIES,
    TEST_BLOCK_INDICIES,
    TEST_BLOCK_VERTEX_SHADER,
    TEST_BLOCK_FRAGMENTS_SHADER)


class DebugLayer(Layer):
    @classmethod
    def OnAttach(
        cls,
        app
    ):
        SceneManager.AddTestObject()
