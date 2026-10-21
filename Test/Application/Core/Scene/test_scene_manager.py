"""SceneManager P0 contract tests — headless, no renderer/GL.

Covers:
  - entity CRUD / names / hierarchy / cascade delete
  - component add/get/remove and component registry
  - editor + render visibility
  - transform world/local and editor coordinate round-trip
  - Scene -> ECS -> Scene sync (stable IDs, parent IDs, ambient/lighting/game type)

Run:
    python Utils/Dev/test_runner.py --only test_scene_manager
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
    print("SceneManager P0 contract (headless)")
    print("=" * 60)

    import esper
    import Application.Core.Events.Event as _ev
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Light
    from Application.Core.Scene.Scene import Scene, GameType

    esper.clear_database()
    orig_cb = _ev.app_callback_func
    _ev.app_callback_func = lambda _e: None
    ResourceManager.Init(FakeEngine)
    st = SceneManager("P0Scene", FakeEngine)
    st.comp_mgr.ensure_defaults()

    created: list[int] = []

    def add(name: str = "", *components) -> int:
        eid = st.AddEntity(name, *components)
        created.append(eid)
        return eid

    try:
        # ── 1. CRUD / naming ──────────────────────────────────────
        print("-- entity CRUD / naming --")
        root = add("Root")
        check("AddEntity returns existing id", isinstance(root, int) and st.EntityExists(root))
        check("AddEntity attaches Transform", st.HasComponent(root, Transform))
        check("explicit name round-trip", st.GetEntityName(root) == "Root")
        check("name lookup", st.GetEntityByName("Root") == root)

        unnamed = add()
        name = st.GetEntityName(unnamed)
        check("unnamed entity gets stable fallback name",
              name.startswith("Entity_") and name.endswith(str(unnamed)), name)

        st.SetEntityName(root, "Renamed")
        check("rename updates lookup", st.GetEntityName(root) == "Renamed"
              and st.GetEntityByName("Renamed") == root)
        check("old name is no longer found", st.GetEntityByName("Root") == -1)
        st.SetEntityName(root, "")
        check("empty name clears name", st.GetEntityName(root) == ""
              and st.GetEntityByName("Renamed") == -1)
        st.SetEntityName(root, "Root")

        missing = 999999
        check("missing entity does not exist", not st.EntityExists(missing))
        check("delete missing entity returns False", st.DeleteEntity(missing) is False)

        # ── 2. hierarchy ─────────────────────────────────────────
        print("-- hierarchy --")
        child = add("Child")
        grandchild = add("Grandchild")
        st.SetEntityParent(child, root)
        st.SetEntityParent(grandchild, child)
        check("parent round-trip", st.GetEntityParent(child) == root)
        check("children order/contents", st.GetEntityChildren(root) == [child])
        check("roots exclude children",
              root in st.GetRootEntities()
              and child not in st.GetRootEntities()
              and grandchild not in st.GetRootEntities())
        st.SetEntityParent(child, 0)
        check("parent 0 clears parent", st.GetEntityParent(child) is None)
        check("child becomes root after detach",
              child in st.GetRootEntities() and grandchild not in st.GetRootEntities())
        st.SetEntityParent(child, root)
        st.SetEntityParent(grandchild, child)

        # ── 3. cascade delete ────────────────────────────────────
        print("-- cascade delete --")
        p = add("DeleteRoot")
        c = add("DeleteChild")
        g = add("DeleteGrandchild")
        st.SetEntityParent(c, p)
        st.SetEntityParent(g, c)
        check("delete parent returns True", st.DeleteEntity(p) is True)
        check("parent removed", not st.EntityExists(p))
        check("child removed recursively", not st.EntityExists(c))
        check("grandchild removed recursively", not st.EntityExists(g))
        check("second delete returns False", st.DeleteEntity(p) is False)

        # ── 4. components ────────────────────────────────────────
        print("-- components --")
        comp_eid = add("Components", Transform())
        check("Transform present", st.HasComponent(comp_eid, Transform))
        check("GetComponent returns instance",
              isinstance(st.GetComponent(comp_eid, Transform), Transform))
        check("remove existing component", st.RemoveComponent(comp_eid, Transform) is True)
        check("remove again returns False", st.RemoveComponent(comp_eid, Transform) is False)
        st.AddComponentToEntity(comp_eid, MeshRenderer(mesh_id=7, material_id=3))
        check("AddComponentToEntity + MeshRenderer",
              st.HasComponent(comp_eid, MeshRenderer)
              and st.GetEntityMesh(comp_eid) == 7
              and st.GetEntityMaterial(comp_eid) == 3)
        comp_names = st.comp_mgr.get_all()
        check("ComponentRegistry exposes Light", "Light" in comp_names)
        check("AddComponentToEntityByName", st.AddComponentToEntityByName(comp_eid, "Light") is True
              and st.HasComponent(comp_eid, Light))
        check("duplicate by-name add returns False",
              st.AddComponentToEntityByName(comp_eid, "Light") is False)
        check("unknown component is rejected",
              st.AddComponentToEntityByName(comp_eid, "NoSuchComponent") is False)

        # ── 5. visibility ───────────────────────────────────────
        print("-- visibility --")
        mesh_eid = add("VisibleMesh", Transform(), MeshRenderer(mesh_id=1, visible=False))
        check("editor visible defaults to True", st.IsEditorVisible(mesh_eid))
        st.SetEditorVisible(mesh_eid, False)
        check("editor visibility toggles", st.IsEditorVisible(mesh_eid) is False)
        check("render visibility starts false", st.IsEntityRenderVisible(mesh_eid) is False)
        check("invisible mesh not renderable", mesh_eid not in st.GetRenderableEntities())
        st.SetEntityRenderVisible(mesh_eid, True)
        check("render visibility toggles", st.IsEntityRenderVisible(mesh_eid) is True)
        check("visible mesh is renderable", mesh_eid in st.GetRenderableEntities())
        st.SetEntityRenderVisible(mesh_eid, False)
        changed = st.SetEntitiesRenderVisible([mesh_eid, root, mesh_eid], True)
        check("batch visibility skips non-mesh/duplicate", changed == 1, str(changed))
        check("batch visibility applied", st.IsEntityRenderVisible(mesh_eid) is True)

        infos = {info["entity_id"]: info for info in st.GetAllEntityInfos()}
        check("GetAllEntityInfos includes name/mesh fields",
              infos[mesh_eid]["name"] == "VisibleMesh"
              and infos[mesh_eid]["has_mesh"] is True
              and infos[mesh_eid]["mesh_id"] == 1)

        # ── 6. transforms ───────────────────────────────────────
        print("-- transforms --")
        t_eid = add("Transform", Transform())
        st.SetEntityTransform(t_eid, position_xyz=(4.0, 5.0, 6.0),
                              rotation_xyz=(10.0, 20.0, 30.0),
                              scale_xyz=(2.0, 2.0, 2.0))
        t = st.GetEntityTransform(t_eid)
        check("world transform set/get",
              (t.position_x, t.position_y, t.position_z) == (4.0, 5.0, 6.0)
              and (t.rotation_x, t.rotation_y, t.rotation_z) == (10.0, 20.0, 30.0)
              and (t.scale_x, t.scale_y, t.scale_z) == (2.0, 2.0, 2.0))
        editor = st.GetEntityTransformEditor(t_eid)
        check("editor transform is a full dict",
              set(editor) == {"position", "rotation", "scale"}
              and len(editor["position"]) == 3)
        st.SetEntityTransformEditor(t_eid, position_xyz=(1.0, 2.0, 3.0))
        gl = st.GetEntityTransform(t_eid)
        check("editor->GL setter writes world position",
              (gl.position_x, gl.position_y, gl.position_z) == (1.0, 3.0, -2.0),
              f"{gl.position_x}/{gl.position_y}/{gl.position_z}")

        parent = add("Parent", Transform())
        st.SetEntityParent(t_eid, parent)
        st.SetEntityTransform(parent, position_xyz=(10.0, 0.0, 0.0))
        st.SetEntityTransform(t_eid, position_xyz=(15.0, 0.0, 0.0))
        local = st.GetEntityLocalTransformEditor(t_eid)
        check("world setter derives local under parent",
              abs(local["position"][0] - 5.0) < 1e-6,
              str(local["position"]))
        st.SetEntityLocalTransformEditor(t_eid, position_xyz=(7.0, 0.0, 0.0))
        world = st.GetEntityTransform(t_eid)
        check("local setter recomputes world under parent",
              abs(world.position_x - 17.0) < 1e-6,
              str(world.position_x))

        # ── 7. scene sync ───────────────────────────────────────
        print("-- scene sync --")
        scene = Scene("P0Sync")
        scene.game_type = GameType.GAME_2D
        scene.ambient_color = (0.1, 0.2, 0.3)
        scene.lighting_fallback = False
        st.SetGameType(GameType.GAME_2D)
        st.SetAmbientColor(0.1, 0.2, 0.3)
        st.SetLightingFallback(False)
        st.SyncToScene(scene)
        check("SyncToScene writes entities", len(scene.entities) >= 8)
        check("SyncToScene preserves names/parents",
              any(ed.name == "Root" and ed.parent_id is None for ed in scene.entities.values())
              and any(ed.name == "Child" and ed.parent_id is not None
                      for ed in scene.entities.values()))
        check("SyncToScene copies scene settings",
              scene.ambient_color == (0.1, 0.2, 0.3)
              and scene.lighting_fallback is False
              and scene.game_type == GameType.GAME_2D)
        check("SyncToScene assigns stable next sid", scene._next_sid > max(scene.entities))

        st2 = SceneManager("P0Reload", FakeEngine)
        st2.comp_mgr.ensure_defaults()
        st2.SyncFromScene(scene)
        check("SyncFromScene restores names",
              st2.GetEntityByName("Root") != -1 and st2.GetEntityByName("Child") != -1)
        check("SyncFromScene restores parent chain",
              st2.GetEntityParent(st2.GetEntityByName("Child")) == st2.GetEntityByName("Root"))
        check("SyncFromScene restores scene settings",
              st2.GetAmbientColor() == (0.1, 0.2, 0.3)
              and st2.GetLightingFallback() is False
              and st2.GetGameType() == GameType.GAME_2D)
        # 无摄像机的 scene 会触发默认相机注入，因此这里只保证原始实体全部恢复；
        # 默认相机实体属于 SyncFromScene 的预期兜底。
        loaded_infos = st2.GetAllEntityInfos()
        check("SyncFromScene preserves all scene entities",
              len(loaded_infos) >= len(scene.entities)
              and all(st2.GetEntityByName(ed.name) != -1 for ed in scene.entities.values()),
              f"{len(loaded_infos)} vs {len(scene.entities)}")

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
