"""
节点编辑器 — 画布 Panel。

负责:
  - 节点/连线/交互的渲染
  - Add 弹出菜单
  - Pin 拖拽创建连线
  - Delete 键删除
  - 位置同步
"""

from __future__ import annotations

import os

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import ERROR_RED

from Application.Editor.UI.controllers.node_editor import (
    NodeCanvas,
    _TYPES,
    _gen_id,
)
from .styling import (
    _col,
    _apply_ne_style,
    _HDR_COLOR,
    MENU_SECTIONS,
    TEXT_DISABLED,
)


# ═══════════════════════════════════════════════════════════════
# Add 菜单辅助
# ═══════════════════════════════════════════════════════════════

def _draw_add_menu_section(
    title: str,
    items: list[tuple[str, str]],
    canvas: NodeCanvas,
    avail: imgui.ImVec2,
) -> None:
    """在 Add 弹出菜单中绘制一个分类区块。"""
    imgui.spacing()
    imgui.text_colored(_HDR_COLOR, title)
    imgui.separator()
    for label, type_name in items:
        changed, _selected = imgui.menu_item(label, "", False, True)
        if changed:
            max_y = max((inst.pos[1] for inst in canvas.nodes.values()), default=40)
            cx = 80.0
            cy = max_y + 200.0
            canvas.add_node(type_name, (cx, cy))
            imgui.close_current_popup()


# ═══════════════════════════════════════════════════════════════
# NodeEditorPanel
# ═══════════════════════════════════════════════════════════════

