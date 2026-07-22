"""
EditorImguiLayer — ImGui 上下文 + 字体 + Backend + 面板（从 EditorLayer 拆分）。

职责:
  - ImGui 上下文创建/销毁
  - 字体加载 (含 Font Awesome 6 图标)
  - GLFW + OpenGL3 Backend 初始化
  - UI 面板注册
  - OnRender: ImGui 帧绘制

设计:
  - 必须在 EditorLayer 之前 OnAttach（EditorLayer 依赖 ImGui 上下文）
  - 零 EditorLayer 依赖 — 仅依赖 imgui_bundle + UIManager
"""

from __future__ import annotations
import ctypes
import os

from imgui_bundle import imgui

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Editor.EditorHost import EditorHost
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel, ResourcePanel


class EditorImguiLayer(Layer):
    """ImGui 层 — 管理 ImGui 生命周期与帧渲染。"""

    FONT_SIZE: float = 17
    FONT_CANDIDATES: list[str] = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    _config_dir: str = ""
    _panels_registered: bool = False

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        """初始化 ImGui — 上下文、字体、Backend、UI 面板。"""
        super().OnAttach()

        imgui.create_context()
        cls._config_dir = os.path.join(os.path.dirname(__file__), "..", "Config")
        os.makedirs(cls._config_dir, exist_ok=True)

        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable
        io.set_ini_filename("")

        cls._load_fonts()

        editor_window = EditorHost.get_editor_window()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 440 core")

        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))

        cls._init_ui_panels()

        # ── 启动时自动创建新 Project ──
        from Application.Editor.ProjectManager import ProjectManager
        if not ProjectManager.is_open():
            ProjectManager.create_new("Untitled")

    @classmethod
    def OnDetach(cls):
        """关闭 ImGui 后端 (需在 GL 上下文有效时调用)。"""
        imgui.backends.opengl3_shutdown()
        imgui.backends.glfw_shutdown()
        imgui.destroy_context()

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        """ImGui 帧绘制 — new_frame → draw → render。"""
        if imgui.get_current_context() is None:
            return
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
        """加载 UI 字体并合并 Font Awesome 6 图标字体。"""
        from imgui_bundle import hello_imgui as _hi

        _resource_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Resource"))
        _hi.set_assets_folder(_resource_dir)

        io = imgui.get_io()
        font_loaded = False

        _font_candidates = [
            "Fonts/Inter-Regular.ttf",
            "Fonts/segoeui.ttf",
            "Fonts/arial.ttf",
        ]
        for rel_path in _font_candidates:
            if _hi.asset_exists(rel_path):
                _hi.load_font_ttf_with_font_awesome_icons(rel_path, cls.FONT_SIZE)
                print(f"[Font] Loaded + FA6: {rel_path} ({cls.FONT_SIZE}px)")
                font_loaded = True
                break

        if not font_loaded:
            io.fonts.add_font_default()
            print(
                "[Font] No bundled font found. Using ImGui default.\n"
                "       Place a .ttf in Resource/Fonts/, e.g. Inter-Regular.ttf"
            )

    @classmethod
    def _init_ui_panels(cls):
        """注册编辑器 UI 面板 (幂等, 仅首次调用生效)。"""
        if cls._panels_registered:
            return
        UIManager.register(ScenePanel())
        UIManager.register(NodeEditorPanel())
        UIManager.register(ResourcePanel())
        cls._panels_registered = True
