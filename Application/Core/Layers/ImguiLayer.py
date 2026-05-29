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
            # ── 滚轮：缩放（改变轨道距离）──
            _, y_offset = ScrollerEvent.UnPack()
            dist = SceneManager.GetOrbitDistance()
            # 指数缩放，手感更自然
            zoom_speed = 0.1
            new_dist = dist * (1.0 - y_offset * zoom_speed)
            SceneManager.SetOrbitDistance(new_dist)
            SceneManager.ApplyOrbitToCamera()
            SceneCameraUpdateEvent.Pack()

        elif event is MouseGragEvent:
            import numpy as np
            bt, offset_x, offset_y = MouseGragEvent.UnPack()
            _, transform = SceneManager.GetSceneCamera()

            if bt == MouseButtonCode.Middle:
                # ── 中键拖动：平移轨道原点（Pan）──
                # 根据当前旋转角计算摄像机的世界空间 right/up 向量
                azimuth = transform.rotation_y
                elevation = transform.rotation_x
                # right = (cos(azimuth), 0, sin(azimuth))
                rx = np.cos(azimuth)
                rz = np.sin(azimuth)
                # up 近似：垂直方向 (0, 1, 0)，不做复杂叉积
                ux = -np.sin(elevation) * np.sin(azimuth)
                uy = np.cos(elevation)
                uz = np.sin(elevation) * np.cos(azimuth)

                pan_speed = 0.01
                tx, ty, tz = SceneManager.GetOrbitTarget()
                tx += rx * (-offset_x * pan_speed) + ux * (offset_y * pan_speed)
                ty += uy * (offset_y * pan_speed)
                tz += rz * (-offset_x * pan_speed) + uz * (offset_y * pan_speed)
                SceneManager.SetOrbitTarget(tx, ty, tz)
                SceneManager.ApplyOrbitToCamera()
                SceneCameraUpdateEvent.Pack()

            if bt == MouseButtonCode.Left:
                # ── 左键拖动：绕轨道原点旋转（Orbit）──
                rot_x_current = transform.rotation_x
                rot_y_current = transform.rotation_y

                orbit_speed = 0.005
                rot_y_next = rot_y_current - offset_x * orbit_speed   # 水平环绕
                rot_x_next = rot_x_current - offset_y * orbit_speed   # 垂直俯仰

                # 限制俯仰角，防止翻转（-89° ~ +89°）
                rot_x_next = np.clip(rot_x_next, -np.pi/2 + 0.01, np.pi/2 - 0.01)

                SceneManager.SetMainCameraTransform(
                    rotation_x=rot_x_next,
                    rotation_y=rot_y_next)
                SceneManager.ApplyOrbitToCamera()
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
