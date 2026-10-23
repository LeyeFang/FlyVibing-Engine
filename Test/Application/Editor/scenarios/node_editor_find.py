"""场景: 节点查询窗口 — 别名搜索 / 命中列表 / Go To / Delete。

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/node_editor_find.py
"""

NAME = "node_editor_find"
TIER = "gui"


def _graph() -> dict:
    from Application.Core.NodeGraph import _TYPES

    seq = [8100]

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
    left = mk("Print", "left cue")
    right = mk("Print", "right cue")
    other = mk("Print", "status")
    # Deliberately identical display labels: Find Node must use stable ids,
    # not the visible alias/type text, for imgui item identity.
    unnamed = [mk("Branch"), mk("Branch"), mk("Compare"), mk("Compare")]
    nodes = {"1": event, "2": left, "3": right, "4": other}
    for i, nd in enumerate(unnamed, start=5):
        nodes[str(i)] = nd
    return {
        "version": "0.1.0",
        "nodes": nodes,
        "links": {
            "1": {"from_pin": event["pin_ids"]["exec"],
                  "to_pin": left["pin_ids"]["exec_in"]},
            "2": {"from_pin": left["pin_ids"]["exec_out"],
                  "to_pin": right["pin_ids"]["exec_in"]},
            "3": {"from_pin": right["pin_ids"]["exec_out"],
                  "to_pin": other["pin_ids"]["exec_in"]},
        },
        "next_id": seq[0] + 1,
    }


def run(ctx) -> None:
    ctx.frames(3)
    panel = ctx.panel("Node Editor")
    ctx.expect(panel is not None, "Node Editor panel registered")
    canvas = getattr(panel, "_canvas", None)
    ctx.expect(canvas is not None, "canvas initialized")

    from Application.Core.NodeGraph import graph_io

    data, refused = graph_io.prepare_import(graph=_graph(), validate_first=False)
    ctx.expect(refused is None, f"find fixture graph prepared ({refused})")
    graph_io.apply_to_canvas(canvas, data)
    ctx.frames(2)

    for pname in ("Scene", "Resources"):
        other_panel = ctx.panel(pname)
        if other_panel is not None:
            other_panel.visible = False
    panel.visible = True
    panel._find_open = True
    panel._find_query = "cue"
    ctx.frames(2)
    from imgui_bundle import imgui_node_editor as ne
    ctx.expect(ne.get_current_zoom() >= 0.55,
               f"persisted node view is readable (zoom={ne.get_current_zoom():.3f})")
    hits = panel._find_results(canvas)
    ctx.expect(len(hits) == 2, f"alias query returns two cues ({len(hits)})")
    ctx.expect({canvas.nodes[n].alias for n in hits} == {"left cue", "right cue"},
               "alias query is alias based")
    snap = ctx.snapshot("find_window")
    ctx.expect(snap["bytes"] > 10000, f"find window snapshot non-trivial ({snap['bytes']} bytes)")

    panel._find_selected = hits[0]
    ctx.frames(1)
    panel._focus_node(hits[0])
    ctx.frames(1)
    ctx.expect(panel._last_focused_node == hits[0],
               f"Go To records focused node ({panel._last_focused_node})")

    before = len(canvas.nodes)
    ctx.expect(panel._delete_find_selected(canvas), "Delete removes selected result")
    ctx.expect(len(canvas.nodes) == before - 1,
               f"node count after delete ({len(canvas.nodes)}/{before})")
    panel._find_query = ""
    ctx.frames(1)
    ctx.expect(len(panel._find_results(canvas)) == before - 1,
               "empty query lists remaining nodes")
    unnamed_nodes = [nid for nid, inst in canvas.nodes.items()
                     if not getattr(inst, "alias", "")]
    ctx.expect(len(unnamed_nodes) >= 4,
               f"duplicate unnamed labels exercised ({len(unnamed_nodes)})")
    snap_all = ctx.snapshot("find_all_duplicate_labels")
    ctx.expect(snap_all["bytes"] > 10000,
               f"duplicate-label list snapshot non-trivial ({snap_all['bytes']} bytes)")
