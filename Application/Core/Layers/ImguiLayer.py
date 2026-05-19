from Application.Core.Layers.Layer import Layer
from Application.Application import (
    WindowType,
    RendererType,
    GetRendererBackend,
    GetWindowBackend,
    GetWindow
)
from Application.Core.Events.Event import Event

import ctypes

from imgui_bundle import imgui


class ImguiLayer(Layer):
    @classmethod
    def OnAttach(cls):
        # Init for Imgui
        imgui.create_context()
        imgui.style_colors_dark()
        app_renderer_type = GetRendererBackend()
        app_window_type = GetWindowBackend()
        match (app_window_type, app_renderer_type):
            case (WindowType.GLFW, RendererType.OpenGL):
                app_window = GetWindow().glfw_window
                window_address = ctypes.cast(app_window, ctypes.c_void_p).value
                imgui.backends.glfw_init_for_opengl(window_address, True)
                imgui.backends.opengl3_init("#version 150")
            case (WindowType.SDL2, RendererType.OpenGL):
                raise NotImplementedError
            case (WindowType.GLFW, RendererType.Vulkan):
                raise NotImplementedError
            case (WindowType.SDL2, RendererType.Vulkan):
                raise NotImplementedError
        # 手动设置 DisplaySize（glfw_new_frame 已移至 Window.Update，首次帧渲染时可能尚未调用）
        io = imgui.get_io()
        w, h = GetWindow().GetSize()
        io.display_size = (float(w), float(h))

    @classmethod
    def OnDetach(cls):
        app_renderer_type = GetRendererBackend()
        app_window_type = GetWindowBackend()
        # 根据后端类型调用对应的 shutdown
        match (app_window_type, app_renderer_type):
            case (WindowType.GLFW, RendererType.OpenGL):
                raise NotImplementedError
            case (WindowType.SDL2, RendererType.OpenGL):
                raise NotImplementedError
            case (WindowType.GLFW, RendererType.Vulkan):
                raise NotImplementedError
            case (WindowType.SDL2, RendererType.Vulkan):
                raise NotImplementedError
        # 最后销毁 ImGui 上下文
        imgui.destroy_context()

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        pass

    @classmethod
    def OnUpdate(cls):
        imgui.backends.glfw_new_frame()
        pass

    @classmethod
    def OnRender(cls):
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        imgui.show_demo_window()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
