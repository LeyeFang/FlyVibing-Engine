"""场景: 节点多选 / 右键组菜单 / 框选限制。

覆盖:
  - Shift+click 追加选择（引擎 InputState 优先，ImGui 注入回退）
  - 右键节点 → Delete Node / Merge into Group
  - 右键组框 → Ungroup / Destroy Group（全删）
  - 框选只保留真实节点（组框 NodeId 被移除）

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/node_group_actions.py
"""

NAME = "node_group_actions"
TIER = "gui"


def _graph() -> dict:
    from Application.Core.NodeGraph import _TYPES

    seq = [8300]

    def mk(t: str, alias: str = "") -> dict:
        pids = {}
        for p in _TYPES[t].pins:
            seq[0] += 1
            pids[p.name] = seq[0]
        data = {"node_type": t, "pos": [0.0, 0.0], "props": {}, "pin_ids": pids}
        if alias:
            data["alias"] = alias
        return data

    event = mk("OnGameStart", "boot")
    first = mk("Print", "first")
    second = mk("Print", "second")
    third = mk("Print", "third")
    return {
        "version": "0.1.0",
        "nodes": {"1": event, "2": first, "3": second, "4": third},
        "links": {
            "1": {"from_pin": event["pin_ids"]["exec"],
                  "to_pin": first["pin_ids"]["exec_in"]},
            "2": {"from_pin": first["pin_ids"]["exec_out"],
                  "to_pin": second["pin_ids"]["exec_in"]},
            "3": {"from_pin": second["pin_ids"]["exec_out"],
                  "to_pin": third["pin_ids"]["exec_in"]},
        },
        "next_id": seq[0] + 1,
    }


def _click(ctx, imgui, x: float, y: float, button: int = 0,
           shift: bool = False) -> None:
    io = imgui.get_io()
    io.add_mouse_pos_event(float(x), float(y))
    if shift:
        io.add_key_event(imgui.Key.left_shift, True)
        io.add_key_event(imgui.Key.mod_shift, True)
    ctx.frames(1)
    io.add_mouse_button_event(button, True)
    ctx.frames(1)
    io.add_mouse_button_event(button, False)
    ctx.frames(1)
    if shift:
        io.add_key_event(imgui.Key.left_shift, False)
        io.add_key_event(imgui.Key.mod_shift, False)
        ctx.frames(1)


def _drag(ctx, imgui, start, end) -> None:
    io = imgui.get_io()
    io.add_mouse_pos_event(float(start[0]), float(start[1]))
    ctx.frames(1)
    io.add_mouse_button_event(0, True)
    ctx.frames(1)
    io.add_mouse_pos_event(float(end[0]), float(end[1]))
    ctx.frames(2)
    io.add_mouse_button_event(0, False)
    ctx.frames(2)


def _double_click(ctx, imgui, x: float, y: float) -> None:
    io = imgui.get_io()
    io.add_mouse_pos_event(float(x), float(y))
    ctx.frames(1)
    for _ in range(2):
        io.add_mouse_button_event(0, True)
        ctx.frames(1)
        io.add_mouse_button_event(0, False)
        ctx.frames(1)


def _node_point(ne, imgui, nid: int):
    p = ne.get_node_position(ne.NodeId(nid))
    # 标题栏内部；经 canvas→screen 转换，避免缩放/滚动导致坐标错位。
    return ne.canvas_to_screen(imgui.ImVec2(p.x + 28.0, p.y + 18.0))


