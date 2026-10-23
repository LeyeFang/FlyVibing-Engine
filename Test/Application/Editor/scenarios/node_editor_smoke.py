"""场景: 节点编辑器冒烟 — 画布就绪 / graph_io 导入（GUI 与 ops 同一实现）/ 快照。

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/node_editor_smoke.py
"""

NAME = "node_editor_smoke"
TIER = "gui"


def _tiny_graph() -> dict:
    from Application.Core.NodeGraph import _TYPES

    seq = [8000]

    def mk(t: str) -> dict:
        pids = {}
        for p in _TYPES[t].pins:
            seq[0] += 1
            pids[p.name] = seq[0]
        return {"node_type": t, "pos": [0.0, 0.0], "props": {}, "pin_ids": pids}

    n1, n2 = mk("OnGameStart"), mk("Print")
    return {
        "version": "0.1.0",
        "nodes": {"1": n1, "2": n2},
        "links": {"1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]}},
        "next_id": seq[0] + 1,
    }


def _widget_graph() -> dict:
    """8 个 widget 子模块各挑一个代表类型（空 props → 默认值填充路径）。"""
    from Application.Core.NodeGraph import _TYPES

    reps = ["Constant",             # flow_io
            "EntitySpawn",          # entity_comp
            "InitSigGenDevice",     # device_siggen
            "CreateDevicePool",     # device_pool
            "EpochCount",           # epoch
            "InitFBCSP",            # algorithm
            "ShowMedia",            # media
            "TimeGetElapsed"]       # flow_io — combo width guard
    seq = [9000]
    nodes = {}
    for i, t in enumerate(reps, start=1):
        pids = {}
        for p in _TYPES[t].pins:
            seq[0] += 1
            pids[p.name] = seq[0]
        nodes[str(i)] = {"node_type": t, "pos": [0.0, 0.0], "props": {}, "pin_ids": pids}
    return {"version": "0.1.0", "nodes": nodes, "links": {},
            "next_id": seq[0] + 1, "_reps": reps}


def run(ctx) -> None:
    ctx.frames(3)
    s1 = ctx.snapshot("node_editor_boot")
    ctx.expect(s1["bytes"] > 10000, f"boot snapshot non-trivial ({s1['bytes']} bytes)")

    panel = ctx.panel("Node Editor")
    ctx.expect(panel is not None, "Node Editor panel registered")
    canvas = getattr(panel, "_canvas", None)
    ctx.expect(canvas is not None, "canvas initialized after first frames")

    # ── graph_io 导入（面板 Import 与 agent ops 的同一实现路径）──
    from Application.Core.NodeGraph import graph_io

    data, refused = graph_io.prepare_import(graph=_tiny_graph(), validate_first=True)
    ctx.expect(refused is None, f"static check passes ({refused})")
    result = graph_io.apply_to_canvas(canvas, data)
    ctx.expect(result["nodes"] == 2 and result["links"] == 1, f"canvas replaced ({result})")

    # 让 Node Editor 从 Tab 组中露出（隐藏 Scene 页）→ 快照可见画布
    scene_panel = ctx.panel("Scene")
    if scene_panel is not None:
        scene_panel.visible = False
    ctx.frames(2)
    s2 = ctx.snapshot("graph_imported")
    ctx.expect(s2["bytes"] > 10000, f"graph snapshot non-trivial ({s2['bytes']} bytes)")
    ctx.expect(len(canvas.nodes) == 2, "canvas state persists")

    # ── widget 模块覆盖: 8 个拆分子模块各画一个代表类型（空 props 默认值路径）──
    for pname in ("Scene", "Resources"):
        other = ctx.panel(pname)
        if other is not None:
            other.visible = False
    panel.visible = True
    ctx.frames(3)
    wg = _widget_graph()
    reps = wg.pop("_reps")
    data2, refused2 = graph_io.prepare_import(graph=wg, validate_first=False)
    ctx.expect(refused2 is None, f"widget graph prepared ({refused2})")
    graph_io.apply_to_canvas(canvas, data2)
    ctx.frames(2)  # 绘制 → draw_node_widgets 分发到全部子模块
    s3 = ctx.snapshot("widgets_all_modules")
    ctx.expect(s3["bytes"] > 10000, f"widgets snapshot non-trivial ({s3['bytes']} bytes)")
    ctx.expect(len(canvas.nodes) == len(reps),
               f"widget graph persists ({len(canvas.nodes)}/{len(reps)})")
    gettime_rect = panel._node_screen_rects.get(8)
    gettime_w = (gettime_rect[2] - gettime_rect[0]) if gettime_rect else 0.0
    # 窗口宽铺满整屏时卡片仍应是正常节点宽度；旧实现 BeginCombo 继承
    # 可用宽度，会把卡片拉到上千像素。
    ctx.expect(gettime_rect is not None and 20.0 < gettime_w < 500.0,
               f"GetTime combo/card width bounded ({gettime_w:.1f}px)")

    # ── 组框 + 别名：元数据穿过 graph_io → 画布 → 面板绘制 ──
    gg = _tiny_graph()
    gg["nodes"]["1"]["alias"] = "boot"
    gg["nodes"]["1"]["description"] = "Starts the example and spawns templates."
    gg["nodes"]["1"]["pos"] = [60.0, 60.0]
    gg["nodes"]["2"]["pos"] = [360.0, 120.0]
    gg["node_groups"] = {
        "g1": {"type": "demo_group", "alias": "demo_grp", "version": 1,
               "params": {}, "members": [1, 2], "slots": {}},
    }
    data3, refused3 = graph_io.prepare_import(graph=gg, validate_first=False)
    ctx.expect(refused3 is None, f"group graph prepared ({refused3})")
    graph_io.apply_to_canvas(canvas, data3)
    ctx.frames(2)
    s4 = ctx.snapshot("group_and_alias")
    ctx.expect(s4["bytes"] > 10000, f"group snapshot non-trivial ({s4['bytes']} bytes)")
    ctx.expect(canvas.nodes[1].alias == "boot", "alias survives graph_io")
    ctx.expect(canvas.nodes[1].description ==
               "Starts the example and spawns templates.",
               "description survives graph_io")
    ctx.expect(canvas.node_groups.get("g1", {}).get("alias") == "demo_grp",
               "node_groups survive graph_io")

    # Fit 视图（工具栏按钮同路径 — 组框/节点整体入镜）
    for pname in ("Scene", "Resources"):
        other_panel = ctx.panel(pname)
        if other_panel is not None:
            other_panel.visible = False
    panel.visible = True
    panel._fit_requested = True
    ctx.frames(2)
    ctx.expect(panel._fit_requested is False,
               "Fit consumes navigate-to-content request")
    s5 = ctx.snapshot("group_fit_view")
    ctx.expect(s5["bytes"] > 10000, f"fit view snapshot non-trivial ({s5['bytes']} bytes)")

    # 描述展开 -> 多行编辑控件（同一帧绘制路径）
    panel._desc_open.add(1)
    ctx.frames(2)
    s6 = ctx.snapshot("description_expanded")
    ctx.expect(s6["bytes"] > 10000,
               f"description expanded snapshot non-trivial ({s6['bytes']} bytes)")
    ctx.expect(canvas.nodes[1].description ==
               "Starts the example and spawns templates.",
               "description stable while expanded")
