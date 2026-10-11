import os

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

    @classmethod
    def unregister(
        cls,
        panel: BasePanel
    ) -> bool:
        """移除一个已注册面板（触发 on_detach 回调）。返回是否成功移除。"""
        try:
            cls._panels.remove(panel)
        except ValueError:
            return False
        try:
            panel.on_detach()
        except Exception:  # noqa: BLE001
            pass
        return True

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

        # ── 依次绘制所有可见面板 (快照迭代: 面板可能在处理链上被注销) ──
        cls._panel_rects.clear()
        for panel in list(cls._panels):
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
    # Project 菜单回调
    # ============================================================

    @classmethod
    def _on_new_project(cls) -> None:
        """创建新项目 → 清空当前场景，恢复到默认状态。"""
        from Application.Editor.ProjectManager import ProjectManager
        from Application.Editor.EditorHost import EditorHost

        # 0. 清空旧场景注册表
        EditorHost._scenes.clear()
        EditorHost._active_scene = None

        # 1. 清空 esper 数据库
        import esper
        try:
            esper.clear_database()
        except Exception:
            pass

        # 2. 重置 SceneManager 追踪数据
        scene_mgr = EditorHost.scene
        if scene_mgr is not None:
            scene_mgr.entities.clear()
            scene_mgr._entity_names.clear()
            scene_mgr._entity_parent.clear()
            scene_mgr._editor_visible.clear()
            scene_mgr.scene_camera = None
            scene_mgr.scene_camera_id = None

        # 3. 重新创建默认实体（cameras + cube）
        scene_mgr.cam_mgr.create_defaults(scene_mgr)
        from Application.Core.Scene.SceneManager import SceneManager
        SceneManager._create_default_cube(scene_mgr)

        # 4. 清空渲染器命令队列 + 可见集合 + 注册新实体
        renderer = getattr(EditorHost, 'renderer', None)
        if renderer is not None:
            # 清空待处理命令（避免旧 entity 的注册命令被执行）
            if hasattr(renderer, '_command_queue') and renderer._command_queue is not None:
                renderer._command_queue.dequeue_all()
            # 清空可见集合
            if hasattr(renderer, '_resources') and hasattr(renderer._resources, '_visible_entities'):
                renderer._resources._visible_entities.clear()
            # 清空已注册 entity（旧 VAO 引用）
            if hasattr(renderer, 'registered_entities'):
                renderer.registered_entities.clear()
            # 注册默认实体
            from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand
            for eid_str in list(scene_mgr.entities.keys()):
                renderer.enqueue(EntityRegistrationCommand(int(eid_str), register=True))

        # 5. 创建新 Project（仅内存）
        ProjectManager.create_new("Untitled")
        # ★ 主线程安全同步窗口标题
        ProjectManager._update_window_title()

        # 6. 重置视口到 3D
        try:
            from Application.Editor.UI.controllers.ViewportController import ViewportController
            ViewportController.switch_to_3d()
        except Exception:
            pass

        # 7. 清除选中
        try:
            from Application.Editor.UI.controllers.SelectionController import SelectionController
            SelectionController.clear()
        except Exception:
            pass

        print("[Project] New project created — all states reset to defaults")

    @classmethod
    def _on_open_project(cls) -> None:
        """打开已有项目 → 弹出打开对话框。"""
        from Application.Editor.UI.FileDialog import FileDialog
        FileDialog.open_project(
            callback=lambda p: cls._do_open_project(p),
        )

    @classmethod
    def _do_open_project(cls, path: str) -> None:
        if not path:
            return
        from Application.Editor.ProjectManager import ProjectManager
        ProjectManager.open_project(path)

    @classmethod
    def _on_save_project(cls) -> None:
        from Application.Editor.ProjectManager import ProjectManager
        ProjectManager.save_project()

    @classmethod
    def _on_save_as_project(cls) -> None:
        """另存为 → 弹出保存对话框。"""
        from Application.Editor.UI.FileDialog import FileDialog
        from Application.Editor.ProjectManager import ProjectManager
        default_name = f"{ProjectManager.get_project_name()}.myproj"
        FileDialog.save_project(
            callback=lambda p: cls._do_save_as_project(p),
            default_name=default_name,
        )

    @classmethod
    def _do_save_as_project(cls, path: str) -> None:
        if not path:
            return
        from Application.Editor.ProjectManager import ProjectManager
        ProjectManager.save_project_as(path)

    @classmethod
    def _on_export_project(cls) -> None:
        """导出 → 打开目标文件夹选择对话框（非阻塞；选中目录下创建 <项目名>/）。"""
        from Application.Editor.ProjectManager import ProjectManager
        if not ProjectManager.get_project_path():
            print("[Export] Save the project first — File ▸ Save Project As...")
            return
        start = os.path.dirname(ProjectManager.get_project_path())
        FileDialog.open_export_dir(
            callback=lambda p: cls._do_export_project(p),
            start_dir=start,
        )

    @classmethod
    def _do_export_project(cls, target_dir: str) -> None:
        """FileDialog 回调：执行自包含工程导出（项目 + 场景 + 资源，路径全部相对化）。"""
        if not target_dir:
            return
        from Application.Editor.ProjectManager import ProjectManager
        ProjectManager.export_project_bundle(target_dir)

    @classmethod
    def _on_exit(cls) -> None:
        """退出应用 — 通过 WindowCloseEvent 走与关闭窗口相同的逻辑。"""
        from Application.Core.Events.WindowEvent import WindowCloseEvent
        from Application.Editor.EditorHost import EditorHost
        WindowCloseEvent.Pack(engine=EditorHost)

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
                if imgui.menu_item("New Project", "", False, True)[0]:
                    cls._on_new_project()
                if imgui.menu_item("Open Project...", "", False, True)[0]:
                    cls._on_open_project()
                imgui.separator()
                from Application.Editor.ProjectManager import ProjectManager
                has_path = bool(ProjectManager.is_open() and ProjectManager.get_project_dir())
                if not has_path:
                    imgui.begin_disabled(True)
                if imgui.menu_item("Save Project", "Ctrl+S", False, True)[0]:
                    cls._on_save_project()
                if not has_path:
                    imgui.end_disabled()
                if imgui.menu_item("Save Project As...", "Ctrl+Shift+S", False, True)[0]:
                    cls._on_save_as_project()
                imgui.separator()
                if imgui.menu_item("Export...", "", False, True)[0]:
                    cls._on_export_project()
                imgui.separator()
                if imgui.menu_item("Exit", "Alt+F4", False, True)[0]:
                    cls._on_exit()
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

            # ── View 菜单：切换面板可见性（动态枚举 — 扩展窗口自动纳入） ──
            if imgui.begin_menu("View", True):
                for panel in list(cls._panels):
                    pname = str(panel.name or "")
                    if not pname or pname.startswith("##"):
                        continue
                    _, panel.visible = imgui.menu_item(
                        pname, "", panel.visible, True
                    )
                imgui.end_menu()

            # ── Extensions 菜单：扩展启停 / 增量扫描入口 ──
            from Application.Editor.Extensions.ExtensionMenu import draw_extensions_menu
            draw_extensions_menu()

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
