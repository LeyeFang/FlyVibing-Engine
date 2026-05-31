from Application.Core.Layers.Layer import Layer
from Application.Application import (
    WindowType,
    GetWindowBackend,
    GetWindow
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
        """检查鼠标是否落在任意面板窗口内（线程安全：只读 UIManager._panel_rects）"""
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False

    @classmethod
    def OnAttach(cls):
        """初始化 ImGui + 后端绑定 + UI 面板注册。"""
        imgui.create_context()
        imgui.style_colors_dark()
        app_window_type = GetWindowBackend()

        match app_window_type:
            case WindowType.GLFW:
                # ModernGL 基于 OpenGL 上下文，imgui 使用相同的 glfw + opengl3 后端
                app_window = GetWindow().glfw_window
                window_address = ctypes.cast(app_window, ctypes.c_void_p).value
                imgui.backends.glfw_init_for_opengl(window_address, True)
                imgui.backends.opengl3_init("#version 150")
            case WindowType.SDL2:
                raise NotImplementedError

        # 手动设置 DisplaySize
        io = imgui.get_io()
        w, h = GetWindow().GetSize()
        io.display_size = (float(w), float(h))

        cls._init_ui_panels()

    @classmethod
    def _init_ui_panels(cls):
        """注册所有 UI 面板（只执行一次）"""
        if not hasattr(cls, '_panels_registered'):
            UIManager.register(ScenePanel())
            UIManager.register(NodeEditorPanel())
            cls._panels_registered = True

    @classmethod
    def OnDetach(cls):
        """清理 ImGui 上下文。"""
        imgui.destroy_context()

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        # 🛑 鼠标落在面板窗口内时，不处理场景视角操作
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
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()

        # ⭐ 由 UIManager 绘制所有面板
        UIManager.draw_all()

        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
