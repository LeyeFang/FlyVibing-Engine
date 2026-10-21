"""工程文件夹提交点 / 材质克隆持久化 / 缺失资产识别 — 无头核心测试。

链路 (2026-10-15 保存体系升级; 概率验证见 stress/test_material_cycle_stress.py):
  A. save_project_as 提交点: 工程目录外的已加载资源 -> 拷贝进 <proj>/assets/<类别>/;
     场景重指入列; 记录改指新文件; material_id 刷新为活 id (对齐不变量)
  B. 编辑器内更改持久化: 被场景引用但无文件的材质 (编辑克隆) -> 保存时落盘 + 登记
  C. 缺失识别: 记录在案但磁盘缺失 -> collect_missing_assets / open_project 报告

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_project_asset_commit.py
"""
# TIER: core

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _write_mat(path: str, name: str, color) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "shader_id": 1, "blend": "opaque",
                   "texture_ids": [], "uniforms": {"uColor": list(color)}}, fh, indent=1)


def _scene_refs_by_name(proj_dir: str, scenes: list) -> dict:
    """读取工程内场景文件的实体材质引用 {实体名: material_id}。"""
    out: dict = {}
    for rel in scenes:
        fp = os.path.join(proj_dir, rel)
        if not os.path.isfile(fp):
            continue
        with open(fp, encoding="utf-8") as fh:
            sd = json.load(fh)
        for _eid, ed in sd.get("scene", {}).get("entities", {}).items():
            mr = ed.get("components", {}).get("MeshRenderer")
            if isinstance(mr, dict):
                out[ed.get("name", "?")] = mr.get("material_id")
    return out


def _read_records(proj: str) -> list:
    with open(proj, encoding="utf-8") as fh:
        return json.load(fh).get("resources", {}).get("materials", [])


