import glfw

from Application.Window.Window import Window

from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowCloseEvent
from Application.Events.WindowEvent import WindowResizeEvent


class glfwWindow(Window):

    glfw_window = None

    @classmethod
    def Create(
        cls,
        app
    ):
        cls.app = app
        cls.glfw_window = cls._create_window()
        return cls

    @classmethod
    def Update(cls):
        glfw.poll_events()
        glfw.swap_buffers(cls.glfw_window)
        if glfw.window_should_close(cls.glfw_window):
            cls.app.SetEvent(WindowCloseEvent)
            print("Window Close")
            glfw.terminate()

    @classmethod
    def Thermite():
        glfw.terminate()

    @classmethod
    def GetSize(cls):
        return glfw.get_framebuffer_size(cls.glfw_window)

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is WindowCloseEvent:
            cls.Therminate()

    @classmethod
    def ResizeCallback(
        cls
    ):
        pass

    def _create_window():
        # 1. 初始化 GLFW
        if not glfw.init():
            print("无法初始化 GLFW")
            return
        # 配置 OpenGL 版本（3.3 核心模式）
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        # 2. 创建窗口
        glfw_window = glfw.create_window(
            800, 600,
            "Test Window",
            None,
            None
        )
        if not glfw_window:
            print("无法创建窗口")
            glfw.terminate()
            return
        glfw.make_context_current(glfw_window)
        return glfw_window
