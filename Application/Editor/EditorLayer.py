# ── 标准库 ──
import ctypes
import os
import time

# ── 第三方库 ──
from imgui_bundle import imgui

# ── 应用层: 核心 ──
from Application.Application import GetEditorWindow, GetEditorRenderer
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.WindowEvent import WindowResizeEvent
from Application.Core.Events.Enum.InputEnum import (
    MouseButtonCode, MouseActionCode, KeyButtonCode, KeyActionCode,
)
from Application.Core.Input.InputState import IsShiftPressed
from Application.Core.Layers.Layer import Layer

# ── 应用层: 编辑器 ──
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.Rendering.Grid import Grid
from Application.Editor.Rendering.Outliner import Outliner
from Application.Editor.Rendering.ViewGizmo import ViewGizmo
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel

# ── 应用层: 渲染器 ──
from Application.Core.Renderer.OpenGL.openGLRenderer import openGLRenderer


class EditorLayer(Layer):

    # ── 字体配置 ────────────────────────────────────────────────
    FONT_SIZE: float = 15.0
    FONT_CANDIDATES: list[str] = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    # ════════════════════════════════════════════════════════════
    # 生命周期 (Layer 接口)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        """编辑器层初始化 — 创建 ImGui 上下文、注册 3D 渲染资源和 UI 面板。"""
        imgui.create_context()

        cls._config_dir = os.path.join(os.path.dirname(__file__), "config")
        os.makedirs(cls._config_dir, exist_ok=True)
        io = imgui.get_io()
        io.set_ini_filename(os.path.join(cls._config_dir, "imgui.ini"))

        cls._load_fonts()

        editor_window = GetEditorWindow()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 440 core")
        io = imgui.get_io()
        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))
        cls._init_ui_panels()

        # ── 渲染器: 注册 Grid + ViewGizmo + Outliner overlay ──
        cls.renderer = GetEditorRenderer()
        Grid.register_to(cls.renderer)
        ViewGizmo.register_to(cls.renderer)
        Outliner.register_to(cls.renderer)

    @classmethod
    def OnDetach(cls):
        if cls.renderer is not None:
            Outliner.unregister_from(cls.renderer)
            ViewGizmo.unregister_from(cls.renderer)
            Grid.unregister_from(cls.renderer)
        imgui.destroy_context()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        # ── 窗口 resize 始终处理，不受面板鼠标拦截影响 ──
        if event is WindowResizeEvent:
            w, h = WindowResizeEvent.UnPack()
            io = imgui.get_io()
            io.display_size = (float(w), float(h))
        if cls._mouse_in_any_panel():
            return
        cam = EditorCamera.get_instance()
        if event is ScrollerEvent:
            _, y_offset = ScrollerEvent.UnPack()
            cam.on_scroll(y_offset)
            SceneCameraUpdateEvent.Pack()
        elif event is MouseGragEvent:
            bt, offset_x, offset_y = MouseGragEvent.UnPack()
            if bt == MouseButtonCode.Left:
                return  # 左键拖动不操作视图，仅用于点选
            cam.on_mouse_drag(bt, offset_x, offset_y, IsShiftPressed())
            SceneCameraUpdateEvent.Pack()
        elif event is MouseButtonEvent:
            if MouseButtonEvent.button != MouseButtonCode.Left:
                return
            if MouseButtonEvent.action != MouseActionCode.Release:
                return
            t0 = time.perf_counter()
            pick_type, pick_value = openGLRenderer.pick_at(
                MouseButtonEvent.pos_x, MouseButtonEvent.pos_y)
            dt = (time.perf_counter() - t0) * 1000
            if pick_type == 'entity':
                print(f"[EditorLayer] Click → Entity#{pick_value}  ({dt:.3f}ms)")
                Outliner.set_selected_entities({pick_value})
            elif pick_type == 'overlay' and pick_value:
                prefix = ViewGizmo.OVERLAY_KEY_PREFIX
                if pick_value.startswith(prefix):
                    face_name = pick_value.rsplit('_', 1)[-1]
                    direction = ViewGizmo.FACE_LOOK_DIRECTIONS.get(face_name)
                    if direction is not None:
                        cam.look_from_direction(direction)
                        SceneCameraUpdateEvent.Pack()
                        print(f"[EditorLayer] ViewGizmo → {face_name}  ({dt:.3f}ms)")
                else:
                    print(f"[EditorLayer] Click → Overlay '{pick_value}'  ({dt:.3f}ms)")
            else:
                print(f"[EditorLayer] Click → nothing  ({dt:.3f}ms)")
                Outliner.clear()

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnRender(cls):
        # ── 处理待处理的轮廓请求 (render thread, GL 调用) ──
        Outliner._sync(cls.renderer)
        # ── ImGui ──
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())

    # ════════════════════════════════════════════════════════════
    # 初始化辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _load_fonts(cls) -> None:
        """加载 UI 字体 — 优先 Inter (Blender 同款)，否则用系统字体。"""
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
    def _init_ui_panels(cls):
        """注册编辑器 UI 面板 (幂等, 仅首次调用生效)。"""
        if not hasattr(cls, '_panels_registered'):
            UIManager.register(ScenePanel())
            UIManager.register(NodeEditorPanel())
            cls._panels_registered = True

    # ════════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _mouse_in_any_panel(cls) -> bool:
        """检查鼠标是否悬停在任意 ImGui 面板区域内。"""
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False
