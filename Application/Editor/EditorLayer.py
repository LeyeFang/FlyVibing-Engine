from Application.Core.Layers.Layer import Layer
from Application.Application import (
    GetEditorWindow,
    GetEditorRenderer
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
from Application.Core.Renderer.ModernGL.ModernGLCore import ModernGLCore
from Application.Editor.Rendering.GridGizmo import GridGizmo

import os
import ctypes

from imgui_bundle import imgui


class EditorLayer(Layer):

    # ── 字体配置 ────────────────────────────────────────────────
    FONT_SIZE: float = 15.0
    # 优先级从高到低: Inter (Blender 同款) → Segoe UI → Arial → 默认
    FONT_CANDIDATES: list[str] = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

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

        # ── 加载字体 (必须在 backend init 之前，否则纹理不会包含新字体) ──
        cls._load_fonts()

        editor_window = GetEditorWindow()
        cls.editor_renderer = GetEditorRenderer()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        # OpenGL 后端: GLFW + OpenGL3
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 150")
        io = imgui.get_io()
        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))
        cls._init_ui_panels()

        # ── 编辑器 3D 渲染资源 ──
        GridGizmo.init(ModernGLCore.ctx)

        # ── 注册 Overlay 回调: 网格/Gizmo 由 StartFrame 在场景实体之后调用 ──
        cls.editor_renderer.register_overlay_callback(
            lambda v, p: GridGizmo.render(v, p)
        )

    @classmethod
    def _init_ui_panels(cls):
        if not hasattr(cls, '_panels_registered'):
            UIManager.register(ScenePanel())
            UIManager.register(NodeEditorPanel())
            cls._panels_registered = True

    @classmethod
    def _load_fonts(cls) -> None:
        """加载 UI 字体 — 优先 Inter (Blender 同款)，否则用系统字体。

        调用时机: create_context() 之后、opengl3_init() 之前。
        """
        io = imgui.get_io()
        font_loaded = False

        for font_path in cls.FONT_CANDIDATES:
            if os.path.isfile(font_path):
                io.fonts.add_font_from_file_ttf(font_path, cls.FONT_SIZE)
                print(f"[Font] Loaded: {font_path} ({cls.FONT_SIZE}px)")
                font_loaded = True
                break

        if not font_loaded:
            print(
                "[Font] No custom font found. Using ImGui default.\n"
                "       To get Blender-style font, download Inter:\n"
                "       https://rsms.me/inter/ → Resource/Fonts/Inter-Regular.ttf"
            )

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
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
