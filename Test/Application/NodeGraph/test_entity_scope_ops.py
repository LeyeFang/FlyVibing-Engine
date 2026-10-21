"""Live entity ops — scope one/tree/list 语义（无头）。

覆盖:
  - entity.visible editor/render + scope tree/list
  - entity.delete scope one（子实体重挂）/ tree / list

TIER: core
运行: python Utils/Dev/test_runner.py --only entity_scope_ops
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


def main() -> int:
    print("=" * 60)
    print("Live entity ops — scope one/tree/list")
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
    from Application.Editor.EditorHost import EditorHost
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    prev = getattr(EditorHost, "scene", None)
    EditorHost.scene = st
    try:
        root = st.AddEntity("Root", Transform(), MeshRenderer())
        a = st.AddEntity("A", Transform(), MeshRenderer())
        b = st.AddEntity("B", Transform(), MeshRenderer())
        c = st.AddEntity("C", Transform(), MeshRenderer())
        st.SetEntityParent(a, root)
        st.SetEntityParent(b, a)
        st.SetEntityParent(c, root)

        # ── editor visibility: tree ──
        print("── entity.visible editor=tree ──")
        res = LiveCommandServer._op_entity_visible(
            {"id": root, "editor": False, "scope": "tree"})
        check("editor tree count 4", res["editor"]["count"] == 4, str(res["editor"]))
        check("editor tree all hidden",
              all(not st.IsEditorVisible(e) for e in (root, a, b, c)))
        LiveCommandServer._op_entity_visible(
            {"id": root, "editor": True, "scope": "tree"})

        # ── render visibility: list ──
        print("── entity.visible render=list ──")
        fake.batches.clear()
        res = LiveCommandServer._op_entity_visible(
            {"ids": [a, c], "render": False, "scope": "list"})
        check("render list count 2", res["render"]["count"] == 2, str(res["render"]))
        check("single batch", len(fake.batches) == 1, str(len(fake.batches)))
        check("a/c hidden, root/b visible",
              not esper.component_for_entity(a, MeshRenderer).visible
              and not esper.component_for_entity(c, MeshRenderer).visible
              and esper.component_for_entity(root, MeshRenderer).visible
              and esper.component_for_entity(b, MeshRenderer).visible)

        # ── delete: tree ──
        print("── entity.delete scope=tree ──")
        res = LiveCommandServer._op_entity_delete(
            {"id": root, "scope": "tree"})
        check("tree deleted count 1", res["deleted_count"] == 1, str(res))
        check("all descendants gone",
              all(st.GetEntityByName(n) < 0 for n in ("Root", "A", "B", "C")))

        # ── delete: one + reparent children ──
        print("── entity.delete scope=one (reparent) ──")
        p = st.AddEntity("P", Transform(), MeshRenderer())
        ch = st.AddEntity("Child", Transform(), MeshRenderer())
        gp = st.GetEntityByName("P")
        st.SetEntityParent(ch, p)
        res = LiveCommandServer._op_entity_delete(
            {"id": p, "scope": "one", "reparent_children": True})
        check("parent deleted", res["deleted_entity"] is True, str(res))
        check("child reparented to root", st.GetEntityParent(ch) is None,
              str(st.GetEntityParent(ch)))
        check("child still exists", st.GetEntityByName("Child") == ch)
        st.DeleteEntity(ch)
    finally:
        EditorHost.scene = prev
        _App.renderer = None

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
