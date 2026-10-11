from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import (
    BLENDER_ORANGE,
    SUCCESS_GREEN,
    WARNING_AMBER,
    ERROR_RED,
)
from Application.Editor.Services.ControllerRegistry import (
    get_ctrl,
    NAME_SIMULATION,
    NAME_SCENE_BROWSER,
    NAME_RESOURCE_BROWSER,
    NAME_VIEWPORT,
    NAME_SELECTION,
)

# ── Font Awesome 6 图标 (imgui_bundle 内置矢量图标方案) ─────
from imgui_bundle import icons_fontawesome_6 as fa

from Application.Editor.UI.FileDialog import FileDialog


class ScenePanel(BasePanel):
    """场景管理器面板 — 四区域布局:
      1. 场景信息 + 运行控制
      2. 2D / 3D / Overlay 视口模式
      3. Entity 树 (可展开，父子层级)
      4. 选中 Entity 的组件检视
    """

    name = "Scene"
    flags = imgui.WindowFlags_.none

    def __init__(
        self
    ) -> None:
        super().__init__()
        self.visible = True
        # ── 从 ControllerRegistry 获取控制器 ──
        self._sim_ctrl = get_ctrl(NAME_SIMULATION)
        self._browser_ctrl = get_ctrl(NAME_SCENE_BROWSER)
        self._resource_ctrl = get_ctrl(NAME_RESOURCE_BROWSER)
        self._viewport_ctrl = get_ctrl(NAME_VIEWPORT)
        self._selection_ctrl = get_ctrl(NAME_SELECTION)
        # ── Transform 空间模式: True=Local, False=Global ──
        self._transform_local: bool = False  # 默认 Global
        # ── 新建场景输入缓冲 ──
        self._new_scene_name: str = ""
        # ── Entity 树: 选中联动 (reveal: 选中变化时展开祖先链一次) ──
        self._last_selected: int | None = None
        self._reveal_pending: bool = False

    # ============================================================
    # Material I/O 回调
    # ============================================================

    @staticmethod
    def _on_mat_save(entity_id: int, file_path: str) -> None:
        """FileDialog 回调: 保存 material 到 .mat 文件。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
        if file_path:
            if not file_path.endswith(".mat"):
                file_path += ".mat"
            SceneBrowserController.save_material_to_file(entity_id, file_path)
            # ★ 自动注册到项目（携带运行时 material_id）
            from Application.Editor.ProjectManager import ProjectManager
            from Application.Editor.EditorHost import EditorHost
            if ProjectManager.is_open():
                mid = EditorHost.scene.GetEntityMaterial(entity_id)
                ProjectManager.register_material(file_path, mid)

    @staticmethod
    def _on_mat_load(entity_id: int, file_path: str) -> None:
        """FileDialog 回调: 从 .mat 文件加载 material。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
        if file_path:
            SceneBrowserController.load_material_from_file(entity_id, file_path)

    # ============================================================
    # Scene I/O 回调
    # ============================================================

    def _on_save_scene(self) -> None:
        """打开保存场景对话框 → 选择路径 → 执行保存。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        default_name = f"{scene.name}.scene" if scene else "Untitled.scene"
        FileDialog.save_scene(
            callback=lambda p: self._do_save_scene(p),
            default_name=default_name,
        )

    @staticmethod
    def _do_save_scene(path: str) -> None:
        """执行场景保存到 .scene 文件。"""
        if not path:
            return
        # ★ 确保有 .scene 后缀
        if not path.endswith(".scene"):
            path += ".scene"
        from Application.Editor.EditorHost import EditorHost
        ok = EditorHost.save_active_scene_to_file(path)
        if ok:
            print(f"[ScenePanel] Scene saved to: {path}")
            # ★ 自动设为项目启动场景
            from Application.Editor.ProjectManager import ProjectManager
            if ProjectManager.is_open():
                ProjectManager.set_startup_scene(path)
        else:
            print(f"[ScenePanel] ERROR: Failed to save scene to: {path}")

    def _on_load_scene(self) -> None:
        """打开加载场景对话框 → 选择文件 → 执行加载。"""
        FileDialog.open_scene(
            callback=lambda p: self._do_load_scene(p),
        )

    @staticmethod
    def _do_load_scene(path: str) -> None:
        """执行从 .scene 文件加载场景。"""
        if not path:
            return
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.load_scene_from_file(path)
        if scene is not None:
            print(f"[ScenePanel] Scene loaded from: {path}")
            print(f"  Name: {scene.name}")
            print(f"  Entities: {len(scene.entities)}")
            print(f"  Node Graph: {'present' if scene.node_graph else 'none'}")
        else:
            print(f"[ScenePanel] ERROR: Failed to load scene from: {path}")

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(
        self
    ) -> None:
        """四区域布局 — 橙色标题 + separator 分隔，区域内无线条。"""
        # ── 区域 1: Scene Information ──
        self._draw_section_title("Scene Information")
        self._draw_header()
        self._draw_controls()

        # ── 区域 2: Scene Type ──
        imgui.spacing()
        imgui.separator()
        self._draw_section_title("Scene Type")
        self._draw_viewport_mode()

        # ── 区域 3: Entities ──
        imgui.spacing()
        imgui.separator()
        self._draw_section_title("Entities")
        self._draw_entity_tree()

        # ── 区域 4: Inspector (含实体名) ──
        selected = self._selection_ctrl.get_selected()
        if selected is not None:
            info = self._browser_ctrl.get_entity_info(selected)
            entity_name = (info.get('name', '') if info else '') or f"Entity #{selected}"
            imgui.spacing()
            imgui.separator()
            self._draw_section_title(f"Inspector  —  \"{entity_name}\"")
            self._draw_entity_summary(selected)

    # ============================================================
    # 区域 1: 场景名 + 运行控制
    # ============================================================

    def _draw_header(
        self
    ) -> None:
        """场景下拉选择器 — Scene: [▼列表] [+] [💾保存] [📂加载]。"""
        scene_names = self._browser_ctrl.get_scene_names()
        current_name = self._browser_ctrl.get_active_scene_name()

        imgui.text("Scene:")
        imgui.same_line()
        # 为 [+] [💾] [📂] 三个按钮预留宽度
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 120)
        if imgui.begin_combo("##scene_select", current_name):
            for sname in scene_names:
                is_sel = (sname == current_name)
                if imgui.selectable(sname, is_sel)[0]:
                    self._browser_ctrl.switch_scene(sname)
                if is_sel:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_PLUS}##new_scene_btn"):
            imgui.open_popup("new_scene_popup")

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_FLOPPY_DISK}##save_scene_btn"):
            self._on_save_scene()

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_FOLDER_OPEN}##load_scene_btn"):
            self._on_load_scene()

        if imgui.begin_popup("new_scene_popup"):
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 0.90), "New Scene")
            imgui.spacing()
            imgui.push_item_width(180)
            changed, self._new_scene_name = imgui.input_text_with_hint(
                "##new_scene_input", "name...", self._new_scene_name, 64,
            )
            imgui.pop_item_width()
            imgui.same_line()
            name_ok = bool(self._new_scene_name.strip()) and (
                self._new_scene_name.strip() not in scene_names
            )
            if not name_ok:
                imgui.begin_disabled(True)
            if imgui.button("Create") or (
                name_ok and imgui.is_key_pressed(imgui.Key.enter)
            ):
                name = self._new_scene_name.strip()
                self._browser_ctrl.create_scene(name)
                self._new_scene_name = ""
                imgui.close_current_popup()
            if not name_ok:
                imgui.end_disabled()
            imgui.end_popup()

    def _draw_controls(
        self
    ) -> None:
        """绘制播放控制按钮组（使用 Font Awesome 6 矢量图标）。"""
        av = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        btn_w = (av - spacing * 2) / 3.0

        # ▶ Run — 绿色（仅在停止状态可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*SUCCESS_GREEN, 1.00))
        imgui.begin_disabled(not self._sim_ctrl.is_stopped())
        if imgui.button(f"{fa.ICON_FA_PLAY}  Run", (btn_w, 0)):
            self._sim_ctrl.play()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ⏸ Pause — 琥珀色（仅在运行时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*WARNING_AMBER, 1.00))
        imgui.begin_disabled(not self._sim_ctrl.is_running())
        if imgui.button(f"{fa.ICON_FA_PAUSE}  Pause", (btn_w, 0)):
            self._sim_ctrl.pause()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ■ Stop — 红色（仅在未停止时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*ERROR_RED, 1.00))
        imgui.begin_disabled(self._sim_ctrl.is_stopped())
        if imgui.button(f"{fa.ICON_FA_STOP}  Stop", (btn_w, 0)):
            self._sim_ctrl.stop()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        # 状态提示
        imgui.text_disabled(self._sim_ctrl.get_state_label())

        # ⚙ Settings — PIE 初始窗口行为 (全屏 / 窗口化尺寸)
        _gear = getattr(fa, 'ICON_FA_GEAR', '')
        if imgui.button(f"{_gear}  Settings##pie_settings", (-1, 0)):
            imgui.open_popup("pie_settings_popup")
        if imgui.begin_popup("pie_settings_popup"):
            self._draw_pie_settings_popup()
            imgui.end_popup()

    def _draw_pie_settings_popup(self) -> None:
        """PIE 初始窗口行为设置 (Settings 按钮弹出层; 下次 Run 生效)。"""
        s = self._sim_ctrl.get_pie_settings()
        imgui.text_disabled("PIE 启动窗口 (下次 Run 生效)")
        imgui.separator()

        _MODES = [("窗口化", "windowed"),
                  ("无边窗口 (全屏尺寸)", "borderless"),
                  ("独占全屏", "fullscreen")]
        labels = [m[0] for m in _MODES]
        keys = [m[1] for m in _MODES]
        cur = keys.index(s["mode"]) if s["mode"] in keys else 0
        changed, idx = imgui.combo("显示模式##pie", cur, labels)
        if changed:
            self._sim_ctrl.set_pie_settings(mode=keys[idx])
            cur = idx

        imgui.separator()
        imgui.begin_disabled(keys[cur] != "windowed")
        for label, pw, ph in (("1280 × 720", 1280, 720),
                              ("1600 × 900", 1600, 900),
                              ("1920 × 1080", 1920, 1080)):
            if imgui.small_button(f"{label}##pie"):
                self._sim_ctrl.set_pie_settings(width=pw, height=ph)
                s = self._sim_ctrl.get_pie_settings()
            imgui.same_line()
        imgui.new_line()
        cw, nw = imgui.input_int("宽度##pie", int(s["width"]))
        ch, nh = imgui.input_int("高度##pie", int(s["height"]))
        if cw or ch:
            self._sim_ctrl.set_pie_settings(width=nw, height=nh)
        imgui.end_disabled()

    # ============================================================
    # 通用: 区域标题
    # ============================================================

    @staticmethod
    def _draw_section_title(title: str) -> None:
        """统一的区域标题 — 橙色文字，上下留白。"""
        imgui.spacing()
        imgui.spacing()
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00), title)
        imgui.spacing()

    # ============================================================
    # 区域 2: Scene Type (GameType + 视口模式联动)
    # ============================================================

    def _draw_viewport_mode(
        self
    ) -> None:
        """绘制 Scene Type 切换按钮 — 同时控制 Scene.game_type 和编辑器视口模式。

        点击 2D / 3D 会:
          1. 更新 SceneManager.game_type → 切换默认活跃摄像机
          2. 更新 ViewportController → 切换 EditorCamera 正交/透视
        """
        av = imgui.get_content_region_avail().x
        btn_w = (av - imgui.get_style().item_spacing.x * 2) / 3.0

        # ── 从 SceneManager 读取当前 game_type 作为信源 ──
        current_gt = self._browser_ctrl.get_game_type()
        is_3d = (current_gt == "3d")
        is_2d = (current_gt == "2d")
        is_overlay = (current_gt == "overlay")

        # ── 3D 按钮 ──
        if is_3d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("3D", (btn_w, 0)):
            self._browser_ctrl.set_game_type("3d")
            self._viewport_ctrl.switch_to_3d()
        if is_3d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # ── 2D 按钮 ──
        if is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("2D", (btn_w, 0)):
            self._browser_ctrl.set_game_type("2d")
            self._viewport_ctrl.switch_to_2d()
        if is_2d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # ── Overlay 按钮 ──
        if is_overlay:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("Overlay", (btn_w, 0)):
            self._browser_ctrl.set_game_type("overlay")
            self._viewport_ctrl.switch_to_overlay()
        if is_overlay:
            imgui.pop_style_color(1)

    # ============================================================
    # 区域 3: Entity 树 (可展开父子层级, 支持拖拽建立父子关系)
    # ============================================================

    def _draw_entity_tree(
        self
    ) -> None:
        """绘制 Entity 层级树 + 工具栏按钮。"""
        # ── 工具栏: New / Delete ──
        self._draw_entity_toolbar()
        imgui.spacing()

        root_ids = self._browser_ctrl.get_root_entities()
        if not root_ids:
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00), "(empty scene)"
            )
            if imgui.begin_drag_drop_target():
                payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
                if payload is not None:
                    self._browser_ctrl.set_entity_parent(payload.data_id, 0)
                imgui.end_drag_drop_target()
            # ★ 空白区域右键菜单 (无实体时)
            self._draw_empty_area_context_menu()
            return

        selected = self._selection_ctrl.get_selected()
        # ★ Reveal: 选中变化 (视口点选 / MCP selection.set / entity.add 自动选中) → 展开祖先链一次
        if selected != self._last_selected:
            self._last_selected = selected
            self._reveal_pending = selected is not None
        reveal_chain: set[int] = set()
        if self._reveal_pending and selected is not None:
            eid = selected
            for _ in range(64):  # 防环防御
                if not eid:
                    break
                reveal_chain.add(int(eid))
                parent = self._browser_ctrl.get_entity_parent(eid)
                if not parent or parent == eid:
                    break
                eid = parent
        for entity_id in root_ids:
            self._draw_entity_node(entity_id, selected, reveal_chain)
        self._reveal_pending = False

        # ── 树底部空白: 拖放到此处解除父子关系 / 点击空白取消选中 ──
        imgui.dummy(imgui.ImVec2(imgui.get_content_region_avail().x, 20))
        if imgui.is_item_clicked():
            self._selection_ctrl.clear()
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
            if payload is not None:
                self._browser_ctrl.set_entity_parent(payload.data_id, 0)
            imgui.end_drag_drop_target()
        # ★ 空白区域右键菜单
        self._draw_empty_area_context_menu()

    def _draw_entity_toolbar(self) -> None:
        """绘制实体工具栏: New / Save / Delete。"""
        av = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        btn_w = (av - spacing * 2) / 3.0

        # ✨ New
        if imgui.button(f"{fa.ICON_FA_PLUS}  New", (btn_w, 0)):
            self._browser_ctrl.add_entity()
        imgui.same_line()

        # 💾 Save — 仅选中时可用
        selected = self._selection_ctrl.get_selected()
        save_disabled = (selected is None)
        if save_disabled:
            imgui.begin_disabled(True)
        if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save", (btn_w, 0)):
            self._save_selected_as_prefab(selected)
        if save_disabled:
            imgui.end_disabled()
        imgui.same_line()

        # 🗑 Delete — 仅选中时可用
        if selected is None:
            imgui.begin_disabled(True)
        if imgui.button(f"{fa.ICON_FA_TRASH}  Delete", (btn_w, 0)):
            self._browser_ctrl.delete_selected()
            self._selection_ctrl.clear()
        if selected is None:
            imgui.end_disabled()

    def _save_selected_as_prefab(self, selected_entity_id: int) -> None:
        """将选中实体及其子实体树保存为 .prefab 文件（非阻塞）。"""
        from Application.Editor.EditorHost import EditorHost
        from Application.Core.Scene.PrefabManager import PrefabManager
        from Application.Editor.UI.FileDialog import FileDialog

        name = EditorHost.scene._entity_names.get(
            selected_entity_id, f"Entity_{selected_entity_id}")
        default_name = f"{name}.prefab"

        # ★ 闭包捕获 selected_entity_id
        def _on_save(filepath: str) -> None:
            if not filepath:
                return
            PrefabManager.save_entity_tree(filepath, selected_entity_id, EditorHost.scene)

        FileDialog.save_prefab(_on_save, default_name=default_name)

    def _draw_entity_node(
        self,
        entity_id: int,
        selected_id: int | None,
        reveal_chain: set | None = None,
    ) -> None:
        """递归绘制单个实体节点及其子节点。支持拖拽重设父子关系 + 右键菜单。"""
        info = self._browser_ctrl.get_entity_info(entity_id)
        if info is None:
            return
        name = info.get('name', '') or f"Entity #{entity_id}"

        # ── 眼图标: 在 entity label 左侧 ──
        eye_visible = self._browser_ctrl.is_editor_visible(entity_id)
        eye_icon = fa.ICON_FA_EYE if eye_visible else fa.ICON_FA_EYE_SLASH
        if not eye_visible:
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(0.35, 0.35, 0.35, 1.00))
        if imgui.small_button(f"{eye_icon}##eye_{entity_id}"):
            # ★ 递归设置实体树可见性 (父 → 所有子实体)
            self._browser_ctrl.set_editor_visible_tree(entity_id, not eye_visible)
        if not eye_visible:
            imgui.pop_style_color(1)
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"Toggle editor visibility of '{name}' and its children")
        imgui.same_line()

        # ── 构建标签: 图标标记 ──
        flags_parts = [f"{fa.ICON_FA_CUBE} "]
        if info.get('has_camera'):
            flags_parts.append(f"{fa.ICON_FA_CAMERA} ")
        flags_str = "".join(flags_parts)

        label = f"{flags_str}{name}##{entity_id}"

        # ── 子节点 ──
        children = self._browser_ctrl.get_entity_children(entity_id)
        has_children = len(children) > 0

        # ★ Reveal: 选中实体的祖先节点 — 强制展开一次 (让选中项在树中可见)
        if (has_children and reveal_chain and entity_id in reveal_chain
                and entity_id != selected_id):
            imgui.set_next_item_open(True)

        if has_children:
            node_flags = imgui.TreeNodeFlags_.open_on_arrow
            if selected_id == entity_id:
                node_flags |= imgui.TreeNodeFlags_.selected
            opened = imgui.tree_node_ex(label, node_flags)
        else:
            # 叶子节点
            node_flags = imgui.TreeNodeFlags_.leaf | imgui.TreeNodeFlags_.no_tree_push_on_open
            if selected_id == entity_id:
                node_flags |= imgui.TreeNodeFlags_.selected
            opened = imgui.tree_node_ex(label, node_flags)

        # ★ 右键菜单 — 必须在 tree_node_ex 之后、子节点递归之前
        self._draw_entity_context_menu(entity_id)

        # ── 点击选中 ──
        if imgui.is_item_clicked():
            self._selection_ctrl.select(entity_id)

        # ── 拖拽源: 可以将此实体拖到其他实体上 ──
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("ENTITY", entity_id)
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 1.00), f"Entity #{entity_id}"
            )
            imgui.end_drag_drop_source()

        # ── 拖拽目标: 接受其他实体作为子实体 ──
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
            if payload is not None and payload.data_id != entity_id:
                self._browser_ctrl.set_entity_parent(payload.data_id, entity_id)
            imgui.end_drag_drop_target()

        if opened and has_children:
            for child_id in children:
                self._draw_entity_node(child_id, selected_id, reveal_chain)
            imgui.tree_pop()
        elif opened:
            # 叶子节点不需要 tree_pop
            pass

    # ============================================================
    # 右键菜单
    # ============================================================

    def _draw_entity_context_menu(self, entity_id: int) -> None:
        """绘制实体节点的右键菜单: Copy / Delete / Save as Prefab。

        必须在 tree_node_ex() 之后立即调用，因为 ImGui 右键菜单
        作用于「上一个提交的 item」。
        """
        if imgui.begin_popup_context_item(
            f"entity_ctx_{entity_id}",
            imgui.PopupFlags_.mouse_button_right,
        ):
            # ★ 选中该实体 (右键操作通常期望以该实体为目标)
            self._selection_ctrl.select(entity_id)

            if imgui.menu_item(f"{fa.ICON_FA_COPY}  Copy", "Ctrl+C", False, True)[0]:
                self._browser_ctrl.copy_entity(entity_id)
                imgui.close_current_popup()

            imgui.separator()

            if imgui.menu_item(f"{fa.ICON_FA_FLOPPY_DISK}  Save as Prefab", "", False, True)[0]:
                self._save_selected_as_prefab(entity_id)
                imgui.close_current_popup()

            imgui.separator()

            # ★ Delete 使用红色文字
            imgui.push_style_color(
                imgui.Col_.text, imgui.ImVec4(*ERROR_RED, 1.00))
            if imgui.menu_item(f"{fa.ICON_FA_TRASH}  Delete", "Del", False, True)[0]:
                self._browser_ctrl.delete_entity(entity_id)
                self._selection_ctrl.clear()
                imgui.close_current_popup()
            imgui.pop_style_color(1)

            imgui.end_popup()

    def _draw_empty_area_context_menu(self) -> None:
        """绘制 entity 列表空白区域的右键菜单: New / Paste。

        使用 begin_popup_context_window 实现右键点击窗口空白区域弹出菜单。
        """
        if imgui.begin_popup_context_window(
            "entity_list_empty_ctx",
            imgui.PopupFlags_.mouse_button_right
            | imgui.PopupFlags_.no_open_over_items,
        ):
            if imgui.menu_item(f"{fa.ICON_FA_PLUS}  New Entity", "", False, True)[0]:
                eid = self._browser_ctrl.add_entity()
                self._selection_ctrl.select(eid)
                imgui.close_current_popup()

            imgui.separator()

            # ★ Paste: 仅剪贴板有数据时可用
            has_clip = self._browser_ctrl.has_clipboard()
            if not has_clip:
                imgui.begin_disabled(True)
            if imgui.menu_item(f"{fa.ICON_FA_PASTE}  Paste", "Ctrl+V", False, True)[0]:
                eid = self._browser_ctrl.paste_entity()
                if eid is not None:
                    self._selection_ctrl.select(eid)
                imgui.close_current_popup()
            if not has_clip:
                imgui.end_disabled()

            imgui.end_popup()

    # ============================================================
    # 区域 4: 选中 Entity 的组件检视
    # ============================================================

    def _draw_entity_summary(
        self,
        entity_id: int
    ) -> None:
        """显示选中实体的所有组件（可展开、可编辑）。"""
        use_local = self._transform_local
        summary = self._browser_ctrl.get_summary(entity_id, use_local=use_local)
        if summary is None:
            imgui.text_disabled("(failed to load entity info)")
            return

        # ── 实体名称（可编辑）+ ID（灰色） ──
        name_buf = summary.name or ""
        changed, new_name = imgui.input_text(
            "##entity_name", name_buf, 256,
        )
        if changed:
            self._browser_ctrl.set_name(entity_id, new_name)
        if not summary.name:
            imgui.same_line()
            imgui.text_disabled("(click to name)")
        imgui.same_line()
        imgui.text_disabled("—")
        imgui.same_line()
        imgui.text_disabled(f"Entity #{summary.entity_id}")

        # ── Transform ──
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 2)
        imgui.begin_disabled(True)  # Transform 不可移除
        if imgui.button(f"-##remove_Transform_{entity_id}", (22, 0)):
            pass
        imgui.end_disabled()
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() - 2)
        imgui.same_line()
        if imgui.collapsing_header("Transform", imgui.TreeNodeFlags_.default_open):
            # ── Local / Global 切换 ──
            av = imgui.get_content_region_avail().x
            btn_w = (av - imgui.get_style().item_spacing.x) / 2.0

            if not use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Global", (btn_w, 0)):
                self._transform_local = False
            if not use_local:
                imgui.pop_style_color(1)
            imgui.same_line()
            if use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Local", (btn_w, 0)):
                self._transform_local = True
            if use_local:
                imgui.pop_style_color(1)

            imgui.spacing()

            pos = list(summary.position)
            changed, new_pos = imgui.drag_float3("Position", pos, 0.1, format="%.2f")
            if changed:
                self._browser_ctrl.set_position(entity_id, tuple(new_pos), use_local=use_local)

            rot = list(summary.rotation)
            changed, new_rot = imgui.drag_float3("Rotation", rot, 1.0, format="%.1f")
            if changed:
                self._browser_ctrl.set_rotation(entity_id, tuple(new_rot), use_local=use_local)

            scl = list(summary.scale)
            changed, new_scl = imgui.drag_float3("Scale", scl, 0.05, format="%.2f")
            if changed:
                self._browser_ctrl.set_scale(entity_id, tuple(new_scl), use_local=use_local)

        # ── MeshRenderer（有 mesh 才显示） ──
        if summary.mesh_id is not None:
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 2)
            if imgui.button(f"-##remove_MeshRenderer_{entity_id}", (22, 0)):
                self._browser_ctrl.remove_component(entity_id, "MeshRenderer")
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() - 2)
            imgui.same_line()
            if imgui.collapsing_header("MeshRenderer", imgui.TreeNodeFlags_.default_open):
                self._draw_mesh_renderer_editor(entity_id, summary)

        # ── Camera（有 camera 才显示，可编辑） ──
        if summary.has_camera:
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 2)
            if imgui.button(f"-##remove_Camera_{entity_id}", (22, 0)):
                self._browser_ctrl.remove_component(entity_id, "Camera")
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() - 2)
            imgui.same_line()
            if imgui.collapsing_header("Camera", imgui.TreeNodeFlags_.default_open):
                try:
                    cam = self._browser_ctrl.get_camera_info(entity_id)
                except Exception:
                    cam = None
                if cam:
                    # ── 投影类型 ──
                    is_persp = cam.get('is_perspective', True)
                    changed, new_persp = imgui.checkbox("Perspective", is_persp)
                    if changed:
                        self._browser_ctrl.set_camera_projection(entity_id, new_persp)
                        cam['is_perspective'] = new_persp

                    # ── 透视: FOV / 正交: ortho_size ──
                    if cam.get('is_perspective', True):
                        fov_val = float(cam.get('fov', 45.0))
                        changed, new_fov = imgui.drag_float("FOV", fov_val, 0.5, 1.0, 179.0, "%.1f")
                        if changed:
                            self._browser_ctrl.set_camera_fov(entity_id, new_fov)
                    else:
                        size_val = float(cam.get('ortho_size', 5.0))
                        changed, new_size = imgui.drag_float("Ortho Size", size_val, 0.1, 0.01, 1000.0, "%.2f")
                        if changed:
                            self._browser_ctrl.set_camera_ortho_size(entity_id, new_size)

                    # ── Aspect Ratio 预设 (联动 Camera Gizmo 2D 边界框) ──
                    _ASPECT_PRESETS = [
                        ("16:9",   16.0 / 9.0),
                        ("16:10",  16.0 / 10.0),
                        ("4:3",    4.0 / 3.0),
                        ("21:9",   21.0 / 9.0),
                        ("1:1",    1.0),
                    ]
                    current_ar = float(cam.get('aspect_ratio', 16.0 / 9.0))
                    preset_idx = min(
                        range(len(_ASPECT_PRESETS)),
                        key=lambda i: abs(_ASPECT_PRESETS[i][1] - current_ar)
                    )
                    changed_ar, new_idx = imgui.combo(
                        "Aspect Ratio", preset_idx,
                        [p[0] for p in _ASPECT_PRESETS]
                    )
                    if changed_ar:
                        self._browser_ctrl.set_camera_aspect_ratio(
                            entity_id, _ASPECT_PRESETS[new_idx][1])
                        cam['aspect_ratio'] = _ASPECT_PRESETS[new_idx][1]

                    # ── 裁剪平面 ──
                    near_val = float(cam.get('near', 0.1))
                    far_val = float(cam.get('far', 1000.0))
                    changed_n, new_near = imgui.drag_float("Near", near_val, 0.01, 0.001, 1000.0, "%.3f")
                    changed_f, new_far = imgui.drag_float("Far", far_val, 1.0, 0.01, 10000.0, "%.1f")
                    if changed_n:
                        self._browser_ctrl.set_camera_clip(entity_id, new_near, far_val)
                    if changed_f:
                        self._browser_ctrl.set_camera_clip(entity_id, near_val, new_far)

                    if cam.get('is_primary'):
                        imgui.text_colored(imgui.ImVec4(*WARNING_AMBER, 1.00), "(Primary Camera)")
                else:
                    imgui.text_disabled("(camera info unavailable)")

        # ── 其它组件 (通用检视 — TextDisplay / MediaPlayer / Light 等) ──
        for comp_name in self._browser_ctrl.get_extra_components(entity_id):
            fields_list = self._browser_ctrl.get_component_fields(entity_id, comp_name)
            if not fields_list:
                continue
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 2)
            if imgui.button(f"-##remove_{comp_name}_{entity_id}", (22, 0)):
                self._browser_ctrl.remove_component(entity_id, comp_name)
            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() - 2)
            imgui.same_line()
            if imgui.collapsing_header(f"{comp_name}##extra_{comp_name}", imgui.TreeNodeFlags_.default_open):
                self._draw_generic_component_fields(entity_id, comp_name, fields_list)

        # ── Add Component ──
        imgui.spacing()
        self._draw_add_component(entity_id)

    def _draw_generic_component_fields(self, entity_id: int, comp_name: str, fields_list) -> None:
        """按值类型通用绘制组件字段 (str/bool/int/float/tuple)。

        - *color* 字段 → ColorEdit4;
        - 带选择集的 str 字段 → **下拉 Combo** (受控枚举, 禁止自由文本 — ui_protocol §11);
        - 其余 str → 自由文本框。
        """
        for fname, fval, choices in fields_list:
            changed = False
            new_value = None
            if isinstance(fval, bool):
                changed, new_value = imgui.checkbox(fname, fval)
            elif isinstance(fval, str):
                if choices:
                    cur_label = next((lbl for v, lbl in choices if v == fval), fval)
                    if imgui.begin_combo(f"{fname}##{comp_name}_{fname}_{entity_id}", cur_label):
                        for v, lbl in choices:
                            selected = (v == fval)
                            if imgui.selectable(f"{lbl}##{v}_{comp_name}_{entity_id}", selected)[0]:
                                changed = True
                                new_value = v
                            if selected:
                                imgui.set_item_default_focus()
                        imgui.end_combo()
                else:
                    changed, new_value = imgui.input_text(
                        f"##{comp_name}_{fname}_{entity_id}", fval, 512)
            elif isinstance(fval, int):
                changed, new_value = imgui.drag_int(fname, fval, 0.25, 0, 4096)
            elif isinstance(fval, float):
                changed, new_value = imgui.drag_float(fname, fval, 0.05, format="%.3f")
            elif isinstance(fval, tuple):
                vals = list(fval)
                numeric = all(isinstance(v, (int, float)) for v in vals)
                if len(vals) == 4 and 'color' in fname and numeric:
                    changed, new_value = imgui.color_edit4(fname, vals)
                    if changed:
                        new_value = tuple(new_value)
                elif len(vals) == 3 and numeric:
                    changed, new_value = imgui.drag_float3(fname, vals, 0.05, format="%.2f")
                    if changed:
                        new_value = tuple(new_value)
                elif len(vals) == 4 and numeric:
                    changed, new_value = imgui.drag_float4(fname, vals, 0.05, format="%.2f")
                    if changed:
                        new_value = tuple(new_value)
                else:
                    imgui.text_disabled(f"{fname}: {fval}")
            else:
                imgui.text_disabled(f"{fname}: {fval!r}")
            if changed:
                self._browser_ctrl.set_component_field(entity_id, comp_name, fname, new_value)

    def _draw_mesh_renderer_editor(self, entity_id: int, summary) -> None:
        """绘制 MeshRenderer 编辑区域 — Visible / Mesh / Material。"""
        # ── Visible 勾选框 ──
        changed, vis = imgui.checkbox("Visible", summary.render_visible)
        if changed:
            self._browser_ctrl.set_entity_render_visible(entity_id, vis)
            summary.render_visible = vis

        mesh_options = self._resource_ctrl.get_mesh_options()

        # ── Mesh 子节点 ──
        if imgui.tree_node_ex("Mesh##mesh_tree", imgui.TreeNodeFlags_.default_open):
            current_mesh_id = summary.mesh_id or 0
            mesh_names = {mid: name for mid, name in mesh_options}
            current_mesh_name = mesh_names.get(current_mesh_id, f"Mesh #{current_mesh_id}")

            if imgui.begin_combo("Mesh##mesh_select", current_mesh_name):
                for mid, mname in mesh_options:
                    selected = (mid == current_mesh_id)
                    if imgui.selectable(f"{mname}##mesh_{mid}", selected)[0]:
                        self._browser_ctrl.set_entity_mesh(entity_id, mid)
                    if selected:
                        imgui.set_item_default_focus()
                imgui.end_combo()
            imgui.tree_pop()

        # ── Material 子节点 ──
        has_mat = summary.material_id is not None and summary.material_id != 0
        if imgui.tree_node_ex("Material##mat_tree",
                               imgui.TreeNodeFlags_.default_open if has_mat else 0):
            self._draw_material_section(entity_id, summary)
            imgui.tree_pop()

    def _draw_material_section(self, entity_id: int, summary) -> None:
        """绘制 Material 子区域。

        层级:
          Material: [下拉选已有材质]  [💾]    ← 选择 + 保存图标
          Name:  [MyMat          ]             ← 可编辑
          Shader / Textures / Uniforms
        """
        from Application.Resource.ResourceManager import ResourceManager
        shader_options = self._resource_ctrl.get_shader_options()
        tex_options = self._resource_ctrl.get_texture_options()
        mat_options = self._resource_ctrl.get_material_options()

        current_mat_id = summary.material_id or 0
        info = self._browser_ctrl.get_entity_material_info(entity_id)
        if current_mat_id == 0 or info is None:
            imgui.text_disabled("(no material)")
            return

        is_saved = info.get('is_saved', False)
        display_name = info.get('display_name', '*Untitled')
        current_name = info.get('material_name', 'Untitled')
        file_path = info.get('file_path', '')

        # ── Material 下拉选择 + 保存图标 ──
        mat_names = {mid: name for mid, name in mat_options}
        current_mat_label = mat_names.get(current_mat_id, display_name)
        # ★ 如果 material 已丢失（不在 loaded_material 中），标记 (Lost)
        mat_lost = (str(current_mat_id) not in ResourceManager.loaded_material)
        if mat_lost:
            current_mat_label = f"{current_mat_label} (Lost)"
        if imgui.begin_combo("Material##mat_select", current_mat_label):
            for mid, mname in mat_options:
                selected = (mid == current_mat_id)
                if imgui.selectable(f"{mname}##mat_opt_{mid}", selected)[0]:
                    self._browser_ctrl.set_entity_material(entity_id, mid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── 保存图标按钮 ──
        imgui.same_line()
        if is_saved:
            imgui.begin_disabled(True)
        if imgui.small_button(f"{fa.ICON_FA_FLOPPY_DISK}##mat_save_{entity_id}"):
            default_name = f"{current_name}.mat" if current_name else "material.mat"
            # ★ 默认保存到项目 Materials 目录
            from Application.Editor.ProjectManager import ProjectManager
            start_dir = None
            if ProjectManager.is_open():
                import os
                proj_dir = ProjectManager.get_project_dir()
                mat_dir = os.path.join(proj_dir, "Materials")
                start_dir = mat_dir
            FileDialog.save_mat(
                callback=lambda p: self._on_mat_save(entity_id, p),
                default_name=default_name,
                start_dir=start_dir,
            )
        if imgui.is_item_hovered():
            imgui.set_tooltip("Save material to .mat file")
        if is_saved:
            imgui.end_disabled()

        # ── Name 可编辑 ──
        changed, new_name = imgui.input_text("Name##mat_name", current_name, 64)
        if changed and new_name.strip():
            self._browser_ctrl.set_material_name(entity_id, new_name.strip())

        # ── Shader ──
        shader_names = {sid: name for sid, name in shader_options}
        current_shader_name = shader_names.get(
            info['shader_id'], info.get('shader_name', f"#{info['shader_id']}"))
        if imgui.begin_combo("Shader##mat_shader", current_shader_name):
            for sid, sname in shader_options:
                selected = (sid == info['shader_id'])
                if imgui.selectable(f"{sname}##shader_{sid}", selected)[0]:
                    self._browser_ctrl.set_material_shader(entity_id, sid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── Blend (混合模式: opaque / alpha) ──
        current_blend = info.get('blend', 'opaque')
        if imgui.begin_combo("Blend##mat_blend", current_blend):
            for opt in ("opaque", "alpha"):
                selected = (opt == current_blend)
                if imgui.selectable(f"{opt}##blend_{opt}", selected)[0]:
                    self._browser_ctrl.set_material_blend(entity_id, opt)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── Basic Shader 颜色 ──
        if info.get('shader_name') == 'Basic':
            self._draw_color_picker(entity_id, info)

        # ── Textures ──
        tex_names = {tid: name for tid, name in tex_options}
        if imgui.tree_node("Textures##mat_tex"):
            for i, tid in enumerate(info['texture_ids']):
                tname = tex_names.get(tid, f"Texture #{tid}")
                imgui.bullet_text(f"[{i}] {tname}")
                imgui.same_line()
                if imgui.small_button(f"x##tex_{entity_id}_{i}"):
                    self._browser_ctrl.remove_material_texture(entity_id, i)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Remove texture")
            imgui.spacing()
            if imgui.small_button(f"{fa.ICON_FA_PLUS}  Add Texture##add_tex_{entity_id}"):
                imgui.open_popup(f"add_tex_popup_{entity_id}")
            if imgui.begin_popup(f"add_tex_popup_{entity_id}"):
                used_tex_ids = set(info['texture_ids'])
                available = [(tid, name) for tid, name in tex_options if tid not in used_tex_ids]
                if available:
                    for tid, tname in available:
                        if imgui.menu_item(tname, "", False, True)[0]:
                            self._browser_ctrl.add_material_texture(entity_id, tid)
                else:
                    imgui.text_disabled("(all textures in use)")
                imgui.end_popup()
            imgui.tree_pop()

        # ── Uniforms ──
        uniforms = info.get('uniforms', {})
        if uniforms and imgui.tree_node("Uniforms##mat_uniforms"):
            for u_name, u_value in uniforms.items():
                if u_name == 'uColor' and info.get('shader_name') == 'Basic':
                    continue
                val = u_value
                if hasattr(val, 'shape'):
                    if val.shape == ():
                        changed, new_v = imgui.drag_float(
                            f"{u_name}##mat_{entity_id}", float(val), 0.1, format="%.3f")
                        if changed:
                            self._browser_ctrl.set_material_uniform(entity_id, u_name, float(new_v))
                    elif val.shape == (4, 4):
                        imgui.text_disabled(f"{u_name}: mat4")
                    elif val.shape == (4,):
                        changed, new_v = imgui.drag_float4(
                            f"{u_name}##mat_{entity_id}", list(val), 0.01, format="%.3f")
                        if changed:
                            self._browser_ctrl.set_material_uniform(entity_id, u_name, tuple(new_v))
                    else:
                        imgui.text_disabled(f"{u_name}: shape {val.shape}")
                elif isinstance(val, (int, float)):
                    changed, new_v = imgui.drag_float(
                        f"{u_name}##mat_{entity_id}", float(val), 0.1, format="%.3f")
                    if changed:
                        self._browser_ctrl.set_material_uniform(entity_id, u_name, float(new_v))
                else:
                    imgui.text_disabled(f"{u_name}: {type(val).__name__}")
            imgui.tree_pop()

    def _draw_color_picker(self, entity_id: int, info: dict) -> None:
        """Basic Shader 专属颜色调色盘 — 预设按钮 + ColorEdit4。"""
        from Application.Resource.ResourceManager import ResourceManager, COLOR_PRESETS

        u_color = info['uniforms'].get('uColor')
        if u_color is None:
            return
        current_color = tuple(float(c) for c in u_color)  # (r, g, b, a)

        # ── 预设颜色按钮 ──
        imgui.text("Presets:")
        preset_names = list(COLOR_PRESETS.keys())
        # 每行 5 个
        cols = 5
        for idx, name in enumerate(preset_names):
            rgba = COLOR_PRESETS[name]
            # 用彩色小按钮
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(*rgba))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(
                min(rgba[0]*1.2, 1.0), min(rgba[1]*1.2, 1.0),
                min(rgba[2]*1.2, 1.0), 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(*rgba))
            if imgui.button(f"##preset_{name}", (16, 16)):
                self._browser_ctrl.set_material_color(
                    entity_id, *rgba)
            imgui.pop_style_color(3)
            # tooltip on hover
            if imgui.is_item_hovered():
                imgui.set_tooltip(name)
            if (idx + 1) % cols != 0:
                imgui.same_line()

        imgui.spacing()

        # ── ColorEdit4 调色盘 ──
        changed, new_color = imgui.color_edit4(
            f"Color##mat_{entity_id}", current_color,
            flags=imgui.ColorEditFlags_.display_hsv | imgui.ColorEditFlags_.float,
        )
        if changed:
            self._browser_ctrl.set_material_color(entity_id, *new_color)

    def _draw_add_component(self, entity_id: int) -> None:
        """绘制 'Add Component' 下拉按钮 — 列出所有已注册但未添加的 Component。"""
        available = self._browser_ctrl.get_available_components()
        existing = self._browser_ctrl.get_entity_components(entity_id)

        # 过滤掉已存在的
        addable = {k: v for k, v in available.items() if k not in existing}
        if not addable:
            imgui.text_disabled("(all available components added)")
            return

        if imgui.button(f"{fa.ICON_FA_PLUS}  Add Component##add_comp"):
            imgui.open_popup("add_component_popup")

        if imgui.begin_popup("add_component_popup"):
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 0.90), "Add Component:")
            for comp_name in addable:
                if imgui.menu_item(comp_name, "", False, True)[0]:
                    self._browser_ctrl.add_component(entity_id, comp_name)
            imgui.end_popup()
