"""场景: 节点组 — 嵌套组布局 / 组框拖动 / 组内重排 / Fit Group。

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/node_groups_smoke.py
"""

NAME = "node_groups_smoke"
TIER = "gui"


def _graph() -> dict:
    from Application.Core.NodeGraph import _TYPES

    seq = [8200]

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
    nested = mk("Print", "nested")
    nested2 = mk("Print", "nested2")
    outside = mk("Print", "outside")
    return {
        "version": "0.1.0",
        "nodes": {"1": event, "2": first, "3": nested,
                  "4": outside, "5": nested2},
        "links": {
            "1": {"from_pin": event["pin_ids"]["exec"],
                  "to_pin": first["pin_ids"]["exec_in"]},
            "2": {"from_pin": first["pin_ids"]["exec_out"],
                  "to_pin": nested["pin_ids"]["exec_in"]},
            "3": {"from_pin": nested["pin_ids"]["exec_out"],
                  "to_pin": nested2["pin_ids"]["exec_in"]},
            "4": {"from_pin": nested2["pin_ids"]["exec_out"],
                  "to_pin": outside["pin_ids"]["exec_in"]},
        },
        "next_id": seq[0] + 1,
        "node_groups": {
            "g2": {
                "type": "container", "alias": "inner", "version": 1,
                "members": [3, 5], "parent": "g1",
                "params": {}, "slots": {},
            },
            "g1": {
                "type": "container", "alias": "outer", "version": 1,
                "members": [2, 3, 5], "children": ["g2"],
                "params": {}, "slots": {},
            },
        },
    }


def run(ctx) -> None:
    ctx.frames(3)
    panel = ctx.panel("Node Editor")
    ctx.expect(panel is not None, "Node Editor panel registered")
    canvas = getattr(panel, "_canvas", None)
    ctx.expect(canvas is not None, "canvas initialized")

    from Application.Core.NodeGraph import graph_io
    from Application.Editor.UI.panels.node_editor.group_layout import group_bounds

    data, refused = graph_io.prepare_import(graph=_graph(), validate_first=False)
    ctx.expect(refused is None, f"group fixture graph prepared ({refused})")
    for pname in ("Scene", "Resources"):
        other_panel = ctx.panel(pname)
        if other_panel is not None:
            other_panel.visible = False
    panel.visible = True
    graph_io.apply_to_canvas(canvas, data)
    panel._auto_layout(canvas)
    panel._groups_open = True
    panel._active_group = "g1"
    panel._fit_requested = True
    ctx.frames(2)

    outer = group_bounds(canvas, "g1")
    inner = group_bounds(canvas, "g2")
    ctx.expect(outer is not None and inner is not None, "both group frames have bounds")
    ctx.expect(inner[0] >= outer[0] and inner[1] >= outer[1]
               and inner[0] + inner[2] <= outer[0] + outer[2]
               and inner[1] + inner[3] <= outer[1] + outer[3],
               f"nested group stays inside parent outer={outer} inner={inner}")
    ctx.expect(outer[0] > canvas.nodes[1].pos[0],
               "group is placed after the upstream event node")

    snap = ctx.snapshot("nested_groups")
    ctx.expect(snap["bytes"] > 10000,
               f"group snapshot non-trivial ({snap['bytes']} bytes)")

    # Real drag path: select the group frame in node-editor, nudge its NodeId;
    # the next draw converts that delta into a member-subtree translation.
    from imgui_bundle import imgui, imgui_node_editor as ne

    group_node = panel._group_editor_id("g2")
    ctx.frames(1)
    ne.select_node(ne.NodeId(group_node))
    frame_pos = ne.get_node_position(ne.NodeId(group_node))
    member_before = tuple(canvas.nodes[3].pos)
    ne.set_node_position(
        ne.NodeId(group_node),
        imgui.ImVec2(frame_pos.x + 37.0, frame_pos.y + 23.0))
    ctx.frames(2)
    ctx.expect(canvas.nodes[3].pos != member_before,
               "dragging a group frame moves its members")

    # Simulate the user moving child cards, then rearrange only that group.
    canvas.nodes[3].pos = (canvas.nodes[3].pos[0] + 111.0,
                           canvas.nodes[3].pos[1] + 47.0)
    canvas.nodes[5].pos = (canvas.nodes[5].pos[0] - 53.0,
                           canvas.nodes[5].pos[1] + 29.0)
    perturbed = {3: tuple(canvas.nodes[3].pos), 5: tuple(canvas.nodes[5].pos)}
    panel._auto_layout_group(canvas, "g2")
    ctx.frames(1)
    ctx.expect(canvas.nodes[3].pos != perturbed[3],
               "group-internal rearrange moves first member")
    ctx.expect(canvas.nodes[5].pos != perturbed[5],
               "group-internal rearrange moves second member")

    before = {nid: tuple(inst.pos) for nid, inst in canvas.nodes.items()}
    moved = panel._move_group(canvas, "g2", 30.0, 20.0)
    ctx.expect(moved == 2, f"drag moves child group members ({moved})")
    ctx.expect(canvas.nodes[3].pos == (before[3][0] + 30.0, before[3][1] + 20.0),
               "child group member follows drag")
    ctx.expect(canvas.nodes[2].pos == before[2],
               "sibling member outside child group stays put")

    panel._fit_group_pending = "g1"
    ctx.frames(2)
    ctx.expect(group_bounds(canvas, "g1") is not None, "Fit Group keeps the frame valid")
