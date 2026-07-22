"""ResourcePanel — 现代化资产浏览器 (Asset Browser)。

类似 Unity/Unreal 的 Asset 面板：
- 顶层工具栏 (Import / New Material / 搜索过滤)
- 分类标签页 (All | Meshes | Shaders | Textures | Materials)
- 网格视图: selectable 卡片 (图标 + 名称 + 类型标签)
- 右键菜单: 删除
- 底部状态栏: 各类型数量统计
- 资产卡片可作为拖拽源 (未来: 拖到 Scene Panel 生成实体 / 赋值)

注意:
  所有 FA6 图标渲染通过 imgui 控件 (button / text / selectable)，
  不使用 draw_list.add_text，确保字型正确。
"""

from imgui_bundle import imgui
from imgui_bundle import icons_fontawesome_6 as fa

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import (
    BLENDER_ORANGE,
    SUCCESS_GREEN,
    TEXT_DISABLED,
)
from Application.Editor.Services.ControllerRegistry import (
    get_ctrl,
    NAME_RESOURCE_BROWSER,
)
from Application.Editor.UI.FileDialog import FileDialog
from Application.Editor.Services.ImportService import ImportService


# ── 资源类型 → FA6 图标映射 ──────────────────────────────────
_TYPE_ICON = {
    "mesh":     fa.ICON_FA_CUBE,
    "shader":   fa.ICON_FA_FILE_CODE,
    "texture":  fa.ICON_FA_IMAGE,
    "material": fa.ICON_FA_CIRCLE,
    "prefab":   fa.ICON_FA_CUBE,
}

_TYPE_LABEL = {
    "mesh":     "Mesh",
    "shader":   "Shader",
    "texture":  "Texture",
    "material": "Material",
    "prefab":   "Prefab",
}

_TYPE_COLOR = {
    "mesh":     (0.420, 0.650, 0.920),   # 淡蓝
    "shader":   (0.788, 0.471, 0.471),   # 淡红
    "texture":  (0.471, 0.714, 0.471),   # 淡绿
    "material": (0.878, 0.753, 0.314),   # 暖金
    "prefab":   (0.420, 0.650, 0.920),   # 与 mesh 同色
}

# ── 类型顺序 (用于排序) ──
_TYPE_ORDER = ["mesh", "shader", "texture", "material", "prefab"]

# ── 未知类型的占位符 ──
_UNKNOWN_ICON = "?"   # fa.ICON_FA_QUESTION 实际是 ASCII '?'，直接用字符串


