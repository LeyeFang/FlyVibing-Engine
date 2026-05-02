# Core
# # Layer
from Application.Core.Layers.Layer import Layer
# # Event
from Application.Core.Events.Event import Event, BindPackCallback
from Application.Core.Events.WindowEvent import WindowCloseEvent
# # Window
from Application.Core.Window.Window import Window
from Application.Core.Window.glfwWindow import glfwWindow
from Application.Core.Window.sdl2Window import sdl2Window
# # Renderer
from Application.Core.Renderer.Renderer import Renderer
from Application.Core.Renderer.openglRenderer import openglRenderer
from Application.Core.Scene.SceneManager import SceneManager
# # Resource & Scene
from Application.Resource.ResourceManager import ResourceManager
# # Timer
from Application.Core.Timer.Timer import FrameProfiler, _start_timer

from typing import Literal, Optional


RendererType = Literal['OpenGL', 'Vulkan']
WindowType = Literal['GLFW', 'SDL2']


class Application:

    window: Window = None
    window_type: WindowType = None
    renderer: Renderer = None
    renderer_type: RendererType = None
    layer_stack: list[Layer] = []
    event: Event = None
    event_stack: list[Event] = []
    run_time: float

    @classmethod
    def Create(
        cls,
        window_type: WindowType = 'GLFW',
        renderer_type: RendererType = 'OpenGL'
    ) -> None:
        cls.window_type = window_type
        cls.renderer_type = renderer_type
        BindPackCallback(cls.OnEvent)
        _start_timer()
        # Setup Resource & Scene System
        ResourceManager.Init(cls)
        SceneManager.Init(cls)
        # Create Window
        if window_type == 'GLFW':
            cls.window = glfwWindow.Create(cls)
        elif window_type == 'SDL2':
            cls.window = sdl2Window.Create(cls)
        # Create Renderer
        if renderer_type == 'OpenGL':
            cls.renderer = openglRenderer.Create(cls)
        elif renderer_type == 'Vulkan':
            pass
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
