from Application.Layers.Layer import Layer
from Application.Events.Event import Event, BindPackCallback
from Application.Events.WindowEvent import WindowCloseEvent
from Application.Window.Window import Window
from Application.Window.glfwWindow import glfwWindow
from Application.Renderer.Renderer import Renderer
from Application.Renderer.openglRenderer import openglRenderer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager
from Application.Timer.Timer import FrameProfiler


class Application:

    window: Window = None
    renderer: Renderer = None
    layer_stack: list[Layer] = []
    event: Event = None
    event_stack: list[Event] = []
    run_time: float

    @classmethod
    def Create(cls):
        ResourceManager.Init(cls)
        SceneManager.Init(cls)
        cls.window = glfwWindow.Create(cls)
        cls.renderer = openglRenderer.Create(cls)
        BindPackCallback(cls.OnEvent)
        return cls

    @classmethod
    def Run(cls):
        try:
            FrameProfiler.Start(1)
            cls.run_state = True
            while cls.run_state:
                # Update Application
                cls.renderer.StartFrame()
                for layer in cls.layer_stack:
                    layer.OnUpdate()
                cls.renderer.EndFrame()
                cls.window.Update()
                FrameProfiler.Tick()
        finally:
            pass

    @classmethod
    def GetApplication(
        cls
    ) -> 'Application':
        return cls

    @classmethod
    def PushLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.append(layer)
        layer.OnAttach()

    @classmethod
    def PopLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.pop(-1)
        layer.OnDetach()

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        # Pass Events
        if event is not None:
            for layer in cls.layer_stack:
                layer.OnEvent(event)
            cls.renderer.OnEvent(event)
            cls.window.OnEvent(event)
        if event is WindowCloseEvent:
            cls.run_state = False

    @classmethod
    def _single_loop(
        cls
    ) -> None:
        pass
