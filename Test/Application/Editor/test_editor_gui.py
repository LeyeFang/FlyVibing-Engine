"""
Test: Editor GUI Visual Design — 零功能·纯视觉调试
═══════════════════════════════════════════════════════════

照搬主线编辑器的 GUI 布局和 Blender 深色主题，所有面板均为桩（无功能）。
用途: 编辑器 GUI 视觉设计调试（颜色 / 字体 / 间距 / 布局）。

布局:
  ┌─────────────────────────────────────────────┐
  │  File  Edit  View  Help         ← 菜单栏    │
  ├──────────┬──────────────────────────────────┤
  │  Scene   │      Node Editor                │
  │  (20%)   │      (80%)                      │
  ├──────────┴──────────────────────────────────┤
  │  Ready                            ← 状态栏  │
  └─────────────────────────────────────────────┘

依赖: imgui_bundle, glfw
引擎依赖: 无 (仅复用 PanelStyle 主题)
运行: python Test/Application/Editor/test_editor_gui.py
"""

from __future__ import annotations
import sys, os, ctypes

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import glfw
from imgui_bundle import imgui
from imgui_bundle import imgui as imgui_internal
from OpenGL import GL as gl

from Application.Editor.UI.PanelStyle import apply_custom_style


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

STATUS_BAR_HEIGHT: float = 22.0
PANEL_NAMES: list[str] = ["Scene", "Node Editor"]


# ═══════════════════════════════════════════════════════════════
# 绘制函数 — 照搬 UIManager.draw_all() 结构
# ═══════════════════════════════════════════════════════════════

_dock_layout_done: bool = False


def draw_main_dockspace() -> None:
    """全屏 DockSpace + 菜单栏 + 停靠面板 + 状态栏。"""
    global _dock_layout_done

    viewport = imgui.get_main_viewport()
    dockspace_h = viewport.work_size.y - STATUS_BAR_HEIGHT

    # ── 全屏背景窗口 (透明, 无边框, 无标题) ──
    imgui.set_next_window_pos(viewport.work_pos)
    imgui.set_next_window_size(imgui.ImVec2(viewport.work_size.x, dockspace_h))
    imgui.set_next_window_viewport(viewport.id_)

    window_flags = (
        imgui.WindowFlags_.no_title_bar
        | imgui.WindowFlags_.no_collapse
        | imgui.WindowFlags_.no_resize
        | imgui.WindowFlags_.no_move
        | imgui.WindowFlags_.no_bring_to_front_on_focus
        | imgui.WindowFlags_.no_nav_focus
        | imgui.WindowFlags_.no_docking
    )

    imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
    # 背景透明 — GL 清屏色 (深灰) 透出作为底色
    imgui.push_style_color(
        imgui.Col_.window_bg, imgui.ImVec4(0, 0, 0, 0))

    imgui.begin("MainDockSpace", None, window_flags)
    imgui.pop_style_var(2)
    imgui.pop_style_color()

    # ── 菜单栏 ──
    draw_menu_bar()

    # ── DockSpace ──
    dockspace_id = imgui.get_id("MainDockSpace")
    imgui.dock_space(dockspace_id, (0.0, 0.0), imgui.DockNodeFlags_.none)

    if not _dock_layout_done:
        _setup_dock_layout(dockspace_id)
        _dock_layout_done = True

    # ── 2 个桩面板 (同主线) ──
    draw_scene_panel()
    draw_node_editor_panel()

    imgui.end()  # MainDockSpace

    # ── 状态栏 ──
    draw_status_bar()


# ═══════════════════════════════════════════════════════════════
# 菜单栏
# ═══════════════════════════════════════════════════════════════

def draw_menu_bar() -> None:
    """主菜单栏 — 结构同主线，所有项 disabled (纯视觉)。"""
    if not imgui.begin_main_menu_bar():
        return

    if imgui.begin_menu("File", True):
        if imgui.begin_menu("Import", True):
            imgui.menu_item("Mesh...", "", False, False)
            imgui.menu_item("Texture...", "", False, False)
            imgui.menu_item("Shader...", "", False, False)
            imgui.end_menu()
        imgui.separator()
        imgui.menu_item("New Scene", "Ctrl+N", False, False)
        imgui.menu_item("Open Scene...", "Ctrl+O", False, False)
        imgui.separator()
        imgui.menu_item("Save Scene", "Ctrl+S", False, False)
        imgui.menu_item("Save As...", "Ctrl+Shift+S", False, False)
        imgui.separator()
        imgui.menu_item("Exit", "Alt+F4", False, False)
        imgui.end_menu()

    if imgui.begin_menu("Edit", True):
        imgui.menu_item("Undo", "Ctrl+Z", False, False)
        imgui.menu_item("Redo", "Ctrl+Y", False, False)
        imgui.separator()
        imgui.menu_item("Preferences...", "", False, False)
        imgui.end_menu()

    if imgui.begin_menu("View", True):
        for name in PANEL_NAMES:
            visible = True  # 桩面板始终可见
            imgui.menu_item(name, "", visible, False)
        imgui.end_menu()

    if imgui.begin_menu("Help", True):
        imgui.menu_item("About", "", False, False)
        imgui.end_menu()

    imgui.end_main_menu_bar()


# ═══════════════════════════════════════════════════════════════
# Dock 布局 — 照搬主线 _setup_default_dock_layout
# ═══════════════════════════════════════════════════════════════