class ResourcePanel(BasePanel):
    """资产浏览器面板 — 网格视图展示已注册资源，支持 CRUD。"""

    name = "Resources"
    flags = imgui.WindowFlags_.none

    CARD_W = 82.0             # 卡片宽度
    CARD_H = 64.0             # 卡片高度
    LABEL_MAX_CHARS = 11      # 名称最大显示字符数

    def __init__(self) -> None:
        super().__init__()
        self.visible = True
        self._resource_ctrl = get_ctrl(NAME_RESOURCE_BROWSER)
        # ── 面板状态 ──
        self._active_tab: int = 0       # 0=All, 1=Mesh, 2=Shader, 3=Texture, 4=Material
        self._search_filter: str = ""
        self._selected_id: int | None = None
        self._selected_type: str | None = None

    @staticmethod
    def _on_import_material(file_path: str) -> None:
        """FileDialog 回调: 从 .mat 文件加载材质到 ResourceManager。"""
        if not file_path:
            return
        try:
            from Application.Resource.Material import Material
            from Application.Resource.ResourceManager import ResourceManager
            mat = Material.load_from_file(file_path)
            new_mid = ResourceManager.material_count + 1
            ResourceManager.material_count = new_mid
            ResourceManager.loaded_material[str(new_mid)] = mat
            print(f"[Resource] Imported Material '{mat.name}' → #{new_mid}")
            # ★ 注册到项目，下次 Open Project 自动加载 + 重映射
            from Application.Editor.ProjectManager import ProjectManager
            if ProjectManager.is_open():
                ProjectManager.register_material(file_path, new_mid)
        except Exception as e:
            print(f"[Resource] Failed to import material: {e}")

    @staticmethod
    def _on_import_prefab(file_path: str) -> None:
        """FileDialog 回调: 从 .prefab 文件加载到 ResourceManager。"""
        if not file_path:
            return
        from Application.Resource.ResourceManager import ResourceManager
        ResourceManager.LoadPrefab(file_path)

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(self) -> None:
        self._draw_toolbar()
        imgui.separator()
        self._draw_category_tabs()
        imgui.separator()
        self._draw_asset_grid()
        imgui.separator()
        self._draw_status_bar()

    # ============================================================
    # 工具栏: Import / New Material / 搜索
    # ============================================================

    def _draw_toolbar(self) -> None:
        """绘制顶部工具栏。"""
        av = imgui.get_content_region_avail().x

        # ── Import 按钮 ──
        import_w = av * 0.18
        if imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Import", (import_w, 0)):
            imgui.open_popup("##import_popup")
        # Hover 提示
        if imgui.is_item_hovered():
            imgui.set_tooltip("Import Mesh / Shader / Texture from disk")

        if imgui.begin_popup("##import_popup"):
            imgui.text_disabled("Import Asset")
            imgui.separator()
            if imgui.menu_item(f"{fa.ICON_FA_CUBE}  Mesh...", "", False, True)[0]:
                FileDialog.open_mesh(ImportService.load_mesh)
                imgui.close_current_popup()
            if imgui.menu_item(f"{fa.ICON_FA_FILE_CODE}  Shader...", "", False, True)[0]:
                FileDialog.open_shader(ImportService.load_shader)
                imgui.close_current_popup()
            if imgui.menu_item(f"{fa.ICON_FA_IMAGE}  Texture...", "", False, True)[0]:
                FileDialog.open_texture(ImportService.load_texture)
                imgui.close_current_popup()
            imgui.separator()
            if imgui.menu_item(f"{fa.ICON_FA_CIRCLE}  Material...", "", False, True)[0]:
                FileDialog.open_mat(callback=self._on_import_material)
                imgui.close_current_popup()
            imgui.separator()
            if imgui.menu_item(f"{fa.ICON_FA_CUBE}  Prefab...", "", False, True)[0]:
                FileDialog.open_prefab(callback=self._on_import_prefab)
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.same_line()

        # ── New Material 按钮 ──
        new_mat_w = av * 0.24
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*SUCCESS_GREEN, 1.00))
        if imgui.button(f"{fa.ICON_FA_PLUS}  New Material", (new_mat_w, 0)):
            mid = self._resource_ctrl.new_material()
            self._selected_type = "material"
            self._selected_id = mid
            print(f"[Resource] Created Material #{mid}")
        imgui.pop_style_color(1)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Create a new Material (based on default Shader)")

        imgui.same_line()

        # ── 搜索框 (靠右) ──
        search_w = av * 0.30
        imgui.set_cursor_pos_x(av - search_w - 24)
        imgui.push_item_width(search_w)
        changed, self._search_filter = imgui.input_text_with_hint(
            "##resource_search", f"{fa.ICON_FA_MAGNIFYING_GLASS}  Filter...",
            self._search_filter, 128,
        )
        imgui.pop_item_width()

        # ── 清除选择 (最右) ──
        imgui.same_line()
        can_clear = (self._selected_id is not None)
        if not can_clear:
            imgui.begin_disabled(True)
        if imgui.small_button(f"{fa.ICON_FA_XMARK}##clear_sel"):
            self._selected_id = None
            self._selected_type = None
        if imgui.is_item_hovered():
            imgui.set_tooltip("Clear selection")
        if not can_clear:
            imgui.end_disabled()

    # ============================================================
    # 分类标签页
    # ============================================================

    def _draw_category_tabs(self) -> None:
        """绘制分类标签页: All | Meshes | Shaders | Textures | Materials"""
        tab_defs = [
            ("",                       "All"),
            (fa.ICON_FA_CUBE,        "Meshes"),
            (fa.ICON_FA_FILE_CODE,   "Shaders"),
            (fa.ICON_FA_IMAGE,       "Textures"),
            (fa.ICON_FA_CIRCLE,      "Materials"),
            (fa.ICON_FA_CUBE,        "Prefabs"),
        ]
        tab_count = len(tab_defs)
        av = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        tab_w = (av - spacing * (tab_count - 1)) / tab_count

        for i, (icon, label) in enumerate(tab_defs):
            if i > 0:
                imgui.same_line()
            was_active = (self._active_tab == i)
            if was_active:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.40))
            if imgui.button(f"{icon}{'  ' if icon else ''}{label}", (tab_w, 0)):
                self._active_tab = i
                self._selected_id = None
                self._selected_type = None
            if was_active:
                imgui.pop_style_color(1)

    # ============================================================
    # 资产网格视图
    # ============================================================

    def _draw_asset_grid(self) -> None:
        """绘制资产图标网格。"""
        resources = self._get_filtered_resources()

        # ── 计算列数 ──
        avail_w = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        cols = max(1, int((avail_w + spacing) / (self.CARD_W + spacing)))

        # ── 子区域: 可滚动的资产网格 ──
        # 留出状态栏高度
        child_h = max(1.0, imgui.get_content_region_avail().y - 28)
        imgui.begin_child("##asset_grid", (0, child_h), False,
                          imgui.WindowFlags_.always_vertical_scrollbar)

        if not resources:
            imgui.spacing()
            imgui.spacing()
            hint = "No assets loaded. Use File → Import or click 'Import'."
            hint_w = imgui.calc_text_size(hint).x
            imgui.set_cursor_pos_x(
                imgui.get_cursor_pos_x()
                + (imgui.get_content_region_avail().x - hint_w) * 0.5
            )
            imgui.text_colored(imgui.ImVec4(*TEXT_DISABLED, 1.00), hint)
            imgui.end_child()
            return

        # ── 右键空白区域 ──
        if imgui.begin_popup_context_window("##grid_ctx", 1):
            if imgui.menu_item(f"{fa.ICON_FA_FOLDER_OPEN}  Import...", "", False, True)[0]:
                imgui.open_popup("##import_popup")
            if imgui.menu_item(f"{fa.ICON_FA_PLUS}  New Material", "", False, True)[0]:
                mid = self._resource_ctrl.new_material()
                self._selected_type = "material"
                self._selected_id = mid
                print(f"[Resource] Created Material #{mid}")
            imgui.end_popup()

        # ── 逐行渲染卡片 ──
        for i, res in enumerate(resources):
            col = i % cols
            if col > 0:
                imgui.same_line()
            self._draw_asset_card(res)

        imgui.end_child()

    # ============================================================
    # 单个资产卡片 (纯 widget 渲染 — 无 draw_list)
    # ============================================================

    def _draw_asset_card(self, res: dict) -> None:
        """绘制单个资产卡片。

        res 结构: {id, name, type, path}

        使用 imgui.selectable 作为卡片，FA6 图标通过控件文字渲染，
        确保字型正确不走 draw_list 低层路径。
        """
        rid = res['id']
        rtype = res['type']
        rname = res['name']
        is_selected = (
            self._selected_type == rtype and self._selected_id == rid
        )

        icon = _TYPE_ICON.get(rtype, _UNKNOWN_ICON)
        type_label = _TYPE_LABEL.get(rtype, rtype)
        type_color = _TYPE_COLOR.get(rtype, (0.5, 0.5, 0.5))

        # ── 名称截断 ──
        display_name = rname
        if len(display_name) > self.LABEL_MAX_CHARS:
            display_name = display_name[:self.LABEL_MAX_CHARS - 1] + "\u2026"  # …

        # ── 构建 selectable 标签 ──
        # 第1行: 🎨 name      第2行:   TypeLabel
        card_label = f" {icon}  {display_name}\n   {type_label}"

        imgui.push_id(f"{rtype}_{rid}")

        # ── 选中高亮 ──
        if is_selected:
            imgui.push_style_color(
                imgui.Col_.header, imgui.ImVec4(*BLENDER_ORANGE, 0.50))

        # 主卡片 selectable
        selected = imgui.selectable(
            card_label, is_selected, 0,
            (self.CARD_W, self.CARD_H),
        )

        if is_selected:
            imgui.pop_style_color(1)

        # ── 右键菜单 ──
        if imgui.begin_popup_context_item(f"##ctx_{rtype}_{rid}", 1):
            imgui.text_colored(
                imgui.ImVec4(*type_color, 1.00),
                f"{icon}  {type_label}: {rname}",
            )
            imgui.separator()
            if rtype == "prefab":
                if imgui.menu_item(f"{fa.ICON_FA_PLUS}  Add to Scene", "", False, True)[0]:
                    from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController
                    eids = ResourceBrowserController.instantiate_prefab(rid)
                    if eids:
                        print(f"[Resource] Added Prefab '{rname}' → {len(eids)} entities")
                    imgui.close_current_popup()
                imgui.separator()
            if imgui.menu_item(f"{fa.ICON_FA_TRASH}  Delete", "", False, True)[0]:
                ok = self._resource_ctrl.delete_resource(rtype, rid)
                if ok:
                    if is_selected:
                        self._selected_id = None
                        self._selected_type = None
                    print(
                        f"[Resource] Deleted {type_label} #{rid} '{rname}'")
                imgui.close_current_popup()
            imgui.end_popup()

        # ── Hover 提示: 显示完整信息 ──
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                f"{type_label} #{rid}\n"
                f"Name: {rname}\n"
                f"Path: {res.get('path', '(none)')}"
            )

        # ── 单击选中 ──
        if selected:
            self._selected_type = rtype
            self._selected_id = rid

        # ── 拖拽源 (rid 作为 payload int) ──
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("RESOURCE", rid)
            imgui.text_colored(
                imgui.ImVec4(*type_color, 1.00),
                f"{icon}  {rname}",
            )
            imgui.end_drag_drop_source()

        imgui.pop_id()

    # ============================================================
    # 底部状态栏
    # ============================================================

    def _draw_status_bar(self) -> None:
        """绘制底部状态栏 — 各类型资源计数 + 选中信息。"""
        counts = self._resource_ctrl.get_resource_count_by_type()
        parts: list[str] = []
        for rtype in _TYPE_ORDER:
            count = counts.get(rtype, 0)
            icon = _TYPE_ICON.get(rtype, _UNKNOWN_ICON)
            label = _TYPE_LABEL.get(rtype, rtype)
            s = "s" if count != 1 else ""
            parts.append(f"{icon}  {count} {label}{s}")

        text = "    ".join(parts)
        imgui.text_disabled(text)

        # ── 选中信息 ──
        if self._selected_id is not None and self._selected_type is not None:
            icon = _TYPE_ICON.get(self._selected_type, _UNKNOWN_ICON)
            type_label = _TYPE_LABEL.get(
                self._selected_type, self._selected_type)
            imgui.same_line()
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 1.00),
                f"  |  {icon}  {type_label} #{self._selected_id}",
            )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_filtered_resources(self) -> list[dict]:
        """根据当前激活的标签页和搜索过滤获取资源列表。"""
        # 映射 active_tab → resource_type (None=All)
        tab_map = {0: None, 1: "mesh", 2: "shader",
                   3: "texture", 4: "material", 5: "prefab"}
        filter_type = tab_map.get(self._active_tab)

        resources = self._resource_ctrl.get_all_resources(filter_type)

        # ── 搜索过滤 ──
        search = self._search_filter.strip().lower()
        if search:
            resources = [
                r for r in resources
                if search in r['name'].lower()
                or search in _TYPE_LABEL.get(r['type'], r['type']).lower()
            ]

        # ── 排序: 类型顺序 → ID ──
        type_rank = {t: i for i, t in enumerate(_TYPE_ORDER)}
        resources.sort(key=lambda r: (
            type_rank.get(r['type'], 99), r['id']))

        return resources