class NodeEditorPanel(BasePanel):
    """节点编辑器画布 — Runtime 生命周期节点编辑"""

    name = "Node Editor"
    flags = imgui.WindowFlags_.none

    _CONFIG_FILE: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "config", "NodeEditor.json",
    )

    _canvas: NodeCanvas | None = None

    def __init__(self) -> None:
        super().__init__()
        self.visible = True
        self._editor_context: node_ed.EditorContext | None = None
        self._editor_initialized: bool = False
        self._canvas_initialized: bool = False
        self._add_popup_active: bool = False

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(self) -> None:
        if not self._editor_initialized:
            try:
                os.makedirs(os.path.dirname(self._CONFIG_FILE), exist_ok=True)
                config = node_ed.Config()
                config.settings_file = self._CONFIG_FILE
                self._editor_context = node_ed.create_editor(config)
                self._editor_initialized = True
            except Exception:
                self._editor_context = None

    def on_detach(self) -> None:
        if self._editor_context is not None:
            try:
                node_ed.destroy_editor(self._editor_context)
            except Exception:
                pass
            self._editor_context = None
            self._editor_initialized = False

    # ============================================================
    # 绘制入口
    # ============================================================

    def draw(self) -> None:
        if self._editor_context is None:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                "Node Editor not available"
            )
            imgui.text_disabled(
                "Ensure imgui_bundle is compiled with node editor support."
            )
            return

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

        # ── Add 按钮 ──
        if imgui.small_button("+ Add Node"):
            self._add_popup_active = True

        # ── 画布背景色 & 网格 ──
        s = ne.get_style()
        s.set_color_(ne.StyleColor.bg,   _col((0.090, 0.090, 0.090), 1.00))
        s.set_color_(ne.StyleColor.grid, _col((0.180, 0.180, 0.180), 0.50))

        ne.begin("NodeEditor", avail)

        self._draw_nodes(canvas, ne)
        self._draw_links(canvas, ne)
        self._handle_link_creation(canvas, ne)
        self._handle_deletion(canvas, ne)

        # ── 空画布提示 ──
        ne.suspend()
        if not canvas.nodes:
            canvas_pos = imgui.get_cursor_screen_pos()
            imgui.set_cursor_screen_pos((
                canvas_pos.x + avail.x / 2 - 80,
                canvas_pos.y + avail.y / 2 - 10,
            ))
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00),
                'Click "Add" button to create nodes',
            )
        ne.resume()
        ne.end()

        self._draw_add_popup(canvas, avail)
        self._sync_positions(canvas, ne)

    # ============================================================
    # 子步骤: 节点渲染
    # ============================================================

    def _draw_nodes(self, canvas: NodeCanvas, ne) -> None:
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

            # 标题栏
            imgui.push_style_color(imgui.Col_.text, _col(nd.accent_color, 1.00))
            imgui.text(nd.label)
            imgui.pop_style_color(1)

            # 属性文字
            if nd.props_text:
                imgui.dummy(imgui.ImVec2(0, 2))
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                for line in nd.props_text.split("\n"):
                    imgui.text(f"  {line}")
                imgui.pop_style_color(1)
                imgui.dummy(imgui.ImVec2(0, 2))

            # PrintString 文本框
            if inst.node_type == "PrintString":
                imgui.dummy(imgui.ImVec2(0, 2))
                msg = inst.props.get("message", "")
                changed, new_msg = imgui.input_text(
                    f"##print_msg_{nid}", msg,
                )
                if changed:
                    inst.props["message"] = new_msg
                imgui.dummy(imgui.ImVec2(0, 2))

            self._draw_pins(canvas, ne, nid, inst, nd)
            ne.end_node()

    def _draw_pins(self, canvas: NodeCanvas, ne, nid: int, inst, nd) -> None:
        """绘制节点的所有引脚 + 分隔线。"""
        _max_in_w = max(
            (imgui.calc_text_size(f"> {p.name}").x
             for p in nd.pins if p.direction == "input"),
            default=0,
        )
        _min_pad = imgui.calc_text_size("> ").x * 4
        _out_pad = max(_max_in_w, _min_pad)

        # 手动画分隔线
        _cursor = imgui.get_cursor_screen_pos()
        _node_w = max(
            imgui.calc_text_size(f"  {nd.label}  ").x,
            max((imgui.calc_text_size(f"> {p.name}").x for p in nd.pins), default=0),
            max((_out_pad + imgui.calc_text_size(f"{p.name} >").x
                 for p in nd.pins if p.direction == "output"), default=0),
            80.0,
        )
        _dl = imgui.get_window_draw_list()
        _dl.add_line(
            imgui.ImVec2(_cursor.x, _cursor.y + 3),
            imgui.ImVec2(_cursor.x + _node_w, _cursor.y + 3),
            imgui.get_color_u32(imgui.Col_.border),
            1.0,
        )
        imgui.dummy(imgui.ImVec2(0, 6))

        for pin in nd.pins:
            pin_id = inst.pin_ids[pin.name]
            kind = ne.PinKind.input if pin.direction == "input" else ne.PinKind.output
            ne.begin_pin(ne.PinId(pin_id), kind)
            if pin.direction == "output":
                imgui.dummy(imgui.ImVec2(_out_pad, 1))
                imgui.same_line()
                imgui.text(f"{pin.name} >")
            else:
                imgui.text(f"> {pin.name}")
            ne.end_pin()

    # ============================================================
    # 子步骤: 连线渲染
    # ============================================================

    def _draw_links(self, canvas: NodeCanvas, ne) -> None:
        for lk in canvas.links.values():
            ne.link(
                ne.LinkId(lk.id),
                ne.PinId(lk.from_pin),
                ne.PinId(lk.to_pin),
                _col((0.7, 0.7, 0.7, 0.7)),
                2.0,
            )

    # ============================================================
    # 子步骤: Pin 拖拽创建连线
    # ============================================================

    def _handle_link_creation(self, canvas: NodeCanvas, ne) -> None:
        if ne.begin_create():
            sp = ne.PinId(0)
            ep = ne.PinId(0)
            if ne.query_new_link(sp, ep):
                if sp.id() != 0 and ep.id() != 0:
                    sd = canvas.find_pin_dir(sp.id())
                    ed = canvas.find_pin_dir(ep.id())
                    sn = canvas.find_pin_node(sp.id())
                    en = canvas.find_pin_node(ep.id())
                    if (sd and ed and sd != ed and sn and en and sn != en):
                        out_pin = sp.id() if sd == "output" else ep.id()
                        in_pin = ep.id() if sd == "output" else sp.id()
                        if (canvas.find_pin_dir(out_pin) == "output"
                                and canvas.find_pin_dir(in_pin) == "input"):
                            if ne.accept_new_item():
                                lid = canvas.add_link(out_pin, in_pin)
                                if lid != -1:
                                    print(
                                        f"[Link] Created: "
                                        f"{canvas.find_pin_name(out_pin)} → "
                                        f"{canvas.find_pin_name(in_pin)}"
                                    )
                                else:
                                    print("[Link] Duplicate — skipped")
            ne.end_create()

    # ============================================================
    # 子步骤: Delete 键删除
    # ============================================================

    def _handle_deletion(self, canvas: NodeCanvas, ne) -> None:
        _del_pressed = imgui.is_key_pressed(imgui.Key.delete, False)
        if _del_pressed:
            _sel_nodes = ne.get_selected_nodes()
            _sel_links = ne.get_selected_links()
            _del_node_count = 0
            _del_link_count = 0
            for sn in _sel_nodes:
                nid = sn.id()
                if nid in canvas.nodes:
                    print(f"[Delete] Node: {canvas.nodes[nid].node_type} (id={nid})")
                    canvas.remove_node(nid)
                    _del_node_count += 1
            for sl in _sel_links:
                lid = sl.id()
                if lid in canvas.links:
                    print(f"[Delete] Link: {lid}")
                    canvas.remove_link(lid)
                    _del_link_count += 1
            if _del_node_count == 0 and _del_link_count == 0:
                print("[Delete] No selection — click a node first, then press Delete")
            ne.clear_selection()

    # ============================================================
    # 子步骤: Add 弹出菜单
    # ============================================================

    def _draw_add_popup(self, canvas: NodeCanvas, avail) -> None:
        if self._add_popup_active:
            imgui.open_popup("Create Node")
            _bpop = imgui.begin_popup("Create Node")
            if _bpop:
                for title, items in MENU_SECTIONS:
                    _draw_add_menu_section(title, items, canvas, avail)
                imgui.end_popup()
            if not imgui.is_popup_open("Create Node"):
                self._add_popup_active = False

    # ============================================================
    # 子步骤: 位置同步
    # ============================================================

    def _sync_positions(self, canvas: NodeCanvas, ne) -> None:
        for nid in list(canvas.nodes.keys()):
            np = ne.get_node_position(ne.NodeId(nid))
            inst = canvas.nodes[nid]
            if -1e6 < np.x < 1e6 and -1e6 < np.y < 1e6:
                if (np.x, np.y) != inst.pos:
                    inst.pos = (np.x, np.y)
