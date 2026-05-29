from Application.Core.Layers.Layer import Layer
from Application.Application import (
    WindowType,
    RendererType,
    GetRendererBackend,
    GetWindowBackend,
    GetWindow
)
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.UI.UIManager import UIManager
from Application.Core.UI.panels import (
    ScenePanel,
    NodeEditorPanel,
)

import ctypes

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor
# 文件顶部新增一行导入
from Application.Core.Math.RendererMath import get_world_forward


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
            case (WindowType.GLFW, RendererType.ModernGL):
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
        # 在末尾追加：
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
        # 🛑 鼠标落在面板窗口内时，不处理场景视角操作
        #     通过 UIManager._panel_rects 检测（渲染线程写入，主线程只读）
        if cls._mouse_in_any_panel():
            return

        if event is ScrollerEvent:
            _, y_offset = ScrollerEvent.UnPack()
            camera, transform = SceneManager.GetSceneCamera()
            world_forward = get_world_forward(camera, transform)
            speed = 0.5
            SceneManager.SetMainCameraTransform(
                position_x=transform.position_x + world_forward[0] * y_offset * speed,
                position_y=transform.position_y + world_forward[1] * y_offset * speed,
                position_z=transform.position_z + world_forward[2] * y_offset * speed
            )
            SceneCameraUpdateEvent.Pack()
        elif event is MouseGragEvent:
            bt, offset_x, offset_y = MouseGragEvent.UnPack()
            _, transform = SceneManager.GetSceneCamera()
            pos_x_current = transform.position_x
            pos_y_current = transform.position_y
            rot_x_current = transform.rotation_x
            rot_z_current = transform.rotation_z
            if bt == MouseButtonCode.Middle:
                pos_x_next = pos_x_current - 0.1*offset_x
                pos_y_next = pos_y_current + 0.1*offset_y
                SceneManager.SetMainCameraTransform(
                    position_x=pos_x_next,
                    position_y=pos_y_next)
            if bt == MouseButtonCode.Left:
                rot_z_next = rot_z_current - 0.01*offset_x
                rot_x_next = rot_x_current - 0.01*offset_y
                SceneManager.SetMainCameraTransform(
                    rotation_z=rot_z_next,
                    rotation_x=rot_x_next)
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
