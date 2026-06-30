from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

import os

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import (
    ERROR_RED, BLENDER_ORANGE,
    COLOR_EVENT, COLOR_FLOW, COLOR_EXEC_PIN, COLOR_DATA_PIN,
    TEXT_DISABLED,
)
from Application.Editor.UI.controllers.NodeEditorController import (
    NodeCanvas,
    LinkInstance,
    _TYPES,
)


# ═══════════════════════════════════════════════════════════════
# 渲染辅助
# ═══════════════════════════════════════════════════════════════

def _col(c: tuple, a: float = 1.0) -> imgui.ImVec4:
    return imgui.ImVec4(c[0], c[1], c[2], a)


def _apply_ne_style(accent: tuple):
    """设置当前节点的 node-editor 样式色（边框、选中、悬停、pin）"""
    s = node_ed.get_style()
    bg_near_black = (0.110, 0.110, 0.110)
    s.set_color_(node_ed.StyleColor.node_bg,           _col(bg_near_black, 0.95))
    s.set_color_(node_ed.StyleColor.node_border,       _col(accent, 0.50))
    s.set_color_(node_ed.StyleColor.sel_node_border,   _col(accent, 1.00))
    s.set_color_(node_ed.StyleColor.hov_node_border,   _col(accent, 0.75))
    s.set_color_(node_ed.StyleColor.pin_rect,          _col(accent, 0.20))
    s.set_color_(node_ed.StyleColor.pin_rect_border,   _col(accent, 0.40))
    s.set_color_(node_ed.StyleColor.flow,              _col(accent, 0.70))
    s.set_color_(node_ed.StyleColor.flow_marker,       _col(accent, 1.00))


