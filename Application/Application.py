# Core
# # Layer
from Application.Core.Layers.Layer import Layer
# # Event
from Application.Core.Events.Event import Event, BindPackCallback
from Application.Core.Events.WindowEvent import WindowCloseEvent
# # Window
from Application.Core.Window.Window import Window
# # Editor
from Application.Editor.EditorWindow import EditorWindow
# # Renderer
from Application.Core.Renderer.Renderer import Renderer
from Application.Core.Renderer.ModernGL.modernGLRenderer import modernGLRenderer
from Application.Core.Renderer.OpenGL.openGLRenderer import openGLRenderer
from Application.Core.Renderer.Vulkan.vulkanRenderer import vulkanRenderer
from Application.Core.Scene.SceneManager import SceneManager
# # Resource & Scene
from Application.Resource.ResourceManager import ResourceManager
# # Stats
from Application.Core.Stats.FrameProfiler import FrameProfiler

from enum import Enum
from typing import Union
import threading
from threading import Thread


class RendererType(Enum):
    OpenGL = "OpenGL"
    ModernGL = "ModernGL"
    Vulkan = "Vulkan"


class WindowType(Enum):
    GLFW = "GLFW"
    SDL2 = "SDL2"


class Application:

    # editor window
    editor_window: EditorWindow = None
    window_type: WindowType = None
    # editor renderer
    editor_renderer: Renderer = None
    renderer_type: RendererType = None
    # preview runtime
    preview_runtime_window = None
    preview_runtime_renderer: Renderer = None
    # application
    layer_stack: list[Layer] = []
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
        cls.editor_window = EditorWindow.Create()
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
                cls.editor_window.Update()
                for layer in cls.layer_stack:
                    layer.OnUpdate()
                pass
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
            cls.editor_renderer.OnEvent(event)
            cls.editor_window.OnEvent(event)
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
                cls.editor_window.MakeContextCurrent()
                cls.editor_renderer = openGLRenderer.Create()
            elif cls.renderer_type == RendererType.ModernGL:
                cls.editor_window.MakeContextCurrent()
                cls.editor_renderer = modernGLRenderer.Create()
            elif cls.renderer_type == RendererType.Vulkan:
                cls.editor_renderer = vulkanRenderer.Create()
            cls.renderer_ready.set()
            # Run only when start
            cls.run_ready.wait()
            for layer in cls.layer_stack:
                layer.OnAttach()
            # Safe render
            cls.editor_renderer.StartFrame()
            cls.editor_renderer.EndFrame()
            if cls.renderer_type in (RendererType.OpenGL, RendererType.ModernGL):
                cls.editor_window.SwapBuffer()
            # Render loop
            FrameProfiler.Start(1)
            while cls.run_state:
                cls.editor_renderer.StartFrame()
                for layer in cls.layer_stack:
                    layer.OnRender()
                cls.editor_renderer.EndFrame()
                if cls.renderer_type in (RendererType.OpenGL, RendererType.ModernGL):
                    cls.editor_window.SwapBuffer()
                FrameProfiler.Tick()
        except Exception as e:
            raise e
        finally:
            pass


def GetApplication() -> Application:
    return Application


def GetEditorWindow() -> Window:
    return Application.editor_window


def GetEditorRenderer() -> Window:
    return Application.editor_renderer


def GetWindowBackend() -> WindowType:
    return Application.window_type


def GetRendererBackend() -> RendererType:
    return Application.renderer_type


def SetTargetFrame(frame: int) -> None:
    Application.target_frame_time = float(1 / frame)
