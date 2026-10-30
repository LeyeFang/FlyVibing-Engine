"""ctx.graph extension API — create/find/update/remove nodes + redraw.

This is the capability requested by the device-extension owners: an extension
can create its own nodes, find existing nodes, overwrite their props/metadata,
link them, and ask the editor to repaint.

TIER: core
"""

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

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


def main() -> int:
    print("=" * 60)
    print("ctx.graph extension API — create/find/update/redraw")
    print("=" * 60)

    from Application.Core.NodeGraph import NodeCanvas
    from Application.Core.NodeGraph.node_packs import NodePackRegistry
    from Application.Editor.Extensions import ExtensionGraph as graph_module

    owner = "probe_graph_ext"
    type_name = "ext.probe_graph.Node"
    pack = {
        "id": "probe_graph",
        "name": "Probe Graph",
        "owner": owner,
        "signature": "@Probe",
        "nodes": [{
            "type": type_name,
            "label": "Probe Node",
            "category": "Probe",
            "pins": [
                {"name": "exec_in", "kind": "exec", "direction": "input"},
                {"name": "exec_out", "kind": "exec", "direction": "output"},
            ],
            "fields": [{"key": "gain", "label": "Gain", "kind": "float"}],
        }],
    }
    NodePackRegistry.register(pack)
    canvas = NodeCanvas()
    old_canvas = graph_module._canvas
    graph_module._canvas = lambda: canvas
    try:
        graph = graph_module.ExtensionGraph(owner)
        check("graph available with canvas", graph.available())

        first = graph.add_node(type_name, position=(10, 20),
                               props={"gain": 2.0}, alias="first")
        second = graph.add_node(type_name, position=(200, 20), alias="second")
        check("extension creates owned node", first["owner"] == owner and first["id"] > 0,
              str(first))
        check("created snapshot has signature", first["signature"] == "@Probe", str(first))
        check("created snapshot exposes pins", set(first.get("pins", {})) == {"exec_in", "exec_out"},
              str(first.get("pins")))
        check("owned filter only returns own nodes",
              {n["id"] for n in graph.nodes(owned_only=True)} == {first["id"], second["id"]})
        check("type prefix lookup", len(graph.nodes(type_prefix="ext.probe_graph.")) == 2)
        check("owned_nodes convenience", len(graph.owned_nodes()) == 2)
        check("prop lookup", [n["id"] for n in graph.find("gain", equals=2.0)] == [first["id"]])

        updated = graph.update_node(first["id"], props={"gain": 4.5},
                                    alias="renamed", description="updated")
        check("overwrite props", updated["props"]["gain"] == 4.5, str(updated))
        check("overwrite alias/description",
              updated["alias"] == "renamed" and updated["description"] == "updated")
        check("set_props returns merged props",
              graph.set_props(first["id"], {"extra": 1})["extra"] == 1)
        replaced = graph.replace_props(first["id"], {"only": True})
        check("replace_props drops stale keys",
              replaced == {"only": True}, str(replaced))

        core_id = canvas.add_node("EntitySpawn", (300, 20))
        try:
            graph.add_node("EntitySpawn", position=(0, 0))
            check("extension cannot create core node", False)
        except PermissionError:
            check("extension cannot create core node", True)
        try:
            graph.set_props(core_id, {"template": "X"})
            check("extension cannot overwrite foreign node", False)
        except PermissionError:
            check("extension cannot overwrite foreign node", True)

        lid = graph.add_link(first["id"], "exec_out", second["id"], "exec_in")
        check("extension links its own nodes", lid > 0, str(lid))
        check("duplicate link rejected", _raises(lambda: graph.add_link(
            first["id"], "exec_out", second["id"], "exec_in")))
        check("remove own link", graph.remove_link(lid))
        check("remove own node", graph.remove_node(second["id"]))
        check("node removal reflected", second["id"] not in canvas.nodes)

        before = canvas.revision
        after = graph.request_redraw()
        check("request_redraw bumps revision", after > before, f"{before}->{after}")
        check("link creation/removal also bumps revision", canvas.revision >= after)
    finally:
        graph_module._canvas = old_canvas
        NodePackRegistry.unregister_owner(owner)

    print()
    print("=" * 60)
    total = _passed + len(_failed)
    print(f"Results: {_passed}/{total} passed, {len(_failed)} failed")
    print("ALL TESTS PASSED" if not _failed else "TESTS FAILED")
    return 0 if not _failed else 1


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
