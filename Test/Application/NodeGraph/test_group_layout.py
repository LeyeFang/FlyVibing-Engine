"""组感知布局 — 嵌套组/组框边界/节点不重叠（无 imgui）。

TIER: core
运行: python Test/Application/NodeGraph/test_group_layout.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        ROOT = ""
        break
    ROOT = parent
assert ROOT, "repo root not found"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Application.Core.NodeGraph.canvas import NodeCanvas  # noqa: E402
from Application.Editor.UI.panels.node_editor.group_layout import (  # noqa: E402
    GroupLayoutEngine,
    group_bounds,
    group_member_ids,
    group_order,
    node_size,
)

_passed = 0
_failed: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _canvas() -> NodeCanvas:
    canvas = NodeCanvas()
    event = canvas.add_node("OnGameStart", (0.0, 0.0))
    first = canvas.add_node("Print", (0.0, 0.0))
    nested = canvas.add_node("Print", (0.0, 0.0))
    outside = canvas.add_node("Print", (0.0, 0.0))
    canvas.nodes[event].alias = "boot"
    canvas.nodes[first].alias = "first"
    canvas.nodes[nested].alias = "nested"
    canvas.nodes[outside].alias = "outside"
    canvas.add_link(canvas.nodes[event].pin_ids["exec"],
                    canvas.nodes[first].pin_ids["exec_in"])
    canvas.add_link(canvas.nodes[first].pin_ids["exec_out"],
                    canvas.nodes[nested].pin_ids["exec_in"])
    canvas.add_link(canvas.nodes[nested].pin_ids["exec_out"],
                    canvas.nodes[outside].pin_ids["exec_in"])
    canvas.node_groups = {
        "g2": {"type": "container", "alias": "inner", "version": 1,
               "members": [nested], "parent": "g1", "params": {}, "slots": {}},
        "g1": {"type": "container", "alias": "outer", "version": 1,
               "members": [first, nested], "children": ["g2"],
               "params": {}, "slots": {}},
    }
    return canvas


def _overlaps(a, b) -> bool:
    ax, ay = a.pos
    bx, by = b.pos
    aw, ah = node_size(a)
    bw, bh = node_size(b)
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def main() -> int:
    print("Group-aware layout")
    canvas = _canvas()
    positions = GroupLayoutEngine(canvas).layout_all()
    check("every node receives a layout position", len(positions) == len(canvas.nodes),
          f"{len(positions)}/{len(canvas.nodes)}")

    for nid, (x, y) in positions.items():
        canvas.nodes[nid].pos = (x, y)

    outer = group_bounds(canvas, "g1")
    inner = group_bounds(canvas, "g2")
    check("group frames have bounds", outer is not None and inner is not None)
    if outer is not None and inner is not None:
        check("child group stays inside parent",
              inner[0] >= outer[0] and inner[1] >= outer[1]
              and inner[0] + inner[2] <= outer[0] + outer[2]
              and inner[1] + inner[3] <= outer[1] + outer[3],
              f"outer={outer} inner={inner}")
    check("group order paints parent before child",
          group_order(canvas).index("g1") < group_order(canvas).index("g2"))
    by_alias = {inst.alias: nid for nid, inst in canvas.nodes.items()}
    check("parent member list includes nested member",
          set(group_member_ids(canvas, "g1")) >=
          {by_alias["first"], by_alias["nested"]},
          str(group_member_ids(canvas, "g1")))
    check("child member list is scoped",
          set(group_member_ids(canvas, "g2")) == {by_alias["nested"]},
          str(group_member_ids(canvas, "g2")))

    ids = list(canvas.nodes)
    overlap = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if
               _overlaps(canvas.nodes[a], canvas.nodes[b])]
    check("no card overlap after layout", not overlap, str(overlap))

    nested_positions = GroupLayoutEngine(canvas).layout_group("g2")
    check("layout_group only returns child members",
          set(nested_positions) == {by_alias["nested"]}, str(sorted(nested_positions)))

    print()
    if _failed:
        print(f"RESULT: FAIL ({len(_failed)}): {', '.join(_failed)}")
        return 1
    print(f"RESULT: OK ({_passed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
