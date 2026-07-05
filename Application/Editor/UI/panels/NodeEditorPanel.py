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
    _gen_id,
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


_HDR_COLOR = imgui.ImVec4(0.600, 0.600, 0.600, 0.70)


def _draw_add_menu_section(
    title: str,
    items: list[tuple[str, str]],   # (label, type_name)
    canvas: NodeCanvas,
    avail: imgui.ImVec2,
) -> None:
    """在 Add 子菜单中绘制一个分类区块：
      - title       → 灰色文字标题（不可点击）
      - separator   → 分隔线
      - items       → 可点击的菜单项，点击后在画布中央创建节点
    """
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
        self._add_popup_active: bool = False  # popup 当前可见（flag 门控 begin_popup）

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

        # ── Add 按钮 ──
        if imgui.small_button("+ Add Node"):
            self._add_popup_active = True

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

            # ── PrintString: 可编辑文本框 ──
            if inst.node_type == "PrintString":
                imgui.dummy(imgui.ImVec2(0, 2))
                msg = inst.props.get("message", "")
                changed, new_msg = imgui.input_text(
                    f"##print_msg_{nid}", msg,
                )
                if changed:
                    inst.props["message"] = new_msg
                imgui.dummy(imgui.ImVec2(0, 2))

            # ── 引脚（输出列对齐到最长输入文字右侧） ──
            _max_in_w = max(
                (imgui.calc_text_size(f"> {p.name}").x
                 for p in nd.pins if p.direction == "input"),
                default=0,
            )
            # 无输入 pin 时给输出一个最小左 padding，让 > 顶到右侧
            _min_pad = imgui.calc_text_size("> ").x * 4
            _out_pad = max(_max_in_w, _min_pad)

            # 手动画分隔线（imgui.separator 在 node editor 内会拉满画布宽度）
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
            imgui.dummy(imgui.ImVec2(0, 6))  # 分隔线占位
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
                # 仅当两端 pin 都有效时处理
                if sp.id() != 0 and ep.id() != 0:
                    sd = canvas.find_pin_dir(sp.id())
                    ed = canvas.find_pin_dir(ep.id())
                    sn = canvas.find_pin_node(sp.id())
                    en = canvas.find_pin_node(ep.id())
                    # 仅当拖到合法的异向/异节点 pin 时，才尝试接受
                    if (sd and ed and sd != ed and sn and en and sn != en):
                        out_pin = sp.id() if sd == "output" else ep.id()
                        in_pin = ep.id() if sd == "output" else sp.id()
                        if (canvas.find_pin_dir(out_pin) == "output"
                                and canvas.find_pin_dir(in_pin) == "input"):
                            if ne.accept_new_item():
                                # 用户松手确认连线
                                lid = canvas.add_link(out_pin, in_pin)
                                if lid != -1:
                                    print(
                                        f"[Link] Created: "
                                        f"{canvas.find_pin_name(out_pin)} → "
                                        f"{canvas.find_pin_name(in_pin)}"
                                    )
                                else:
                                    print("[Link] Duplicate — skipped")
                            # NOTE: 不要 else: reject_new_item()！
                            # accept_new_item()==False 仅表示用户还没松手，
                            # 下一帧 begin_create() 仍然为 True，继续等待。
            ne.end_create()

        # ══════════════════════════════════════════════════════
        # 交互: Delete 键删除选中节点/连线
        # ══════════════════════════════════════════════════════
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

        # ══════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════
        # 空画布提示
        # ══════════════════════════════════════════════════════
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

        # ── Add 弹出菜单（同帧 open_popup + begin_popup，flag 门控） ──
        if self._add_popup_active:
            imgui.open_popup("Create Node")
            _bpop = imgui.begin_popup("Create Node")
            if _bpop:
                _draw_add_menu_section("Math", [
                    ("+ Add", "MathAdd"),
                    ("Subtract", "MathSubtract"),
                    ("Multiply", "MathMultiply"),
                    ("Divide", "MathDivide"),
                    ("Random Uniform", "MathRandomUniform"),
                    ("Random Gaussian", "MathRandomGaussian"),
                ], canvas, avail)
                _draw_add_menu_section("Time", [
                    ("Get Time", "TimeGetElapsed"),
                    ("Get Delta Time", "TimeGetDelta"),
                    ("Delay", "TimeDelay"),
                ], canvas, avail)
                _draw_add_menu_section("Entity", [
                    ("Create Entity", "EntityCreate"),
                    ("Destroy Entity", "EntityDestroy"),
                    ("Set Transform", "EntitySetTransform"),
                    ("Get Transform", "EntityGetTransform"),
                    ("Add Mesh Component", "EntityAddMesh"),
                    ("Add Camera Component", "EntityAddCamera"),
                    ("Find Entity By Name", "EntityFindByName"),
                    ("Set Visibility", "EntitySetVisibility"),
                ], canvas, avail)
                _draw_add_menu_section("Variable", [
                    ("Set Variable", "VarSet"),
                    ("Get Variable", "VarGet"),
                ], canvas, avail)
                _draw_add_menu_section("Debug", [
                    ("Print", "Print"),
                    ("Print String", "PrintString"),
                ], canvas, avail)
                imgui.end_popup()
            if not imgui.is_popup_open("Create Node"):
                self._add_popup_active = False

        # ══════════════════════════════════════════════════════
        # 同步拖拽后的节点位置（新节点第一帧 get_node_position 返回未初始化极值，跳过）
        # ══════════════════════════════════════════════════════
        for nid in list(canvas.nodes.keys()):
            np = ne.get_node_position(ne.NodeId(nid))
            inst = canvas.nodes[nid]
            # 只接受合理范围内的位置（-1e6 ~ 1e6），排除 INT_MIN/FLT_MAX 等垃圾值
            if -1e6 < np.x < 1e6 and -1e6 < np.y < 1e6:
                if (np.x, np.y) != inst.pos:
                    inst.pos = (np.x, np.y)