def main() -> int:
    print("=" * 60)
    print("Project Asset Commit / Clone Persistence / Missing Scan")
    print("=" * 60)

    tmp = os.environ.get("MGE_TEST_TMP") or tempfile.mkdtemp(prefix="mge_commit_")
    work = os.path.join(tmp, "asset_commit")
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    ext_dir = os.path.join(work, "external")      # 工程目录外的"已加载内容"
    proj_dir = os.path.join(work, "proj1")
    os.makedirs(ext_dir, exist_ok=True)
    ext_mat = os.path.join(ext_dir, "ext_A.mat")
    _write_mat(ext_mat, "ExtA", (1.0, 0.0, 0.0, 1.0))

    # ── 引导（无头编辑器上下文 — 与 test_export_game_bundle 同款底座）──
    from Application.Core.Engine import Engine
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(Engine)
    import Application.Core.NodeGraph.canvas  # noqa: F401  (NodeCanvas 契约注册)
    SceneManager.Init(Engine)
    from Application.Editor.EditorHost import EditorHost

    SceneManager.Init(EditorHost)
    EditorHost.scene = SceneManager._state_for("EditorHost")
    try:
        from Application.Core.Events import EventManager
        EventManager.get().app_callback_func = lambda _e: None
    except Exception:
        pass

    from Application.Editor.ProjectManager import ProjectManager

    # ── 1. 新工程 + 模拟"Resource 面板已加载外部材质" ──
    print("-- 1. load external material into session (unsaved project) --")
    ProjectManager.create_new("CommitTest")
    from Application.Resource.Material import Material

    mat = Material.load_from_file(ext_mat)
    ResourceManager.material_count += 1
    mid = ResourceManager.material_count
    ResourceManager.loaded_material[str(mid)] = mat
    ProjectManager.register_material(ext_mat, mid)

    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer

    EditorHost.scene.AddEntity("E1", Transform(), MeshRenderer(material_id=mid))
    EditorHost.create_scene("S2")
    EditorHost.scene.AddEntity("E2", Transform(), MeshRenderer(material_id=mid))
    EditorHost.scene.AddEntity("E3", Transform(), MeshRenderer(material_id=mid))
    check("two scenes in session", len(EditorHost._scenes) >= 2,
          f"scenes={list(EditorHost._scenes)}")

    # ── 2. 提交点: save_project_as -> 资源拷入 + 场景归位 + 记录刷新 ──
    print("-- 2. commit: save_project_as (consolidation) --")
    proj = os.path.join(proj_dir, "commit.myproj")
    ok = ProjectManager.save_project_as(proj)
    check("save_project_as returns True", ok)

    copied = os.path.join(proj_dir, "assets", "materials", "ext_A.mat")
    check("external material copied into project", os.path.isfile(copied))
    check("origin file untouched (fork)", os.path.isfile(ext_mat))

    d = json.loads(open(proj, encoding="utf-8").read())
    mrecs = d.get("resources", {}).get("materials", [])
    rec = next((e for e in mrecs if "ext_A.mat" in e.get("path", "")), None)
    check("record points into project (relative)",
          rec is not None and not os.path.isabs(rec["path"]), f"records={mrecs}")
    check("record id == live id (aligned)",
          rec is not None and rec.get("material_id") == mid, f"record={rec} live={mid}")
    scene_rels = d.get("scenes", [])
    check("scenes listed", len(scene_rels) >= 2, f"scenes={scene_rels}")
    check("scene files written", all(os.path.isfile(os.path.join(proj_dir, r))
                                     for r in scene_rels), f"scenes={scene_rels}")
    check("startup scene valid", bool(d.get("startup_scene")))
    refs = _scene_refs_by_name(proj_dir, scene_rels)
    check("E1/E2/E3 reference live id", refs.get("E1") == mid and refs.get("E2") == mid
          and refs.get("E3") == mid, f"refs={refs} mid={mid}")
    check("no missing assets after commit", ProjectManager.collect_missing_assets() == [])

    # ── 3. 编辑器内编辑 -> 克隆持久化 (B) ──
    print("-- 3. in-editor edit -> clone persistence --")
    import esper
    from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

    eid = None
    for _e, _mr in esper.get_component(MeshRenderer):
        try:
            if EditorHost.scene.GetEntityName(_e) == "E2":
                eid = _e
        except Exception:
            continue
    check("found live entity E2", eid is not None)
    if eid is not None:
        SceneBrowserController.set_material_color(eid, 0.0, 1.0, 0.0, 1.0)
        mr = esper.component_for_entity(eid, MeshRenderer)
        clone_id = mr.material_id
        check("edit created an independent clone", clone_id != mid, f"{clone_id} vs {mid}")

        ok2 = ProjectManager.save_project()
        check("save_project returns True", ok2)
        mrecs2 = _read_records(proj)
        clone_rec = next((e for e in mrecs2 if e.get("material_id") == clone_id), None)
        check("clone recorded in project", clone_rec is not None, f"records={mrecs2}")
        if clone_rec:
            cf = os.path.join(proj_dir, clone_rec["path"])
            check("clone file on disk", os.path.isfile(cf), clone_rec["path"])
        rec_ids = {e.get("material_id") for e in mrecs2}
        d2 = json.loads(open(proj, encoding="utf-8").read())
        refs2 = _scene_refs_by_name(proj_dir, d2.get("scenes", []))
        sentinel = {n: refs2.get(n) for n in ("E1", "E2", "E3")}
        check("all scene refs covered by records",
              set(sentinel.values()) <= rec_ids and sentinel.get("E2") == clone_id,
              f"refs={refs2} recs={rec_ids}")
        check("E3 still shares original material", refs2.get("E3") == mid, f"refs={refs2}")

        # ── 4. 缺失识别 (C): 删除克隆文件 -> 扫描报告 ──
        print("-- 4. missing-asset detection --")
        clone_file = os.path.join(proj_dir, clone_rec["path"]) if clone_rec else ""
        if clone_file:
            backup = clone_file + ".bak"
            shutil.move(clone_file, backup)
            missing = ProjectManager.collect_missing_assets()
            hit = [m for m in missing if m["category"] == "materials"
                   and clone_rec["path"].replace("\\", "/") in m["path"].replace("\\", "/")]
            check("deleted clone file reported missing", bool(hit), f"missing={missing}")
            reopened = ProjectManager.open_project(proj)
            check("open_project still succeeds with missing asset", reopened)
            check("open_project reports missing via get_missing_assets()",
                  any(clone_rec["path"].replace("\\", "/") in m["path"].replace("\\", "/")
                      for m in ProjectManager.get_missing_assets()),
                  f"missing={ProjectManager.get_missing_assets()}")
            shutil.move(backup, clone_file)
            check("missing cleared after restore (re-open)",
                  ProjectManager.open_project(proj)
                  and ProjectManager.collect_missing_assets() == [])

            # ── 5. 恢复后绑定正确 (跨会话语义: 重新加载) ──
            print("-- 5. bindings correct after re-open --")
            names = {}

            def _collect() -> None:
                # esper 只持有活跃场景的实体 — 需逐场景切换收集
                for e, e_mr in esper.get_component(MeshRenderer):
                    try:
                        nm = EditorHost.scene.GetEntityName(e)
                    except Exception:
                        continue
                    m = ResourceManager.GetMaterial(e_mr.material_id)
                    names[nm] = getattr(m, "name", None) if m is not None else None

            _collect()                       # 活跃场景 (Default): E1
            EditorHost.switch_scene("S2")    # E2/E3 在 S2
            _collect()
            check("E1 binds ExtA", names.get("E1") == "ExtA", f"bindings={names}")
            check("E2 binds clone", (names.get("E2") or "").startswith("ExtA_copy"),
                  f"bindings={names}")
            check("E3 binds ExtA", names.get("E3") == "ExtA", f"bindings={names}")

        # ── 6. 导出自洽性: 会话内已加载过工程 → 活 id 漂移 → 导出仍对齐 ──
        #    (2026-10-16 修复回归: 场景从内存态写出用活 id, 记录必须同步取活 id)
        print("-- 6. export self-consistency under id drift --")
        check("re-open succeeds (forces fresh live ids)",
              ProjectManager.open_project(proj))
        exp_parent = os.path.join(work, "exports")
        os.makedirs(exp_parent, exist_ok=True)
        summary = ProjectManager.export_project_bundle(exp_parent, include_player=False)
        check("export returns summary", bool(summary))
        if summary:
            bdir = summary["dir"]
            bd = json.loads(open(os.path.join(bdir, "commit.myproj"), encoding="utf-8").read())
            brec_ids = {e.get("material_id")
                        for e in bd.get("resources", {}).get("materials", [])
                        if isinstance(e, dict) and e.get("material_id") is not None}
            brefs = _scene_refs_by_name(bdir, bd.get("scenes", []))
            sentinel_b = {n: brefs.get(n) for n in ("E1", "E2", "E3")}
            check("bundle sentinel refs covered by bundle records",
                  bool(sentinel_b) and None not in sentinel_b.values()
                  and set(sentinel_b.values()) <= brec_ids,
                  f"refs={brefs} recs={brec_ids}")

    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    if _RESULTS["fail"] == 0:
        print("ALL TESTS PASSED")
        return 0
    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
