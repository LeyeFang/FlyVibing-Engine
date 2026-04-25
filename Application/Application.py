from Application.Layers.Layer import Layer
from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowCloseEvent
from Application.Window.Window import Window
from Application.Window.glfwWindow import glfwWindow
from Application.Renderer.Renderer import Renderer
from Application.Renderer.openglRenderer import openglRenderer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager


class Application:

    window: Window = None
    renderer: Renderer = None
    layer_stack: list[Layer] = []
    event: Event = None

    @classmethod
    def Create(cls):
        SceneManager.Init(cls)
        ResourceManager.Init(cls)
        cls.window = glfwWindow.Create(cls)
        cls.renderer = openglRenderer.Create(cls)
        return cls

    @classmethod
    def GetApplication(cls):
        return cls

    @classmethod
    def Stop(cls):
        pass

    @classmethod
    def Run(cls):
        cls.run_state = True
        while cls.run_state:
            # Update Application
            cls.renderer.StartFrame()
            for layer in cls.layer_stack:
                layer.OnUpdate()
            cls.renderer.EndFrame()
            cls.window.Update()
            # Pass Events
            if cls.event is not None:
                for layer in cls.layer_stack:
                    layer.OnEvent(cls.event)
                cls.renderer.OnEvent(cls.event)
                cls.window.OnEvent(cls.event)
                cls.OnEvent(cls.event)
                cls.event = None

    @classmethod
    def Pause(self):
        pass

    @classmethod
    def PushLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.append(layer)
        layer.OnAttach(cls)

    @classmethod
    def PopLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.pop(-1)
        layer.OnDetach()

    @classmethod
    def SetEvent(
        cls,
        event: Event
    ) -> None:
        cls.event = event

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is WindowCloseEvent:
            cls.run_state = False
