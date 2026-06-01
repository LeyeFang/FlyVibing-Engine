from Application.Core.Layers.Layer import Layer
from Application.Application import (
    WindowType,
    RendererType,
    GetWindowBackend,
    GetWindow,
    GetRendererBackend,
)
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import (
    ScenePanel,
    NodeEditorPanel,
)
from Application.Editor.EditorCamera import EditorCamera

import ctypes

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor


class ImguiLayer(Layer):

    @classmethod
    def _mouse_in_any_panel(cls) -> bool:
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False

    @classmethod
    def OnAttach(cls):
        imgui.create_context()
        imgui.style_colors_dark()

        renderer_type = GetRendererBackend()
        app_window = GetWindow().glfw_window
        window_address = ctypes.cast(app_window, ctypes.c_void_p).value

        if renderer_type == RendererType.Vulkan:
            # Vulkan 后端: GLFW + Vulkan (需要 int 地址)
            imgui.backends.glfw_init_for_vulkan(window_address, True)
            from Application.Core.Renderer.Vulkan.VulkanCore import VulkanCore
            VulkanCore.init_imgui()
        else:
            # OpenGL 后端: GLFW + OpenGL3
            imgui.backends.glfw_init_for_opengl(window_address, True)
            imgui.backends.opengl3_init("#version 150")

        io = imgui.get_io()
        w, h = GetWindow().GetSize()
        io.display_size = (float(w), float(h))

        cls._init_ui_panels()

    @classmethod
    def _init_ui_panels(cls):
        if not hasattr(cls, '_panels_registered'):
            UIManager.register(ScenePanel())
            UIManager.register(NodeEditorPanel())
            cls._panels_registered = True

    @classmethod
    def OnDetach(cls):
        imgui.destroy_context()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        if cls._mouse_in_any_panel():
            return
        cam = EditorCamera.get_instance()

        if event is ScrollerEvent:
            _, y_offset = ScrollerEvent.UnPack()
            cam.on_scroll(y_offset)
            SceneCameraUpdateEvent.Pack()
        elif event is MouseGragEvent:
            bt, offset_x, offset_y = MouseGragEvent.UnPack()
            cam.on_mouse_drag(bt, offset_x, offset_y)
            SceneCameraUpdateEvent.Pack()

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnRender(cls):
        renderer_type = GetRendererBackend()

        if renderer_type == RendererType.Vulkan:
            pass
        else:
            imgui.backends.glfw_new_frame()
            imgui.backends.opengl3_new_frame()

        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()

        if renderer_type == RendererType.Vulkan:
            from Application.Core.Renderer.Vulkan.VulkanCore import VulkanCore
            draw_data = imgui.get_draw_data()
            VulkanCore.render_imgui(draw_data, VulkanCore._current_image_index)
        else:
            imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
