"""节点组元数据操作 — merge / ungroup / delete（纯数据）。"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402,F401

from Application.Core.NodeGraph.group_ops import (  # noqa: E402
    delete_group,
    destroy_group,
    group_for_node,
    merge_nodes,
    rename_group,
    resolve_group,
    set_group_description,
    ungroup,
)
from Application.Core.NodeGraph.group_nodes import (  # noqa: E402
    END_TYPE,
    START_TYPE,
    ensure_group_io_nodes,
    io_node_ids,
)
from Application.Core.NodeGraph.group_geometry import (  # noqa: E402
    ensure_box,
    expand_group_to_rect,
    fit_group,
    get_box,
    get_min_box,
    group_at_point,
    scale_group_to_box,
    set_member,
    translate_group,
)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _Canvas:
    def __init__(self, count: int = 6) -> None:
        self.nodes = {nid: SimpleNamespace(pos=(0.0, 0.0)) for nid in range(1, count + 1)}
        self.node_groups: dict = {}


def main() -> int:
    print("=" * 60)
    print("Node graph group metadata ops")
    print("=" * 60)

    canvas = _Canvas()
    result = merge_nodes(canvas, [1, 2])
    check("merge creates group", result["ok"], str(result.get("errors")))
    check("merge allocates g1", result.get("gid") == "g1", str(result.get("gid")))
    check("merge auto alias", result.get("alias") == "group_1", str(result.get("alias")))
    check("merge keeps both members",
          canvas.node_groups["g1"]["members"] == [1, 2],
          str(canvas.node_groups["g1"]["members"]))
    check("group_for_node finds g1", group_for_node(canvas, 2) == "g1",
          str(group_for_node(canvas, 2)))

    duplicate = merge_nodes(canvas, [3, 4], alias="group_1")
    check("duplicate alias rejected", not duplicate["ok"] and "duplicate" in duplicate["errors"][0],
          str(duplicate.get("errors")))

    result = merge_nodes(canvas, [1, 2, 3])
    check("merge group + node creates parent", result["ok"] and result.get("gid") == "g2",
          str(result))
    check("selected group becomes child",
          canvas.node_groups["g2"]["children"] == ["g1"]
          and canvas.node_groups["g1"].get("parent") == "g2",
          str(canvas.node_groups))

    partial = merge_nodes(canvas, [2, 4])
    check("partial group selection rejected",
          not partial["ok"] and "partially" in partial["errors"][0],
          str(partial.get("errors")))

    result = ungroup(canvas, "g2")
    check("ungroup removes only frame", result["ok"] and "g2" not in canvas.node_groups,
          str(result))
    check("ungroup re-roots child",
          "parent" not in canvas.node_groups["g1"],
          str(canvas.node_groups["g1"]))
    check("ungroup keeps nodes", set(canvas.nodes) == set(range(1, 7)),
          f"{sorted(canvas.nodes)}")

    canvas.nodes[5].alias = "ref_a"
    canvas.nodes[6].alias = "ref_b"
    alias_merge = merge_nodes(canvas, ["@ref_a", "ref_b"])
    check("merge resolves @alias refs", alias_merge["ok"], str(alias_merge.get("errors")))
    check("alias merge members",
          sorted((canvas.node_groups.get(alias_merge.get("gid") or "") or {}).get("members") or [])
          == [5, 6], str(canvas.node_groups))
    ungroup(canvas, alias_merge.get("gid") or "")

    # Nested delete: remove parent + child metadata, keep nodes. IDs are reused
    # only inside this fixture (g1 is intentionally re-created).
    canvas.node_groups["g1"] = {
        "type": "container", "alias": "outer", "members": [1, 2],
        "children": ["g3"], "slots": {},
    }
    canvas.node_groups["g3"] = {
        "type": "container", "alias": "inner", "members": [3],
        "parent": "g1", "slots": {},
    }
    result = delete_group(canvas, "outer")
    check("delete resolves alias", result["ok"], str(result.get("errors")))
    check("delete removes nested frames",
          not canvas.node_groups, str(canvas.node_groups))
    check("delete keeps member nodes", set(canvas.nodes) == set(range(1, 7)),
          f"{sorted(canvas.nodes)}")

    check("resolve_group ignores unknown", resolve_group(canvas, "missing") is None)

    # ── 组框几何：持久化 box / 进入扩展 / 离开收紧 / min / 比例缩放 ──
    print("── group geometry ──")
    canvas.node_groups.clear()
    for nid in range(1, 7):
        canvas.nodes[nid].pos = (0.0, 0.0)
    merged = merge_nodes(canvas, [1, 2])
    gid = str(merged.get("gid") or "g1")
    size_of = lambda _nid, _inst: (100.0, 40.0)  # noqa: E731
    box0 = ensure_box(canvas, gid, size_of)
    check("geometry initializes box", box0 is not None and get_box(canvas, gid) == box0,
          f"{box0}")
    canvas.nodes[1].pos = (100.0, 100.0)
    canvas.nodes[2].pos = (300.0, 100.0)
    box1 = fit_group(canvas, gid, size_of, shrink=True)
    check("geometry fit covers members + margin",
          box1 is not None and box1[0] <= 100.0 and box1[0] + box1[2] >= 400.0,
          f"{box1}")
    min1 = get_min_box(canvas, gid)
    check("geometry records min box", min1 == (box1[2], box1[3]) if box1 else False,
          f"{min1}")

    set_member(canvas, 3, gid)
    canvas.nodes[3].pos = (700.0, 160.0)
    box2 = expand_group_to_rect(canvas, gid, (700.0, 160.0, 100.0, 40.0), size_of)
    check("entering node expands group right edge",
          box2 is not None and box2[0] + box2[2] >= 800.0, f"{box2}")
    unchanged = expand_group_to_rect(canvas, gid, (110.0, 110.0, 100.0, 40.0), size_of)
    check("already-covered node keeps box", unchanged == box2, f"{unchanged} vs {box2}")

    set_member(canvas, 3, None)
    box3 = fit_group(canvas, gid, size_of, shrink=True)
    check("leaving node shrinks group",
          box3 is not None and box2 is not None and box3[2] < box2[2],
          f"{box3} vs {box2}")
    before_pos = (canvas.nodes[1].pos, canvas.nodes[2].pos)
    box4 = scale_group_to_box(canvas, gid, (box3[0], box3[1], box3[2] * 2.0,
                                           box3[3] * 2.0), size_of)
    check("manual resize applies new box", box4 is not None and box4[2] > box3[2],
          f"{box4}")
    check("manual resize moves members proportionally",
          canvas.nodes[1].pos != before_pos[0]
          and canvas.nodes[2].pos != before_pos[1],
          f"{canvas.nodes[1].pos} / {canvas.nodes[2].pos}")
    box5 = scale_group_to_box(canvas, gid, (box4[0], box4[1], 10.0, 10.0), size_of)
    min_now = get_min_box(canvas, gid)
    check("manual resize cannot go below min box",
          box5 is not None and min_now is not None
          and box5[2] >= min_now[0] - 0.01 and box5[3] >= min_now[1] - 0.01,
          f"{box5} min={min_now}")
    box6 = translate_group(canvas, gid, 11.0, 22.0)
    check("translate moves persisted box",
          get_box(canvas, gid)[0] == box5[0] + 11.0
          and get_box(canvas, gid)[1] == box5[1] + 22.0,
          f"{get_box(canvas, gid)}")
    check("group_at_point hits persisted box",
          group_at_point(canvas, (get_box(canvas, gid)[0] + 5.0,
                                  get_box(canvas, gid)[1] + 5.0), size_of) == gid)

    renamed = rename_group(canvas, gid, "renamed")
    check("rename group updates alias",
          renamed["ok"] and canvas.node_groups[gid]["alias"] == "renamed",
          str(renamed))
    merge_nodes(canvas, [4, 5], alias="other")
    dup_alias = rename_group(canvas, gid, "other")
    check("rename rejects duplicate alias",
          not dup_alias["ok"] and "duplicate" in dup_alias["errors"][0],
          str(dup_alias))

    # ── 组内部起点/终点节点 + description + 销毁语义 ──
    print("── group io nodes ──")
    from Application.Core.NodeGraph import NodeCanvas
    real = NodeCanvas()
    na = real.add_node("Print", (0.0, 0.0))
    nb = real.add_node("Print", (260.0, 0.0))
    merged_real = merge_nodes(real, [na, nb])
    rgid = str(merged_real.get("gid") or "")
    check("real group merged", merged_real["ok"], str(merged_real))
    ids = ensure_group_io_nodes(real, rgid)
    check("group gets start/end nodes",
          io_node_ids(real, rgid).get("start") and io_node_ids(real, rgid).get("end"),
          f"{io_node_ids(real, rgid)}")
    check("start node only has exec out",
          real.nodes[ids["start"]].node_type == START_TYPE
          and "exec_out" in real.nodes[ids["start"]].pin_ids
          and "exec_in" not in real.nodes[ids["start"]].pin_ids,
          str(real.nodes[ids["start"]].pin_ids))
    check("end node only has exec in",
          real.nodes[ids["end"]].node_type == END_TYPE
          and "exec_in" in real.nodes[ids["end"]].pin_ids
          and "exec_out" not in real.nodes[ids["end"]].pin_ids,
          str(real.nodes[ids["end"]].pin_ids))
    members = set(real.node_groups[rgid].get("members") or [])
    check("io nodes join group members",
          ids["start"] in members and ids["end"] in members, f"{members}")
    same = ensure_group_io_nodes(real, rgid)
    check("io nodes are idempotent", same == ids, f"{same} vs {ids}")

    desc = set_group_description(real, rgid, "trial container")
    check("group description stored",
          desc["ok"] and real.node_groups[rgid].get("description") == "trial container",
          str(desc))

    ungrouped = ungroup(real, rgid)
    check("ungroup removes io nodes",
          ungrouped["ok"] and ids["start"] not in real.nodes
          and ids["end"] not in real.nodes,
          f"{ungrouped} nodes={sorted(real.nodes)}")
    check("ungroup keeps user nodes", na in real.nodes and nb in real.nodes,
          str(sorted(real.nodes)))

    merged2 = merge_nodes(real, [na, nb])
    rgid2 = str(merged2.get("gid") or "")
    ensure_group_io_nodes(real, rgid2)
    destroyed = destroy_group(real, rgid2)
    check("destroy removes group frame",
          destroyed["ok"] and rgid2 not in real.node_groups, str(destroyed))
    check("destroy removes every member node",
          na not in real.nodes and nb not in real.nodes and not real.nodes,
          f"{sorted(real.nodes)}")

    na2 = real.add_node("Print", (0.0, 0.0))
    nb2 = real.add_node("Print", (200.0, 0.0))
    merged3 = merge_nodes(real, [na2, nb2])
    rgid3 = str(merged3.get("gid") or "")
    io3 = ensure_group_io_nodes(real, rgid3)
    deleted = delete_group(real, rgid3)
    check("metadata delete removes only io nodes",
          deleted["ok"] and io3["start"] not in real.nodes
          and io3["end"] not in real.nodes
          and na2 in real.nodes and nb2 in real.nodes,
          f"{deleted} nodes={sorted(real.nodes)}")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