def _setup_dock_layout(dockspace_id: int) -> None:
    """默认分栏 (同主线):
        ┌──────────┬────────────────────┐
        │  Scene   │   Node Editor      │
        │  (20%)   │   (80%)            │
        └──────────┴────────────────────┘
    """
    internal = imgui_internal.internal

    internal.dock_builder_remove_node(dockspace_id)
    internal.dock_builder_add_node(dockspace_id)

    _, dock_left, dock_right = internal.dock_builder_split_node_py(
        dockspace_id, imgui.Dir_.left, 0.20)

    internal.dock_builder_dock_window("Scene", dock_left)
    internal.dock_builder_dock_window("Node Editor", dock_right)

    internal.dock_builder_finish(dockspace_id)


# ═══════════════════════════════════════════════════════════════
# 桩面板
# ═══════════════════════════════════════════════════════════════

def _begin_panel(title: str) -> bool:
    """开始一个停靠面板窗口（不透明深灰背景，可读）。"""
    flags = imgui.WindowFlags_.none
    return imgui.begin(title, None, flags)


def draw_scene_panel() -> None:
    """Scene 面板桩 — 标题 + 控件栏 + Entities/Resources 选项卡。"""
    expanded = _begin_panel("Scene")
    if expanded:
        # 标题
        imgui.text("Scene: ")
        imgui.same_line()
        imgui.text_colored(imgui.ImVec4(0.878, 0.416, 0.153, 1.0), "Default")

        # 控件栏 (Play / Pause / Stop — 视觉桩)
        imgui.spacing()
        imgui.button("▶")
        imgui.same_line()
        imgui.button("⏸")
        imgui.same_line()
        imgui.button("⏹")
        imgui.same_line()
        imgui.text_disabled("Simulation Controls")

# 占位列表
        imgui.spacing()
        imgui.separator()
        imgui.text_disabled("  Entity list placeholder")
        imgui.text_disabled("  Resource list placeholder")

        imgui.end()


def draw_node_editor_panel() -> None:
    """Node Editor 面板桩 — 空白画布。"""
    expanded = _begin_panel("Node Editor")
    if expanded:
        imgui.text_disabled("(empty node editor canvas)")
        imgui.end()


# ═══════════════════════════════════════════════════════════════
# 状态栏
# ═══════════════════════════════════════════════════════════════

def draw_status_bar() -> None:
    """底部状态栏 — 照搬主线 _draw_status_bar 结构。"""
    viewport = imgui.get_main_viewport()
    bar_y = viewport.work_pos.y + viewport.work_size.y - STATUS_BAR_HEIGHT

    imgui.set_next_window_pos(imgui.ImVec2(viewport.work_pos.x, bar_y))
    imgui.set_next_window_size(
        imgui.ImVec2(viewport.work_size.x, STATUS_BAR_HEIGHT))

    imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(10, 3))

    window_flags = (
        imgui.WindowFlags_.no_title_bar
        | imgui.WindowFlags_.no_collapse
        | imgui.WindowFlags_.no_resize
        | imgui.WindowFlags_.no_move
        | imgui.WindowFlags_.no_bring_to_front_on_focus
        | imgui.WindowFlags_.no_nav_focus
        | imgui.WindowFlags_.no_scrollbar
        | imgui.WindowFlags_.no_scroll_with_mouse
    )

    imgui.begin("##StatusBar", False, window_flags)
    imgui.text("Ready")
    imgui.end()
    imgui.pop_style_var(3)


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── GLFW ──
    if not glfw.init():
        print("glfw.init() failed"); return

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    window = glfw.create_window(
        1600, 900, "Editor GUI — Visual Design Debug", None, None)
    if not window:
        glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── ImGui ──
    imgui.create_context()
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.docking_enable
    io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
    io.set_ini_filename(os.path.join(os.path.dirname(__file__), "imgui.ini"))

    # 字体: Inter (同主线)
    font_candidates = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            io.fonts.add_font_from_file_ttf(fp, 15.0)
            break

    # Backend (与 test_runtime_node_editor 一致)
    glfw_window_ptr = ctypes.cast(window, ctypes.c_void_p).value
    imgui.backends.glfw_init_for_opengl(glfw_window_ptr, True)
    imgui.backends.opengl3_init("#version 440 core")

    # ── 主线主题 ──
    apply_custom_style()
    # 统一所有层背景透明 — GL 清屏深灰统一透出
    style = imgui.get_style()
    style.set_color_(imgui.Col_.docking_empty_bg,
                     imgui.ImVec4(0, 0, 0, 0))

    # ── 回调 ──
    # ESC 通过 imgui.is_key_pressed 检测 (与 test_runtime_node_editor 一致)
    print("[GUI Test] Ready. ESC to exit.")

    # 首帧立即交换一次 (避免白屏)
    glfw.swap_buffers(window)

    # GL 清屏色: 白色 — 诊断 ImGui 遮挡情况
    gl.glClearColor(1.0, 1.0, 1.0, 1.0)

    # ── 主循环 ──
    while not glfw.window_should_close(window):
        glfw.poll_events()

        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()

        # ESC 退出
        if imgui.is_key_pressed(imgui.Key.escape, False):
            glfw.set_window_should_close(window, True)

        draw_main_dockspace()

        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
        glfw.swap_buffers(window)

    # ── 清理 ──
    imgui.backends.opengl3_shutdown()
    imgui.backends.glfw_shutdown()
    imgui.destroy_context()
    glfw.terminate()
    print("[GUI Test] Done")


if __name__ == "__main__":
    main()
