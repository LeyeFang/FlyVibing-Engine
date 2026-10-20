import os

from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import apply_custom_style
from Application.Editor.UI.FileDialog import FileDialog
from Application.Editor.Services.ImportService import ImportService
from Application.Editor.I18n import t

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

    # 默认工作区：一个右侧面板 + 三个标签页。其余面板（Settings、扩展监视器）
    # 启动时隐藏，由菜单/扩展启用路径按需打开。
    DEFAULT_PANEL_ORDER = ("Scene", "Resources", "Node Editor")
    DEFAULT_VISIBLE_PANELS = frozenset(DEFAULT_PANEL_ORDER)
    DEFAULT_DOCK_RIGHT_FRACTION: float = 1.0 / 3.0
    _right_dock_id: int = 0

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
        """每帧由 ImguiLayer 调用：菜单栏 → 右侧 DockSpace → 各面板"""
        # 首次运行时应用自定义主题
        if not cls._style_applied:
            apply_custom_style()
            cls._style_applied = True

        # ── 主视口 / 菜单栏 ──
        # begin_main_menu_bar 自己创建 ##MainMenuBar 窗口；不再套一层全屏
        # MainDockSpace（全屏窗口会挡住右侧面板的 tab 命中，导致标签点不动）。
        cls._draw_menu_bar()

        # 菜单栏绘制后 main viewport 的 work_pos/work_size 已经让出菜单高度。
        viewport = imgui.get_main_viewport()
        content_top = viewport.work_pos.y
        content_h = max(1.0, viewport.work_size.y - cls.STATUS_BAR_HEIGHT)

        # ── 右侧 1/3 独立 DockSpace ──
        # 左侧 2/3 不创建 dock 节点，因此不会出现空 tab bar
        # （那条菜单栏下的空栏正是左侧 central node 的单 tab bar）。
        right_w = viewport.work_size.x * cls.DEFAULT_DOCK_RIGHT_FRACTION
        right_pos = imgui.ImVec2(
            viewport.work_pos.x + viewport.work_size.x - right_w,
            content_top,
        )

        first_layout = not cls._dock_layout_done
        if first_layout:
            # 启动工作区只保留三个主标签页；Settings / 扩展监视器默认关闭。
            for panel in cls._panels:
                if panel.name not in cls.DEFAULT_VISIBLE_PANELS:
                    panel.visible = False

        right_flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.no_nav_focus
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_scroll_with_mouse
            | imgui.WindowFlags_.no_docking
        )
        imgui.set_next_window_pos(right_pos)
        imgui.set_next_window_size(imgui.ImVec2(right_w, content_h))
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 0))
        imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0, 0, 0, 0))
        imgui.begin("##RightDockHost", None, right_flags)
        imgui.pop_style_var()
        imgui.pop_style_color()
        right_dockspace_id = imgui.get_id("##RightDockSpace")
        cls._right_dock_id = right_dockspace_id
        cls._dockspace_id = right_dockspace_id
        imgui.dock_space(right_dockspace_id, (0.0, 0.0),
                         imgui.DockNodeFlags_.none)
        imgui.end()
        cls._dock_layout_done = True

        # ── 依次绘制所有可见面板 (快照迭代: 面板可能在处理链上被注销) ──
        # 默认三标签页按 DEFAULT_PANEL_ORDER 排序，不依赖注册顺序；扩展/其他
        # 面板保持原注册顺序排在后面。
        panels = list(cls._panels)
        by_name = {p.name: p for p in panels}
        ordered = [by_name[n] for n in cls.DEFAULT_PANEL_ORDER if n in by_name]
        ordered += [p for p in panels if p.name not in cls.DEFAULT_VISIBLE_PANELS]
        cls._panel_rects.clear()
        for panel in ordered:
            if panel.visible:
                # 首帧用 set_next_window_dock_id 显式把三个主面板放到同一个
                # 右侧节点；比按窗口标题名 DockBuilderDockWindow 更可靠（标题
                # 会随语言变化，但窗口 dock 目标不会）。
                if first_layout and panel.name in cls.DEFAULT_VISIBLE_PANELS \
                        and cls._right_dock_id:
                    imgui.set_next_window_dock_id(
                        cls._right_dock_id, imgui.Cond_.always)
                expanded = panel.begin_panel()
                # 📸 无论展开还是折叠，都记录窗口矩形，防止摄像头穿透
                pos = imgui.get_window_pos()
                size = imgui.get_window_size()
                cls._panel_rects.append((pos.x, pos.y, size.x, size.y))
                if expanded:
                    panel.draw()
                panel.end_panel()

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

    # ── Examples ──────────────────────────────────────────────

    @classmethod
    def _example_dirs(cls) -> list[str]:
        """示例工程目录（开发区优先，发布区预留）。"""
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        return [
            os.path.join(repo, "Examples"),
            os.path.join(repo, "Test", "TestProject", "Examples"),
        ]

    @classmethod
    def _example_projects(cls) -> list[tuple[str, str]]:
        """返回 [(显示名, .myproj 绝对路径)]，支持每个示例一个子目录。"""
        raw: list[tuple[str, str, str]] = []  # (label, folder, path)
        for root in cls._example_dirs():
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                path = os.path.join(root, name)
                if os.path.isfile(path) and name.lower().endswith(".myproj"):
                    raw.append((os.path.splitext(name)[0], "", path))
                    continue
                if not os.path.isdir(path):
                    continue
                for sub in sorted(os.listdir(path)):
                    proj = os.path.join(path, sub)
                    if os.path.isfile(proj) and sub.lower().endswith(".myproj"):
                        raw.append((os.path.splitext(sub)[0], name, proj))
        counts: dict[str, int] = {}
        for label, _folder, _path in raw:
            counts[label.lower()] = counts.get(label.lower(), 0) + 1
        return sorted(
            (((f"{folder}/{label}" if counts.get(label.lower(), 0) > 1 else label), path)
             for label, folder, path in raw),
            key=lambda item: item[0].lower(),
        )

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
            print("[Export] Save the project first — File -> Save Project As...")
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
    # 菜单栏（独立 BeginMainMenuBar 窗口）
    # ============================================================

    @classmethod
    def _draw_menu_bar(
        cls
    ) -> None:
        """绘制顶层菜单栏；由 begin_main_menu_bar 自己创建窗口。"""
        if imgui.begin_main_menu_bar():

            # ── File 菜单 ──
            if imgui.begin_menu(t("menu.file.title"), True):
                if imgui.menu_item(t("menu.file.new_project"), "", False, True)[0]:
                    cls._on_new_project()
                if imgui.menu_item(t("menu.file.open_project"), "", False, True)[0]:
                    cls._on_open_project()
                examples = cls._example_projects()
                if examples:
                    if imgui.begin_menu(t("menu.file.open_example")):
                        for label, path in examples:
                            if imgui.menu_item(label, "", False, True)[0]:
                                cls._do_open_project(path)
                        imgui.end_menu()
                imgui.separator()
                from Application.Editor.ProjectManager import ProjectManager
                has_path = bool(ProjectManager.is_open() and ProjectManager.get_project_dir())
                if not has_path:
                    imgui.begin_disabled(True)
                if imgui.menu_item(t("menu.file.save_project"), "Ctrl+S", False, True)[0]:
                    cls._on_save_project()
                if not has_path:
                    imgui.end_disabled()
                if imgui.menu_item(t("menu.file.save_project_as"), "Ctrl+Shift+S", False, True)[0]:
                    cls._on_save_as_project()
                imgui.separator()
                if imgui.menu_item(t("menu.file.export"), "", False, True)[0]:
                    cls._on_export_project()
                imgui.separator()
                if imgui.menu_item(t("menu.file.exit"), "Alt+F4", False, True)[0]:
                    cls._on_exit()
                imgui.end_menu()

            # ── Edit 菜单 ──
            if imgui.begin_menu(t("menu.edit.title"), True):
                if imgui.menu_item(t("menu.edit.undo"), "Ctrl+Z", False, False)[0]:
                    pass
                if imgui.menu_item(t("menu.edit.redo"), "Ctrl+Y", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item(t("menu.edit.preferences"), "", False, True)[0]:
                    from Application.Editor.UI.panels.SettingsPanel import SettingsPanel
                    SettingsPanel.open()
                imgui.end_menu()

            # ── View 菜单：切换面板可见性（动态枚举 — 扩展窗口自动纳入） ──
            if imgui.begin_menu(t("menu.view.title"), True):
                for panel in list(cls._panels):
                    pname = str(panel.name or "")
                    if not pname or pname.startswith("##"):
                        continue
                    label = t(panel.title_key) if getattr(panel, "title_key", "") else pname
                    _, panel.visible = imgui.menu_item(
                        label, "", panel.visible, True
                    )
                imgui.end_menu()

            # ── Extensions 菜单：扩展启停 / 增量扫描入口 ──
            from Application.Editor.Extensions.ExtensionMenu import draw_extensions_menu
            draw_extensions_menu()

            # ── Help 菜单 ──
            if imgui.begin_menu(t("menu.help.title"), True):
                if imgui.menu_item(t("menu.help.about"), "", False, True)[0]:
                    pass
                imgui.end_menu()

            imgui.end_main_menu_bar()

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
