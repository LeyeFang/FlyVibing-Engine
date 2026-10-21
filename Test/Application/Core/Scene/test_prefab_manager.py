"""PrefabManager P0 contract tests — save/load/instantiate entity trees.

Run:
    python Utils/Dev/test_runner.py --only test_prefab_manager
"""
# TIER: core

from __future__ import annotations

import json
import os
import sys
import tempfile

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


class FakeEngine:
    renderer = None
    scene = None


def main() -> int:
    print("=" * 60)
    print("PrefabManager P0 contract (headless)")
    print("=" * 60)

    import esper
    import Application.Core.Events.Event as _ev
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.PrefabManager import PrefabManager
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer

    esper.clear_database()
    orig_cb = _ev.app_callback_func
    _ev.app_callback_func = lambda _e: None
    ResourceManager.Init(FakeEngine)
    st = SceneManager("P0Prefab", FakeEngine)
    st.comp_mgr.ensure_defaults()

    def add(name: str, *components) -> int:
        return st.AddEntity(name, *components)

    try:
        # ── 1. save tree ───────────────────────────────────────
        print("-- save --")
        root = add("PrefabRoot", Transform(), MeshRenderer(mesh_id=2, material_id=1))
        child = add("PrefabChild", Transform(), MeshRenderer(mesh_id=3, material_id=1))
        grandchild = add("PrefabGrandchild", Transform())
        st.SetEntityParent(child, root)
        st.SetEntityParent(grandchild, child)
        st.SetEntityTransform(root, position_xyz=(1.0, 2.0, 3.0))
        st.SetEntityTransform(child, position_xyz=(4.0, 5.0, 6.0))

        with tempfile.TemporaryDirectory(prefix="mge_prefab_") as tmp:
            path = os.path.join(tmp, "P0Tree.prefab")
            check("save_entity_tree returns True",
                  PrefabManager.save_entity_tree(path, root, st) is True)
            check("prefab file created", os.path.isfile(path))
            raw = json.load(open(path, encoding="utf-8"))
            check("prefab header/name", raw.get("format_version") == 1
                  and raw.get("prefab_name") == "P0Tree")
            check("prefab root/children written",
                  raw["root"]["name"] == "PrefabRoot" and len(raw["children"]) == 2,
                  str(raw.get("children")))
            check("prefab internal parent remap",
                  raw["children"]["1"]["parent_id"] == 0
                  and raw["children"]["2"]["parent_id"] == 1,
                  json.dumps(raw["children"], ensure_ascii=False))
            check("missing-entity save returns False",
                  PrefabManager.save_entity_tree(os.path.join(tmp, "none.prefab"), 999999, st) is False)

            # ── 2. load ─────────────────────────────────────────
            print("-- load --")
            data = PrefabManager.load(path)
            check("load returns PrefabData", data is not None)
            check("loaded name/root/children", data.prefab_name == "P0Tree"
                  and data.root.name == "PrefabRoot" and len(data.children) == 2)
            check("loaded transform payload",
                  data.root.components["Transform"]["position_x"] == 1.0,
                  str(data.root.components.get("Transform")))
            check("missing prefab returns None",
                  PrefabManager.load(os.path.join(tmp, "missing.prefab")) is None)

            bad = os.path.join(tmp, "bad.prefab")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not-json")
            check("corrupt prefab returns None", PrefabManager.load(bad) is None)

            # ── 3. instantiate ───────────────────────────────────
            print("-- instantiate --")
            st2 = SceneManager("P0PrefabReload", FakeEngine)
            st2.comp_mgr.ensure_defaults()
            created = PrefabManager.instantiate_to_scene(data, st2)
            check("instantiate returns root + children", len(created) == 3, str(created))
            check("root instantiated with name", st2.GetEntityName(created[0]) == "PrefabRoot")
            check("child names instantiated",
                  st2.GetEntityName(created[1]) == "PrefabChild"
                  and st2.GetEntityName(created[2]) == "PrefabGrandchild")
            check("parent hierarchy restored",
                  st2.GetEntityParent(created[1]) == created[0]
                  and st2.GetEntityParent(created[2]) == created[1],
                  f"{st2.GetEntityParent(created[1])}/{st2.GetEntityParent(created[2])}")
            check("transform/components restored",
                  st2.GetEntityTransform(created[0]).position_x == 1.0
                  and st2.HasComponent(created[0], MeshRenderer)
                  and st2.HasComponent(created[1], MeshRenderer)
                  and not st2.HasComponent(created[2], MeshRenderer))

    finally:
        _ev.app_callback_func = orig_cb
        try:
            esper.clear_database()
        except Exception:
            pass

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