class NodeEditorPanel(BasePanel):
    """节点编辑器画布 — Runtime 生命周期节点编辑"""

    name = "Node Editor"
    flags = imgui.WindowFlags_.none

    # ── 配置文件路径 (与 EditorLayer 共用 Application/Editor/config/) ──
    _CONFIG_FILE: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config", "NodeEditor.json",
    )

    # ── 节点画布 ────────────────────────────────────────────────
    _canvas: NodeCanvas | None = None

    def __init__(
        self
    ) -> None:
        super().__init__()
        self.visible = True
        self._editor_context: node_ed.EditorContext | None = None
        self._editor_initialized: bool = False
        self._canvas_initialized: bool = False

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(
        self
    ) -> None:
        """面板注册时创建节点编辑器上下文"""
        if not self._editor_initialized:
            try:
                os.makedirs(os.path.dirname(self._CONFIG_FILE), exist_ok=True)
                config = node_ed.Config()
                config.settings_file = self._CONFIG_FILE
                self._editor_context = node_ed.create_editor(config)
                self._editor_initialized = True
            except Exception:
                self._editor_context = None

    def on_detach(
        self
    ) -> None:
        """面板移除时销毁节点编辑器上下文"""
        if self._editor_context is not None:
            try:
                node_ed.destroy_editor(self._editor_context)
            except Exception:
                pass
            self._editor_context = None
            self._editor_initialized = False

    # ============================================================
    # 绘制
    # ============================================================

    def draw(
        self
    ) -> None:
        """绘制节点编辑画布 — 节点、连线、右键菜单"""
        if self._editor_context is None:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                "Node Editor not available"
            )
            imgui.text_disabled(
                "Ensure imgui_bundle is compiled with node editor support."
            )
            return

        # ── 首次绘制时初始化画布并创建默认节点 ──
        if not self._canvas_initialized:
            self._canvas = NodeCanvas()
            self._canvas.create_default_nodes()
            self._canvas_initialized = True

        canvas = self._canvas
        avail = imgui.get_content_region_avail()
        if avail.x <= 0 or avail.y <= 0:
            return

        ne = node_ed
        ne.set_current_editor(self._editor_context)

        # ── 画布背景色 & 网格 ──
        s = ne.get_style()
        s.set_color_(ne.StyleColor.bg,   _col((0.090, 0.090, 0.090), 1.00))
        s.set_color_(ne.StyleColor.grid, _col((0.180, 0.180, 0.180), 0.50))

        ne.begin("NodeEditor", avail)

        # ══════════════════════════════════════════════════════
        # 绘制节点
        # ══════════════════════════════════════════════════════
        for nid, inst in list(canvas.nodes.items()):
            nd = _TYPES.get(inst.node_type)
            if nd is None:
                continue

            ne.set_node_position(
                ne.NodeId(nid),
                imgui.ImVec2(inst.pos[0], inst.pos[1]),
            )
            ne.begin_node(ne.NodeId(nid))
            _apply_ne_style(nd.accent_color)

            # ── 标题栏 ──
            imgui.push_style_color(imgui.Col_.text, _col(nd.accent_color, 1.00))
            imgui.text(nd.label)
            imgui.pop_style_color(1)

            # ── 节点体属性文字 ──
            if nd.props_text:
                imgui.dummy(imgui.ImVec2(0, 2))
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                for line in nd.props_text.split("\n"):
                    imgui.text(f"  {line}")
                imgui.pop_style_color(1)
                imgui.dummy(imgui.ImVec2(0, 2))

            # ── 引脚 ──
            imgui.separator()
            for pin in nd.pins:
                kind = ne.PinKind.input if pin.direction == "input" else ne.PinKind.output
                ne.begin_pin(ne.PinId(pin.id), kind)
                imgui.text(f" {pin.name}")
                ne.end_pin()

            ne.end_node()

        # ══════════════════════════════════════════════════════
        # 绘制连线
        # ══════════════════════════════════════════════════════
        for lk in canvas.links.values():
            ne.link(
                ne.LinkId(lk.id),
                ne.PinId(lk.from_pin),
                ne.PinId(lk.to_pin),
                _col((0.7, 0.7, 0.7, 0.7)),
                2.0,
            )

        # ══════════════════════════════════════════════════════
        # 交互: Pin 拖拽创建连线
        # ══════════════════════════════════════════════════════
        if ne.begin_create():
            sp = ne.PinId(0)
            ep = ne.PinId(0)
            if ne.query_new_link(sp, ep):
                sd = canvas.find_pin_dir(sp.id())
                ed = canvas.find_pin_dir(ep.id())
                sn = canvas.find_pin_node(sp.id())
                en = canvas.find_pin_node(ep.id())
                valid = (
                    sd is not None and ed is not None and sd != ed
                    and sn is not None and en is not None and sn != en
                )
                if valid:
                    out_pin = sp.id() if sd == "output" else ep.id()
                    in_pin = ep.id() if sd == "output" else sp.id()
                    if canvas.find_pin_dir(out_pin) == "output" and \
                       canvas.find_pin_dir(in_pin) == "input":
                        ne.accept_new_item(_col((0.8, 0.8, 0.8, 0.5)), 2.0)
                    else:
                        ne.reject_new_item()
                else:
                    ne.reject_new_item()
            ne.end_create()

        # ══════════════════════════════════════════════════════
        # 交互: Delete 删除选中节点/连线
        # ══════════════════════════════════════════════════════
        if ne.begin_delete():
            del_link = ne.LinkId(0)
            while ne.query_deleted_link(del_link):
                if del_link.id() in canvas.links:
                    canvas.remove_link(del_link.id())
                    ne.accept_new_item()
                else:
                    ne.reject_new_item()

            del_node = ne.NodeId(0)
            while ne.query_deleted_node(del_node):
                if del_node.id() in canvas.nodes:
                    canvas.remove_node(del_node.id())
                    ne.accept_new_item()
                else:
                    ne.reject_new_item()
            ne.end_delete()

        # ══════════════════════════════════════════════════════
        # 收集创建的新 link
        # ══════════════════════════════════════════════════════
        for lid in ne.get_action_context_links():
            if lid.id() in canvas.links:
                continue
            sp = ne.PinId(0)
            ep = ne.PinId(0)
            if ne.get_link_pins(lid, sp, ep):
                sd = canvas.find_pin_dir(sp.id())
                if sd == "output":
                    canvas.links[lid.id()] = LinkInstance(lid.id(), sp.id(), ep.id())
                else:
                    canvas.links[lid.id()] = LinkInstance(lid.id(), ep.id(), sp.id())

        # ══════════════════════════════════════════════════════
        # 右键菜单（在 suspend 块中绘制普通 imgui）
        # suspend/resume 必须放在 begin/end 内部
        # ══════════════════════════════════════════════════════
        ne.suspend()
        if ne.show_background_context_menu():
            imgui.open_popup("Create Node")

        # ── 空画布提示 ──
        if not canvas.nodes:
            canvas_pos = imgui.get_cursor_screen_pos()
            imgui.set_cursor_screen_pos((
                canvas_pos.x + avail.x / 2 - 80,
                canvas_pos.y + avail.y / 2 - 10,
            ))
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00),
                "Right-click canvas to add nodes",
            )

        # ── 右键菜单内容 ──
        if imgui.begin_popup("Create Node"):
            imgui.text_disabled("Add Node...")
            imgui.separator()
            # 按 category 分组显示
            categories = {}
            for td in _TYPES.values():
                categories.setdefault(td.category, []).append(td)
            for cat, type_list in categories.items():
                if imgui.begin_menu(cat, True):
                    for td in type_list:
                        changed, _ = imgui.menu_item(td.label, "", False, True)
                        if changed:
                            # 在画布中心附近创建节点
                            cx = avail.x / 2 - 60 + len(canvas.nodes) * 20
                            cy = avail.y / 2 - 40 + len(canvas.nodes) * 20
                            canvas.add_node(td.type_name, (cx, cy))
                    imgui.end_menu()
            imgui.end_popup()
        ne.resume()

        ne.end()

        # ══════════════════════════════════════════════════════
        # 同步拖拽后的节点位置
        # ══════════════════════════════════════════════════════
        for nid in list(canvas.nodes.keys()):
            np = ne.get_node_position(ne.NodeId(nid))
            canvas.nodes[nid].pos = (np.x, np.y)
