"""画布元数据 round-trip — alias 与 node_groups 必须穿过引擎序列化。

覆盖:
  1. NodeInstance.alias / NodeCanvas.node_groups 的 to_dict ↔ from_dict;
  2. 空 alias / 空组不写入 JSON（保持旧场景文件干净）;
  3. clear() / replace_from() 的元数据生命周期;
  4. graph_io.export_graph 产出包含 node_groups。

TIER: core
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
    a = canvas.add_node("Constant", (10.0, 20.0))
    b = canvas.add_node("Branch", (300.0, 20.0))
    canvas.nodes[a].props["value"] = 7
    canvas.add_link(canvas.nodes[a].pin_ids["Result"],
                    canvas.nodes[b].pin_ids["Condition"])
    canvas.nodes[a].alias = "trial_end"
    canvas.nodes[a].description = "Ends the trial and advances the counter."
    canvas.node_groups = {
        "g1": {
            "type": "cue_n_way",
            "alias": "cue_rand",
            "version": 1,
            "params": {"addr": 16376, "arms": [{"id": "left", "entity": "L", "code": 3}]},
            "members": [a, b],
            "slots": {"entry": canvas.nodes[b].pin_ids["exec_in"]},
        }
    }
    return canvas


def main() -> int:
    print("Canvas metadata round-trip")

    canvas = _canvas()
    data = canvas.to_dict()
    check("alias serialized", data["nodes"][str(min(canvas.nodes))].get("alias") == "trial_end")
    check("description serialized",
          data["nodes"][str(min(canvas.nodes))].get("description") ==
          "Ends the trial and advances the counter.")
    check("node_groups serialized", "node_groups" in data and "g1" in data["node_groups"])

    restored = NodeCanvas.from_dict(data)
    alias_map = {nid: inst.alias for nid, inst in restored.nodes.items()}
    check("alias restored", "trial_end" in alias_map.values(), str(alias_map))
    check("description restored",
          any(inst.description == "Ends the trial and advances the counter."
              for inst in restored.nodes.values()))
    check("node_groups restored", restored.node_groups.get("g1", {}).get("alias") == "cue_rand")
    check("round-trip stable", restored.to_dict()["node_groups"] == data["node_groups"])

    # 空元数据不写键（旧场景保持干净）
    plain = NodeCanvas()
    plain.add_node("Constant", (0.0, 0.0))
    plain_data = plain.to_dict()
    check("empty alias omitted", all("alias" not in nd for nd in plain_data["nodes"].values()))
    check("empty description omitted",
          all("description" not in nd for nd in plain_data["nodes"].values()))
    check("empty node_groups omitted", "node_groups" not in plain_data)

    # clear / replace_from
    plain.node_groups = {"g9": {"type": "x"}}
    plain.clear()
    check("clear drops groups", plain.node_groups == {})
    plain.replace_from(restored)
    check("replace_from copies groups",
          plain.node_groups.get("g1", {}).get("alias") == "cue_rand")
    check("replace_from copies alias",
          any(inst.alias == "trial_end" for inst in plain.nodes.values()))
    check("replace_from copies description",
          any(inst.description == "Ends the trial and advances the counter."
              for inst in plain.nodes.values()))

    # graph_io 导出（落盘 = canvas.to_dict）
    from Application.Core.NodeGraph import graph_io
    exported = graph_io.export_graph(restored)
    check("export_graph includes groups", "g1" in exported["graph"].get("node_groups", {}))

    # Scene 存档往返（场景 node_graph 字段走同一契约）
    from Application.Core.Scene.Scene import Scene
    scene = Scene("MetaRoundTrip")
    scene.node_graph = restored
    scene2 = Scene.from_dict(scene.to_dict())
    check("scene round-trip alias",
          any(inst.alias == "trial_end" for inst in scene2.node_graph.nodes.values()))
    check("scene round-trip description",
          any(inst.description == "Ends the trial and advances the counter."
              for inst in scene2.node_graph.nodes.values()))
    check("scene round-trip groups",
          scene2.node_graph.node_groups.get("g1", {}).get("alias") == "cue_rand")

    print(f"\nRESULT: {'OK' if not _failed else 'FAIL'} ({_passed}/{_passed + len(_failed)})")
    if _failed:
        print("failed: " + "; ".join(_failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
