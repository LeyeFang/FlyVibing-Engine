"""
Test 变体 EditorLayer — 完整复制主线 EditorLayer，仅改 3 处:
  1. import: 用 EditorHost 取代 Application 的全局函数
  2. OnAttach: GetEditorWindow() → EditorHost.get_editor_window()
  3. OnAttach: GetEditorRenderer() → EditorHost.get_editor_renderer()
  4. config path: 指向主线 Application/Editor/config/

原理: EditorHost 在 _create_window/_create_renderer 中显式赋值
editor_window/editor_renderer，保证不管哪个子类调 init()，这两个稳定
访问点始终可用。无需子类同步 hack。

其他所有逻辑与主线完全一致。验证完毕后可直接覆盖主线。
"""

from __future__ import annotations

# ── 标准库 ──
import ctypes
import os
import time

# ── 第三方库 ──
from imgui_bundle import imgui

# ── 应用层: 核心 ──
from Application.Editor.EditorHost import EditorHost      # ← 改了: 用 EditorHost 稳定访问点
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.WindowEvent import WindowResizeEvent
from Application.Core.Events.Enum.InputEnum import (
    MouseButtonCode,
    MouseActionCode,
    KeyButtonCode,
    KeyActionCode,)
from Application.Core.Input.InputState import IsShiftPressed
from Application.Core.Layers.Layer import Layer

# ── 应用层: 编辑器 ──
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.Gizmos.Grid import Grid
from Application.Editor.Gizmos.Outliner import Outliner
from Application.Editor.Gizmos.ViewGizmo import ViewGizmo
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel


# ── config 目录路径: 指向主线 Application/Editor/config/ ──
# 因为本文件在 Test/engineclass/editor/ 下, 需要回到项目根再进 Application/Editor/config/
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "Application", "Editor", "config")


class EditorLayer(Layer):
    """编辑器主层 — 3D 视口交互 + ImGui 面板渲染。

    与主线 EditorLayer 完全一致, 仅将 GetEditorWindow()/GetEditorRenderer()
    替换为 EditorHost 方法。
    """

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
        cls._config_dir = _CONFIG_DIR
        os.makedirs(cls._config_dir, exist_ok=True)
        io = imgui.get_io()
        io.set_ini_filename(os.path.join(cls._config_dir, "imgui.ini"))
        cls._load_fonts()
        # ← 改了: 用 EditorHost.get_editor_window() 取代 GetEditorWindow()
        editor_window = EditorHost.get_editor_window()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 440 core")
        io = imgui.get_io()
        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))
        cls._init_ui_panels()
        # ← 改了: 用 EditorHost.get_editor_renderer() 取代 GetEditorRenderer()
        cls.renderer = EditorHost.get_editor_renderer()
        cam = EditorCamera.get_instance()
        cls.renderer.set_active_camera(cam)
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
        if isinstance(event, WindowResizeEvent):
            w, h = event.unpack()
            io = imgui.get_io()
            io.display_size = (float(w), float(h))
        if cls._mouse_in_any_panel():
            return
        cam = EditorCamera.get_instance()
        if isinstance(event, ScrollerEvent):
            _, y_offset = event.unpack()
            cam.on_scroll(y_offset)
            SceneCameraUpdateEvent.Pack()
        elif isinstance(event, MouseGragEvent):
            bt, offset_x, offset_y = event.unpack()
            if bt == MouseButtonCode.Left:
                return  # 左键拖动不操作视图，仅用于点选
            cam.on_mouse_drag(bt, offset_x, offset_y, IsShiftPressed())
            SceneCameraUpdateEvent.Pack()
        elif isinstance(event, MouseButtonEvent):
            if event.button != MouseButtonCode.Left:
                return
            if event.action != MouseActionCode.Release:
                return
            t0 = time.perf_counter()
            pick_type, pick_value = cls.renderer.pick_at(
                event.pos_x, event.pos_y)
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
        """加载 UI 字体并合并 Font Awesome 6 图标字体。

        hello_imgui.load_font_ttf_with_font_awesome_icons 需要字体文件位于
        assets 目录内，因此我们统一使用 Resource/Fonts/ 下的字体副本。
        """
        from imgui_bundle import hello_imgui as _hi

        # hello_imgui 的资源目录指向 Resource/，字体相对路径为 Fonts/xxx.ttf
        _resource_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                         "Resource"))
        _hi.set_assets_folder(_resource_dir)

        io = imgui.get_io()
        font_loaded = False

        # 候选字体（相对于 Resource/ 的路径）
        _font_candidates = [
            "Fonts/Inter-Regular.ttf",
            "Fonts/segoeui.ttf",
            "Fonts/arial.ttf",
        ]
        for rel_path in _font_candidates:
            if _hi.asset_exists(rel_path):
                _hi.load_font_ttf_with_font_awesome_icons(
                    rel_path, cls.FONT_SIZE)
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
        """注册编辑器 UI 面板 (幂等, 仅首次调用生效)。

        默认隐藏 Scene 面板和 Node Editor 面板 — 用户通过 View 菜单手动打开。
        """
        if not hasattr(cls, '_panels_registered'):
            scene_panel = UIManager.register(ScenePanel())
            node_panel = UIManager.register(NodeEditorPanel())
            scene_panel.visible = False
            node_panel.visible = False
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
