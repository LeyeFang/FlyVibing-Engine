"""MI example: nested phase groups + 2–6 s overlap regression.

0–6 s class cue, 2–6 s task cue, 6–10 s rest; headless evaluator with a fake
scene so it does not need a window/GL context.
"""
# TIER: core

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.NodeGraph import (  # noqa: E402
    ExecutionContext, GraphEvaluator, NodeCanvas, _TYPES,
)
from Application.Core.NodeGraph.evaluators.math import seed_global_rng  # noqa: E402
from flyvibing_node_editor.ops import apply_ops  # noqa: E402

_SCENE = os.path.join(_ROOT, "Examples", "MI", "scenes", "MI.scene")
_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class FakeScene:
    def __init__(self) -> None:
        self.names = {
            "LeftCue": 7, "L_arrow_body": 8, "L_arrow_head": 9,
            "RightCue": 10, "R_arrow_head": 11, "R_arrow_body": 12,
            "TaskCue": 13, "NullCue": 14, "part1": 15, "part2": 16,
        }
        self.children = {7: [8, 9], 10: [11, 12], 14: [15, 16]}
        self.visible = {eid: False for eid in self.names.values()}

    def GetEntityByName(self, name: str) -> int:
        return self.names.get(name, -1)

    def EntityExists(self, eid: int) -> bool:
        return eid in self.visible

    def GetEntityChildren(self, eid: int) -> list[int]:
        return list(self.children.get(eid, []))

    def SetEntityRenderVisible(self, eid: int, visible: bool) -> None:
        if eid in self.visible:
            self.visible[eid] = bool(visible)

    def SetEntitiesRenderVisible(self, eids, visible: bool) -> None:
        for eid in eids:
            self.SetEntityRenderVisible(int(eid), visible)


def main() -> int:
    with open(_SCENE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    graph = data["scene"]["node_graph"]
    groups = graph.get("node_groups") or {}
    check("MI has 4 groups", len(groups) == 4, str(list(groups)))
    check("class group", groups.get("g1", {}).get("alias") == "class_cue")
    check("task group", groups.get("g2", {}).get("type") == "cue_window")
    check("rest group", groups.get("g3", {}).get("type") == "hide_group")
    trial = groups.get("g4", {})
    check("outer container children", trial.get("children") == ["g1", "g2", "g3"],
          str(trial.get("children")))
    check("child parent links",
          all(groups[gid].get("parent") == "g4" for gid in ("g1", "g2", "g3")))

    r = apply_ops(data, [{"op": "set_group", "group": "@class_cue",
                          "params": {}}])
    check("class group re-expand keeps parent", r["ok"], str(r["errors"]))
    if r["ok"]:
        updated = r["scene"]["scene"]["node_graph"]["node_groups"]
        check("class group still nested", updated["g1"].get("parent") == "g4")
        check("container members refreshed",
              len(updated["g4"]["members"]) == len(updated["g1"]["members"]) +
              len(updated["g2"]["members"]) + len(updated["g3"]["members"]),
              str(len(updated["g4"]["members"])))

    canvas = NodeCanvas.from_dict(graph)
    evaluator = GraphEvaluator(canvas, _TYPES)
    ctx = ExecutionContext()
    scene = FakeScene()
    ctx.scene = scene
    ctx.create_timer("trial_phase")
    ctx.set_timer("trial_phase", 0.0)
    seed_global_rng(1)

    import Application.Functions.SerialParallelDevice as spd
    original = spd.write_parallel
    spd.write_parallel = lambda *a, **k: None
    try:
        def tick(t: float) -> None:
            ctx.elapsed_time = t
            evaluator.trigger("OnFrameUpdate", ctx)

        class_parts = (8, 9, 11, 12, 15, 16)
        tick(1.0)
        class_t1 = [eid for eid in class_parts if scene.visible[eid]]
        check("class cue visible at 1 s", bool(class_t1), str(scene.visible))
        check("task cue hidden at 1 s", not scene.visible[13], str(scene.visible))

        tick(3.0)
        class_t3 = [eid for eid in class_parts if scene.visible[eid]]
        check("class cue stays visible during overlap",
              class_t3 == class_t1, f"{class_t1} -> {class_t3}")
        check("task cue visible at 3 s", scene.visible[13], str(scene.visible))

        tick(7.0)
        check("all cues hidden in rest",
              not any(scene.visible[eid] for eid in class_parts + (13,)),
              str(scene.visible))
    finally:
        spd.write_parallel = original

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
