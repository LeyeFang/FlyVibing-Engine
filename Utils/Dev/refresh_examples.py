"""Refresh Examples/*.scene for the node-group editor features.

- ensures each group has a human description;
- adds real GroupStart/GroupEnd nodes (``io_nodes``) and group boxes;
- lays out groups and members with the group-aware layout engine;
- rewrites only ``scene.node_graph`` and keeps the rest of the scene intact.

Run after changing group layout / group IO conventions:

    .venv-py314t\\Scripts\\python.exe Utils\\Dev\\refresh_examples.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Application.Core.NodeGraph import NodeCanvas  # noqa: E402
from Application.Core.NodeGraph.group_geometry import (  # noqa: E402
    GROUP_LAYOUT_VERSION,
    fit_group,
    get_box,
    group_depth,
)
from Application.Core.NodeGraph.group_nodes import (  # noqa: E402
    _io_layout,
    ensure_all_group_io_nodes,
    io_node_ids,
)
from Application.Editor.UI.panels.node_editor.group_layout import (  # noqa: E402
    GroupLayoutEngine,
    node_size,
)

EXAMPLES = ROOT / "Examples"

MI_DESCRIPTIONS = {
    "trial": "One trial: class cue 0-6 s, task cue overlay 2-6 s, rest 6-10 s.",
    "class_cue": "Pick one of three cue arms, show its two mesh parts, and send code 3/4/5.",
    "task_cue": "2-6 s overlay: write TaskCue visibility every frame inside the window.",
    "rest_cue": "At 6 s, batch-hide every cue root and child, then enter rest.",
}

RESTING_GROUPS = {
    "g1": {
        "type": "container", "version": 1, "alias": "resting_block",
        "description": "One resting-state block: open phase, closed phase, then timer reset.",
        "params": {"children": ["g2", "g3", "g4"]},
        "members": [207], "parent": "", "children": ["g2", "g3", "g4"],
    },
    "g2": {
        "type": "container", "version": 1, "alias": "open_phase",
        "description": "0 s: show the fixation cross and send parallel code 1 (eyes open).",
        "params": {}, "members": [208, 211, 212, 213, 214, 215, 216],
        "parent": "g1", "children": [],
    },
    "g3": {
        "type": "container", "version": 1, "alias": "closed_phase",
        "description": "20 s: send parallel code 2 (eyes closed); the cross stays visible.",
        "params": {}, "members": [209, 217, 218],
        "parent": "g1", "children": [],
    },
    "g4": {
        "type": "container", "version": 1, "alias": "cycle",
        "description": "40 s: rewind the block timer and repeat the open/closed cycle.",
        "params": {}, "members": [210, 219],
        "parent": "g1", "children": [],
    },
}


def _load_graph(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = data["scene"]["node_graph"]
    return data, graph


def _refresh_mi(graph: dict) -> dict:
    groups = graph.setdefault("node_groups", {})
    for gid, grp in groups.items():
        alias = str(grp.get("alias") or "")
        if alias in MI_DESCRIPTIONS:
            grp["description"] = MI_DESCRIPTIONS[alias]
    return graph


def _refresh_resting(graph: dict) -> dict:
    groups = graph.setdefault("node_groups", {})
    for gid, spec in RESTING_GROUPS.items():
        current = groups.setdefault(gid, {})
        current.update(spec)
    # Parent container membership is the union of its children plus its own
    # direct members. The editor/refresh step below will add the IO nodes.
    child_members: list[int] = []
    for cgid in RESTING_GROUPS["g1"]["children"]:
        for raw in groups[cgid].get("members") or []:
            nid = int(raw)
            if nid not in child_members:
                child_members.append(nid)
    direct = [int(nid) for nid in groups["g1"].get("members") or []]
    groups["g1"]["members"] = sorted(set(direct + child_members))
    return graph


def _refresh_scene(path: Path, graph: dict, check_only: bool) -> int:
    canvas = NodeCanvas.from_dict(graph)
    ensure_all_group_io_nodes(canvas, node_size)

    positions = GroupLayoutEngine(canvas).layout_all()
    for nid, pos in positions.items():
        if nid in canvas.nodes:
            canvas.nodes[nid].pos = (float(pos[0]), float(pos[1]))

    groups = canvas.node_groups
    for gid in sorted(groups, key=lambda g: group_depth(canvas, g), reverse=True):
        fit_group(canvas, str(gid), node_size, shrink=True)
        groups[str(gid)]["layout_version"] = GROUP_LAYOUT_VERSION
        ids = io_node_ids(canvas, str(gid))
        box = get_box(canvas, str(gid))
        if box is not None and ids:
            start, end = _io_layout(box)
            if "start" in ids:
                canvas.nodes[ids["start"]].pos = start
            if "end" in ids:
                canvas.nodes[ids["end"]].pos = end

    refreshed = canvas.to_dict()
    refreshed.pop("_rules", None)
    print(f"  groups={len(groups)} nodes={len(canvas.nodes)} links={len(canvas.links)}")
    for gid in sorted(groups):
        grp = groups[gid]
        box = get_box(canvas, gid)
        io = io_node_ids(canvas, gid)
        print(f"    {gid} @{grp.get('alias')}: members={len(grp.get('members') or [])} "
              f"io={io} box={box}")
    if check_only:
        return 0

    data, _ = _load_graph(path)
    data["scene"]["node_graph"] = refreshed
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"  wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="validate in memory without rewriting scenes")
    args = parser.parse_args()

    for path, refresher in (
        (EXAMPLES / "MI" / "scenes" / "MI.scene", _refresh_mi),
        (EXAMPLES / "RestingState" / "scenes" / "RestingState.scene", _refresh_resting),
    ):
        print(f"[refresh] {path}")
        _, graph = _load_graph(path)
        graph = refresher(graph)
        _refresh_scene(path, graph, args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