def run(ctx) -> None:
    from imgui_bundle import imgui, imgui_node_editor as ne
    from Application.Core.NodeGraph import graph_io

    ctx.frames(3)
    panel = ctx.panel("Node Editor")
    ctx.expect(panel is not None, "Node Editor panel registered")
    canvas = getattr(panel, "_canvas", None)
    ctx.expect(canvas is not None, "canvas initialized")

    data, refused = graph_io.prepare_import(graph=_graph(), validate_first=False)
    ctx.expect(refused is None, f"group action fixture prepared ({refused})")
    for pname in ("Scene", "Resources"):
        other = ctx.panel(pname)
        if other is not None:
            other.visible = False
    panel.visible = True
    graph_io.apply_to_canvas(canvas, data)
    panel._auto_layout(canvas)
    panel._fit_requested = True
    # 浮动的 Node Groups 窗口会遮住左侧节点；本场景用直接动作验证组操作，
    # 不需要打开它，否则合成点击会落到浮窗上（按视口宽度偶发）。
    panel._groups_open = False
    ctx.frames(3)

    # 画布外（工具栏/其它视口）的点击不能留下框选起点；否则下一次
    # 空白点击会把整个延迟矩形当成框选，误选到远处的节点。
    canvas_rect = getattr(panel, "_canvas_rect", None)
    ctx.expect(canvas_rect is not None, "node canvas screen rect recorded")
    if canvas_rect is not None:
        _click(ctx, imgui, canvas_rect[0] + 5.0, max(canvas_rect[1] - 18.0, 24.0))
        ctx.expect(panel._box_start_screen is None,
                   f"click outside canvas leaves no box start ({panel._box_start_screen})")

    n_a, n_b = 1, 2
    p1 = _node_point(ne, imgui, n_a)
    p2 = _node_point(ne, imgui, n_b)
    print(f"  [INFO] node points: #{n_a}=({p1.x:.0f},{p1.y:.0f}) "
          f"#{n_b}=({p2.x:.0f},{p2.y:.0f})")

    _click(ctx, imgui, p1.x, p1.y)
    selected = [n.id() for n in ne.get_selected_nodes()]
    ctx.expect(selected == [n_a], f"plain click selects one node ({selected})")

    # 单选节点右键菜单必须提供 Delete Node。
    _click(ctx, imgui, p1.x, p1.y, button=1)
    ctx.expect(panel._group_context_kind == "node"
               and panel._group_context_selection == {n_a},
               f"single-node context menu ({panel._group_context_kind}/"
               f"{panel._group_context_selection})")
    ctx.snapshot("context_menu_node")
    ctx.key(imgui.Key.escape, True)
    ctx.frames(1)
    ctx.key(imgui.Key.escape, False)
    ctx.frames(1)
    _click(ctx, imgui, p1.x, p1.y)

    # Simulate the InputState Shift modifier; the injected ImGui key also
    # exercises the fallback path in panel._shift_down.
    old_shift = panel._shift_down
    panel._shift_down = lambda: True
    try:
        _click(ctx, imgui, p2.x, p2.y, shift=True)
    finally:
        panel._shift_down = old_shift
    selected = {n.id() for n in ne.get_selected_nodes()}
    ctx.expect(selected == {n_a, n_b},
               f"shift+click adds a node ({sorted(selected)})")

    # Right-click empty background with multi-selection: Merge menu must keep it.
    _click(ctx, imgui, 1100, 520, button=1)
    ctx.expect(panel._group_context_kind == "background",
               f"right-click background context ({panel._group_context_kind})")
    ctx.expect(panel._group_context_selection == {n_a, n_b},
               f"background context keeps multi-selection ({panel._group_context_selection})")
    ctx.key(imgui.Key.escape, True)
    ctx.frames(1)
    ctx.key(imgui.Key.escape, False)
    ctx.frames(1)

    # Right-click one of the selected nodes: context menu kind must be node.
    _click(ctx, imgui, p2.x, p2.y, button=1)
    ctx.expect(panel._group_context_kind == "node",
               f"right-click node context ({panel._group_context_kind})")
    ctx.expect(panel._group_context_selection == {n_a, n_b},
               f"context keeps multi-selection ({panel._group_context_selection})")

    # Use the same action the popup menu calls; menu item click itself is
    # covered by ImGui, while this verifies the graph mutation path.
    panel._merge_group_from_selection(canvas, ne)
    ctx.frames(1)
    imgui.close_current_popup()
    ctx.key(imgui.Key.escape, True)
    ctx.frames(1)
    ctx.key(imgui.Key.escape, False)
    ctx.frames(1)
    ctx.expect("g1" in canvas.node_groups, f"merge creates group ({list(canvas.node_groups)})")
    group = canvas.node_groups.get("g1") or {}
    from Application.Core.NodeGraph.group_nodes import io_node_ids
    g_io = io_node_ids(canvas, "g1")
    user_members = [m for m in (group.get("members") or [])
                    if m not in g_io.values()]
    ctx.expect(sorted(user_members) == [n_a, n_b],
               f"group members are selected nodes ({group.get('members')})")
    ctx.expect(g_io.get("start") in canvas.nodes and g_io.get("end") in canvas.nodes,
               f"group owns start/end nodes ({g_io})")

    # 组命名：核心 rename_group 同步 alias，画布标题下帧读取同一字段。
    from Application.Core.NodeGraph.group_ops import rename_group
    renamed = rename_group(canvas, "g1", "trial_group")
    ctx.expect(renamed.get("ok") and group.get("alias") == "trial_group",
               f"group rename syncs alias ({renamed})")
    ctx.frames(1)
    title_text = panel._group_title_texts.get("g1", "")
    ctx.expect("@trial_group" in title_text,
               f"group title text follows alias ({title_text!r})")
    title_rect = panel._group_title_rects.get("g1")
    if title_rect is not None:
        _double_click(ctx, imgui, (title_rect[0] + title_rect[2]) * 0.5,
                      (title_rect[1] + title_rect[3]) * 0.5)
        ctx.expect(panel._group_inline_edit_gid == "g1"
                   and panel._group_inline_field == "name",
                   f"double-click title starts inline rename "
                   f"({panel._group_inline_edit_gid}/"
                   f"{panel._group_inline_field})")
        ctx.frames(1)
        ctx.snapshot("group_inline_rename")
        panel._clear_group_inline_edit()
    from Application.Core.NodeGraph.group_ops import set_group_description
    set_group_description(canvas, "g1", "trial description")
    ctx.frames(1)
    ctx.expect(panel._group_description_texts.get("g1") == "trial description",
               f"group description drawn under title "
               f"({panel._group_description_texts.get('g1')!r})")
    desc_rect = panel._group_description_rects.get("g1")
    if desc_rect is not None:
        _double_click(ctx, imgui, (desc_rect[0] + desc_rect[2]) * 0.5,
                      (desc_rect[1] + desc_rect[3]) * 0.5)
        ctx.expect(panel._group_inline_edit_gid == "g1"
                   and panel._group_inline_field == "description",
                   f"double-click description starts inline edit "
                   f"({panel._group_inline_edit_gid}/"
                   f"{panel._group_inline_field})")
        panel._clear_group_inline_edit()
    rename_group(canvas, "g1", "group_1")

    # 拖组标题：整组 + 成员一起平移（不依赖原生 group drag 区域）。
    from Application.Core.NodeGraph.group_geometry import get_box as _get_box
    drag_box_before = _get_box(canvas, "g1")
    drag_pos_before = {nid: tuple(canvas.nodes[nid].pos) for nid in (1, 2)}
    title_rect = panel._group_title_rects.get("g1")
    if drag_box_before is not None and title_rect is not None:
        _drag(ctx, imgui, ((title_rect[0] + title_rect[2]) * 0.5,
                           (title_rect[1] + title_rect[3]) * 0.5),
              ((title_rect[0] + title_rect[2]) * 0.5 + 36.0,
               (title_rect[1] + title_rect[3]) * 0.5 + 24.0))
        ctx.frames(2)
        drag_box_after = _get_box(canvas, "g1")
        ctx.expect(drag_box_after is not None
                   and drag_box_after[0] > drag_box_before[0] + 10.0
                   and drag_box_after[1] > drag_box_before[1] + 5.0,
                   f"dragging title moves group box ({drag_box_before} -> {drag_box_after})")
        ctx.expect(any(tuple(canvas.nodes[nid].pos) != drag_pos_before[nid]
                       for nid in (1, 2)),
                   "dragging title moves group members")

    # 成员进入/离开：在组内空白点松开 → 节点加入并扩框；拖到组外 → 移除并收紧。
    from Application.Core.NodeGraph.group_geometry import get_box, get_min_box

    box_before = get_box(canvas, "g1")
    canvas.nodes[3].pos = (box_before[0] + box_before[2] * 0.5,
                           box_before[1] + box_before[3] * 0.5)
    panel._apply_node_drop(canvas, 3,
                           (box_before[0] + box_before[2] * 0.5,
                            box_before[1] + box_before[3] * 0.5))
    ctx.frames(1)
    ctx.expect(3 in (canvas.node_groups.get("g1") or {}).get("members", []),
               "dragging into group adds membership")
    box_after = get_box(canvas, "g1") or box_before
    ctx.expect(box_after[2] >= box_before[2]
               and box_after[3] >= box_before[3],
               f"entering node expands group box ({box_before} -> {box_after})")

    canvas.nodes[3].pos = (box_after[0] + box_after[2] + 240.0,
                           box_after[1] + box_after[3] + 160.0)
    panel._apply_node_drop(canvas, 3,
                           (canvas.nodes[3].pos[0] + 10.0,
                            canvas.nodes[3].pos[1] + 10.0))
    ctx.frames(1)
    ctx.expect(3 not in (canvas.node_groups.get("g1") or {}).get("members", []),
               "dragging out of group removes membership")
    min_box = get_min_box(canvas, "g1")
    ctx.expect(min_box is not None, f"group records min box after leave ({min_box})")

    # 右下角手柄缩放：成员 position 按比例移动，且不能缩到 min_box 以下。
    frame = panel._group_frame_rects.get("g1")
    ctx.expect(frame is not None, f"group resize handle frame ({frame})")
    if frame is not None:
        before_box = get_box(canvas, "g1")
        before_pos = {nid: tuple(canvas.nodes[nid].pos) for nid in (1, 2)}
        _drag(ctx, imgui, (frame[2] - 4.0, frame[3] - 4.0),
              (frame[2] + 60.0, frame[3] + 40.0))
        ctx.frames(2)
        after_box = get_box(canvas, "g1")
        after_frame = panel._group_frame_rects.get("g1")
        ctx.expect(after_box is not None and before_box is not None
                   and after_box[2] > before_box[2]
                   and after_box[3] > before_box[3],
                   f"corner handle resizes group ({before_box} -> {after_box})")
        ctx.expect(after_frame is not None
                   and (after_frame[2] - after_frame[0])
                   > (frame[2] - frame[0]) + 1.0,
                   f"corner handle changes drawn frame ({frame} -> {after_frame})")
        ctx.expect(any(tuple(canvas.nodes[nid].pos) != before_pos[nid]
                       for nid in (1, 2)),
                   "corner resize moves members proportionally")
        # 反向拖动手柄也不能小于成员包围盒 + margin 纪录的 min_box。
        min_now = get_min_box(canvas, "g1")
        if after_frame is not None and min_now is not None:
            _drag(ctx, imgui, (after_frame[2] - 4.0, after_frame[3] - 4.0),
                  (after_frame[2] - 520.0, after_frame[3] - 360.0))
            ctx.frames(2)
            clamped = get_box(canvas, "g1")
            ctx.expect(clamped is not None
                       and clamped[2] >= min_now[0] - 0.1
                       and clamped[3] >= min_now[1] - 0.1,
                       f"corner resize clamps to min box ({clamped} / {min_now})")

    snap_group = ctx.snapshot("group_created")
    ctx.expect(snap_group["bytes"] > 10000,
               f"group frame snapshot non-trivial ({snap_group['bytes']} bytes)")
    io_info = panel._group_io.get("g1") or {}
    ctx.expect(io_info.get("start_node") in canvas.nodes
               and io_info.get("end_node") in canvas.nodes
               and canvas.nodes[io_info["start_node"]].node_type == "GroupStart"
               and canvas.nodes[io_info["end_node"]].node_type == "GroupEnd",
               f"group exposes real start/end nodes ({io_info})")
    ctx.expect(io_info.get("out_pin") is not None
               and io_info.get("in_pin") is not None,
               f"group start/end pins are real ({io_info})")

    # 组标题必须紧贴组框（官方顺序: Text 在 Group 之前），不能落到画布空白处。
    title_rect = panel._group_title_rects.get("g1")
    frame_rect = panel._group_frame_rects.get("g1")
    ctx.expect(title_rect is not None and frame_rect is not None,
               f"group title/frame rects recorded ({title_rect} / {frame_rect})")
    if title_rect is not None and frame_rect is not None:
        # 标题现在画在组框内部左上角（Group() 之后显式定位）。
        aligned = (title_rect[0] >= frame_rect[0] - 1.0
                   and title_rect[1] >= frame_rect[1] - 1.0
                   and title_rect[2] <= frame_rect[2] + 1.0
                   and title_rect[3] <= frame_rect[3] + 1.0)
        ctx.expect(aligned,
                   f"group title sits inside its frame (title={title_rect}, "
                   f"frame={frame_rect})")

    # Select the group frame, then right-click it.
    gid = "g1"
    group_node = ne.NodeId(panel._group_editor_id(gid))
    ne.clear_selection()
    ne.select_node(group_node)
    ctx.frames(1)
    ctx.frames(1)
    rect = panel._group_screen_rects.get(gid)
    ctx.expect(rect is not None, f"group frame has drawn screen rect ({rect})")
    # 组框中央是“洞”（imgui-node-editor 不接收交互），要点边框；
    # 左侧可能被浮动的 Node Groups 窗口遮住，取右边缘内 4px。
    canvas_rect = panel._canvas_rect
    gy = max(rect[1] + 3.0, canvas_rect[1] + 10.0)
    gscreen = imgui.ImVec2(rect[2] - 4.0, gy)
    ne.clear_selection()
    _click(ctx, imgui, gscreen.x, gscreen.y)
    ctx.expect(ne.is_node_selected(group_node), "left click selects group frame")
    _click(ctx, imgui, gscreen.x, gscreen.y, button=1)
    ctx.expect(panel._group_context_kind == "group",
               f"right-click group context ({panel._group_context_kind})")
    ctx.snapshot("context_menu_group")

    panel._ungroup_group_action(canvas, ne, gid)
    ctx.frames(2)
    ctx.expect(gid not in canvas.node_groups, "ungroup removes frame")
    ctx.expect(set(canvas.nodes) == {1, 2, 3, 4}, "ungroup keeps nodes")

    # Recreate a group to exercise Delete Group through the same action path.
    panel._group_context_selection = {n_a, n_b}
    panel._merge_group_from_selection(canvas, ne)
    ctx.frames(1)
    second_gid = next(iter(canvas.node_groups), "")
    ctx.expect(bool(second_gid), f"second merge creates a group ({second_gid})")

    # Box selection must select concrete nodes only, never the group frame it
    # intersects (the frame is a node-editor Node too, but only in the UI layer).
    # 按当前节点屏幕矩形构造框选区域（覆盖 #2/#3，同时跨过组框）。
    rect2 = panel._node_screen_rects.get(2)
    rect3 = panel._node_screen_rects.get(3)
    ctx.expect(rect2 is not None and rect3 is not None,
               "nodes #2/#3 have drawn screen rects")
    if rect2 is not None and rect3 is not None:
        x0 = min(rect2[0], rect3[0]) - 20.0
        y0 = min(rect2[1], rect3[1]) - 20.0
        x1 = max(rect2[2], rect3[2]) + 20.0
        y1 = max(rect2[3], rect3[3]) + 20.0
        cr = panel._canvas_rect
        # 从组框左上方画布空白开始，避免起点落在组框边缘/缩放手柄上
        # （那些区域被组拖动/缩放接管，不是框选起点）。
        group_rect = panel._group_screen_rects.get(second_gid)
        bx0 = max(cr[0] + 4.0, (group_rect[0] - 40.0) if group_rect else x0 - 80.0)
        by0 = max(cr[1] + 4.0, (group_rect[1] - 40.0) if group_rect else y1 + 80.0)
        bx1 = min(cr[2] - 12.0, x1 + 80.0)
        by1 = min(cr[3] - 12.0, y1 + 80.0)
        _drag(ctx, imgui, (bx0, by0), (bx1, by1))
    box_nodes = panel._selected_real_nodes(canvas, ne)
    box_groups = panel._selected_group_ids(canvas, ne)
    ctx.expect(len(box_nodes) >= 2, f"box selection selects nodes ({box_nodes})")
    ctx.expect(not box_groups, f"box selection skips groups ({box_groups})")

    # 框选松开后的第一次点击必须只命中目标节点，不能复用旧框选矩形。
    cr = panel._canvas_rect
    _click(ctx, imgui, cr[2] - 24.0, cr[1] + 24.0)
    clicked_after_box = [n.id() for n in ne.get_selected_nodes()]
    ctx.expect(clicked_after_box == [],
               f"click after box release clears selection ({clicked_after_box})")

    # 空白右键在零选择时也必须打开菜单（显示 no selected node）。
    _click(ctx, imgui, cr[2] - 24.0, cr[1] + 24.0, button=1)
    ctx.expect(panel._group_context_kind == "background"
               and not panel._group_context_selection,
               f"empty background context has no selection "
               f"({panel._group_context_kind}/{panel._group_context_selection})")
    ctx.snapshot("context_menu_empty")
    ctx.key(imgui.Key.escape, True)
    ctx.frames(1)
    ctx.key(imgui.Key.escape, False)
    ctx.frames(1)

    panel._delete_group_action(canvas, ne, second_gid)
    ctx.frames(1)
    ctx.expect(second_gid not in canvas.node_groups, "destroy removes group frame")
    ctx.expect(set(canvas.nodes) == {3, 4},
               f"destroy removes every member node ({sorted(canvas.nodes)})")

    # 单节点右键的 Delete Node 走同一删除路径。
    ne.clear_selection()
    ne.select_node(ne.NodeId(3))
    ctx.frames(1)
    deleted_nodes = panel._delete_selected_nodes(canvas, ne)
    ctx.frames(1)
    ctx.expect(deleted_nodes == 1 and 3 not in canvas.nodes,
               f"delete selected node removes it ({deleted_nodes}/{sorted(canvas.nodes)})")

    snap = ctx.snapshot("group_actions")
    ctx.expect(snap["bytes"] > 10000, f"group action snapshot non-trivial ({snap['bytes']} bytes)")
