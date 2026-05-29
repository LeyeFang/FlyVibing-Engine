from imgui_bundle import imgui

# DockBuilder API 在 imgui.internal 命名空间
from imgui_bundle import imgui as imgui_internal

from Application.Core.UI.BasePanel import BasePanel
from Application.Core.UI.PanelStyle import apply_custom_style


class UIManager:
    """面板注册中心 + DockSpace 布局管理器"""

    # ============================================================
    # 类属性
    # ============================================================

    _panels: list[BasePanel] = []
    _dockspace_id: int = 0
    _dock_layout_done: bool = False
    _style_applied: bool = False

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
        imgui.set_next_window_pos(viewport.work_pos)
        imgui.set_next_window_size(viewport.work_size)
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

        # 取消圆角和边框，背景透明（让 3D 场景透出来）
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0, 0, 0, 0))

        imgui.begin("MainDockSpace", None, window_flags)
        imgui.pop_style_var(2)
        imgui.pop_style_color()

        # ── 绘制主菜单栏（必须在 MainDockSpace 内部） ──
        cls._draw_menu_bar()

        # ── 创建 DockSpace 停靠系统 ──
        dockspace_id = imgui.get_id("MainDockSpace")
        cls._dockspace_id = dockspace_id
        imgui.dock_space(dockspace_id, (0.0, 0.0),
                         imgui.DockNodeFlags_.none)

        # 首次运行时设置默认停靠布局
        if not cls._dock_layout_done:
            cls._setup_default_dock_layout(dockspace_id)
            cls._dock_layout_done = True

        # ── 依次绘制所有可见面板 ──
        cls._panel_rects.clear()
        for panel in cls._panels:
            if panel.visible:
                if panel.begin_panel():
                    # 📸 记录面板窗口矩形，供下一帧事件处理判断鼠标归属
                    pos = imgui.get_window_pos()
                    size = imgui.get_window_size()
                    cls._panel_rects.append((pos.x, pos.y, size.x, size.y))
                    panel.draw()
                panel.end_panel()

        imgui.end()  # MainDockSpace

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
        创建默认分栏布局：
          ┌────────────┬──────────────────────────┐
          │   Scene    │     Node Editor          │
          │  (left)    │     (center)             │
          └────────────┴──────────────────────────┘
        """
        internal = imgui_internal.internal

        # 重置 dock 树
        internal.dock_builder_remove_node(dockspace_id)
        internal.dock_builder_add_node(dockspace_id)

        # 左右分割：左 20% Scene，右 80% Node Editor
        _, dock_left, dock_center = internal.dock_builder_split_node_py(
            dockspace_id, imgui.Dir_.left, 0.20
        )

        # 将面板窗口分配到对应的 dock 节点
        internal.dock_builder_dock_window("Scene", dock_left)
        internal.dock_builder_dock_window("Node Editor", dock_center)

        internal.dock_builder_finish(dockspace_id)

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
