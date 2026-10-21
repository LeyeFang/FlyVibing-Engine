"""EntityManager direct facade tests — CRUD/hierarchy/component lookup.

SceneManager delegates to this facade; this file locks the facade behavior
without relying only on the SceneManager integration test.

Run:
    python Utils/Dev/test_runner.py --only test_entity_manager
"""
# TIER: core

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


class FakeEngine:
    renderer = None
    scene = None


def main() -> int:
    print("=" * 60)
    print("EntityManager facade (headless)")
    print("=" * 60)

    import esper
    import Application.Core.Events.Event as _ev
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, Light

    esper.clear_database()
    orig_cb = _ev.app_callback_func
    _ev.app_callback_func = lambda _e: None
    st = SceneManager("P0EntityManager", FakeEngine)
    st.comp_mgr.ensure_defaults()
    mgr = st.entity_mgr

    try:
        root = mgr.add("Root", Transform())
        child = mgr.add("Child", Transform())
        check("add returns tracked id", mgr.exists(root) and mgr.exists(child))
        check("get_name/set_name", mgr.get_name(root) == "Root"
              and (mgr.set_name(root, "Renamed") is None or True)
              and mgr.get_name(root) == "Renamed")
        check("get_id_by_name", mgr.get_id_by_name("Renamed") == root
              and mgr.get_id_by_name("Missing") == -1)
        mgr.set_parent(child, root)
        check("get_parent/children", mgr.get_parent(child) == root
              and mgr.get_children(root) == [child])
        check("get_roots", root in mgr.get_roots() and child not in mgr.get_roots())
        mgr.set_parent(child, 0)
        check("parent 0 detaches", mgr.get_parent(child) is None and child in mgr.get_roots())
        mgr.set_parent(child, root)

        check("get_component", isinstance(mgr.get_component(child, Transform), Transform))
        check("add_component", mgr.add_component(child, Light()) is None
              and mgr.get_component(child, Light) is not None)
        check("get_all_with_component",
              any(eid == child for eid, _ in mgr.get_all_with_component(Light)))
        infos = {info["entity_id"]: info for info in mgr.get_all_infos()}
        check("get_all_infos", infos[root]["name"] == "Renamed"
              and infos[child]["has_camera"] is False)

        check("delete returns True", mgr.delete(root) is True)
        check("delete cascades", not mgr.exists(root) and not mgr.exists(child))
        check("delete missing returns False", mgr.delete(root) is False)

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
