"""Examples catalog + readable graph guard.

Covers:
  1. File ▸ Open Example catalog finds the built Examples project.
  2. Both example scenes load and pass offline static validation.
  3. MI uses one cue_n_way group with multi-entity arms.
  4. Alias + description coverage on example graphs.

TIER: core
"""

from __future__ import annotations

import json
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
EXAMPLES = os.path.join(ROOT, "Examples")
MI_DIR = os.path.join(EXAMPLES, "MI")
REST_DIR = os.path.join(EXAMPLES, "RestingState")

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


def _graph(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["scene"]["node_graph"]


def main() -> int:
    print("Examples catalog")
    check("MI project exists", os.path.isfile(os.path.join(MI_DIR, "MI.myproj")))
    check("RestingState project exists",
          os.path.isfile(os.path.join(REST_DIR, "RestingState.myproj")))
    with open(os.path.join(MI_DIR, "MI.myproj"), encoding="utf-8") as fh:
        mi_project = json.load(fh)
    with open(os.path.join(REST_DIR, "RestingState.myproj"), encoding="utf-8") as fh:
        rest_project = json.load(fh)
    check("MI project metadata",
          mi_project.get("name") == "MI"
          and mi_project.get("startup_scene") == "scenes\\MI.scene", str(mi_project))
    check("RestingState project metadata",
          rest_project.get("name") == "RestingState"
          and rest_project.get("startup_scene") == "scenes\\RestingState.scene",
          str(rest_project))
    check("README index exists", os.path.isfile(os.path.join(EXAMPLES, "README.md")))

    from Application.Editor.UI.UIManager import UIManager
    catalog = dict(UIManager._example_projects())
    check("File menu lists MI",
          catalog.get("MI") == os.path.join(MI_DIR, "MI.myproj"), str(catalog))
    check("File menu lists RestingState",
          catalog.get("RestingState") == os.path.join(
              REST_DIR, "RestingState.myproj"), str(catalog))

    from flyvibing_node_editor.node_graph_validator import validate_static

    mi = _graph(os.path.join(MI_DIR, "scenes", "MI.scene"))
    resting = _graph(os.path.join(REST_DIR, "scenes", "RestingState.scene"))
    for label, graph in (("MI", mi), ("Resting", resting)):
        errors = validate_static(graph)
        check(f"{label} static validation clean", not errors, str(errors[:3]))

    mi_nodes = mi["nodes"]
    aliases = {nd.get("alias") for nd in mi_nodes.values() if nd.get("alias")}
    check("MI key aliases", {"start", "phase", "tt_cue", "next_trial"} <= aliases,
          str(sorted(aliases)))
    described = sum(1 for nd in mi_nodes.values() if nd.get("description"))
    check("MI description coverage >= 80%", described >= int(len(mi_nodes) * 0.8),
          f"{described}/{len(mi_nodes)}")
    spawn_templates = {nd.get("props", {}).get("template") for nd in mi_nodes.values()
                       if nd.get("node_type") == "EntitySpawn"}
    check("MI spawns every cue root",
          {"Cross", "LeftCue", "RightCue", "NullCue", "TaskCue"} <= spawn_templates,
          str(sorted(x for x in spawn_templates if x)))

    groups = mi.get("node_groups") or {}
    by_alias = {g.get("alias"): g for g in groups.values()}
    check("MI has four groups", len(groups) == 4, str(list(groups)))
    group = by_alias.get("class_cue") or next(iter(groups.values()))
    check("MI class group alias", group.get("alias") == "class_cue", str(group.get("alias")))
    check("MI task window group",
          (by_alias.get("task_cue") or {}).get("type") == "cue_window",
          str((by_alias.get("task_cue") or {}).get("type")))
    check("MI rest hide group",
          (by_alias.get("rest_cue") or {}).get("type") == "hide_group",
          str((by_alias.get("rest_cue") or {}).get("type")))
    trial = by_alias.get("trial") or {}
    check("MI outer container children",
          trial.get("children") == ["g1", "g2", "g3"], str(trial.get("children")))
    arms = (group.get("params") or {}).get("arms") or []
    check("MI 3 arms", [a.get("id") for a in arms] == ["left", "right", "rest"],
          str([a.get("id") for a in arms]))
    check("MI multi-entity arms", all(len(a.get("entities") or []) == 2 for a in arms),
          str(arms))

    rest_aliases = {nd.get("alias") for nd in resting["nodes"].values()
                    if nd.get("alias")}
    check("Resting key aliases", {"start", "phase", "tt_open", "tt_closed"} <= rest_aliases,
          str(sorted(rest_aliases)))
    rest_desc = sum(1 for nd in resting["nodes"].values() if nd.get("description"))
    check("Resting description coverage >= 80%",
          rest_desc >= int(len(resting["nodes"]) * 0.8),
          f"{rest_desc}/{len(resting['nodes'])}")

    print(f"\nRESULT: {'OK' if not _failed else 'FAIL'} ({_passed}/{_passed + len(_failed)})")
    if _failed:
        print("failed: " + "; ".join(_failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
