from imgui_bundle import imgui

# DockBuilder API 在 imgui.internal 命名空间
from imgui_bundle import imgui as imgui_internal

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import apply_custom_style
from Application.Editor.UI.FileDialog import FileDialog
from Application.Editor.Services.ImportService import ImportService

# ── 输入状态 (状态栏显示修饰键/组合键) ──
from Application.Core.Input import (
    GetModifierMask, GetHeldKeys, GetMouseButtonLabel,
)
from Application.Core.Events.Enum.InputEnum import KeyModifier, KeyButtonCode


class UIManager:
    """面板注册中心 + DockSpace 布局管理器"""

    # ============================================================
    # 类属性
    # ============================================================

    _panels: list[BasePanel] = []
    _dockspace_id: int = 0
    _dock_layout_done: bool = False
    _style_applied: bool = False

    # 底部状态栏高度 (像素)
    STATUS_BAR_HEIGHT: float = 22.0

    # 由渲染线程在 draw_all 中写入，主线程在 ImguiLayer.OnEvent 中读取
    # (x, y, w, h) — 用于判断鼠标是否落在面板区域内
    _panel_rects: list[tuple[float, float, float, float]] = []

    # ============================================================
    # 面板注册
    # ============================================================

    @classmethod
    def register(
        cls,
        panel: BasePanel
    ) -> BasePanel:
        """注册一个面板实例，触发其 on_attach 回调"""
        panel.on_attach()
        cls._panels.append(panel)
        return panel

    @classmethod
    def find(
        cls,
        name: str
    ) -> BasePanel | None:
        """按名称查找已注册的面板"""
        for p in cls._panels:
            if p.name == name:
                return p
        return None

    # ============================================================
    # 每帧绘制
    # ============================================================

    @classmethod
    def draw_all(
        cls
    ) -> None:
        """每帧由 ImguiLayer 调用：画 DockSpace 背景 → 菜单栏 → 各面板"""
        # 首次运行时应用自定义主题
        if not cls._style_applied:
            apply_custom_style()
            cls._style_applied = True

        # ── 准备全屏 DockSpace 背景窗口 ──
        viewport = imgui.get_main_viewport()
        # 底部留出状态栏空间
        dockspace_h = viewport.work_size.y - cls.STATUS_BAR_HEIGHT
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
        )

        # 取消圆角、边框、内边距，背景透明（让 3D 场景透出来，面板贴边）
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 0))
        imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0, 0, 0, 0))

        imgui.begin("MainDockSpace", None, window_flags)
        imgui.pop_style_var(3)
        imgui.pop_style_color()

        # ── 绘制主菜单栏（必须在 MainDockSpace 内部） ──
        cls._draw_menu_bar()

        # ── 创建 DockSpace 停靠系统 ──
        dockspace_id = imgui.get_id("MainDockSpace")
        cls._dockspace_id = dockspace_id
        imgui.dock_space(
            dockspace_id,
            (0.0, 0.0),
            imgui.DockNodeFlags_.none)

        # 首次运行时设置默认停靠布局
        if not cls._dock_layout_done:
            cls._setup_default_dock_layout(dockspace_id)
            cls._dock_layout_done = True

        # ── 依次绘制所有可见面板 ──
        cls._panel_rects.clear()
        for panel in cls._panels:
            if panel.visible:
                expanded = panel.begin_panel()
                # 📸 无论展开还是折叠，都记录窗口矩形，防止摄像头穿透
                pos = imgui.get_window_pos()
                size = imgui.get_window_size()
                cls._panel_rects.append((pos.x, pos.y, size.x, size.y))
                if expanded:
                    panel.draw()
                panel.end_panel()

        imgui.end()  # MainDockSpace

        # ── 渲染文件对话框 (在 DockSpace 外部, 独立窗口) ──
        FileDialog.render()

        # ── 底部状态栏 ──
        cls._draw_status_bar()

    # ============================================================
    # 菜单栏（内联在 MainDockSpace 中）
    # ============================================================

    @classmethod
    def _draw_menu_bar(
        cls
    ) -> None:
        """
        在主窗口内绘制菜单栏（不单独开窗口）。
        必须放在 imgui.begin() 和 dock_space() 之间。
        """
        if imgui.begin_main_menu_bar():

            # ── File 菜单 ──
            if imgui.begin_menu("File", True):
                # Import 子菜单
                if imgui.begin_menu("Import", True):
                    if imgui.menu_item("Mesh...", "", False, True)[0]:
                        FileDialog.open_mesh(ImportService.load_mesh)
                    if imgui.menu_item("Texture...", "", False, True)[0]:
                        FileDialog.open_texture(ImportService.load_texture)
                    if imgui.menu_item("Shader...", "", False, True)[0]:
                        FileDialog.open_shader(ImportService.load_shader)
                    imgui.end_menu()
                imgui.separator()
                if imgui.menu_item("New Scene", "Ctrl+N", False, False)[0]:
                    pass
                if imgui.menu_item("Open Scene...", "Ctrl+O", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Save Scene", "Ctrl+S", False, False)[0]:
                    pass
                if imgui.menu_item("Save As...", "Ctrl+Shift+S", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Exit", "Alt+F4", False, False)[0]:
                    pass
                imgui.end_menu()

            # ── Edit 菜单 ──
            if imgui.begin_menu("Edit", True):
                if imgui.menu_item("Undo", "Ctrl+Z", False, False)[0]:
                    pass
                if imgui.menu_item("Redo", "Ctrl+Y", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Preferences...", "", False, False)[0]:
                    pass
                imgui.end_menu()

            # ── View 菜单：切换面板可见性 ──
            if imgui.begin_menu("View", True):
                for target_name in [
                    "Scene",
                    "Node Editor",
                    "Resources",
                    "Properties",
                    "Console"
                ]:
                    panel = cls.find(target_name)
                    if panel:
                        _, panel.visible = imgui.menu_item(
                            target_name, "", panel.visible, True
                        )
                imgui.end_menu()

            # ── Help 菜单 ──
            if imgui.begin_menu("Help", True):
                if imgui.menu_item("About", "", False, True)[0]:
                    pass
                imgui.end_menu()

            imgui.end_main_menu_bar()

    # ============================================================
    # 默认停靠布局
    # ============================================================

    @classmethod
    def _setup_default_dock_layout(
        cls,
        dockspace_id: int
    ) -> None:
        """
        Scene + Node Editor + Resources → 右侧 1/4 标签页。
        """
        internal = imgui_internal.internal

        # 分割: 右侧 1/4
        result = internal.dock_builder_split_node(
            dockspace_id, imgui.Dir_.right, 0.25,
        )
        dock_right = result.id_at_dir

        # 停靠到右侧 (同一节点 → 自动标签页)
        internal.dock_builder_dock_window("Scene", dock_right)
        internal.dock_builder_dock_window("Node Editor", dock_right)
        internal.dock_builder_dock_window("Resources", dock_right)

        internal.dock_builder_finish(dockspace_id)

    # ============================================================
    # 状态栏
    # ============================================================

    @classmethod
    def _draw_status_bar(cls) -> None:
        """绘制底部状态栏 — 显示当前修饰键/组合键/鼠标按键状态。"""
        viewport = imgui.get_main_viewport()
        bar_y = viewport.work_pos.y + viewport.work_size.y - cls.STATUS_BAR_HEIGHT

        imgui.set_next_window_pos(imgui.ImVec2(viewport.work_pos.x, bar_y))
        imgui.set_next_window_size(imgui.ImVec2(viewport.work_size.x, cls.STATUS_BAR_HEIGHT))

        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(10, 3))
        imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.176, 0.176, 0.176, 1.00))

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

        # ── 左下: 输入状态文字 ──
        status_text = cls._build_input_status_text()
        if status_text:
            imgui.text(status_text)

        # ── 右下: 可扩展 (FPS / 实体数 / ...) ──
        # (预留)

        imgui.end()
        imgui.pop_style_color()
        imgui.pop_style_var(3)

    @staticmethod
    def _build_input_status_text() -> str:
        """构造状态栏左下角的输入状态文字。

        格式示例:
            "Ctrl"
            "Shift"
            "Ctrl + Shift"
            "Ctrl + G"
            "Shift + Mouse Button 1"
            "Ctrl + Shift + Mouse Button 1"
        """
        mod_mask = GetModifierMask()
        held_keys = GetHeldKeys()
        mouse_label = GetMouseButtonLabel()

        parts: list[str] = []

        # ── 修饰键部分 ──
        if mod_mask & KeyModifier.CTRL:
            parts.append("Ctrl")
        if mod_mask & KeyModifier.SHIFT:
            parts.append("Shift")
        if mod_mask & KeyModifier.ALT:
            parts.append("Alt")

        # ── 普通按键部分 (取第一个非修饰键) ──
        if held_keys:
            key_name = KeyButtonCode[held_keys[0]]  # 枚举名称, 如 "G", "Space", "F1"
            parts.append(key_name)
        elif mouse_label:
            # ── 鼠标按键部分 (仅在无普通按键时显示) ──
            parts.append(mouse_label)

        if not parts:
            return ""

        return " + ".join(parts)

    # ============================================================
    # 工具方法
    # ============================================================

    @classmethod
    def toggle_panel(
        cls,
        name: str
    ) -> None:
        """切换指定面板的可见性"""
        panel = cls.find(name)
        if panel:
            panel.visible = not panel.visible
