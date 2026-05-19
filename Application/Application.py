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
from Application.Core.Timer.Timer import FrameProfiler

from enum import Enum
from typing import Union
import threading
from threading import Thread


class RendererType(Enum):
    OpenGL = "OpenGL"
    Vulkan = "Vulkan"


class WindowType(Enum):
    GLFW = "GLFW"
    SDL2 = "SDL2"


class Application:

    window: Window = None
    window_type: WindowType = None
    renderer: Renderer = None
    renderer_type: RendererType = None
    layer_stack: list[Layer] = []
    event: Event = None
    event_stack: list[Event] = []
    run_state: bool = True
    renderer_ready = threading.Event()
    run_ready = threading.Event()

    @classmethod
    def Create(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL
    ) -> None:
        if isinstance(window_type, str):
            window_type = WindowType(window_type)
        if isinstance(renderer_type, str):
            renderer_type = RendererType(renderer_type)
        cls.window_type = window_type
        cls.renderer_type = renderer_type
        BindPackCallback(cls.OnEvent)
        # Setup Resource & Scene System
        ResourceManager.Init(cls)
        SceneManager.Init(cls)
        # Create Window
        if window_type == WindowType.GLFW:
            cls.window = glfwWindow.Create(cls)
        elif window_type == WindowType.SDL2:
            cls.window = sdl2Window.Create(cls)
        cls.run_state = True
        renderer_thread = Thread(target=cls.render_loop, daemon=True)
        renderer_thread.start()
        cls.renderer_ready.wait()
        return cls

    @classmethod
    def Run(cls):
        try:
            cls.run_ready.set()
            while cls.run_state:
                cls.window.Update()
                for layer in cls.layer_stack:
                    layer.OnUpdate()
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
    ) -> None:
        cls.layer_stack.append(layer)
        # layer.OnAttach()

    @classmethod
    def PopLayer(
        cls,
        layer: Layer
    ) -> None:
        cls.layer_stack.pop(-1)
        layer.OnDetach()

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is not None:
            for layer in cls.layer_stack:
                layer.OnEvent(event)
            cls.renderer.OnEvent(event)
            cls.window.OnEvent(event)
        if event is WindowCloseEvent:
            cls.run_state = False

    # For multi-thread
    @classmethod
    def render_loop(
        cls
    ) -> None:
        try:
            # Create Renderer
            if cls.renderer_type == RendererType.OpenGL:
                cls.window.MakeContextCurrent()
                cls.renderer = openglRenderer.Create(cls)
            elif cls.renderer_type == RendererType.Vulkan:
                pass
            cls.renderer_ready.set()
            # Run only when start
            cls.run_ready.wait()
            for layer in cls.layer_stack:
                layer.OnAttach()
            cls.renderer.StartFrame()
            cls.renderer.EndFrame()
            cls.window.SwapBuffer()
            FrameProfiler.Start(1)
            while cls.run_state:
                cls.renderer.StartFrame()
                for layer in cls.layer_stack:
                    layer.OnRender()
                cls.renderer.EndFrame()
                cls.window.SwapBuffer()
                FrameProfiler.Tick()
        except Exception as e:
            raise e
        finally:
            pass


def GetWindow() -> Window:
    return Application.window


def GetWindowBackend() -> WindowType:
    return Application.window_type


def GetRendererBackend() -> RendererType:
    return Application.renderer_type
