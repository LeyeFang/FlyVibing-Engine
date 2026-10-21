"""entity_list 节点 — EntityGetTree / EntityPack / EntityListMerge / 批量显隐与销毁。

TIER: core
运行: python Utils/Dev/test_runner.py --only entity_list_nodes
"""

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _App:
    renderer = None


class _FakeRenderer:
    def __init__(self) -> None:
        self.batches: list[list] = []

    def enqueue(self, cmd) -> None:
        pass

    def enqueue_many(self, cmds) -> None:
        self.batches.append(list(cmds))


def _graph_with(kind: str) -> dict:
    from flyvibing_node_editor.graph_builder import GraphBuilder

    g = GraphBuilder()
    gs, _fu, _gp = g.event_nodes()
    eg = g.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                {"entity_name": "Root"})
    g.link(gs, "exec", eg, "exec_in")
    const = g.node("Constant", ["Result"], {"value": 0})

    if kind == "tree_visible":
        tree = g.node("EntityGetTree", ["Entity", "Entities", "Count"])
        lst = g.node("EntityListSetVisible",
                     ["exec_in", "Entities", "Visible", "exec_out"])
        g.link(eg, "Entity", tree, "Entity")
        g.link(eg, "exec_out", lst, "exec_in")
        g.link(tree, "Entities", lst, "Entities")
        g.link(const, "Result", lst, "Visible")
    elif kind == "pack_merge":
        eg2 = g.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                     {"entity_name": "A"})
        eg3 = g.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                     {"entity_name": "B"})
        pack1 = g.node("EntityPack",
                       ["Entity1", "Entity2", "Entity3", "Entity4", "Entities", "Count"])
        pack2 = g.node("EntityPack",
                       ["Entity1", "Entity2", "Entity3", "Entity4", "Entities", "Count"])
        merge = g.node("EntityListMerge", ["A", "B", "Entities", "Count"])
        lst = g.node("EntityListSetVisible",
                     ["exec_in", "Entities", "Visible", "exec_out"])
        g.link(eg, "exec_out", eg2, "exec_in")
        g.link(eg2, "exec_out", eg3, "exec_in")
        g.link(eg3, "exec_out", lst, "exec_in")
        g.link(eg, "Entity", pack1, "Entity1")
        g.link(eg2, "Entity", pack1, "Entity2")
        g.link(pack1, "Entities", merge, "A")
        g.link(eg3, "Entity", pack2, "Entity1")
        g.link(pack2, "Entities", merge, "B")
        g.link(merge, "Entities", lst, "Entities")
        g.link(const, "Result", lst, "Visible")
    elif kind == "tree_destroy":
        tree = g.node("EntityGetTree", ["Entity", "Entities", "Count"])
        destroy = g.node("EntityListDestroy", ["exec_in", "Entities", "exec_out"])
        g.link(eg, "Entity", tree, "Entity")
        g.link(eg, "exec_out", destroy, "exec_in")
        g.link(tree, "Entities", destroy, "Entities")
    return g.build()


def main() -> int:
    print("=" * 60)
    print("entity_list nodes — tree/pack/merge/visible/destroy")
    print("=" * 60)

    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import MeshRenderer, Transform

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_App)
    SceneManager.Init(_App)
    st = SceneManager._state_for(_App.__name__)
    _App.scene = st
    fake = _FakeRenderer()
    _App.renderer = fake

    import esper
    from Application.Core.NodeGraph import NodeCanvas, GraphEvaluator, ExecutionContext, _TYPES

    root = st.AddEntity("Root", Transform(), MeshRenderer(visible=True))
    a = st.AddEntity("A", Transform(), MeshRenderer(visible=True))
    b = st.AddEntity("B", Transform(), MeshRenderer(visible=True))
    c = st.AddEntity("C", Transform(), MeshRenderer(visible=True))
    st.SetEntityParent(a, root)
    st.SetEntityParent(b, root)
    st.SetEntityParent(c, b)

    def trigger(graph: dict):
        canvas = NodeCanvas.from_dict(graph)
        evaluator = GraphEvaluator(canvas, _TYPES)
        ctx = ExecutionContext()
        ctx.scene = st
        evaluator.trigger("OnGameStart", ctx)

    # ── EntityGetTree → EntityListSetVisible ──
    print("── tree -> list visible (single batch) ──")
    fake.batches.clear()
    trigger(_graph_with("tree_visible"))
    check("one batch", len(fake.batches) == 1, str(len(fake.batches)))
    batch = fake.batches[0] if fake.batches else []
    check("batch covers root + 3 descendants", len(batch) == 4, str(len(batch)))
    check("all hidden",
          all(not esper.component_for_entity(e, MeshRenderer).visible
              for e in (root, a, b, c)))

    # ── EntityPack + EntityListMerge ──
    print("── pack + merge -> list visible ──")
    for e in (root, a, b, c):
        esper.component_for_entity(e, MeshRenderer).visible = True
    fake.batches.clear()
    trigger(_graph_with("pack_merge"))
    check("one batch", len(fake.batches) == 1, str(len(fake.batches)))
    check("merged list has 3", len(fake.batches[0]) == 3 if fake.batches else False,
          str(len(fake.batches[0]) if fake.batches else 0))
    check("list targets hidden",
          all(not esper.component_for_entity(e, MeshRenderer).visible
              for e in (root, a, b)))

    # ── EntityListDestroy ──
    print("── tree destroy ──")
    trigger(_graph_with("tree_destroy"))
    check("root gone", st.GetEntityByName("Root") < 0)
    check("descendants gone",
          all(st.GetEntityByName(n) < 0 for n in ("A", "B", "C")))

    _App.renderer = None
    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
